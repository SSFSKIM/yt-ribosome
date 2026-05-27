# full-blog usage reference

## Prerequisites

| Requirement | Needed for |
|---|---|
| `yt-dlp` (recent) | video + transcript download |
| `ffmpeg` | frame extraction (uniform sampling) |
| `pip install -r requirements-full-blog.txt` | phash dedup + Gemini ranker + OpenAI fallback |
| `GEMINI_API_KEY` or `GOOGLE_API_KEY` | Gemini ranker |
| `OPENAI_API_KEY` (optional) | transcribe.py audio fallback for videos without captions |

API keys are read from the environment or a `.env` file in the current working
directory.

**Python interpreter gotcha (macOS)**: `python3` may resolve to Homebrew's
copy (`/opt/homebrew/bin/python3`) while you installed the deps into the
system Python (`/usr/bin/python3`), or vice versa. Install with `<python> -m
pip install --user -r requirements-full-blog.txt` against the *same*
interpreter you intend to run the script with. `which python3` tells you
which one your shell will pick.

## Flags

| Flag | Default | Purpose |
|---|---|---|
| `--out-dir DIR` | `blogs` | Output directory for `.html` + image folders |
| `--ranker-model NAME` | `gemini-2.5-flash` | Or `gemini-2.0-flash` (3× cheaper, fine on slide content) |
| `--max-frames-per-video N` | `25` | Final cap per video |
| `--batch-size N` | `10` | Frames per Gemini call (lower if hitting rate limits) |
| `--sample-interval N` | `5` | Seconds between uniform samples; raise to 10 for long videos |
| `--workers N` | `2` | Parallel videos |
| `--keep-temp` | `false` | Keep `/tmp/yt-ribosome-blog-*/` for debugging |
| `--force` | `false` | Overwrite existing `.html` |
| `--max-cost-usd N` | `1.00` | Warns when estimated cumulative cost exceeds this (does not auto-stop) |
| `--no-resume` | `false` | Skip re-using existing /tmp/yt-ribosome-blog-* directories |

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

**Filename sanitisation**: characters unsafe in filesystem paths are
replaced — most commonly `:` and `?` become ` - ` and the trailing chars
are trimmed. The output filename therefore won't be an exact substring of
the YouTube title; use `_run_summary.json` if you need to map machine-side.

## Troubleshooting

- **"transcribe produced no .srt"** — the video had no caption track and the
  audio fallback was unable to write an srt. The video cannot be turned into
  a full-blog without timestamps; try `--no-audio-fallback` off, or skip it.
- **`[DEGRADED]` on every video** — Gemini API errors. Check
  `GEMINI_API_KEY` and rate limits. The output still uses evenly-sampled
  frames so nothing is lost.
- **Too many talking-head frames** — the ranker's job is to suppress these,
  but if many slip through, lower `--max-frames-per-video` or raise
  `--sample-interval` (e.g. `10` to halve the candidate pool).
- **"yt-dlp video failed"** — region-block or private video. Re-run with a
  different network or skip the video.
