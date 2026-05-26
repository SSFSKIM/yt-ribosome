---
name: transcribe
version: 0.1.0
description: This skill should be used when the user asks to "transcribe a YouTube video", "get the transcript of this playlist", "유튜브 트랜스크립트 받아줘", "유튜브 영상 전사해줘", "download captions/subtitles as markdown", or wants spoken video content turned into text. Uses yt-dlp captions in the original language and falls back to the OpenAI transcription API (gpt-4o-transcribe / whisper-1) when no captions exist, writing Markdown (and .srt when timestamps are available). For transcription PLUS translation in one step, use the transcribe-and-translate skill instead.
argument-hint: <youtube-url> [--out-dir DIR] [--fallback-model gpt-4o-transcribe|whisper-1] [--audio-language xx] [--no-audio-fallback]
allowed-tools: Bash, Read, Write, Edit
---

# Transcribe YouTube to Markdown

Turn a YouTube video or playlist into original-language Markdown transcripts. This skill
performs TRANSCRIPTION ONLY (no translation); translate afterward with the `translate` skill.
Handles a single video URL or a full playlist URL.

## How it works

Run the bundled script — it does the whole pipeline (caption download, parsing, audio
fallback, Markdown output) deterministically. Do NOT re-implement this inline.

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/skills/transcribe/scripts/transcribe.py" "<URL>" [options]
```

Per video the script:
1. Downloads the **original-language** caption (the YouTube `*-orig` ASR track) or a manual
   subtitle via yt-dlp, then parses it into clean segments (rolling-duplicate lines removed).
2. If there is no caption, downloads the audio, splits it into <=24MB chunks, and transcribes
   with the OpenAI API (default `gpt-4o-transcribe`, more accurate than `whisper-1`).
3. Writes `NN - Title.md` (H1 title + YouTube link + paragraphed body) and, when the caption
   carried timestamps, `NN - Title.srt`.

## Steps

1. **Confirm prerequisites.** `yt-dlp` and `ffmpeg` must be installed. The OpenAI fallback
   needs the `openai` package and `OPENAI_API_KEY` (read from the environment or a `.env` in
   the current directory). Captions-only runs need neither.
2. **Choose options** from the user's intent:
   - `--out-dir DIR` — where to write transcripts (default `transcripts`).
   - `--fallback-model` — `gpt-4o-transcribe` (default) or `whisper-1`.
   - `--audio-language xx` — force an ISO language for the audio fallback when the original
     language is known (prevents speech-to-text mis-detection on unclear audio).
   - `--no-audio-fallback` — captions only; report videos that have none.
   - `--workers N` — parallel videos (default 4).
3. **Run the script** with the URL and options.
4. **Report** the per-video results the script prints (caption vs audio source, char counts,
   any failures), and the output directory.

## Notes

- Auto-generated captions and speech-to-text contain minor errors (e.g. "Claude" heard as
  "Cloud"); this is expected. The downstream `translate` skill is prompted to correct them.
- The audio fallback can be slow and costs OpenAI usage for long videos; mention this before
  transcribing large playlists with no captions.
- For more detail on flags, behavior, and dependencies, read
  `references/usage.md` and the script's docstring.

## Resources

- **`scripts/transcribe.py`** — the full transcription pipeline (run it; don't reimplement).
- **`references/usage.md`** — options, prerequisites, troubleshooting, and output format.
