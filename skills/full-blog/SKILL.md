---
name: full-blog
version: 0.2.1
description: This skill should be used when the user asks to "turn this YouTube video into a blog post", "make a full blog from a YouTube URL with images", "유튜브 영상을 블로그로 변환해줘", "video to blog", "embed slides into the transcript", or wants the transcript PLUS meaningful frame snapshots in an HTML page. Extracts frames by uniform sampling, deduplicates with perceptual hash, ranks with Gemini Flash against transcript context, and renders semantic HTML with clickable YouTube deep-links. For transcript-only output, use the `transcribe` skill instead.
argument-hint: <youtube-url> [--out-dir DIR] [--ranker-model gemini-2.5-flash|gemini-2.0-flash] [--max-frames-per-video N] [--sample-interval N] [--workers N] [--max-cost-usd N] [--no-resume] [--force]
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

1. Calls the existing `transcribe.py` to produce `.md` + sentence-level `.srt`.
2. Downloads the video with `yt-dlp` to a temp dir.
3. Samples one frame every `--sample-interval` seconds (default 5) with ffmpeg.
   Uniform sampling (vs. scene-cut) is intentional: pixel-based scene detection
   misses slide transitions on lecture/code content where the template stays
   the same and only text changes.
4. Deduplicates near-identical frames with imagehash phash (Hamming ≤ 5).
   Held slides collapse into a single representative.
5. Batches the survivors to Gemini Flash with the matching transcript window;
   Gemini filters talking-head / duplicate / low-value frames and writes
   alt-text + caption for the keepers.
6. Aligns each kept frame to the right markdown paragraph (token overlap of
   sentence-level srt cues) and emits HTML with `<figure>` blocks. Adjacent
   figures inside the same paragraph are grouped into a `.figure-row` gallery.

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
   - `--sample-interval N` — seconds between uniform samples (default 5).
     Lower = denser coverage + more Gemini cost; raise to 10 for long lectures
     where you don't need slide-by-slide capture.
   - `--workers N` — parallel videos (default 2; Gemini RPM-aware).
   - `--max-cost-usd N` — soft ceiling on estimated total Gemini spend (default 1.00).
   - `--no-resume` — don't reuse cached /tmp dirs from earlier runs (default off, i.e. reuse enabled).
   - `--force` — overwrite existing `.html`.
3. **Run the script** with the URL and options.
4. **Restructure each HTML for readability** (see "Restructure for readability"
   below). The script produces a *scaffold* — flat paragraphs in a styled
   template. You turn that scaffold into a real blog post by adding `<h2>`
   section headings, a lead paragraph, and dividers.
5. **Report** the per-video summary the script prints. The machine-readable
   `_run_summary.json` is written to the output directory.

## Restructure for readability

The script renders paragraphs flat — one `<p data-srt-start="N">` per
transcript paragraph, with figures spliced in between. That's deliberate:
deciding the *structure* of a blog (topic boundaries, lead, hierarchy) is an
editorial judgement that belongs to you, not to the renderer.

For each `.html` the script produced, use **Read** + **Edit** to:

1. **Read the file** and skim the paragraphs. The `data-srt-start` attribute
   on each `<p>` gives you the second mark in the source video, so you can
   group paragraphs by time + topic.
2. **Promote a lead paragraph.** Take the first 1–3 sentences that frame the
   video's premise and wrap them as `<p class="lead">…</p>` (drop cap is
   automatic). If the first transcript paragraph is throat-clearing
   ("안녕하세요 여러분, 오늘은…"), tighten it into a 1–2 sentence hook.
3. **Insert `<h2>` section headings** at natural topic boundaries — usually
   3–6 sections for a typical talk. Headings should be short (2–6 words) and
   substantive (`API의 본질`, `실생활 비유`, `왜 표준이 중요한가`), not
   sequential ("Part 1, Part 2"). Use the speaker's words where possible.
4. **Split monolithic paragraphs.** Transcript paragraphs are often 5–10
   sentences glued together; break them at clear conversational pivots so
   each `<p>` stays ~2–4 sentences. Preserve `data-srt-start` on the *first*
   piece of a split paragraph; omit it on the continuation pieces.
5. **Add `<hr class="divider">`** between major sections only when the topic
   really shifts (a triple-dot ornament; don't overuse).
6. **Empty the "Additional frames" tail.** Move each `<figure>` in
   `<section class="tail-section">` into the body section that matches its
   `data-timestamp`, then delete the empty tail `<section>`. (If a figure
   truly doesn't belong anywhere, leaving it in the tail is fine — but try
   first.)
7. **Polish the H1 if needed.** The default `<h1 class="post-title">` is the
   raw YouTube title (often padded with prefixes like `01.` or channel
   noise). Rewrite it as a clean editorial title if it reads poorly.

**Do not:**
- Rewrite the *meaning* of paragraphs. This is a transcript-faithful blog,
  not a summary. Tighten phrasing only where the transcript is obviously
  speech-disfluent.
- Move, rename, or alter `<figure>` elements other than their position in
  the document. The `src`, `alt`, `caption`, `data-timestamp`, and deep-link
  href are correct as-emitted.
- Touch the CSS, `<head>`, or page chrome. Only edit inside
  `<div class="post-body">`.
- Translate. If a translation is needed, finish restructuring first, then
  run the `translate` skill on the result (it preserves the structure).

The CSS classes the template understands:
`p.lead` (drop-cap lead), `h2` / `h3` (sectioning), `blockquote`
(pull-quotes for memorable lines), `hr.divider` (triple-dot ornament),
`ul`/`ol` (lists), inline `<code>` for technical terms.

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
- **`scripts/frame_extract.py`** — uniform ffmpeg sampling + phash dedup.
- **`scripts/frame_rank.py`** — Gemini batched ranker.
- **`scripts/render_html.py`** — srt-paragraph alignment + HTML template.
- **`references/usage.md`** — options, prerequisites, troubleshooting.
- **`references/ranker-prompt.md`** — the Gemini ranker prompt (tunable).
