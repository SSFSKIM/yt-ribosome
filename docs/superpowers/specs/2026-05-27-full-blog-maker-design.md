# Full-Blog Maker — Design Spec

**Status:** Approved (brainstorming complete)
**Date:** 2026-05-27
**Author:** SSFSKIM
**Target version:** yt-ribosome v0.2.0

---

## 1. Overview

yt-ribosome currently converts YouTube videos into plain-text Markdown transcripts
(optionally translated). Text captures less than half of a video's information density —
slides, diagrams, charts, code-on-screen, and visual demonstrations are lost.

**Full-Blog Maker** adds a new skill, `full-blog`, that emits an **HTML blog page** with
**transcript text + meaningful frames** extracted from the source video, inline at the
right moments. The output is a self-contained `.html` file plus an adjacent images
folder.

The new pipeline reuses the existing `transcribe.py` for text and srt timestamps,
layering frame extraction, perceptual-hash deduplication, vision-model ranking, and
HTML rendering on top. The existing `translate` skill is extended to recognize `.html`
files and translate them safely via structured (JSON in / JSON out) batched calls.

## 2. Goals and non-goals

### Goals

- **G1.** Convert any YouTube video (or playlist) to a readable, self-contained HTML
  blog with transcript text and ~10–25 meaningful frames embedded inline.
- **G2.** Frame placement is **timestamp-accurate** — each `<figure>` appears at the
  paragraph that covers the moment in the video the frame was captured.
- **G3.** Frame selection produces visually informative frames (slides, diagrams,
  charts) and suppresses near-duplicates and uninformative shots (talking heads,
  filler).
- **G4.** Reuse transcribe.py as-is (no regressions for v0.1.3 users) and extend the
  existing translate skill so translated full-blog (e.g., Korean) works end-to-end.
- **G5.** Predictable cost (target ≤ $0.15 per 60-min video) and deterministic
  resumability (skip already-done videos, cache Gemini ranker by frame hash).

### Non-goals

- **N1.** OCR — Gemini Flash reads text on slides natively; standalone OCR is
  redundant for v0.2.0.
- **N2.** Face/speaker detection — vision-model ranker already deprioritizes
  talking-head frames.
- **N3.** Self-contained HTML with images base64-inlined — adds bulk and complicates
  translate; stick to adjacent images folder.
- **N4.** Per-paragraph LLM-generated chapter headings — out of scope, possible v0.3.
- **N5.** Caching/serving infrastructure — output is a file artifact.

## 3. Background research summary

Key findings that shaped this design (full citations at end):

- **ffmpeg scene-cut** with threshold 0.3 produces ~30–100 candidate frames for a
  60-min slide-heavy talk; threshold 0.4 is canonical for mixed content; 0.5+ for
  vlogs. The naïve `select='gt(scene,X)'` filter has no temporal smoothing —
  fade-out/fade-in transitions slip under threshold.
- **Vision-model pricing**: Gemini 2.5 Flash, the cheapest production-grade vision
  model, costs ~$0.0003/image at 1024×768. A 60-min video with 150 candidate frames
  costs ~$0.05–0.15 to rank end-to-end. Gemini 2.0 Flash is 3× cheaper.
- **Prior art**: `vidnote` (github.com/amingilani/vidnote) solves a very similar
  problem (lecture video → markdown with slide images) but uses pure frame-diff with
  no LLM ranker. yt-ribosome's differentiator is the **vision-model ranker informed
  by transcript context**.
- **HTML vs Markdown output**: HTML wins for `<figure><img><figcaption>` semantics,
  alt-text, lazy loading, and deep-linking back to YouTube. Markdown-with-embedded-
  HTML is portable but loses some structure.
- **Perceptual hash dedup** with Hamming distance ≤5 collapses the
  same-slide-captured-twice problem common in lecture videos (camera tremor,
  speaker overlays cause spurious scene cuts).

## 4. Architecture

### 4.1 Skill layout

```
yt-ribosome/
└── skills/
    ├── transcribe/                       # existing, no changes
    ├── translate/                        # existing, extend with .html support
    ├── transcribe-and-translate/         # existing, no changes
    └── full-blog/                        # NEW
        ├── SKILL.md
        ├── references/
        │   ├── usage.md
        │   └── ranker-prompt.md          # Gemini ranker prompt template
        └── scripts/
            ├── full_blog.py              # CLI entrypoint, orchestrator
            ├── frame_extract.py          # ffmpeg scene-cut + adaptive threshold + phash
            ├── frame_rank.py             # Gemini batched ranker + alt-text
            └── render_html.py            # VTT alignment + <figure> insertion + template
```

### 4.2 Dependencies

| Package | Reason | Notes |
|---|---|---|
| `imagehash` | perceptual hash dedup | ~10KB, single-purpose |
| `Pillow` | imagehash transitive dep | auto-installed |
| `beautifulsoup4` | translate-side HTML parsing | adds to translate, not full-blog |

Existing deps used as-is: `yt-dlp`, `ffmpeg` (CLI), `google-genai` (Gemini),
`openai` (already there for transcribe fallback, available if user prefers OpenAI
vision later).

**Excluded** (considered, rejected): OpenCV (face detection — ranker handles it),
Tesseract (OCR — vision model handles it), PySceneDetect (adaptive threshold —
ffmpeg 2-pass sample is sufficient).

### 4.3 Reuse strategy for transcribe.py

`full_blog.py` invokes `transcribe.py` as a **subprocess**, getting `.md` + `.srt`
as output. transcribe.py is unchanged. Downside: subprocess overhead per video.
Upside: zero refactoring risk, immediate compatibility.

Library-mode extraction (so both skills import the same module) is deferred to
v0.3.0 if it becomes painful.

### 4.4 CLI interface (consistent with transcribe.py)

```
python3 ${CLAUDE_PLUGIN_ROOT}/skills/full-blog/scripts/full_blog.py <URL> [options]
```

| Flag | Default | Purpose |
|---|---|---|
| `--out-dir DIR` | `blogs/` | Output directory |
| `--ranker-model` | `gemini-2.5-flash` | Or `gemini-2.0-flash` (3× cheaper) |
| `--max-frames-per-video N` | `25` | Hard cap on final frames per video |
| `--scene-threshold X` | auto | Override adaptive threshold |
| `--max-cost-usd X` | `1.00` | Stop run if estimated total exceeds |
| `--workers N` | `2` | Parallel videos (Gemini RPM-aware) |
| `--keep-temp` | `false` | Keep intermediate frames for debugging |
| `--force` | `false` | Overwrite existing output |

## 5. Pipeline

### 5.1 Data flow (60-min slide-heavy talk, typical numbers)

```
URL ──▶ [1] transcribe.py subprocess          ── outputs .md + .srt
        │
        └──▶ [2] yt-dlp video download         ── ~250 MB to /tmp
                  │
                  ├──▶ [3a] adaptive threshold ── sample 60s mid-video → θ
                  ├──▶ [3b] ffmpeg scene-cut@θ ── ~150 candidate frames
                  ├──▶ [4]  imagehash dedup    ── ~50–80 survivors
                  └──▶ [5]  Gemini batched     ── ~15–25 keep + alt + caption
                                ranker            (8 calls × 10 frames)
        
        [6] render_html.py:
            srt cues + paragraphs + ranked frames
            ─▶ post.html + images/
```

### 5.2 Adaptive scene-cut threshold

Sample 60 seconds from the video's middle (avoiding intro/outro) and count cuts at
θ=0.3:

| Cuts in sample | Mode | Threshold |
|---|---|---|
| 0–5 | Slide-heavy talk | 0.20 |
| 6–20 | Mixed | 0.30 |
| 21+ | Dynamic/vlog | 0.50 |

User override: `--scene-threshold`.

### 5.3 Perceptual hash dedup

`imagehash.phash` (8×8 DCT), Hamming distance ≤ 5 = same cluster. Keep first frame.
Cost: microseconds per frame. Effect: removes 3–5× duplicate captures of the same
slide common with lecture videos.

### 5.4 Gemini ranker

**Batch**: 10 frames per call, ~5–8 calls per 60-min video. Each call includes the
transcript text covering that batch's timestamp window (~100–300 words).

**Per-frame output** (STRICT JSON, JSON mode):
```json
{
  "frame_index": 0,
  "include": true,
  "alt_text": "Speaker showing 'bet factory' diagram with three columns...",
  "caption": "Bet factory: small teams making bets",
  "confidence": 0.92
}
```

**Final cap**: if total `include:true` exceeds `--max-frames-per-video`, drop lowest
confidence first, then enforce even distribution across the video (avoid clustering).

**Cost model** (per 60-min video):
- ~150 candidate frames → ~70 after dedup → 8 Gemini calls × 10 frames
- ~$0.05–0.15 with Gemini 2.5 Flash
- ~$0.02–0.05 with Gemini 2.0 Flash

### 5.5 Frame placement (srt cue ↔ markdown paragraph alignment)

The hardest part. Transcribe outputs paragraphed markdown + a separate `.srt` with
timestamps. We must place each ranked frame between paragraphs at the right moment.

Algorithm:

1. For each paragraph in the markdown, walk the srt cues sequentially and find the
   subset whose accumulated text best matches the paragraph (substring/token
   overlap).
2. Record `(paragraph_idx, start_time, end_time)`.
3. For each ranked frame at timestamp `t`: find the paragraph whose
   `[start, end]` covers `t`, and insert the `<figure>` between that paragraph and
   the next.
4. If multiple frames fall on the same paragraph, stack in timestamp order.
5. Frames that fail to match (rare) get appended to a final "Additional frames"
   section so they are not lost.

## 6. HTML output

### 6.1 Files

```
blogs/
├── 01 - Designing with Claude.html
└── 01 - Designing with Claude/
    ├── 00_03_12.jpg
    ├── 00_05_44.jpg
    └── 00_08_21.jpg
```

Per-video folder name matches the html filename — copyable as a unit.

### 6.2 Template (semantic HTML5, inline CSS)

```html
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>01. Designing with Claude: From prompt to production</title>
<style>
  body{max-width:720px;margin:2rem auto;padding:0 1rem;
       font:17px/1.6 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;color:#222}
  h1{font-size:1.8rem;line-height:1.2}
  p{margin:0.8em 0}
  figure{margin:1.5em 0}
  figure img{width:100%;height:auto;border-radius:6px;
             box-shadow:0 2px 8px rgba(0,0,0,0.08)}
  figcaption{font-size:0.9em;color:#666;margin-top:0.4em;text-align:center}
  .ts-link{color:#888;text-decoration:none}
  .ts-link:hover{color:#06f}
  .source{display:block;margin:0 0 2em;color:#06f}
</style>
</head>
<body>
<article>
  <h1>01. Designing with Claude: From prompt to production</h1>
  <p class="source"><a href="https://www.youtube.com/watch?v=Uvl-tRga98g">▶ Watch on YouTube</a></p>
  
  <p>How is everybody? A little bit more than that...</p>
  
  <figure data-timestamp="00:03:12">
    <a href="https://www.youtube.com/watch?v=Uvl-tRga98g&t=192">
      <img src="01 - Designing with Claude/00_03_12.jpg"
           alt="Speaker showing 'bet factory' diagram"
           loading="lazy">
    </a>
    <figcaption>
      Bet factory: small teams making bets
      <a class="ts-link" href="https://www.youtube.com/watch?v=Uvl-tRga98g&t=192">(03:12)</a>
    </figcaption>
  </figure>
  
  <p>Cloud Code came out of labs...</p>
</article>
</body>
</html>
```

### 6.3 Design choices and their rationales

| Choice | Rationale |
|---|---|
| Inline CSS (no external file) | Single-file portable; works in Notion import, email, offline |
| Adjacent `images/` folder | Cleaner than base64; renames + moves are atomic via folder |
| `loading="lazy"` | Pages with 20+ images stay snappy |
| `<figure>` wraps `<a>` to YouTube `?t=` | Click image = jump to that moment in YouTube |
| `data-timestamp` attribute | Machine-readable; future tools can re-derive video segments |
| Semantic `<article>` wrapper | Screen-reader-friendly; gives translate a clear scope |
| Relative image paths | Folder moves intact |

## 7. translate skill extension

### 7.1 Change scope

- Existing markdown path: **0 lines changed**
- New HTML path: ~80–120 lines in `translate.py` + `beautifulsoup4` dep

### 7.2 Translatable nodes (whitelist)

| Element | Translate? | Why |
|---|---|---|
| `<h1>–<h6>`, `<p>`, `<li>` text | ✅ | body content |
| `<figcaption>` text | ✅ | figure caption |
| `<title>` text | ✅ | browser tab |
| `<img alt="...">` attribute | ✅ | accessibility + SEO |
| `<a>` link text | ✅ | except stock phrases like "▶ Watch on YouTube" (pre-mapped) |
| `<code>`, `<pre>` content | ❌ | code |
| `href`, `src`, `data-*` | ❌ | machine data |
| Timestamp tokens like `(03:12)` | ❌ | regex-protected |

### 7.3 Batched JSON-in/JSON-out translation

Extract translatable text nodes with IDs, send as JSON list to the LLM with strict
output schema, validate length and ID set match, replace nodes, re-serialize.

```python
nodes = [{"id": 0, "kind": "p", "text": "..."}, ...]
# LLM call with response_mime_type="application/json"
translated = json.loads(response)
assert len(translated) == len(nodes)
assert {x["id"] for x in translated} == {x["id"] for x in nodes}
```

Translation context: alt-text and figcaption are translated in the **same batch** as
the surrounding body so the LLM has full context (slide content informs paragraph
phrasing).

Batch sizing:
- ≤120 nodes → one batch
- 120–250 → two batches with 3-node overlap for context
- 250+ → 3–4 batches

### 7.4 Idempotency & output naming

- `01 - Designing with Claude.html` → `01 - Designing with Claude.ko.html`
- Existing `.ko.html` → skip (use `--force` to overwrite)
- Images: not duplicated — translated HTML references original folder via the same
  relative `src`. Translated HTML must sit in the same directory as the original.

## 8. Error handling

### 8.1 Stage-by-stage fallbacks

| Stage | Failure | Response |
|---|---|---|
| yt-dlp download | private / deleted / region-block | skip video, report reason, continue playlist |
| yt-dlp download | transient network / 429 | exponential backoff 3× (1s, 4s, 16s) |
| transcribe.py | no captions + audio fallback fails | skip video (no transcript = no blog) |
| ffmpeg scene-cut | codec / corrupt | one re-download retry, then skip |
| frame extract | disk full | hard fail with diagnostic ("need ~500 MB in /tmp") |
| phash | corrupt jpg | skip that frame, continue |
| Gemini ranker | rate limit 429 | exponential backoff up to 5 attempts (2s → 32s) |
| Gemini ranker | JSON parse fail | retry once with batch halved |
| Gemini ranker | All retries exhausted (429 backoff failed, or JSON-halve retry failed) | **graceful degrade**: pick `--max-frames-per-video` frames from phash survivors via even-timestamp sampling; mark result `degraded: true` and continue to render |
| HTML render | no paragraph matches frame | move to "Additional frames" tail section |

### 8.2 Cost ceiling

- `--max-cost-usd` (default 1.00) caps total estimated cost.
- Cost is estimated per video before its Gemini call and accumulated to
  `cost_estimate.json`. If exceeded mid-run, prompt yes/no before continuing.

### 8.3 Temp file lifecycle

```
/tmp/yt-ribosome-blog-<videoId>/
├── video.mp4           ~250 MB, auto-deleted on success
├── frames/             ~15 MB,  auto-deleted on success
└── ranker_cache.json   keyed by frame phash — kept across runs for $0 reruns
```

`--keep-temp` to preserve everything for debugging.

### 8.4 Resumability (3 layers)

| Layer | Key | Skip condition |
|---|---|---|
| Playlist | output `.html` exists | unless `--force` |
| Per-video | `/tmp/yt-ribosome-blog-<id>/video.mp4` exists | unless `--no-resume` |
| Ranker | `ranker_cache.json` keyed by frame phash | always (deterministic) |

## 9. Testing strategy

### 9.1 Fixture corpus

```
skills/full-blog/tests/fixtures/
├── SOURCE.txt                  committed: stable public YouTube URL of test video
├── short_talk.mp4              gitignored: ~90 s slide-heavy talk, fetched on first run
├── short_talk.srt              committed: verified transcript with timestamps
├── short_talk.md               committed: verified markdown paragraphing
└── expected_post.html          committed: golden output of full pipeline against above
```

Only `short_talk.mp4` is gitignored (avoids redistributing copyrighted content). The
text artifacts (`srt`, `md`, `expected_post.html`) are committed as ground truth so
tests are reproducible without re-running transcribe.py against the live URL each
time. A test setup helper downloads `short_talk.mp4` from `SOURCE.txt` if absent;
the srt/md/expected files are read directly.

### 9.2 Test layers

1. **Pure unit tests** — `render_html.py` paragraph-srt alignment, phash dedup
   logic. No LLM, no ffmpeg. Fast.
2. **ffmpeg integration** — `frame_extract.py` against `short_talk.mp4`, assert
   candidate count within bounds and adaptive threshold selects slide-mode.
3. **Mocked Gemini end-to-end** — `unittest.mock` replays a fixtured ranker
   response. Deterministic full pipeline.
4. **Manual QA** — 3 real videos (slide talk, interview, vlog) on first user run,
   eyeball outputs.

### 9.3 Result report (matches transcribe.py style)

Per video to stdout:
```
[12] 03 - The thinking lever
    transcribe: caption (1842 segments)
    frames: 134 candidates → 71 after dedup → 18 after ranker
    cost: $0.08 (gemini-2.5-flash, 8 calls)
    output: blogs/03 - The thinking lever.html + 18 images
    elapsed: 9m 12s
```

Playlist summary: totals + failure list with reasons.

## 10. Open questions and future work

Not blocking v0.2.0; capture for later iterations.

- **OQ1.** Should `transcribe-and-translate` get a `--with-images` flag that internally
  calls full-blog + translate? Yes if users want one-command end-to-end Korean blog.
  Defer to user feedback.
- **OQ2.** Chapter headings: should Gemini also generate H2 section breaks based on
  topic shifts in transcript + frame content? Powerful but expanded scope. v0.3
  candidate.
- **OQ3.** Library-mode extraction of transcribe.py (so full_blog can call it
  in-process instead of subprocess). Cleanup task for v0.3+.
- **OQ4.** Self-contained single-file HTML (base64 images) as an opt-in
  `--single-file` mode for shareability via email/messaging.
- **OQ5.** OCR re-enabled as an opt-in for users who want full-text-search-grade
  alt-text. Tesseract or Gemini batch-extract.

## 11. References

- vidnote — github.com/amingilani/vidnote (prior art, no LLM ranker)
- lecture2notes — github.com/HHousen/lecture2notes (CNN slide classifier, arXiv 2202.03540)
- SliTraNet — arxiv.org/abs/2202.03540 (slide transition detection SOTA)
- ffmpeg scene-cut docs — ffmpeg.org/ffmpeg-filters.html#select_002c-aselect
- PySceneDetect — scenedetect.com/docs/latest/api/detectors.html
- Gemini pricing — ai.google.dev/gemini-api/docs/pricing
- Gemini image tokenization — ai.google.dev/gemini-api/docs/tokens
- Claude vision — platform.claude.com/docs/en/build-with-claude/vision
- W3C WebVTT — w3.org/TR/webvtt1/
- imagehash — pypi.org/project/imagehash/

## 12. Out of brainstorming, into planning

This spec is the **what** and **why**. The next step is `writing-plans` to produce a
sequenced, reviewable implementation plan (the **how**): file-by-file changes, build
order, review checkpoints. After plan approval, implementation can begin.
