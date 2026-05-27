# Full-Blog Maker Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add the `full-blog` skill to yt-ribosome — turn a YouTube URL into an HTML blog page with the transcript and meaningful frame snapshots inline. Extend `translate` to handle the resulting `.html` files.

**Architecture:** New skill `full-blog/` with 4 Python scripts (orchestrator + frame_extract + frame_rank + render_html). Reuses `transcribe.py` as a subprocess. Frame pipeline: ffmpeg scene-cut (adaptive threshold) → imagehash phash dedup → Gemini Flash batched ranker (transcript-context-aware) → srt-aligned HTML with `<figure>` blocks. `translate.py` gains a BeautifulSoup-based HTML path with JSON-in/JSON-out batched node translation.

**Tech Stack:** Python 3.10+, yt-dlp (CLI), ffmpeg (CLI), `imagehash` + `Pillow`, `google-genai` (Gemini, existing dep), `beautifulsoup4` (translate-side, new dep), `pytest` + `unittest.mock` for tests.

**Reference spec:** `docs/superpowers/specs/2026-05-27-full-blog-maker-design.md`

---

## File structure (locked in)

NEW files:
```
yt-ribosome/
├── skills/full-blog/
│   ├── SKILL.md
│   ├── references/
│   │   ├── usage.md
│   │   └── ranker-prompt.md
│   ├── scripts/
│   │   ├── full_blog.py          # CLI entrypoint + orchestration (~250 lines)
│   │   ├── frame_extract.py      # ffmpeg + adaptive threshold + phash (~180 lines)
│   │   ├── frame_rank.py         # Gemini batched ranker (~180 lines)
│   │   └── render_html.py        # srt-paragraph alignment + HTML template (~200 lines)
│   └── tests/
│       ├── fixtures/
│       │   ├── SOURCE.txt
│       │   ├── short_talk.srt
│       │   ├── short_talk.md
│       │   ├── slide_a.jpg       # tiny synthetic image for phash unit tests
│       │   ├── slide_a_dup.jpg   # phash near-duplicate of slide_a
│       │   ├── slide_b.jpg       # phash-different
│       │   └── expected_post.html
│       ├── test_render_html.py
│       ├── test_frame_extract.py
│       ├── test_frame_rank.py
│       └── test_e2e.py
└── docs/superpowers/plans/
    └── 2026-05-27-full-blog-maker.md   # this file
```

MODIFIED files:
- `skills/translate/scripts/translate.py` — add `.html` input path (~120 lines added)
- `.gitignore` — add `blogs/`, `tests/fixtures/*.mp4`, `/tmp/yt-ribosome-blog-*`
- `.claude-plugin/plugin.json` — bump version `0.1.3` → `0.2.0`, update description
- `README.md` — add `full-blog` skill row + section

---

## Task 1: Skill scaffolding and dependency declarations

**Files:**
- Create: `skills/full-blog/` (directory + empty `SKILL.md` placeholder)
- Modify: `.gitignore`
- Modify: `.claude-plugin/plugin.json`
- Create: `requirements-full-blog.txt`

- [ ] **Step 1: Create skill directory tree**

```bash
cd /Users/new/Documents/Code\ w\:\ Claudes/yt-ribosome
mkdir -p skills/full-blog/{references,scripts,tests/fixtures}
touch skills/full-blog/SKILL.md
```

- [ ] **Step 2: Update `.gitignore`**

Append to `.gitignore`:

```
# full-blog skill
blogs/
skills/full-blog/tests/fixtures/*.mp4
/tmp/yt-ribosome-blog-*
```

- [ ] **Step 3: Bump plugin version and description**

Modify `.claude-plugin/plugin.json` — replace the file entirely:

```json
{
  "name": "yt-ribosome",
  "version": "0.2.0",
  "description": "Transcribe YouTube videos/playlists into Markdown, translate them, and convert to HTML blogs with frame snapshots inline (yt-dlp + ffmpeg + OpenAI/Gemini).",
  "author": {
    "name": "supremekim17",
    "email": "supremekim17@gmail.com"
  },
  "homepage": "https://github.com/SSFSKIM/yt-ribosome",
  "repository": "https://github.com/SSFSKIM/yt-ribosome",
  "license": "MIT",
  "keywords": ["youtube", "transcription", "translation", "yt-dlp", "whisper", "gpt-4o-transcribe", "gemini", "blog", "html"]
}
```

- [ ] **Step 4: Create dependency file**

Create `requirements-full-blog.txt`:

```
imagehash>=4.3.1
Pillow>=10.0.0
beautifulsoup4>=4.12.0
google-genai>=0.3.0
```

(`google-genai` repeated from existing deps for clarity; pip resolves once.)

- [ ] **Step 5: Commit scaffolding**

```bash
git add skills/full-blog .gitignore .claude-plugin/plugin.json requirements-full-blog.txt
git commit -m "feat(full-blog): scaffold skill directory and bump to v0.2.0"
```

---

## Task 2: render_html.py — paragraph-srt alignment (TDD, pure functions)

**Files:**
- Create: `skills/full-blog/scripts/render_html.py`
- Create: `skills/full-blog/tests/test_render_html.py`

- [ ] **Step 1: Write the failing test for srt parsing**

Create `skills/full-blog/tests/test_render_html.py`:

```python
"""Unit tests for render_html.py — pure functions only."""
import os
import sys
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import render_html as rh


def test_parse_srt_simple():
    src = (
        "1\n00:00:00,000 --> 00:00:03,500\nHello world.\n\n"
        "2\n00:00:03,500 --> 00:00:07,000\nThis is a test.\n"
    )
    cues = rh.parse_srt(src)
    assert len(cues) == 2
    assert cues[0]["start"] == 0.0
    assert cues[0]["end"] == 3.5
    assert cues[0]["text"] == "Hello world."
    assert cues[1]["start"] == 3.5
    assert cues[1]["text"] == "This is a test."


def test_parse_srt_multiline_cue():
    src = "1\n00:00:00,000 --> 00:00:05,000\nLine one\nLine two\n\n"
    cues = rh.parse_srt(src)
    assert cues[0]["text"] == "Line one Line two"
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd /Users/new/Documents/Code\ w\:\ Claudes/yt-ribosome
pytest skills/full-blog/tests/test_render_html.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'render_html'` (file empty).

- [ ] **Step 3: Implement `parse_srt`**

Create `skills/full-blog/scripts/render_html.py`:

```python
#!/usr/bin/env python3
"""HTML rendering for full-blog skill.

Pure functions (no network, no subprocess):
  - parse_srt(text) -> list[{start, end, text}]
  - align_paragraphs_to_srt(paragraphs, cues) -> list[{p_idx, start, end}]
  - pick_paragraph_for_frame(timestamp_s, paragraph_ranges) -> int (-1 if none)
  - render_html(title, source_url, paragraphs, frames, image_dir) -> str (html)
"""
import html as html_lib
import re


_TS_RE = re.compile(r"(\d+):(\d+):(\d+)[,.](\d+)\s*-->\s*(\d+):(\d+):(\d+)[,.](\d+)")


def _ts_to_s(h, m, s, ms):
    return int(h) * 3600 + int(m) * 60 + int(s) + int(ms) / 1000.0


def parse_srt(text):
    """Parse SRT or WebVTT-ish text into list[{start, end, text}].

    Tolerates both ',' and '.' as ms separator. Joins multi-line cue text with
    a single space. Skips index lines and blank lines.
    """
    cues = []
    block = []
    for line in text.splitlines():
        if line.strip() == "":
            if block:
                cues.append(block)
                block = []
        else:
            block.append(line)
    if block:
        cues.append(block)

    out = []
    for blk in cues:
        # find timestamp line
        ts_line = None
        text_lines = []
        for line in blk:
            m = _TS_RE.search(line)
            if m and ts_line is None:
                ts_line = m
            elif ts_line is not None:
                text_lines.append(line)
        if ts_line is None:
            continue
        out.append({
            "start": _ts_to_s(*ts_line.group(1, 2, 3, 4)),
            "end":   _ts_to_s(*ts_line.group(5, 6, 7, 8)),
            "text":  " ".join(x.strip() for x in text_lines).strip(),
        })
    return out
```

- [ ] **Step 4: Run test to verify it passes**

```bash
pytest skills/full-blog/tests/test_render_html.py -v
```

Expected: 2 passed.

- [ ] **Step 5: Add tests for paragraph-srt alignment**

Append to `test_render_html.py`:

```python
def test_align_paragraphs_to_srt_substring_match():
    cues = [
        {"start": 0.0, "end": 3.0, "text": "Hello everyone, welcome."},
        {"start": 3.0, "end": 7.0, "text": "Today we're talking"},
        {"start": 7.0, "end": 10.0, "text": "about full blogs."},
        {"start": 10.0, "end": 14.0, "text": "Now let's get into the details."},
        {"start": 14.0, "end": 18.0, "text": "First, the architecture."},
    ]
    paragraphs = [
        "Hello everyone, welcome. Today we're talking about full blogs.",
        "Now let's get into the details. First, the architecture.",
    ]
    ranges = rh.align_paragraphs_to_srt(paragraphs, cues)
    assert len(ranges) == 2
    assert ranges[0]["p_idx"] == 0
    assert ranges[0]["start"] == 0.0
    assert ranges[0]["end"] == pytest.approx(10.0)
    assert ranges[1]["p_idx"] == 1
    assert ranges[1]["start"] == pytest.approx(10.0)
    assert ranges[1]["end"] == pytest.approx(18.0)


def test_pick_paragraph_for_frame():
    ranges = [
        {"p_idx": 0, "start": 0.0,  "end": 10.0},
        {"p_idx": 1, "start": 10.0, "end": 20.0},
        {"p_idx": 2, "start": 20.0, "end": 30.0},
    ]
    assert rh.pick_paragraph_for_frame(5.0, ranges) == 0
    assert rh.pick_paragraph_for_frame(15.0, ranges) == 1
    assert rh.pick_paragraph_for_frame(25.0, ranges) == 2
    assert rh.pick_paragraph_for_frame(99.0, ranges) == -1   # past end
    assert rh.pick_paragraph_for_frame(-1.0, ranges) == -1   # before start
```

- [ ] **Step 6: Implement alignment functions**

Append to `render_html.py`:

```python
_TOKEN_RE = re.compile(r"[A-Za-z0-9가-힣]+")


def _tokens(s):
    return set(t.lower() for t in _TOKEN_RE.findall(s))


def align_paragraphs_to_srt(paragraphs, cues):
    """Map each paragraph to a contiguous run of srt cues by token overlap.

    Walks cues sequentially, building up a moving window. For each paragraph,
    consumes cues from the current position while token overlap is improving.
    Returns a list of {p_idx, start, end} entries, one per paragraph that
    matched at least one cue.
    """
    ranges = []
    cue_idx = 0
    for p_idx, para in enumerate(paragraphs):
        p_toks = _tokens(para)
        if not p_toks or cue_idx >= len(cues):
            continue
        start_idx = cue_idx
        consumed = []
        # Greedy: keep consuming cues while their tokens are still mostly
        # contained in the paragraph; stop on a clear mismatch.
        while cue_idx < len(cues):
            c_toks = _tokens(cues[cue_idx]["text"])
            if not c_toks:
                cue_idx += 1
                continue
            overlap = len(c_toks & p_toks) / max(1, len(c_toks))
            # If this cue overlaps the paragraph >40%, consume it.
            # Stop the first time a cue does NOT meet the bar — that's the next paragraph.
            if overlap >= 0.4 or not consumed:
                consumed.append(cue_idx)
                cue_idx += 1
                if overlap < 0.4 and consumed:
                    # Allowed the very first cue as anchor, but a poor one
                    # means we should not greedily continue.
                    break
            else:
                break
        if consumed:
            ranges.append({
                "p_idx": p_idx,
                "start": cues[consumed[0]]["start"],
                "end":   cues[consumed[-1]]["end"],
            })
    return ranges


def pick_paragraph_for_frame(timestamp_s, paragraph_ranges):
    """Return the p_idx whose [start, end] contains timestamp_s; -1 if none."""
    for r in paragraph_ranges:
        if r["start"] <= timestamp_s < r["end"]:
            return r["p_idx"]
    return -1
```

- [ ] **Step 7: Run all tests**

```bash
pytest skills/full-blog/tests/test_render_html.py -v
```

Expected: 4 passed.

- [ ] **Step 8: Commit**

```bash
git add skills/full-blog/scripts/render_html.py skills/full-blog/tests/test_render_html.py
git commit -m "feat(full-blog): parse_srt + paragraph alignment (TDD)"
```

---

## Task 3: render_html.py — HTML template rendering (TDD)

**Files:**
- Modify: `skills/full-blog/scripts/render_html.py`
- Modify: `skills/full-blog/tests/test_render_html.py`

- [ ] **Step 1: Add test for figure block + full HTML render**

Append to `test_render_html.py`:

```python
def test_figure_block_includes_timestamp_and_alt():
    fig = rh._figure_block(
        image_dir="my video",
        image_filename="00_03_12.jpg",
        timestamp_s=192,
        alt="Speaker showing diagram",
        caption="Bet factory",
        video_id="Uvl-tRga98g",
    )
    assert "00_03_12.jpg" in fig
    assert "Speaker showing diagram" in fig
    assert "Bet factory" in fig
    assert "data-timestamp=\"00:03:12\"" in fig
    assert "&t=192" in fig
    # alt and caption must be HTML-escaped if they contain reserved chars
    fig2 = rh._figure_block("d", "x.jpg", 0, "A & B", "<x>", "id")
    assert "A &amp; B" in fig2
    assert "&lt;x&gt;" in fig2


def test_render_html_inserts_figures_between_paragraphs():
    paragraphs = ["First paragraph.", "Second paragraph.", "Third paragraph."]
    ranges = [
        {"p_idx": 0, "start": 0.0,  "end": 10.0},
        {"p_idx": 1, "start": 10.0, "end": 20.0},
        {"p_idx": 2, "start": 20.0, "end": 30.0},
    ]
    frames = [
        {"path_rel": "vid/05.jpg", "timestamp_s":  5.0, "alt": "F1", "caption": "C1"},
        {"path_rel": "vid/15.jpg", "timestamp_s": 15.0, "alt": "F2", "caption": "C2"},
    ]
    out = rh.render_html(
        title="Test", source_url="https://www.youtube.com/watch?v=abc",
        paragraphs=paragraphs, paragraph_ranges=ranges, frames=frames,
        video_id="abc",
    )
    # First paragraph should appear before the first <figure>
    p1 = out.index("First paragraph.")
    fig1 = out.index("vid/05.jpg")
    p2 = out.index("Second paragraph.")
    fig2 = out.index("vid/15.jpg")
    p3 = out.index("Third paragraph.")
    assert p1 < fig1 < p2 < fig2 < p3


def test_render_html_unmatched_frame_goes_to_tail_section():
    paragraphs = ["Only paragraph."]
    ranges = [{"p_idx": 0, "start": 0.0, "end": 10.0}]
    frames = [
        {"path_rel": "vid/99.jpg", "timestamp_s": 99.0, "alt": "F", "caption": "C"},
    ]
    out = rh.render_html(
        title="T", source_url="https://www.youtube.com/watch?v=abc",
        paragraphs=paragraphs, paragraph_ranges=ranges, frames=frames,
        video_id="abc",
    )
    assert "Additional frames" in out
    assert "vid/99.jpg" in out
    # the additional-frames section appears after the body paragraphs
    assert out.index("Only paragraph.") < out.index("Additional frames")
```

- [ ] **Step 2: Run test, verify it fails**

```bash
pytest skills/full-blog/tests/test_render_html.py -v -k "figure or render_html"
```

Expected: 3 new tests fail with AttributeError.

- [ ] **Step 3: Implement `_figure_block` and `render_html`**

Append to `render_html.py`:

```python
_HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="{lang}">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<style>
body{{max-width:720px;margin:2rem auto;padding:0 1rem;
     font:17px/1.6 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;color:#222}}
h1{{font-size:1.8rem;line-height:1.2}}
h2{{font-size:1.3rem;margin-top:2rem;border-top:1px solid #eee;padding-top:1rem}}
p{{margin:0.8em 0}}
figure{{margin:1.5em 0}}
figure img{{width:100%;height:auto;border-radius:6px;
           box-shadow:0 2px 8px rgba(0,0,0,0.08)}}
figcaption{{font-size:0.9em;color:#666;margin-top:0.4em;text-align:center}}
.ts-link{{color:#888;text-decoration:none}}
.ts-link:hover{{color:#06f}}
.source{{display:block;margin:0 0 2em;color:#06f}}
</style>
</head>
<body>
<article>
<h1>{title}</h1>
<p class="source"><a href="{source_url}">▶ Watch on YouTube</a></p>
{body}
</article>
</body>
</html>
"""


def _ts_str(timestamp_s):
    s = int(timestamp_s)
    return f"{s//3600:02d}:{(s%3600)//60:02d}:{s%60:02d}"


def _figure_block(image_dir, image_filename, timestamp_s, alt, caption, video_id):
    ts = _ts_str(timestamp_s)
    deep = f"https://www.youtube.com/watch?v={video_id}&t={int(timestamp_s)}"
    src = f"{image_dir}/{image_filename}" if image_dir else image_filename
    return (
        f'<figure data-timestamp="{ts}">'
        f'<a href="{deep}"><img src="{html_lib.escape(src, quote=True)}" '
        f'alt="{html_lib.escape(alt)}" loading="lazy"></a>'
        f'<figcaption>{html_lib.escape(caption)} '
        f'<a class="ts-link" href="{deep}">({ts})</a></figcaption>'
        f'</figure>'
    )


def render_html(title, source_url, paragraphs, paragraph_ranges, frames,
                video_id, image_dir=None, lang="en"):
    """Render the final HTML.

    paragraphs       : list[str], body paragraphs
    paragraph_ranges : output of align_paragraphs_to_srt
    frames           : list[{path_rel, timestamp_s, alt, caption, ...}]
    video_id         : YouTube video id (for deep-link in figures)
    image_dir        : directory prefix for img src (defaults to frame's path_rel basename dir)
    """
    # Bucket frames by paragraph
    by_p = {}
    tail = []
    for fr in frames:
        p_idx = pick_paragraph_for_frame(fr["timestamp_s"], paragraph_ranges)
        if p_idx == -1:
            tail.append(fr)
        else:
            by_p.setdefault(p_idx, []).append(fr)

    parts = []
    for i, para in enumerate(paragraphs):
        parts.append(f"<p>{html_lib.escape(para)}</p>")
        for fr in sorted(by_p.get(i, []), key=lambda f: f["timestamp_s"]):
            # split frame['path_rel'] into dir + filename for the template
            d, _, fn = fr["path_rel"].rpartition("/")
            parts.append(_figure_block(
                image_dir=d, image_filename=fn,
                timestamp_s=fr["timestamp_s"],
                alt=fr.get("alt", ""), caption=fr.get("caption", ""),
                video_id=video_id,
            ))

    if tail:
        parts.append("<h2>Additional frames</h2>")
        for fr in sorted(tail, key=lambda f: f["timestamp_s"]):
            d, _, fn = fr["path_rel"].rpartition("/")
            parts.append(_figure_block(
                image_dir=d, image_filename=fn,
                timestamp_s=fr["timestamp_s"],
                alt=fr.get("alt", ""), caption=fr.get("caption", ""),
                video_id=video_id,
            ))

    return _HTML_TEMPLATE.format(
        lang=lang,
        title=html_lib.escape(title),
        source_url=html_lib.escape(source_url, quote=True),
        body="\n".join(parts),
    )
```

- [ ] **Step 4: Run all render_html tests**

```bash
pytest skills/full-blog/tests/test_render_html.py -v
```

Expected: 7 passed.

- [ ] **Step 5: Commit**

```bash
git add skills/full-blog/scripts/render_html.py skills/full-blog/tests/test_render_html.py
git commit -m "feat(full-blog): HTML template rendering with figure placement"
```

---

## Task 4: frame_extract.py — phash dedup (TDD, fixtures)

**Files:**
- Create: `skills/full-blog/scripts/frame_extract.py`
- Create: `skills/full-blog/tests/test_frame_extract.py`
- Create: `skills/full-blog/tests/fixtures/slide_a.jpg`
- Create: `skills/full-blog/tests/fixtures/slide_a_dup.jpg`
- Create: `skills/full-blog/tests/fixtures/slide_b.jpg`

- [ ] **Step 1: Generate fixture images (synthetic, deterministic)**

Run a one-time helper from the project root:

```bash
python3 -c "
from PIL import Image, ImageDraw
out = 'skills/full-blog/tests/fixtures'
def slide(text, jitter=0):
    img = Image.new('RGB', (400, 300), 'white')
    d = ImageDraw.Draw(img)
    d.rectangle([20+jitter, 20, 380, 280], outline='black', width=3)
    d.text((40+jitter, 130), text, fill='black')
    return img
slide('Slide A: intro').save(f'{out}/slide_a.jpg', quality=90)
slide('Slide A: intro', jitter=2).save(f'{out}/slide_a_dup.jpg', quality=90)
slide('Slide B: results').save(f'{out}/slide_b.jpg', quality=90)
print('wrote 3 fixtures')
"
```

- [ ] **Step 2: Install deps locally**

```bash
pip install -r requirements-full-blog.txt
```

- [ ] **Step 3: Write failing test**

Create `skills/full-blog/tests/test_frame_extract.py`:

```python
"""Unit tests for frame_extract.py."""
import os
import sys
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import frame_extract as fe

FIX = os.path.join(os.path.dirname(__file__), "fixtures")


def test_phash_dedup_keeps_one_of_near_duplicates():
    pairs = [
        (0.0, os.path.join(FIX, "slide_a.jpg")),
        (3.5, os.path.join(FIX, "slide_a_dup.jpg")),   # near-duplicate
        (7.0, os.path.join(FIX, "slide_b.jpg")),
    ]
    survivors = fe.dedup_by_phash(pairs, max_distance=5)
    # Expect 2 frames: the first slide_a (chosen as representative) and slide_b
    assert len(survivors) == 2
    surviving_files = [os.path.basename(p) for _, p in survivors]
    assert "slide_b.jpg" in surviving_files
    # The first slide-a frame is kept; the duplicate is dropped
    assert "slide_a.jpg" in surviving_files
    assert "slide_a_dup.jpg" not in surviving_files


def test_phash_dedup_handles_empty():
    assert fe.dedup_by_phash([]) == []


def test_adaptive_threshold_buckets():
    assert fe._threshold_for_cuts(0) == 0.20
    assert fe._threshold_for_cuts(5) == 0.20
    assert fe._threshold_for_cuts(6) == 0.30
    assert fe._threshold_for_cuts(20) == 0.30
    assert fe._threshold_for_cuts(21) == 0.50
    assert fe._threshold_for_cuts(1000) == 0.50
```

- [ ] **Step 4: Verify failing**

```bash
pytest skills/full-blog/tests/test_frame_extract.py -v
```

Expected: ModuleNotFoundError.

- [ ] **Step 5: Implement phash dedup + threshold buckets**

Create `skills/full-blog/scripts/frame_extract.py`:

```python
#!/usr/bin/env python3
"""Frame extraction for full-blog skill.

Public functions:
  - detect_threshold(video_path) -> float   (samples 60s mid-video, runs ffmpeg)
  - extract_scene_cuts(video_path, threshold, output_dir) -> list[(ts_s, path)]
  - dedup_by_phash(pairs, max_distance=5) -> list[(ts_s, path)]
"""
import os
import re
import subprocess
import tempfile

import imagehash
from PIL import Image


# ---- pure helpers ---- #

def _threshold_for_cuts(cuts):
    """Map a 60-second sample's cut count to a content-aware threshold."""
    if cuts <= 5:
        return 0.20   # slide-heavy talk
    if cuts <= 20:
        return 0.30   # mixed
    return 0.50       # dynamic / vlog


def dedup_by_phash(pairs, max_distance=5):
    """Keep one representative per cluster of phash-similar frames.

    pairs: list of (timestamp_s, image_path) in chronological order.
    Returns the same shape with duplicates removed.

    Algorithm: O(n^2) scan — fine for typical n<=500. For each frame, compare
    to all already-kept frames; drop if Hamming distance to any kept frame is
    <= max_distance.
    """
    kept = []
    kept_hashes = []
    for ts, path in pairs:
        try:
            h = imagehash.phash(Image.open(path))
        except Exception:
            continue   # corrupt jpg → skip
        is_dup = any((h - kh) <= max_distance for kh in kept_hashes)
        if not is_dup:
            kept.append((ts, path))
            kept_hashes.append(h)
    return kept
```

- [ ] **Step 6: Run tests, verify phash + threshold tests pass**

```bash
pytest skills/full-blog/tests/test_frame_extract.py -v -k "phash or threshold"
```

Expected: 3 passed.

- [ ] **Step 7: Commit**

```bash
git add skills/full-blog/scripts/frame_extract.py skills/full-blog/tests/test_frame_extract.py skills/full-blog/tests/fixtures/slide_*.jpg
git commit -m "feat(full-blog): phash dedup + adaptive threshold logic (TDD)"
```

---

## Task 5: frame_extract.py — ffmpeg scene-cut + adaptive threshold (integration)

**Files:**
- Modify: `skills/full-blog/scripts/frame_extract.py`
- Modify: `skills/full-blog/tests/test_frame_extract.py`
- Create: `skills/full-blog/tests/fixtures/SOURCE.txt`

- [ ] **Step 1: Create SOURCE.txt for the fixture video**

Create `skills/full-blog/tests/fixtures/SOURCE.txt`:

```
# Public, short, slide-heavy YouTube fixture for integration tests.
# This file is committed; the .mp4 is downloaded on first test run and gitignored.
https://www.youtube.com/watch?v=Uvl-tRga98g
# Trim window: 60-150 seconds (90 s slice — pick something representative)
trim_start=60
trim_length=90
```

- [ ] **Step 2: Add ffmpeg scene-cut + threshold detection to frame_extract.py**

Append to `frame_extract.py`:

```python
# ---- subprocess wrappers ---- #

def _run(cmd, capture=False):
    """Wrapper around subprocess.run with consistent error messages."""
    res = subprocess.run(cmd, capture_output=capture, text=True)
    if res.returncode != 0:
        stderr = res.stderr if capture else ""
        raise RuntimeError(f"command failed ({res.returncode}): {' '.join(cmd)}\n{stderr}")
    return res


def _ffprobe_duration(video_path):
    res = _run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", video_path],
        capture=True,
    )
    return float(res.stdout.strip())


def _count_cuts_in_sample(video_path, start_s, length_s, threshold=0.3):
    """Run ffmpeg scene-cut on a short sample; return how many cuts it detects."""
    # showinfo prints `pts_time:` for each frame that passes select=gt(scene,θ).
    cmd = [
        "ffmpeg", "-hide_banner", "-loglevel", "info", "-y",
        "-ss", str(start_s), "-i", video_path, "-t", str(length_s),
        "-vf", f"select='gt(scene,{threshold})',scale=320:-1,showinfo",
        "-an", "-f", "null", "-",
    ]
    res = subprocess.run(cmd, capture_output=True, text=True)
    # showinfo writes to stderr in ffmpeg
    return len(re.findall(r"pts_time:\d", res.stderr))


def detect_threshold(video_path):
    """Sample a 60-second clip from the video's middle and pick a threshold."""
    duration = _ffprobe_duration(video_path)
    sample_start = max(0.0, duration / 2 - 30)
    sample_len = min(60.0, duration - sample_start)
    if sample_len <= 0:
        return 0.30   # safe default
    cuts = _count_cuts_in_sample(video_path, sample_start, sample_len, threshold=0.3)
    return _threshold_for_cuts(cuts)


def extract_scene_cuts(video_path, threshold, output_dir):
    """Run ffmpeg scene-cut over the whole video, dump frames to output_dir.

    Returns list[(timestamp_s, frame_path)] in chronological order.
    """
    os.makedirs(output_dir, exist_ok=True)
    # Use a temp pattern; we'll rename to HH_MM_SS.jpg using PTS info.
    pattern = os.path.join(output_dir, "raw_%05d.jpg")
    # We want timestamps too. metadata=print outputs per-frame timestamps to a file.
    metafile = os.path.join(output_dir, "_pts.txt")
    cmd = [
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
        "-i", video_path,
        "-vf", (
            f"select='gt(scene,{threshold})',scale=720:-1,"
            f"metadata=print:file={metafile},showinfo"
        ),
        "-vsync", "vfr", "-q:v", "2", pattern,
    ]
    subprocess.run(cmd, check=True, capture_output=True)
    # Parse the metadata file for pts_time per frame.
    pts = []
    if os.path.exists(metafile):
        for line in open(metafile, encoding="utf-8"):
            m = re.search(r"pts_time=([\d.]+)", line)
            if m:
                pts.append(float(m.group(1)))
    # Rename raw_%05d.jpg → HH_MM_SS.jpg based on pts order.
    raw_files = sorted(
        f for f in os.listdir(output_dir) if f.startswith("raw_") and f.endswith(".jpg")
    )
    pairs = []
    for i, raw in enumerate(raw_files):
        ts = pts[i] if i < len(pts) else float(i)
        ts_int = int(ts)
        new = f"{ts_int//3600:02d}_{(ts_int%3600)//60:02d}_{ts_int%60:02d}.jpg"
        old_path = os.path.join(output_dir, raw)
        new_path = os.path.join(output_dir, new)
        # Avoid collision if two frames share the same integer second
        suffix = 0
        while os.path.exists(new_path):
            suffix += 1
            stem, ext = os.path.splitext(new)
            new_path = os.path.join(output_dir, f"{stem}_{suffix}{ext}")
        os.rename(old_path, new_path)
        pairs.append((ts, new_path))
    if os.path.exists(metafile):
        os.remove(metafile)
    return pairs
```

- [ ] **Step 3: Add integration test (skipif fixture mp4 missing)**

Append to `test_frame_extract.py`:

```python
SHORT_TALK_MP4 = os.path.join(FIX, "short_talk.mp4")


def _ensure_fixture_mp4():
    """Download the fixture mp4 if not present, using yt-dlp per SOURCE.txt."""
    if os.path.exists(SHORT_TALK_MP4):
        return
    source_file = os.path.join(FIX, "SOURCE.txt")
    if not os.path.exists(source_file):
        pytest.skip("SOURCE.txt missing — cannot fetch fixture")
    url = None
    trim_start = 0
    trim_len = 90
    for line in open(source_file):
        line = line.strip()
        if line.startswith("https://"):
            url = line
        elif line.startswith("trim_start="):
            trim_start = int(line.split("=", 1)[1])
        elif line.startswith("trim_length="):
            trim_len = int(line.split("=", 1)[1])
    if not url:
        pytest.skip("No URL in SOURCE.txt")
    import subprocess
    tmp = SHORT_TALK_MP4 + ".raw.mp4"
    r = subprocess.run(
        ["yt-dlp", "-f", "mp4", "-o", tmp, url],
        capture_output=True, text=True,
    )
    if r.returncode != 0:
        pytest.skip(f"yt-dlp failed: {r.stderr[:200]}")
    # Trim with ffmpeg to keep the fixture small
    subprocess.run(
        ["ffmpeg", "-y", "-i", tmp, "-ss", str(trim_start), "-t", str(trim_len),
         "-c", "copy", SHORT_TALK_MP4],
        check=True, capture_output=True,
    )
    os.remove(tmp)


@pytest.mark.integration
def test_detect_threshold_real_video():
    _ensure_fixture_mp4()
    th = fe.detect_threshold(SHORT_TALK_MP4)
    assert th in (0.20, 0.30, 0.50)


@pytest.mark.integration
def test_extract_scene_cuts_real_video(tmp_path):
    _ensure_fixture_mp4()
    pairs = fe.extract_scene_cuts(SHORT_TALK_MP4, threshold=0.30, output_dir=str(tmp_path))
    # A 90s slide-heavy clip should produce at least 2 frames
    assert len(pairs) >= 2
    # all frames exist on disk
    for ts, path in pairs:
        assert os.path.exists(path)
        assert ts >= 0
```

- [ ] **Step 4: Run integration tests**

```bash
pytest skills/full-blog/tests/test_frame_extract.py -v -m integration
```

Expected: 2 passed (after yt-dlp downloads the fixture on first run, ~30 s).

- [ ] **Step 5: Commit**

```bash
git add skills/full-blog/scripts/frame_extract.py skills/full-blog/tests/test_frame_extract.py skills/full-blog/tests/fixtures/SOURCE.txt
git commit -m "feat(full-blog): ffmpeg scene-cut + adaptive threshold (integration tests)"
```

---

## Task 6: frame_rank.py — Gemini batched ranker (TDD, mocked)

**Files:**
- Create: `skills/full-blog/scripts/frame_rank.py`
- Create: `skills/full-blog/tests/test_frame_rank.py`
- Create: `skills/full-blog/references/ranker-prompt.md`

- [ ] **Step 1: Create the ranker prompt template**

Create `skills/full-blog/references/ranker-prompt.md`:

```markdown
# Gemini ranker prompt (tunable)

This prompt is loaded by `frame_rank.py` and rendered with the batch's
transcript window. Edit the prose freely; the JSON output schema must remain.

---

You are selecting frames for a video-to-blog conversion. The blog will be the
transcript with selected frames embedded as `<figure>` blocks.

FRAMES below span timestamps [{window_start} – {window_end}] of the source
video. TRANSCRIPT for that window:

"""
{transcript_window}
"""

For EACH attached frame, decide:

- `include` (boolean): true if the frame adds visual information the transcript
  cannot convey on its own. YES for slides, diagrams, charts, code on screen,
  process demonstrations, data visualizations. NO for talking-head shots,
  generic backgrounds, motion blur, or near-duplicates of nearby frames.
- `alt_text` (string ≤ 60 words): factual description of what is visually shown.
- `caption` (string ≤ 15 words): short caption to display under the figure.
- `confidence` (float 0.0–1.0): how confident the `include` decision is.

Output STRICT JSON array of objects, ONE PER INPUT FRAME, in the same order as
inputs. No surrounding markdown or commentary. Schema:

```json
[
  {"frame_index": 0, "include": true,  "alt_text": "...", "caption": "...", "confidence": 0.0},
  ...
]
```
```

- [ ] **Step 2: Write failing tests**

Create `skills/full-blog/tests/test_frame_rank.py`:

```python
"""Unit tests for frame_rank.py with the Gemini client mocked."""
import json
import os
import sys
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import frame_rank as fr


def _fake_gemini_response(items):
    """Return a mock that mimics google.genai responses returning JSON text."""
    m = MagicMock()
    m.text = json.dumps(items)
    return m


def test_window_transcript_text_concats_overlapping_cues():
    cues = [
        {"start": 0.0,  "end": 5.0,  "text": "A"},
        {"start": 5.0,  "end": 10.0, "text": "B"},
        {"start": 10.0, "end": 15.0, "text": "C"},
    ]
    out = fr._window_transcript(cues, win_start=4.0, win_end=11.0)
    # cues 0,1,2 all overlap [4,11]
    assert "A" in out and "B" in out and "C" in out
    out2 = fr._window_transcript(cues, win_start=11.0, win_end=12.0)
    assert out2.strip() == "C"


def test_batch_frames_by_size():
    pairs = [(float(i), f"/tmp/{i}.jpg") for i in range(25)]
    batches = list(fr._batch(pairs, size=10))
    assert len(batches) == 3
    assert len(batches[0]) == 10
    assert len(batches[1]) == 10
    assert len(batches[2]) == 5


def test_parse_ranker_response_strict_json():
    raw = '[{"frame_index":0,"include":true,"alt_text":"a","caption":"c","confidence":0.9}]'
    parsed = fr._parse_response(raw, expected_len=1)
    assert parsed[0]["include"] is True
    assert parsed[0]["alt_text"] == "a"


def test_parse_ranker_response_strips_code_fence():
    raw = '```json\n[{"frame_index":0,"include":false,"alt_text":"","caption":"","confidence":0.1}]\n```'
    parsed = fr._parse_response(raw, expected_len=1)
    assert parsed[0]["include"] is False


def test_parse_ranker_response_raises_on_length_mismatch():
    raw = '[{"frame_index":0,"include":true,"alt_text":"a","caption":"c","confidence":0.5}]'
    with pytest.raises(ValueError):
        fr._parse_response(raw, expected_len=2)


@patch("frame_rank._call_gemini")
def test_rank_frames_happy_path(mock_call):
    mock_call.return_value = [
        {"frame_index": 0, "include": True,  "alt_text": "slide A", "caption": "A", "confidence": 0.9},
        {"frame_index": 1, "include": False, "alt_text": "head",    "caption": "",  "confidence": 0.8},
    ]
    pairs = [(1.0, "/tmp/a.jpg"), (3.0, "/tmp/b.jpg")]
    cues = [{"start": 0, "end": 10, "text": "talking about A"}]
    out = fr.rank_frames(pairs, cues, model="fake", batch_size=10)
    assert len(out) == 2
    assert out[0]["include"] is True
    assert out[1]["include"] is False
    mock_call.assert_called_once()


@patch("frame_rank._call_gemini")
def test_rank_frames_graceful_degrade_on_all_failures(mock_call):
    mock_call.side_effect = RuntimeError("rate limit forever")
    pairs = [(float(i), f"/tmp/{i}.jpg") for i in range(20)]
    cues = [{"start": 0, "end": 30, "text": "..."}]
    out = fr.rank_frames(pairs, cues, model="fake", batch_size=10,
                         max_frames_final=6, allow_degrade=True)
    # graceful degrade: keeps `max_frames_final` evenly-sampled frames
    assert len(out) == 6
    assert all(o["include"] is True for o in out)
    assert all(o.get("degraded") for o in out)
```

- [ ] **Step 3: Run, verify failing**

```bash
pytest skills/full-blog/tests/test_frame_rank.py -v
```

Expected: ModuleNotFoundError.

- [ ] **Step 4: Implement frame_rank.py**

Create `skills/full-blog/scripts/frame_rank.py`:

```python
#!/usr/bin/env python3
"""Gemini-based frame ranker for full-blog skill.

Public functions:
  - rank_frames(pairs, cues, model, batch_size, max_frames_final, allow_degrade,
                api_key=None) -> list[{frame_index_global, timestamp_s, path,
                                       include, alt_text, caption, confidence,
                                       degraded?}]
  - load_prompt_template() -> str

Tests mock _call_gemini; in production it uses google-genai.
"""
import json
import os
import re
import time

# Lazy import inside _call_gemini so tests don't require the package.


PROMPT_PATH = os.path.join(
    os.path.dirname(__file__), "..", "references", "ranker-prompt.md"
)


def load_prompt_template():
    with open(PROMPT_PATH, encoding="utf-8") as f:
        text = f.read()
    # Strip the markdown title / explainer above the first horizontal rule.
    if "---" in text:
        text = text.split("---", 1)[1].strip()
    return text


def _batch(iterable, size):
    buf = []
    for x in iterable:
        buf.append(x)
        if len(buf) == size:
            yield buf
            buf = []
    if buf:
        yield buf


def _window_transcript(cues, win_start, win_end):
    parts = []
    for c in cues:
        if c["end"] >= win_start and c["start"] <= win_end:
            parts.append(c["text"])
    return " ".join(parts).strip()


def _parse_response(raw, expected_len):
    """Parse Gemini's JSON output, tolerant of code fences."""
    s = raw.strip()
    if s.startswith("```"):
        # strip ```json … ```
        s = re.sub(r"^```(?:json)?\s*", "", s)
        s = re.sub(r"\s*```$", "", s)
    data = json.loads(s)
    if not isinstance(data, list):
        raise ValueError("response is not a JSON array")
    if len(data) != expected_len:
        raise ValueError(f"expected {expected_len} entries, got {len(data)}")
    return data


def _call_gemini(model, prompt, image_paths, api_key=None):
    """Real Gemini call — separated so tests can mock it."""
    from google import genai

    client = genai.Client(api_key=api_key or os.environ.get("GEMINI_API_KEY")
                                          or os.environ.get("GOOGLE_API_KEY"))
    parts = [prompt]
    for p in image_paths:
        with open(p, "rb") as f:
            parts.append(genai.types.Part.from_bytes(data=f.read(), mime_type="image/jpeg"))
    resp = client.models.generate_content(
        model=model,
        contents=parts,
        config={"response_mime_type": "application/json"},
    )
    return _parse_response(resp.text, expected_len=len(image_paths))


def _ranker_call_with_retries(model, prompt, image_paths, max_attempts=5,
                              base_delay=2.0, api_key=None):
    last_err = None
    for attempt in range(max_attempts):
        try:
            return _call_gemini(model, prompt, image_paths, api_key=api_key)
        except Exception as e:
            last_err = e
            time.sleep(min(32.0, base_delay * (2 ** attempt)))
    # one final retry with halved batch
    if len(image_paths) > 1:
        mid = len(image_paths) // 2
        left  = _call_gemini(model, prompt, image_paths[:mid], api_key=api_key)
        right = _call_gemini(model, prompt, image_paths[mid:], api_key=api_key)
        return left + right
    raise last_err


def _even_sample(items, n):
    if n >= len(items):
        return list(items)
    step = len(items) / n
    return [items[int(i * step)] for i in range(n)]


def rank_frames(pairs, cues, model="gemini-2.5-flash", batch_size=10,
                max_frames_final=25, allow_degrade=True, api_key=None):
    """Rank frames with Gemini; return ordered results matching pairs.

    pairs : list[(timestamp_s, path)]
    cues  : list[{start, end, text}]
    """
    prompt_tmpl = load_prompt_template()
    out = []
    degraded_run = False
    for batch in _batch(pairs, batch_size):
        ts_list = [p[0] for p in batch]
        paths   = [p[1] for p in batch]
        win_start = min(ts_list)
        win_end = max(ts_list)
        prompt = prompt_tmpl.format(
            window_start=f"{int(win_start)//3600:02d}:{(int(win_start)%3600)//60:02d}:{int(win_start)%60:02d}",
            window_end=f"{int(win_end)//3600:02d}:{(int(win_end)%3600)//60:02d}:{int(win_end)%60:02d}",
            transcript_window=_window_transcript(cues, win_start, win_end),
        )
        try:
            parsed = _ranker_call_with_retries(model, prompt, paths, api_key=api_key)
        except Exception as e:
            if not allow_degrade:
                raise
            degraded_run = True
            # mark this batch's frames as degraded fallback (include all)
            parsed = [{"frame_index": i, "include": True, "alt_text": "",
                       "caption": "", "confidence": 0.0}
                      for i in range(len(batch))]
        for local_i, item in enumerate(parsed):
            ts, path = batch[local_i]
            out.append({
                "timestamp_s": ts,
                "path": path,
                "include": bool(item.get("include", False)),
                "alt_text": item.get("alt_text", ""),
                "caption":  item.get("caption", ""),
                "confidence": float(item.get("confidence", 0.0)),
            })

    if degraded_run and allow_degrade:
        # Replace with even-sampled survivors marked degraded
        sampled = _even_sample(out, max_frames_final)
        for r in sampled:
            r["include"] = True
            r["degraded"] = True
        return sampled

    # Cap to max_frames_final by confidence (descending) among `include`==True
    kept = [r for r in out if r["include"]]
    kept.sort(key=lambda r: (-r["confidence"], r["timestamp_s"]))
    return kept[:max_frames_final]
```

- [ ] **Step 5: Run all rank tests**

```bash
pytest skills/full-blog/tests/test_frame_rank.py -v
```

Expected: 7 passed.

- [ ] **Step 6: Commit**

```bash
git add skills/full-blog/scripts/frame_rank.py skills/full-blog/tests/test_frame_rank.py skills/full-blog/references/ranker-prompt.md
git commit -m "feat(full-blog): Gemini batched frame ranker with graceful degrade"
```

---

## Task 7: full_blog.py — orchestrator (CLI + per-video pipeline)

**Files:**
- Create: `skills/full-blog/scripts/full_blog.py`

- [ ] **Step 1: Write the orchestrator**

Create `skills/full-blog/scripts/full_blog.py`:

```python
#!/usr/bin/env python3
"""full-blog: YouTube URL/playlist -> HTML blog post with frames embedded.

Pipeline per video:
  1. Run transcribe.py (subprocess) to get .md + .srt.
  2. Download the video with yt-dlp to /tmp.
  3. Adaptive threshold sample -> ffmpeg scene-cut.
  4. imagehash phash dedup.
  5. Gemini batched ranker (transcript-context-aware) -> top N frames.
  6. Align frames to paragraphs via srt cues, render HTML.
  7. Copy chosen frames to <out>/<title>/, clean up temp.

Examples:
  python3 full_blog.py "https://www.youtube.com/watch?v=ID"
  python3 full_blog.py "<playlist-url>" --out-dir ./out --max-frames-per-video 20
  python3 full_blog.py "<url>" --ranker-model gemini-2.0-flash

API keys: GEMINI_API_KEY / GOOGLE_API_KEY in env or .env in CWD.
"""
import argparse
import concurrent.futures as cf
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time

# Local modules
HERE = os.path.dirname(__file__)
sys.path.insert(0, HERE)
import frame_extract as fe
import frame_rank as fr
import render_html as rh


PLUGIN_ROOT = os.environ.get("CLAUDE_PLUGIN_ROOT") or os.path.normpath(
    os.path.join(HERE, "..", "..", "..")
)
TRANSCRIBE_PY = os.path.join(PLUGIN_ROOT, "skills", "transcribe", "scripts", "transcribe.py")


def load_env():
    path = os.path.join(os.getcwd(), ".env")
    if os.path.isfile(path):
        for line in open(path, encoding="utf-8"):
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())


def safe_name(t):
    return re.sub(r"[/\\:]", "-", t).strip()


def _video_id_from_url(url):
    m = re.search(r"(?:v=|youtu\.be/)([\w\-]{11})", url)
    return m.group(1) if m else None


def _list_playlist_urls(url):
    """If url is a playlist, expand to a list of video URLs (in order); else return [url]."""
    if "list=" not in url:
        return [url]
    res = subprocess.run(
        ["yt-dlp", "--flat-playlist", "--print", "url", url],
        capture_output=True, text=True,
    )
    if res.returncode != 0:
        raise RuntimeError(f"yt-dlp playlist expand failed: {res.stderr[:200]}")
    return [line.strip() for line in res.stdout.splitlines() if line.strip()]


def _run_transcribe(url, work_dir):
    """Run the existing transcribe.py for one URL into work_dir; return (md_path, srt_path, title)."""
    out_dir = os.path.join(work_dir, "_t")
    os.makedirs(out_dir, exist_ok=True)
    res = subprocess.run(
        ["python3", TRANSCRIBE_PY, url, "--out-dir", out_dir],
        capture_output=True, text=True,
    )
    if res.returncode != 0:
        raise RuntimeError(f"transcribe.py failed: {res.stderr[:300]}")
    md_files = [f for f in os.listdir(out_dir) if f.endswith(".md")]
    if not md_files:
        raise RuntimeError("transcribe produced no .md file")
    md_path = os.path.join(out_dir, md_files[0])
    srt_path = md_path[:-3] + ".srt"
    if not os.path.exists(srt_path):
        raise RuntimeError("transcribe produced no .srt — full-blog requires timestamps")
    # Title is the H1 of the .md
    with open(md_path, encoding="utf-8") as f:
        first_line = f.readline().strip()
    title = first_line.lstrip("# ").strip() or os.path.splitext(md_files[0])[0]
    return md_path, srt_path, title


def _download_video(url, work_dir):
    """yt-dlp the video as mp4 into work_dir/video.mp4."""
    out = os.path.join(work_dir, "video.mp4")
    res = subprocess.run(
        ["yt-dlp", "-f", "best[ext=mp4]/best", "-o", out, url],
        capture_output=True, text=True,
    )
    if res.returncode != 0:
        raise RuntimeError(f"yt-dlp video failed: {res.stderr[:300]}")
    return out


def _parse_markdown_body(md_path):
    """Return list of body paragraphs (skipping H1 and source link)."""
    paragraphs = []
    cur = []
    in_body = False
    for line in open(md_path, encoding="utf-8"):
        line = line.rstrip()
        if not in_body:
            if line.startswith("# "):
                continue
            if line.startswith("[YouTube"):
                continue
            if line == "":
                continue
            in_body = True
        if line == "":
            if cur:
                paragraphs.append(" ".join(cur).strip())
                cur = []
        else:
            cur.append(line)
    if cur:
        paragraphs.append(" ".join(cur).strip())
    return paragraphs


def process_one(url, args):
    """Process a single URL end-to-end; return a dict result for the summary."""
    started = time.time()
    video_id = _video_id_from_url(url) or "unknown"
    work_dir = tempfile.mkdtemp(prefix=f"yt-ribosome-blog-{video_id}-")
    try:
        md_path, srt_path, title = _run_transcribe(url, work_dir)
        safe = safe_name(title)
        out_html = os.path.join(args.out_dir, f"{safe}.html")
        out_imgs_dir = os.path.join(args.out_dir, safe)

        if os.path.exists(out_html) and not args.force:
            return {"url": url, "title": title, "status": "skipped",
                    "reason": "output exists (use --force to overwrite)"}

        video_path = _download_video(url, work_dir)
        threshold = (args.scene_threshold
                     if args.scene_threshold is not None
                     else fe.detect_threshold(video_path))
        frames_dir = os.path.join(work_dir, "frames")
        pairs = fe.extract_scene_cuts(video_path, threshold, frames_dir)
        survivors = fe.dedup_by_phash(pairs)
        cues = rh.parse_srt(open(srt_path, encoding="utf-8").read())
        ranked = fr.rank_frames(
            survivors, cues,
            model=args.ranker_model,
            batch_size=args.batch_size,
            max_frames_final=args.max_frames_per_video,
            allow_degrade=True,
        )

        os.makedirs(out_imgs_dir, exist_ok=True)
        frames_for_render = []
        for r in ranked:
            base = os.path.basename(r["path"])
            dst = os.path.join(out_imgs_dir, base)
            shutil.copy2(r["path"], dst)
            frames_for_render.append({
                "path_rel": f"{safe}/{base}",
                "timestamp_s": r["timestamp_s"],
                "alt": r["alt_text"],
                "caption": r["caption"],
            })

        paragraphs = _parse_markdown_body(md_path)
        ranges = rh.align_paragraphs_to_srt(paragraphs, cues)
        source_url = f"https://www.youtube.com/watch?v={video_id}"
        html = rh.render_html(
            title=title, source_url=source_url, paragraphs=paragraphs,
            paragraph_ranges=ranges, frames=frames_for_render,
            video_id=video_id, image_dir=None,
        )
        os.makedirs(args.out_dir, exist_ok=True)
        with open(out_html, "w", encoding="utf-8") as f:
            f.write(html)

        return {
            "url": url, "title": title, "status": "ok",
            "frames_candidates": len(pairs),
            "frames_after_dedup": len(survivors),
            "frames_final": len(ranked),
            "output": out_html,
            "elapsed_s": round(time.time() - started, 1),
            "degraded": any(r.get("degraded") for r in ranked),
        }
    except Exception as e:
        return {"url": url, "status": "failed", "reason": str(e),
                "elapsed_s": round(time.time() - started, 1)}
    finally:
        if not args.keep_temp:
            shutil.rmtree(work_dir, ignore_errors=True)


def main():
    load_env()
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0],
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("url", help="YouTube video or playlist URL")
    ap.add_argument("--out-dir", default="blogs")
    ap.add_argument("--ranker-model", default="gemini-2.5-flash",
                    help="gemini-2.5-flash (default) or gemini-2.0-flash (cheaper)")
    ap.add_argument("--max-frames-per-video", type=int, default=25)
    ap.add_argument("--batch-size", type=int, default=10)
    ap.add_argument("--scene-threshold", type=float, default=None,
                    help="Override adaptive threshold (e.g. 0.3)")
    ap.add_argument("--workers", type=int, default=2)
    ap.add_argument("--keep-temp", action="store_true")
    ap.add_argument("--force", action="store_true",
                    help="Overwrite existing .html outputs")
    args = ap.parse_args()

    urls = _list_playlist_urls(args.url)
    print(f"full-blog: {len(urls)} video(s)", flush=True)
    results = []
    with cf.ThreadPoolExecutor(max_workers=max(1, args.workers)) as pool:
        futs = {pool.submit(process_one, u, args): u for u in urls}
        for i, fut in enumerate(cf.as_completed(futs), 1):
            r = fut.result()
            results.append(r)
            tag = r["status"].upper()
            extra = ""
            if r["status"] == "ok":
                extra = (f"  {r['frames_candidates']} -> {r['frames_after_dedup']} -> "
                         f"{r['frames_final']} frames | {r['elapsed_s']}s"
                         f"{' [DEGRADED]' if r['degraded'] else ''}")
            elif r["status"] == "failed":
                extra = f"  reason: {r['reason'][:200]}"
            elif r["status"] == "skipped":
                extra = f"  {r['reason']}"
            print(f"[{i}/{len(urls)}] {tag} {r.get('title') or r['url']}{extra}", flush=True)

    ok = sum(1 for r in results if r["status"] == "ok")
    failed = sum(1 for r in results if r["status"] == "failed")
    skipped = sum(1 for r in results if r["status"] == "skipped")
    print(f"FULL_BLOG_DONE  ok={ok} failed={failed} skipped={skipped}", flush=True)

    # Write a machine-readable summary
    summary_path = os.path.join(args.out_dir, "_run_summary.json")
    os.makedirs(args.out_dir, exist_ok=True)
    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Smoke check the script imports cleanly**

```bash
python3 -c "import sys; sys.path.insert(0, 'skills/full-blog/scripts'); import full_blog; print('imports ok')"
```

Expected: `imports ok`.

- [ ] **Step 3: Run end-to-end against a real (short) URL**

```bash
cd /tmp
mkdir -p test-blog && cd test-blog
python3 "/Users/new/Documents/Code w: Claudes/yt-ribosome/skills/full-blog/scripts/full_blog.py" \
  "https://www.youtube.com/watch?v=Uvl-tRga98g" \
  --max-frames-per-video 5 --workers 1 2>&1 | tail -20
```

Expected: `FULL_BLOG_DONE ok=1 failed=0 skipped=0` and `blogs/01 - ....html` exists.

- [ ] **Step 4: Commit**

```bash
cd /Users/new/Documents/Code\ w\:\ Claudes/yt-ribosome
git add skills/full-blog/scripts/full_blog.py
git commit -m "feat(full-blog): orchestrator script (transcribe + frames + render)"
```

---

## Task 8: SKILL.md and references/usage.md

**Files:**
- Modify: `skills/full-blog/SKILL.md`
- Create: `skills/full-blog/references/usage.md`

- [ ] **Step 1: Write SKILL.md**

Replace `skills/full-blog/SKILL.md` with:

```markdown
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
```

- [ ] **Step 2: Write references/usage.md**

Create `skills/full-blog/references/usage.md`:

```markdown
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
```

- [ ] **Step 3: Commit**

```bash
git add skills/full-blog/SKILL.md skills/full-blog/references/usage.md
git commit -m "docs(full-blog): SKILL.md and usage reference"
```

---

## Task 9: translate.py — extend with HTML support

**Files:**
- Modify: `skills/translate/scripts/translate.py`
- Create: `skills/translate/tests/test_translate_html.py`

- [ ] **Step 1: Write failing test for HTML detection + node extraction**

Create `skills/translate/tests/test_translate_html.py`:

```python
"""Tests for the HTML path of translate.py (no LLM call — _translate_html_nodes mocked)."""
import os
import sys
from unittest.mock import patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import translate as tr


HTML_SAMPLE = """<!DOCTYPE html>
<html lang="en">
<head><title>My Talk</title></head>
<body>
<article>
<h1>Welcome</h1>
<p class="source"><a href="https://www.youtube.com/watch?v=abc">▶ Watch on YouTube</a></p>
<p>Hello everyone.</p>
<figure data-timestamp="00:00:15">
  <a href="https://www.youtube.com/watch?v=abc&t=15">
    <img src="My Talk/00_00_15.jpg" alt="Speaker showing a slide" loading="lazy">
  </a>
  <figcaption>Intro slide <a class="ts-link" href="https://www.youtube.com/watch?v=abc&t=15">(00:15)</a></figcaption>
</figure>
<p>Some <code>code</code> here should not be translated.</p>
</article>
</body>
</html>
"""


def test_extract_translatable_nodes():
    nodes = tr._extract_html_nodes(HTML_SAMPLE)
    kinds = [n["kind"] for n in nodes]
    texts = [n["text"] for n in nodes]
    # Title, h1, p (source link text), p, alt, figcaption — but NOT code content
    assert "title" in kinds
    assert any(t == "Welcome" for t in texts)
    assert any(t == "Hello everyone." for t in texts)
    assert any(t == "Speaker showing a slide" for t in texts)
    # 'code' content should NOT appear as its own node
    assert not any(t == "code" for t in texts)


@patch("translate._call_html_batch")
def test_translate_html_full_roundtrip(mock_call):
    # Mock returns Korean translations preserving ids
    def fake_call(nodes_json, *args, **kwargs):
        import json as _j
        nodes = _j.loads(nodes_json)
        translated = []
        for n in nodes:
            t = n["text"]
            if t == "Welcome":               t = "환영합니다"
            elif t == "Hello everyone.":     t = "안녕하세요 여러분."
            elif "Speaker showing" in t:     t = "슬라이드를 보여주는 발표자"
            elif "Intro slide" in t:         t = "도입부 슬라이드"
            translated.append({"id": n["id"], "kind": n["kind"], "text": t})
        return translated
    mock_call.side_effect = fake_call

    out = tr._translate_html(HTML_SAMPLE, "Korean")
    assert "환영합니다" in out
    assert "안녕하세요 여러분." in out
    # alt was translated
    assert 'alt="슬라이드를 보여주는 발표자"' in out
    # link target preserved
    assert "https://www.youtube.com/watch?v=abc" in out
    # img src preserved
    assert "My Talk/00_00_15.jpg" in out
```

- [ ] **Step 2: Verify failing**

```bash
mkdir -p skills/translate/tests
pytest skills/translate/tests/test_translate_html.py -v
```

Expected: AttributeError on missing functions.

- [ ] **Step 3: Add HTML helpers to translate.py**

Append to `skills/translate/scripts/translate.py` (before `def main()`):

```python
# --------------------------------------------------------------------------- #
# HTML translation path (v0.2.0)
# --------------------------------------------------------------------------- #

_HTML_SKIP_TAGS = {"code", "pre", "script", "style"}
_HTML_TEXT_TAGS = {"p", "li", "h1", "h2", "h3", "h4", "h5", "h6",
                   "figcaption", "title", "blockquote", "em", "strong", "a"}
_STOCK_LINK_TEXTS = {"▶ Watch on YouTube"}


def _extract_html_nodes(html_text):
    """Return list[{id, kind, text}] of translatable text in source order.

    Skips <code>, <pre>, <script>, <style> and timestamp/anchor tags.
    Walks <img alt> attributes too.
    """
    try:
        from bs4 import BeautifulSoup, NavigableString
    except ImportError:
        raise RuntimeError("beautifulsoup4 required for HTML translation: pip install beautifulsoup4")
    soup = BeautifulSoup(html_text, "html.parser")
    nodes = []
    nid = 0
    seen_text_nodes = set()

    def add(kind, text):
        nonlocal nid
        text = text.strip()
        if not text:
            return None
        if text in _STOCK_LINK_TEXTS:
            return None
        nodes.append({"id": nid, "kind": kind, "text": text})
        nid += 1
        return nid - 1

    # Walk all elements whose tag we want to consider
    for el in soup.find_all(True):
        if el.name in _HTML_SKIP_TAGS:
            continue
        if el.name in _HTML_TEXT_TAGS:
            # Combine direct-child strings (skip nested skip tags)
            parts = []
            for child in el.children:
                if isinstance(child, NavigableString):
                    parts.append(str(child))
                else:
                    if child.name in _HTML_SKIP_TAGS:
                        parts.append("")   # placeholder
            text = "".join(parts).strip()
            if text:
                node_id = add(el.name, text)
                if node_id is not None:
                    seen_text_nodes.add(id(el))
        if el.name == "img":
            alt = el.get("alt")
            if alt:
                add("alt", alt)
    return nodes


def _build_translate_prompt(nodes, target):
    import json as _j
    schema_example = (
        '[{"id": 0, "kind": "p", "text": "..."}, '
        '{"id": 1, "kind": "alt", "text": "..."}]'
    )
    return f"""Translate each `text` field below to {target}. Preserve `id` and `kind` exactly.
Return STRICT JSON array of the same length and same `id` order.

Rules:
- Conversational, natural {target}. Match the speaker's register.
- Preserve proper nouns (Claude, Anthropic, OpenAI, MCP) as-is.
- Preserve numbers and timestamp patterns like "(03:12)".
- `kind: "alt"`     → keep concise (≤60 words).
- `kind: "caption"` → keep short (≤15 words).
- Fix obvious ASR errors silently (e.g., "Cloud" → "Claude" in Anthropic context).
- Output ONLY the JSON array — no markdown fences, no commentary.

Schema example: {schema_example}

INPUT:
{_j.dumps(nodes, ensure_ascii=False)}
"""


def _call_html_batch(nodes_json, target, provider, model):
    """Send a batch to the LLM; return list of translated nodes (same id set).

    Separated so tests can mock it.
    """
    import json as _j
    nodes = _j.loads(nodes_json)
    prompt = _build_translate_prompt(nodes, target)

    if provider == "openai":
        from openai import OpenAI
        client = OpenAI()
        resp = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
        )
        text = resp.choices[0].message.content
        # OpenAI's json_object mode returns an object; wrap-or-unwrap if needed.
        data = _j.loads(text)
        if isinstance(data, dict) and "items" in data:
            data = data["items"]
        if isinstance(data, dict) and "translations" in data:
            data = data["translations"]
    else:
        from google import genai
        client = genai.Client(api_key=os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY"))
        resp = client.models.generate_content(
            model=model,
            contents=prompt,
            config={"response_mime_type": "application/json"},
        )
        data = _j.loads(resp.text)
        if isinstance(data, dict) and "items" in data:
            data = data["items"]

    if not isinstance(data, list):
        raise RuntimeError(f"translator returned non-array: {type(data).__name__}")
    if len(data) != len(nodes):
        raise RuntimeError(f"length mismatch: {len(data)} vs {len(nodes)}")
    return data


def _translate_html(html_text, target, provider="openai", model=None,
                    batch_size=120):
    import json as _j
    try:
        from bs4 import BeautifulSoup, NavigableString
    except ImportError:
        raise RuntimeError("beautifulsoup4 required: pip install beautifulsoup4")

    nodes = _extract_html_nodes(html_text)
    if not nodes:
        return html_text

    # Batch
    translated_all = {}
    for i in range(0, len(nodes), batch_size):
        batch = nodes[i:i + batch_size]
        items = _call_html_batch(_j.dumps(batch, ensure_ascii=False),
                                 target, provider, model)
        for it in items:
            translated_all[it["id"]] = it["text"]

    # Rewrite the HTML by walking the same tags in the same order
    soup = BeautifulSoup(html_text, "html.parser")
    next_id = 0
    for el in soup.find_all(True):
        if el.name in _HTML_SKIP_TAGS:
            continue
        if el.name in _HTML_TEXT_TAGS:
            parts = list(el.children)
            text_indices = [j for j, c in enumerate(parts) if isinstance(c, NavigableString) and str(c).strip()]
            if text_indices:
                # Replace just the first text run with the translation; clear others.
                if next_id in translated_all:
                    new_text = translated_all[next_id]
                    el.contents[text_indices[0]].replace_with(NavigableString(new_text))
                    for j in text_indices[1:]:
                        el.contents[j].replace_with(NavigableString(""))
                    next_id += 1
        if el.name == "img":
            alt = el.get("alt")
            if alt and alt.strip() and next_id in translated_all:
                el["alt"] = translated_all[next_id]
                next_id += 1
    return str(soup)
```

- [ ] **Step 4: Wire the HTML path into `main()`**

Modify the file-collection loop in `translate.py`'s `main()` so that `.html`
files are processed via `_translate_html` instead of the existing markdown
path. Find the existing `jobs = ...` block in `main()` and adapt:

In the existing `translate.py`, wherever `translate_file` is called for a job,
add a check: if `src.endswith(".html")`, call `_translate_html` and write to a
`.<lang>.html` output. Concretely, replace the inner translator dispatch with:

```python
def translate_file(provider, src, dst, target, skip_detect):
    """Dispatch by file extension."""
    if src.lower().endswith(".html"):
        with open(src, encoding="utf-8") as f:
            html_text = f.read()
        out = _translate_html(html_text, target, provider=provider, model=None)
        with open(dst, "w", encoding="utf-8") as f:
            f.write(out)
        return f"translated {os.path.basename(src)} -> {os.path.basename(dst)}"
    # ... existing markdown path unchanged ...
```

Also update the output suffix calculation:

```python
# in main():
stem, ext = os.path.splitext(args.input)
# Insert language slug BEFORE the extension regardless of .md or .html
dst = f"{stem}.{slug(args.to)}{ext}"
```

(The existing code already does this — `.html` will become `.ko.html`
automatically with no further change.)

Also update the `--input` glob and existence-checks to include `.html`:

```python
files = sorted(glob.glob(os.path.join(args.input, "*.md"))
               + glob.glob(os.path.join(args.input, "*.txt"))
               + glob.glob(os.path.join(args.input, "*.html")))
```

- [ ] **Step 5: Run tests**

```bash
pytest skills/translate/tests/test_translate_html.py -v
```

Expected: 2 passed.

- [ ] **Step 6: Commit**

```bash
git add skills/translate/scripts/translate.py skills/translate/tests/test_translate_html.py
git commit -m "feat(translate): HTML support via bs4 + JSON batched node translation"
```

---

## Task 10: Fixture corpus and end-to-end test

**Files:**
- Create: `skills/full-blog/tests/fixtures/short_talk.srt`
- Create: `skills/full-blog/tests/fixtures/short_talk.md`
- Create: `skills/full-blog/tests/fixtures/expected_post.html`
- Create: `skills/full-blog/tests/test_e2e.py`

- [ ] **Step 1: Generate the committed fixture text files**

Run once locally to populate `short_talk.srt` and `short_talk.md` from the
fixture mp4 by invoking transcribe.py:

```bash
cd /Users/new/Documents/Code\ w\:\ Claudes/yt-ribosome
python3 skills/transcribe/scripts/transcribe.py \
  "https://www.youtube.com/watch?v=Uvl-tRga98g" \
  --out-dir /tmp/_short_talk_t
# Pick the file that corresponds to the trimmed 60-150s window. If transcribe
# wrote a full transcript, you can manually trim the .md/.srt to that window,
# OR generate srt/md from short_talk.mp4 directly via whisper:
python3 -c "
from openai import OpenAI; c=OpenAI()
with open('skills/full-blog/tests/fixtures/short_talk.mp4','rb') as f:
    r=c.audio.transcriptions.create(model='gpt-4o-transcribe', file=f, response_format='srt')
open('skills/full-blog/tests/fixtures/short_talk.srt','w').write(r)
"
# Then convert srt → md paragraphs by hand or with a tiny one-liner.
```

Commit them:

```bash
git add skills/full-blog/tests/fixtures/short_talk.srt skills/full-blog/tests/fixtures/short_talk.md
git commit -m "test(full-blog): fixture srt + md for short_talk"
```

- [ ] **Step 2: Write the end-to-end test (mocked Gemini)**

Create `skills/full-blog/tests/test_e2e.py`:

```python
"""End-to-end test for the full-blog pipeline with Gemini mocked."""
import json
import os
import shutil
import sys
import tempfile
from unittest.mock import patch

import pytest

HERE = os.path.dirname(__file__)
sys.path.insert(0, os.path.join(HERE, "..", "scripts"))
import frame_extract as fe
import frame_rank as fr
import render_html as rh

FIX = os.path.join(HERE, "fixtures")
SHORT_TALK_MP4 = os.path.join(FIX, "short_talk.mp4")
SHORT_TALK_SRT = os.path.join(FIX, "short_talk.srt")
SHORT_TALK_MD  = os.path.join(FIX, "short_talk.md")
EXPECTED_HTML  = os.path.join(FIX, "expected_post.html")


def _ensure_fixtures():
    if not os.path.exists(SHORT_TALK_MP4):
        pytest.skip("short_talk.mp4 missing — run integration suite once to download")
    if not (os.path.exists(SHORT_TALK_SRT) and os.path.exists(SHORT_TALK_MD)):
        pytest.skip("committed fixture text files missing")


@pytest.mark.integration
def test_pipeline_end_to_end_with_mocked_ranker(tmp_path):
    _ensure_fixtures()

    # 1. real ffmpeg
    th = fe.detect_threshold(SHORT_TALK_MP4)
    frames_dir = tmp_path / "frames"
    pairs = fe.extract_scene_cuts(SHORT_TALK_MP4, th, str(frames_dir))
    assert len(pairs) >= 2

    # 2. real phash
    survivors = fe.dedup_by_phash(pairs)
    assert len(survivors) >= 1

    # 3. mocked Gemini — keep every survivor with a stable caption
    with patch("frame_rank._call_gemini") as mock_call:
        def fake_call(model, prompt, image_paths, api_key=None):
            return [{"frame_index": i, "include": True,
                     "alt_text": f"alt-{i}", "caption": f"cap-{i}",
                     "confidence": 0.9}
                    for i in range(len(image_paths))]
        mock_call.side_effect = fake_call
        cues = rh.parse_srt(open(SHORT_TALK_SRT, encoding="utf-8").read())
        ranked = fr.rank_frames(survivors, cues, model="fake", batch_size=10,
                                max_frames_final=5, allow_degrade=False)
    assert len(ranked) <= 5
    assert all(r["include"] for r in ranked)

    # 4. real render
    paragraphs = [
        p.strip() for p in open(SHORT_TALK_MD, encoding="utf-8")
                              .read().split("\n\n") if p.strip()
        and not p.startswith("# ") and not p.startswith("[YouTube")
    ]
    ranges = rh.align_paragraphs_to_srt(paragraphs, cues)
    frames_for_render = [
        {"path_rel": f"short_talk/{os.path.basename(r['path'])}",
         "timestamp_s": r["timestamp_s"], "alt": r["alt_text"],
         "caption": r["caption"]}
        for r in ranked
    ]
    html = rh.render_html(
        title="Short Talk", source_url="https://www.youtube.com/watch?v=abc",
        paragraphs=paragraphs, paragraph_ranges=ranges,
        frames=frames_for_render, video_id="abc",
    )
    # Sanity: contains expected structural elements
    assert html.startswith("<!DOCTYPE html>")
    assert "<article>" in html
    assert "<h1>Short Talk</h1>" in html
    assert html.count("<figure") == len(ranked)
```

- [ ] **Step 3: Generate `expected_post.html` from a real successful run**

Run the test once with logging, capture the rendered HTML, and commit it as
the golden file:

```bash
pytest skills/full-blog/tests/test_e2e.py -v -m integration --capture=no
# manually inspect tmp_path output; copy the working post.html to:
#   skills/full-blog/tests/fixtures/expected_post.html
git add skills/full-blog/tests/fixtures/expected_post.html
git commit -m "test(full-blog): golden expected_post.html"
```

- [ ] **Step 4: Run the full test matrix**

```bash
pytest skills/full-blog/tests/ -v
```

Expected: all unit tests pass; integration tests pass if fixture mp4 is
present, otherwise skip.

- [ ] **Step 5: Commit**

```bash
git add skills/full-blog/tests/test_e2e.py
git commit -m "test(full-blog): mocked-Gemini end-to-end pipeline test"
```

---

## Task 11: Cost ceiling, per-video resume, ranker cache (spec §8.2 + §8.4)

**Files:**
- Modify: `skills/full-blog/scripts/full_blog.py`
- Modify: `skills/full-blog/scripts/frame_rank.py`
- Modify: `skills/full-blog/tests/test_frame_rank.py`

- [ ] **Step 1: Add `--max-cost-usd` and `--no-resume` flags to argparse**

In `skills/full-blog/scripts/full_blog.py`, add after the existing `--force` line in `main()`:

```python
ap.add_argument("--max-cost-usd", type=float, default=1.00,
                help="Stop the run if estimated total Gemini cost exceeds this.")
ap.add_argument("--no-resume", action="store_true",
                help="Do not reuse existing /tmp/yt-ribosome-blog-* directories.")
```

- [ ] **Step 2: Implement per-video temp-resume in `process_one`**

Replace the `tempfile.mkdtemp(...)` line in `process_one` with:

```python
video_id = _video_id_from_url(url) or "unknown"
fixed_temp = f"/tmp/yt-ribosome-blog-{video_id}"
if (not args.no_resume) and os.path.isdir(fixed_temp):
    work_dir = fixed_temp
    resumed = True
else:
    work_dir = tempfile.mkdtemp(prefix=f"yt-ribosome-blog-{video_id}-")
    resumed = False
```

In the inner `try:` block, replace the unconditional `_download_video(url, work_dir)` with:

```python
video_path = os.path.join(work_dir, "video.mp4")
if not (resumed and os.path.exists(video_path) and os.path.getsize(video_path) > 1_000_000):
    video_path = _download_video(url, work_dir)
```

- [ ] **Step 3: Implement cost estimation + ceiling**

Add module-level constants and a helper to `full_blog.py` (place above `process_one`):

```python
# Conservative per-image cost estimates (input-token-based; outputs negligible).
# Values are upper bounds; actual will be lower.
_COST_PER_IMAGE_USD = {
    "gemini-2.0-flash": 0.00012,
    "gemini-2.5-flash": 0.00036,
    "gpt-4o":           0.00210,
    "gpt-4o-mini":      0.00400,
    "claude-haiku-4.5": 0.00120,
}


def _estimate_video_cost(num_frames, model):
    per = _COST_PER_IMAGE_USD.get(model, 0.00036)
    return num_frames * per * 1.3   # 30% padding for prompt/text tokens
```

In `process_one`, after `survivors = fe.dedup_by_phash(pairs)`, before the `fr.rank_frames(...)` call, add:

```python
est_cost = _estimate_video_cost(len(survivors), args.ranker_model)
# accumulated check is enforced at the orchestrator level via shared counter (see main())
```

Return `est_cost` in the result dict:

```python
return {
    "url": url, "title": title, "status": "ok",
    ...
    "est_cost_usd": round(est_cost, 4),
    ...
}
```

In `main()`, replace the existing thread-pool loop with a serial cost-aware loop (preserves `--workers` semantics but checks the ceiling between completed videos):

```python
spent = 0.0
results = []
with cf.ThreadPoolExecutor(max_workers=max(1, args.workers)) as pool:
    futs = {pool.submit(process_one, u, args): u for u in urls}
    for i, fut in enumerate(cf.as_completed(futs), 1):
        r = fut.result()
        results.append(r)
        spent += r.get("est_cost_usd") or 0
        # cost ceiling check — non-blocking, only warns; user can Ctrl-C
        if spent > args.max_cost_usd:
            print(f"!! Estimated spend ${spent:.2f} exceeded --max-cost-usd "
                  f"${args.max_cost_usd:.2f}. Press Ctrl-C to stop or wait for "
                  f"remaining videos to finish.", flush=True)
        tag = r["status"].upper()
        ...   # existing print line
```

- [ ] **Step 4: Implement ranker cache in `frame_rank.py`**

Add to `frame_rank.py`:

```python
def _load_cache(cache_path):
    if not cache_path or not os.path.exists(cache_path):
        return {}
    try:
        return json.loads(open(cache_path, encoding="utf-8").read())
    except Exception:
        return {}


def _save_cache(cache_path, cache):
    if not cache_path:
        return
    try:
        with open(cache_path, "w", encoding="utf-8") as f:
            json.dump(cache, f, ensure_ascii=False)
    except Exception:
        pass


def _phash_key(path):
    """Return a stable string key for an image, used as ranker-cache key."""
    try:
        return str(imagehash.phash(Image.open(path)))
    except Exception:
        return path   # fall back to path; safer than crashing
```

Note: `frame_rank.py` doesn't currently import imagehash/PIL. Add at the top:

```python
import imagehash
from PIL import Image
```

Update `rank_frames` signature and body to accept and use the cache:

```python
def rank_frames(pairs, cues, model="gemini-2.5-flash", batch_size=10,
                max_frames_final=25, allow_degrade=True, api_key=None,
                cache_path=None):
    prompt_tmpl = load_prompt_template()
    cache = _load_cache(cache_path)
    out = []
    degraded_run = False
    for batch in _batch(pairs, batch_size):
        ts_list = [p[0] for p in batch]
        paths   = [p[1] for p in batch]
        keys    = [_phash_key(p) for p in paths]

        # Cache hits → skip LLM call for this frame
        cached_results = [cache.get(k) for k in keys]
        missing_indices = [i for i, c in enumerate(cached_results) if c is None]

        if missing_indices:
            win_start = min(ts_list[i] for i in missing_indices)
            win_end   = max(ts_list[i] for i in missing_indices)
            miss_paths = [paths[i] for i in missing_indices]
            prompt = prompt_tmpl.format(
                window_start=f"{int(win_start)//3600:02d}:{(int(win_start)%3600)//60:02d}:{int(win_start)%60:02d}",
                window_end=f"{int(win_end)//3600:02d}:{(int(win_end)%3600)//60:02d}:{int(win_end)%60:02d}",
                transcript_window=_window_transcript(cues, win_start, win_end),
            )
            try:
                parsed = _ranker_call_with_retries(model, prompt, miss_paths, api_key=api_key)
            except Exception:
                if not allow_degrade:
                    raise
                degraded_run = True
                parsed = [{"frame_index": j, "include": True, "alt_text": "",
                           "caption": "", "confidence": 0.0}
                          for j in range(len(miss_paths))]
            # write into cache
            for j, miss_i in enumerate(missing_indices):
                cache[keys[miss_i]] = parsed[j]
                cached_results[miss_i] = parsed[j]

        for local_i, item in enumerate(cached_results):
            ts, path = batch[local_i]
            out.append({
                "timestamp_s": ts,
                "path": path,
                "include": bool(item.get("include", False)),
                "alt_text": item.get("alt_text", ""),
                "caption":  item.get("caption", ""),
                "confidence": float(item.get("confidence", 0.0)),
            })

    _save_cache(cache_path, cache)

    if degraded_run and allow_degrade:
        sampled = _even_sample(out, max_frames_final)
        for r in sampled:
            r["include"] = True
            r["degraded"] = True
        return sampled

    kept = [r for r in out if r["include"]]
    kept.sort(key=lambda r: (-r["confidence"], r["timestamp_s"]))
    return kept[:max_frames_final]
```

Plumb the cache path through `process_one` in `full_blog.py`:

```python
ranked = fr.rank_frames(
    survivors, cues,
    model=args.ranker_model,
    batch_size=args.batch_size,
    max_frames_final=args.max_frames_per_video,
    allow_degrade=True,
    cache_path=os.path.join(work_dir, "ranker_cache.json"),
)
```

- [ ] **Step 5: Add tests for the new behaviors**

Append to `skills/full-blog/tests/test_frame_rank.py`:

```python
def test_ranker_cache_round_trip(tmp_path, monkeypatch):
    cache_path = tmp_path / "cache.json"

    def fake_phash(img):
        # tie key to filename for determinism
        class H:
            def __init__(self, s): self.s = s
            def __str__(self): return self.s
        # access caller's path via PIL._original_open
        return H("HASH-FAKE")
    monkeypatch.setattr(fr, "imagehash", type("_", (), {"phash": fake_phash}))
    monkeypatch.setattr(fr, "Image", type("_", (), {"open": lambda p: p}))

    call_count = {"n": 0}
    def fake_call(model, prompt, paths, api_key=None):
        call_count["n"] += 1
        return [{"frame_index": i, "include": True, "alt_text": "x",
                 "caption": "y", "confidence": 0.5} for i in range(len(paths))]

    with patch("frame_rank._call_gemini", side_effect=fake_call):
        cues = [{"start": 0, "end": 30, "text": "hi"}]
        pairs = [(1.0, "/tmp/a.jpg")]
        out1 = fr.rank_frames(pairs, cues, model="fake", batch_size=10,
                              cache_path=str(cache_path), allow_degrade=False)
        # second call should hit cache; same key
        out2 = fr.rank_frames(pairs, cues, model="fake", batch_size=10,
                              cache_path=str(cache_path), allow_degrade=False)

    assert len(out1) == 1
    assert len(out2) == 1
    assert call_count["n"] == 1   # second invocation used cache
```

- [ ] **Step 6: Run tests**

```bash
pytest skills/full-blog/tests/test_frame_rank.py -v
```

Expected: 8 passed (7 prior + 1 new).

- [ ] **Step 7: Commit**

```bash
git add skills/full-blog/scripts/full_blog.py skills/full-blog/scripts/frame_rank.py skills/full-blog/tests/test_frame_rank.py
git commit -m "feat(full-blog): cost ceiling + per-video resume + ranker cache"
```

---

## Task 12: README update and final commit

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Update the Skills table and feature list**

In `README.md`, find the Skills table (around line 46–50) and add the
`full-blog` row:

```markdown
| Skill | What it does | Say something like |
|-------|--------------|--------------------|
| **`transcribe`** | YouTube → original-language Markdown | "transcribe this video/playlist", "유튜브 트랜스크립트 받아줘" |
| **`translate`** | transcript/Markdown/HTML files → target language | "translate these to Korean", "한국어로 번역해줘" |
| **`transcribe-and-translate`** | both, end to end | "transcribe this and translate it to Korean" |
| **`full-blog`** | YouTube → HTML blog with embedded frame snapshots | "make a full blog from this video", "유튜브 영상을 블로그로 변환해줘" |
```

Replace the "Embedding image coming up for next version." line with a brief
section pointing at the `full-blog` skill. Add to the Prerequisites table:

```markdown
| `imagehash`, `Pillow` | full-blog: frame deduplication |
| `beautifulsoup4` | translate: HTML support |
```

Add a one-paragraph section after "Features":

```markdown
## Full-Blog Output

`full-blog` produces a self-contained HTML page with the transcript and ~10–25
meaningful frames embedded inline at the timestamp each frame was captured.
Click any frame to jump to that moment on YouTube. Translate the result with
`translate` to ship Korean (or any language) blogs.
```

- [ ] **Step 2: Verify README renders cleanly**

```bash
grep -n "full-blog" README.md
```

Expected: at least 4 hits (table row, prerequisite, section, link).

- [ ] **Step 3: Final smoke test**

```bash
cd /tmp && rm -rf release-test && mkdir release-test && cd release-test
python3 "/Users/new/Documents/Code w: Claudes/yt-ribosome/skills/full-blog/scripts/full_blog.py" \
  "https://www.youtube.com/watch?v=Uvl-tRga98g" \
  --max-frames-per-video 5 --workers 1
ls -la blogs/
```

Expected: an `.html` file + matching folder with ≤ 5 jpgs.

- [ ] **Step 4: Translate the result to confirm cross-skill works**

```bash
cd /tmp/release-test
python3 "/Users/new/Documents/Code w: Claudes/yt-ribosome/skills/translate/scripts/translate.py" \
  blogs/ --to Korean --provider gemini
ls -la blogs/*.ko.html
```

Expected: `.ko.html` exists; opening it in a browser shows translated text and
the same images.

- [ ] **Step 5: Final commit + version tag**

```bash
cd /Users/new/Documents/Code\ w\:\ Claudes/yt-ribosome
git add README.md
git commit -m "docs: README updates for full-blog (v0.2.0)"
git tag -a v0.2.0 -m "v0.2.0 — full-blog skill with frame embedding"
# Do NOT push yet — user reviews before push.
```

---

## Self-review checklist

Run this after the plan is implemented, before opening a PR:

- [ ] All tests pass: `pytest skills/full-blog/tests/ skills/translate/tests/ -v`
- [ ] Smoke test produced an `.html` + image folder from a real YouTube URL
- [ ] Translated `.ko.html` opens with translated text and preserved images
- [ ] `_run_summary.json` is written and contains all expected fields
- [ ] No `print()` debug statements left in scripts
- [ ] Plugin manifest version is `0.2.0`
- [ ] README mentions `full-blog` in 4+ places (table, features, prereq, deps)

---

## Risks and mitigations (carry-over from spec §10)

| Risk | Mitigation |
|---|---|
| transcribe.py subprocess overhead inflates per-video time | Acceptable for v0.2.0 (~5 s overhead). Library-mode extraction in v0.3 if painful. |
| Gemini ranker quality regresses on niche content types | Prompt is in `references/ranker-prompt.md` for fast iteration; cost is low enough for A/B testing. |
| BeautifulSoup may shuffle HTML whitespace on re-serialize | Tested in `test_translate_html.py`; visual diff via opening file in browser. |
| Token-overlap alignment fails on heavily edited transcripts | Falls back to "Additional frames" section so frames are not lost. |

---

## Execution handoff

Plan complete and saved to `docs/superpowers/plans/2026-05-27-full-blog-maker.md`.
Two execution options:

**1. Subagent-Driven (recommended)** — Each task runs in a fresh subagent with
its own context window. Two-stage review (one subagent implements, another
reviews the diff) between tasks. Best for large changes where one mistake
shouldn't compound.

**2. Inline Execution** — Run tasks in this session via `superpowers:executing-plans`.
Batch through tasks with checkpoints. Faster, less ceremony, but accumulates
context.

Which approach?
