# transcribe.py — usage reference

## Prerequisites

| Need | For |
|------|-----|
| `yt-dlp` (recent) | listing videos, downloading captions/audio |
| `ffmpeg` | re-encoding + chunking audio for the OpenAI fallback |
| `openai` (pip) | audio fallback only |
| `OPENAI_API_KEY` | audio fallback only — from env, or a `.env` in the CWD |

Captions-only runs (`--no-audio-fallback`, or videos that all have captions) need only
`yt-dlp`.

If `yt-dlp` is outdated, downloads may fail signature solving. Update with
`pip install -U yt-dlp`. The script already passes `--remote-components ejs:github` so yt-dlp
fetches the JS challenge solver needed for audio downloads.

## Command

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/skills/transcribe/scripts/transcribe.py" <URL> [options]
```

| Option | Default | Meaning |
|--------|---------|---------|
| `--out-dir DIR` | `transcripts` | output directory |
| `--fallback-model M` | `gpt-4o-transcribe` | `gpt-4o-transcribe`, `gpt-4o-mini-transcribe`, or `whisper-1` |
| `--audio-language xx` | auto | force ISO code for audio transcription (e.g. `en`, `ko`) |
| `--no-audio-fallback` | off | captions only; list videos lacking captions |
| `--no-srt` | off | skip writing `.srt` even when timestamps exist |
| `--workers N` | `4` | parallel videos |
| `--overwrite` | off | re-process even if the `.md` already exists |

## How original language is detected

YouTube exposes the source ASR track as a `<lang>-orig` automatic-caption code
(e.g. `en-orig`, `ko-orig`). The script requests `--sub-langs ".*-orig,.*"`, preferring the
`-orig` track, so the transcript is always in the video's spoken language regardless of the
video's title language or the uploader's metadata. A manual subtitle (`.vtt`) is preferred
over auto-captions when present.

## Output

- `NN - Title.md` — `# NN. Title`, a `[YouTube](url)` link, then the transcript grouped into
  ~4-sentence paragraphs.
- `NN - Title.srt` — timestamped subtitles, only when a caption with timestamps was used
  (audio-fallback transcripts have no timestamps) and `--no-srt` was not passed.

Filenames replace `/ \ :` with `-`. The index `NN` is the playlist position (or `01` for a
single video).

## Idempotency & resuming

A video is skipped when its `.md` already exists, so re-running resumes an interrupted
playlist. Use `--overwrite` to force regeneration.

## Troubleshooting

- **"No videos found"** — the URL may be private/region-locked, or a bare playlist ID that
  doesn't resolve; pass the full `watch?v=...&list=...` URL, or make the playlist public.
- **All videos go to audio fallback unexpectedly** — the channel disabled captions; expect
  OpenAI cost and slower runs. Consider `--audio-language` to pin the language.
- **Audio fallback mis-transcribes into the wrong language** — pass `--audio-language` with
  the correct ISO code; auto-detection can hallucinate on noisy/short audio.
- **`openai` import error** — only needed for the fallback: `pip install openai`.
