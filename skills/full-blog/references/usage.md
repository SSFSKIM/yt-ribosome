# full-blog usage reference

## Prerequisites

| Requirement | Needed for |
|---|---|
| `yt-dlp` (recent) | video + transcript download |
| `ffmpeg` | scene-cut, frame extraction |
| `pip install imagehash Pillow google-genai` | phash dedup + Gemini ranker |
| `GEMINI_API_KEY` or `GOOGLE_API_KEY` | Gemini ranker |
| `OPENAI_API_KEY` (optional) | transcribe.py audio fallback for videos without captions |

API keys are read from the environment or a `.env` file in the current working
directory.

## Flags

| Flag | Default | Purpose |
|---|---|---|
| `--out-dir DIR` | `blogs` | Output directory for `.html` + image folders |
| `--ranker-model NAME` | `gemini-2.5-flash` | Or `gemini-2.0-flash` (3× cheaper, fine on slide content) |
| `--max-frames-per-video N` | `25` | Final cap per video |
| `--batch-size N` | `10` | Frames per Gemini call (lower if hitting rate limits) |
| `--scene-threshold X` | auto | Override adaptive threshold |
| `--workers N` | `2` | Parallel videos |
| `--keep-temp` | `false` | Keep `/tmp/yt-ribosome-blog-*/` for debugging |
| `--force` | `false` | Overwrite existing `.html` |

## Output structure

```
blogs/
├── 01 - Designing with Claude.html
├── 01 - Designing with Claude/
│   ├── 00_03_12.jpg
│   ├── 00_05_44.jpg
│   └── 00_08_21.jpg
└── _run_summary.json
```

Each `.html` file is self-contained (inline CSS, relative image paths). The
adjacent folder of the same name holds the chosen frames.

## Troubleshooting

- **"transcribe produced no .srt"** — the video had no caption track and the
  audio fallback was unable to write an srt. The video cannot be turned into
  a full-blog without timestamps; try `--no-audio-fallback` off, or skip it.
- **`[DEGRADED]` on every video** — Gemini API errors. Check
  `GEMINI_API_KEY` and rate limits. The output still uses evenly-sampled
  frames so nothing is lost.
- **Too many talking-head frames** — the ranker's job is to suppress these,
  but if many slip through, lower `--max-frames-per-video` or raise
  `--scene-threshold` (e.g. `0.4`).
- **"yt-dlp video failed"** — region-block or private video. Re-run with a
  different network or skip the video.
