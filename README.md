# yt-ribosome

Transcribe YouTube videos and playlists into Markdown, then translate the transcripts into any
language. Like a ribosome turning transcription into translation — `transcribe` → `translate`.

## Skills

| Skill | Does | Triggers (examples) |
|-------|------|---------------------|
| `transcribe` | YouTube → original-language Markdown (yt-dlp captions, OpenAI audio fallback) | "transcribe this video/playlist", "유튜브 트랜스크립트 받아줘" |
| `translate` | transcript/Markdown files → target language (OpenAI or Gemini) | "translate these to Korean", "한국어로 번역해줘" |
| `transcribe-and-translate` | both, end-to-end | "transcribe this and translate to Korean" |

## How it works

- **Original language first.** Transcription always produces the spoken language of the video
  (via YouTube's `*-orig` ASR caption track), then translation is a separate pass.
- **Caption-first, audio fallback.** Uses yt-dlp captions when available; otherwise downloads
  audio, chunks it under the 25MB API limit, and transcribes with the OpenAI API.
- **Structure-preserving translation.** Chunks on paragraph boundaries so Markdown headings and
  URLs stay intact; corrects auto-transcription errors; skips files already in the target language.

## Prerequisites

| Tool / key | Needed for |
|------------|-----------|
| `yt-dlp` (recent), `ffmpeg` | all transcription |
| `openai` (pip) + `OPENAI_API_KEY` | audio fallback; OpenAI translation |
| `google-genai` (pip) + `GEMINI_API_KEY` or `GOOGLE_API_KEY` | Gemini translation |

API keys are read from the environment or a `.env` file in the current working directory.
A Gemini key beginning with `AQ.` is auto-detected as a Vertex AI Express key.

```bash
pip install -U yt-dlp openai google-genai   # ffmpeg via your OS package manager
```

## Usage

```bash
# Transcribe (original language) → ./transcripts
python3 skills/transcribe/scripts/transcribe.py "<youtube-url>"

# Translate a folder → ./transcripts-ko  (OpenAI default; or --provider gemini)
python3 skills/translate/scripts/translate.py ./transcripts --to Korean

# End-to-end via the orchestrator skill (Claude runs both)
#   "transcribe <url> and translate it to Korean"
```

In Claude Code the skills trigger from natural-language requests; the scripts above are what
they run under the hood.

## Install

From the marketplace (this repo is a single-plugin marketplace):

```
/plugin marketplace add SSFSKIM/yt-ribosome
/plugin install yt-ribosome@yt-ribosome
```

Or test locally without installing:

```bash
claude --plugin-dir /path/to/yt-ribosome
```

## Defaults

- Transcription fallback model: `gpt-4o-transcribe` (more accurate than `whisper-1`).
- Translation provider: `openai` (`gpt-5.4-2026-03-05`, reasoning effort `high`); switch with
  `--provider gemini` (`gemini-3.5-flash`), or `--model` / `--openai-effort` to tune.

See each skill's `references/usage.md` for the full option list.
