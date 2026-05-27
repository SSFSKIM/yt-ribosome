---
name: transcribe
version: 0.2.0
description: This skill should be used when the user asks to "transcribe a YouTube video", "get the transcript of this playlist", "유튜브 트랜스크립트 받아줘", "유튜브 영상 전사해줘", "download captions/subtitles as markdown", or wants spoken video content turned into text. Prefers manual (creator-uploaded) subtitles when present; otherwise transcribes the audio via the OpenAI API (gpt-4o-transcribe / whisper-1). YouTube auto-generated captions are skipped by default (they're noisy); opt in with `--allow-auto-captions`. Writes Markdown plus `.srt` when timestamps are available. For transcription PLUS translation in one step, use the transcribe-and-translate skill instead.
argument-hint: <youtube-url> [--out-dir DIR] [--fallback-model gpt-4o-transcribe|whisper-1] [--audio-language xx] [--no-audio-fallback] [--allow-auto-captions]
allowed-tools: Bash, Read, Write, Edit
---

# Transcribe YouTube to Markdown

Turn a YouTube video or playlist into original-language Markdown transcripts. This skill
performs TRANSCRIPTION ONLY (no translation); translate afterward with the `translate` skill.
Handles a single video URL or a full playlist URL.

## How it works

Run the bundled script — it does the whole pipeline (caption download, parsing, audio
transcription, Markdown output) deterministically. Do NOT re-implement this inline.

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/skills/transcribe/scripts/transcribe.py" "<URL>" [options]
```

Per video the script:
1. Tries to download a **manual** subtitle (creator-uploaded) via yt-dlp. If found,
   parses it into clean segments (rolling-duplicate lines removed). YouTube's
   auto-generated `*-orig` ASR track is **NOT** used by default — auto-captions are
   noisy and produce poor downstream blogs/translations. Pass `--allow-auto-captions`
   to opt back into the old caption-first behavior.
2. Otherwise downloads the audio, splits it into <=24MB chunks, and transcribes with
   the OpenAI API (default `gpt-4o-transcribe`, more accurate than `whisper-1`).
3. Writes `NN - Title.md` (H1 title + YouTube link + paragraphed body) and, when a
   caption with timestamps was used, also writes `NN - Title.srt`.

## Steps

1. **Confirm prerequisites.** `yt-dlp` and `ffmpeg` must be installed. The OpenAI path
   needs the `openai` package and `OPENAI_API_KEY` (env or `.env` in CWD). Required by
   default because manual captions are uncommon — only skippable with
   `--allow-auto-captions` (cheap path) or `--no-audio-fallback` (manual-only).
2. **Choose options** from the user's intent:
   - `--out-dir DIR` — where to write transcripts (default `transcripts`).
   - `--fallback-model` — `gpt-4o-transcribe` (default) or `whisper-1`.
   - `--audio-language xx` — force an ISO language for the audio transcription when
     the original language is known (prevents speech-to-text mis-detection).
   - `--allow-auto-captions` — opt back into the old caption-first behavior (cheaper,
     lower quality).
   - `--no-audio-fallback` — manual captions only; report videos that have none.
   - `--workers N` — parallel videos (default 4).
3. **Run the script** with the URL and options.
4. **Report** the per-video results the script prints (source = `caption:manual` /
   `caption:auto` / `audio:gpt-4o-transcribe`, char counts, failures) and the output
   directory.

## Notes

- The audio fallback (now the default for videos without manual subs) costs OpenAI
  usage and time — surface this to the user before transcribing large playlists.
- For videos with creator-uploaded manual subtitles (common on professional
  channels), no audio cost is incurred — the script auto-detects them.
- Auto-generated captions and speech-to-text contain minor errors (e.g. "Claude"
  heard as "Cloud"); the downstream `translate` skill silently corrects them.
- For more detail on flags, behavior, and dependencies, read
  `references/usage.md` and the script's docstring.

## Resources

- **`scripts/transcribe.py`** — the full transcription pipeline (run it; don't reimplement).
- **`references/usage.md`** — options, prerequisites, troubleshooting, and output format.
