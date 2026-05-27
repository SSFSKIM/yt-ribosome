---
name: full-blog
version: 0.1.0
description: This skill should be used when the user asks to "turn this YouTube video into a blog post", "make a full blog from a YouTube URL with images", "유튜브 영상을 블로그로 변환해줘", "video to blog", "embed slides into the transcript", or wants the transcript PLUS meaningful frame snapshots in an HTML page. Extracts scene-cut frames with ffmpeg, deduplicates with perceptual hash, ranks with Gemini Flash against transcript context, and renders semantic HTML with clickable YouTube deep-links. For transcript-only output, use the `transcribe` skill instead.
argument-hint: <youtube-url> [--out-dir DIR] [--ranker-model gemini-2.5-flash|gemini-2.0-flash] [--max-frames-per-video N] [--scene-threshold X] [--workers N] [--force]
allowed-tools: Bash, Read, Write, Edit
---

# Transcribe YouTube to HTML blog with embedded frames

Turn a YouTube video or playlist into an HTML blog post: the transcript text plus
~10–25 meaningful frame snapshots embedded inline at the moments they appear in
the source video. The output is a self-contained `.html` file plus an adjacent
folder of `.jpg` frames.

## How it works

Run the bundled script — it does the whole pipeline.

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/skills/full-blog/scripts/full_blog.py" "<URL>" [options]
```

Per video, the script:

1. Calls the existing `transcribe.py` to produce `.md` + `.srt`.
2. Downloads the video with `yt-dlp` to a temp dir.
3. Samples 60 s of the video to pick an adaptive scene-cut threshold (0.20 for
   slide-heavy talks, 0.30 for mixed, 0.50 for vlogs).
4. Runs `ffmpeg scene-cut` to extract candidate frames.
5. Deduplicates near-identical frames with imagehash phash (Hamming ≤ 5).
6. Batches the survivors to Gemini Flash with the matching transcript window;
   Gemini decides which frames are informative and writes alt-text + caption.
7. Aligns each kept frame to the right markdown paragraph (token overlap of
   accumulated srt cues) and emits HTML with `<figure>` blocks.

Cost target: ~$0.10 per 60-min video with `gemini-2.5-flash`. ~$0.03 with
`gemini-2.0-flash`.

## Steps

1. **Confirm prerequisites.** `yt-dlp`, `ffmpeg`, and Python deps from
   `requirements-full-blog.txt`. A Gemini API key
   (`GEMINI_API_KEY` or `GOOGLE_API_KEY`) in env or `.env` in CWD.
2. **Choose options** from the user's intent:
   - `--out-dir DIR` — where to write `.html` and image folders (default `blogs`).
   - `--ranker-model` — `gemini-2.5-flash` (default) or `gemini-2.0-flash` (3×
     cheaper).
   - `--max-frames-per-video N` — final cap (default 25).
   - `--scene-threshold X` — override adaptive (e.g. `0.4`).
   - `--workers N` — parallel videos (default 2; Gemini RPM-aware).
   - `--force` — overwrite existing `.html`.
3. **Run the script** with the URL and options.
4. **Report** the per-video summary the script prints. The machine-readable
   `_run_summary.json` is written to the output directory.

## Notes

- `transcribe.py` is required and runs first; full-blog will fail for videos
  without captions and without an audio fallback (no transcript = no blog).
- Translate the resulting HTML with the `translate` skill — it recognizes
  `.html` and translates only visible text + alt-text.
- Frames that couldn't be aligned to any paragraph appear in an "Additional
  frames" tail section rather than being dropped.
- When the Gemini ranker fails after all retries, the run continues in
  **degraded mode**: frames are evenly sampled from phash survivors and the
  output is tagged `[DEGRADED]` in the summary.

## Resources

- **`scripts/full_blog.py`** — orchestrator (run this; don't reimplement).
- **`scripts/frame_extract.py`** — ffmpeg scene-cut + adaptive threshold + phash.
- **`scripts/frame_rank.py`** — Gemini batched ranker.
- **`scripts/render_html.py`** — srt-paragraph alignment + HTML template.
- **`references/usage.md`** — options, prerequisites, troubleshooting.
- **`references/ranker-prompt.md`** — the Gemini ranker prompt (tunable).
