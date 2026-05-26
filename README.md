# 🧬 yt-ribosome

[![Claude Code Plugin](https://img.shields.io/badge/Claude%20Code-plugin-8A2BE2.svg)](https://code.claude.com/docs/en/plugins)
[![License: Apache-2.0](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](LICENSE)
[![Version](https://img.shields.io/badge/version-0.1.2-green.svg)](.claude-plugin/plugin.json)

**Turn any YouTube video or playlist into clean Markdown transcripts — then translate them into any language.**

Like a ribosome reads a transcript and synthesizes a product, this plugin goes
**transcription → translation**: pull the spoken words out of a video, then localize them.

```
YouTube URL ──▶ transcribe ──▶ Markdown (original language) ──▶ translate ──▶ Markdown (your language)
```

---

## Why

Getting usable text out of YouTube is fiddly: captions are sometimes missing, come in the wrong
language, are riddled with rolling-duplicate lines, or are auto-translated rather than original.
And once you have a transcript, translating a long talk hits model output limits and mangles
formatting. `yt-ribosome` handles all of that for you, as natural-language skills inside Claude Code.

## Features

- 🎯 **Original-language transcripts** — pulls the true source ASR track, not an auto-translation.
- 🔁 **Caption-first, audio fallback** — uses captions when present; otherwise transcribes the
  audio with the OpenAI API.
- 🧹 **Clean output** — strips YouTube's rolling-duplicate caption lines; paragraphs even
  punctuation-less captions; writes `.srt` too when timestamps exist.
- 🌍 **Translate to any language** — OpenAI or Gemini, preserving Markdown structure and URLs.
- ✍️ **Transcription-error aware** — the translator silently fixes ASR slips (e.g. "Cloud" → Claude).
- ⏭️ **Skips what's already done** — files already in the target language are passed through; both
  steps are resumable.
- ⚡ **Parallel** — videos and files are processed concurrently.

## Skills

| Skill | What it does | Say something like |
|-------|--------------|--------------------|
| **`transcribe`** | YouTube → original-language Markdown | "transcribe this video/playlist", "유튜브 트랜스크립트 받아줘" |
| **`translate`** | transcript/Markdown files → target language | "translate these to Korean", "한국어로 번역해줘" |
| **`transcribe-and-translate`** | both, end to end | "transcribe this and translate it to Korean" |

## Install

```text
/plugin marketplace add SSFSKIM/yt-ribosome
/plugin install yt-ribosome@yt-ribosome
```

Or run it locally without installing:

```bash
claude --plugin-dir /path/to/yt-ribosome
```

### Prerequisites

| Requirement | Needed for |
|-------------|-----------|
| `yt-dlp` (recent) + `ffmpeg` | all transcription |
| `openai` + `OPENAI_API_KEY` | audio fallback **and** OpenAI translation |
| `google-genai` + `GEMINI_API_KEY` or `GOOGLE_API_KEY` | Gemini translation |

```bash
pip install -U yt-dlp openai google-genai     # ffmpeg: brew install ffmpeg / apt install ffmpeg
```

API keys are read from the environment or a `.env` file in the current working directory. A Gemini
key starting with `AQ.` is auto-detected as a **Vertex AI Express** key; an `AIza…` key uses the
standard Gemini API.

## Quickstart

In Claude Code, just ask:

> "Transcribe `https://youtube.com/watch?v=…` and translate it to Korean."

Claude picks the right skill and runs the bundled scripts. Under the hood those are:

```bash
# 1) Transcribe (original language) → ./transcripts/NN - Title.md (+ .srt when captioned)
python3 skills/transcribe/scripts/transcribe.py "<youtube-or-playlist-url>"

# 2) Translate a whole folder → ./transcripts-ko/  (OpenAI by default)
python3 skills/translate/scripts/translate.py ./transcripts --to Korean

# …or Gemini, to Japanese, on a single file
python3 skills/translate/scripts/translate.py "talk.md" --to "日本語" --provider gemini
```

### Output format

```markdown
# 01. What is a Hypervisor?

[YouTube](https://www.youtube.com/watch?v=LMAEbB2a50M)

Hi there, and thanks for coming by today! My name is Bradley Knapp, and I'm one of the product
managers here at IBM Cloud. And the question that we're trying to help you solve today is: what
is a hypervisor?…
```

One `NN - Title.md` per video (index + title heading, a source link, then paragraphed text), plus
`NN - Title.srt` when the source caption carried timestamps.

## Options

**`transcribe.py <url>`**

| Flag | Default | Purpose |
|------|---------|---------|
| `--out-dir DIR` | `transcripts` | output directory |
| `--fallback-model M` | `gpt-4o-transcribe` | `gpt-4o-transcribe` / `gpt-4o-mini-transcribe` / `whisper-1` |
| `--audio-language xx` | auto | force ISO language for the audio fallback |
| `--no-audio-fallback` | off | captions only; list videos that have none |
| `--no-srt` / `--workers N` / `--overwrite` | — | skip srt / parallelism (4) / re-process |

**`translate.py <file-or-dir> --to <language>`**

| Flag | Default | Purpose |
|------|---------|---------|
| `--provider P` | `openai` | `openai` or `gemini` |
| `--model M` | `gpt-5.4-2026-03-05` / `gemini-3.5-flash` | override model |
| `--openai-effort L` | `high` | reasoning effort (OpenAI reasoning models) |
| `--gemini-thinking L` | `low` | thinking level (Gemini 3.x) |
| `--out-dir DIR` / `--workers N` / `--no-skip-detect` / `--overwrite` | — | output / parallelism (8) / force-translate / re-run |

Full reference: [`skills/transcribe/references/usage.md`](skills/transcribe/references/usage.md) ·
[`skills/translate/references/usage.md`](skills/translate/references/usage.md).

## How it works

- **Original language, always.** YouTube marks the source ASR track as `<lang>-orig` (or a bare
  `<lang>` on older videos); `yt-ribosome` selects that track, so the transcript matches the spoken
  language regardless of the video's title or metadata — and never grabs an auto-translation.
- **Clean parsing.** Auto-caption `json3` events tagged as rolling continuations are dropped, so
  you get real lines instead of YouTube's overlapping duplicates.
- **Audio fallback.** When a video has no caption, the audio is downloaded, re-encoded to 16 kHz
  mono, and split into <25 MB chunks before transcription — long talks just work.
- **Structure-preserving translation.** Files are chunked on paragraph boundaries (not mid-line),
  keeping headings and URLs intact and staying within model output limits; any chunk that still
  truncates is split and retried recursively.

## Troubleshooting

- **"No videos found"** — pass the full `watch?v=…&list=…` URL, or make a private playlist public.
- **Audio fallback transcribes into the wrong language** — pass `--audio-language` with the correct
  ISO code (auto-detection can misfire on short/noisy audio).
- **yt-dlp download/signature errors** — `pip install -U yt-dlp` (the scripts already enable the
  EJS challenge solver).
- **Gemini `PERMISSION_DENIED`** — enable the Gemini API on the Cloud project tied to an `AQ.` key.

## Defaults at a glance

- Transcription fallback: **`gpt-4o-transcribe`** (more accurate than `whisper-1`).
- Translation: **`openai`** with **`gpt-5.4-2026-03-05`** at reasoning effort **`high`**; switch
  with `--provider gemini`, or tune via `--model` / `--openai-effort` / `--gemini-thinking`.

## License

[Apache-2.0](LICENSE) — includes an explicit patent grant. See [`NOTICE`](NOTICE) for attribution.

Bundled nothing third-party; `yt-ribosome` orchestrates external tools that keep their own
licenses: [yt-dlp](https://github.com/yt-dlp/yt-dlp), [ffmpeg](https://ffmpeg.org), the
[OpenAI API](https://platform.openai.com), and the [Google Gemini API](https://ai.google.dev).
