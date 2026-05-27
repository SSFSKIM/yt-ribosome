#!/usr/bin/env python3
"""HTML rendering for full-blog skill.

Pure functions (no network, no subprocess):
  - parse_srt(text) -> list[{start, end, text}]
  - align_paragraphs_to_srt(paragraphs, cues) -> list[{p_idx, start, end}]
  - pick_paragraph_for_frame(timestamp_s, paragraph_ranges) -> int (-1 if none)
  - render_html(title, source_url, paragraphs, frames, image_dir) -> str (html)

The HTML template implements the "Humanist Creator" design system: a warm,
editorial reading layout with Plus Jakarta Sans (display) + Literata (body),
terracotta accents on a cream surface. The script only produces the
*skeleton* — paragraphs are emitted flat with `data-srt-start` time anchors
so the calling agent can re-group them into thematic <h2> sections, add a
lead paragraph, etc., as a separate post-processing step described in
SKILL.md.
"""
import html as html_lib
import re
import urllib.parse


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
        consumed = []
        while cue_idx < len(cues):
            c_toks = _tokens(cues[cue_idx]["text"])
            if not c_toks:
                cue_idx += 1
                continue
            overlap = len(c_toks & p_toks) / max(1, len(c_toks))
            if overlap >= 0.4 or not consumed:
                consumed.append(cue_idx)
                cue_idx += 1
                if overlap < 0.4 and consumed:
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


# --- HTML scaffold: Humanist Creator design system ----------------------------
#
# Plus Jakarta Sans (display) + Literata (body). Terracotta primary (#9f402d)
# on a cream surface (#fbf9f8). All spacing on an 8 px baseline; rounded
# shapes; warm, terracotta-tinted shadows. The reading column is 720 px wide
# so figures can break out slightly without overwhelming the text.
#
# Agent contract: this template is intentionally a *scaffold*. The script
# emits paragraphs flat with `data-srt-start` (seconds) so a subsequent
# editing pass can splice in `<h2>` section headings, a lead paragraph
# (`<p class="lead">`), and decorative `<hr class="divider">` rules between
# logical sections. See SKILL.md "Restructure for readability".
_HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="{lang}">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Literata:ital,wght@0,400;0,500;0,600;0,700;1,400;1,500&family=Plus+Jakarta+Sans:wght@500;600;700;800&display=swap" rel="stylesheet">
<style>
:root {{
  --surface: #fbf9f8;
  --surface-container-low: #f6f3f2;
  --surface-container: #f0eded;
  --surface-container-high: #eae7e7;
  --on-surface: #1b1c1c;
  --on-surface-variant: #56423e;
  --outline: #89726d;
  --outline-variant: #ddc0ba;
  --primary: #9f402d;
  --on-primary: #ffffff;
  --primary-container: #e2725b;
  --on-primary-container: #5a0d02;
  --secondary: #8d4f11;
  --secondary-container: #feac67;
  --on-secondary-container: #773e00;
  --tertiary: #635e53;
  --primary-fixed: #ffdad3;

  --space-xs: 4px;
  --space-sm: 12px;
  --space-md: 24px;
  --space-lg: 40px;
  --space-xl: 64px;

  --r-sm: 0.25rem;
  --r: 0.5rem;
  --r-md: 0.75rem;
  --r-lg: 1rem;
  --r-xl: 1.5rem;
  --r-full: 9999px;

  --font-display: 'Plus Jakarta Sans', system-ui, -apple-system, sans-serif;
  --font-body: 'Literata', 'Iowan Old Style', Georgia, serif;

  --shadow-1: 0 1px 2px rgba(159, 64, 45, 0.06), 0 2px 8px rgba(159, 64, 45, 0.05);
  --shadow-2: 0 4px 16px rgba(159, 64, 45, 0.08), 0 12px 32px rgba(159, 64, 45, 0.06);
}}

* {{ box-sizing: border-box; }}

html, body {{ margin: 0; padding: 0; }}

body {{
  background-color: var(--surface);
  background-image:
    radial-gradient(ellipse 60% 40% at 15% -10%, rgba(254, 172, 103, 0.10) 0%, transparent 60%),
    radial-gradient(ellipse 50% 35% at 95% 110%, rgba(226, 114, 91, 0.07) 0%, transparent 65%);
  background-attachment: fixed;
  color: var(--on-surface);
  font-family: var(--font-body);
  font-size: 18px;
  line-height: 1.7;
  -webkit-font-smoothing: antialiased;
  text-rendering: optimizeLegibility;
}}

a {{ color: var(--primary); text-decoration: none; }}
a:hover {{ text-decoration: underline; text-underline-offset: 3px; }}

/* ---------- Top bar ---------- */
.site-bar {{
  max-width: 1200px;
  margin: 0 auto;
  padding: var(--space-md);
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-md);
}}
.brand {{
  display: inline-flex;
  align-items: center;
  gap: 10px;
  font-family: var(--font-display);
  font-weight: 700;
  font-size: 13px;
  letter-spacing: 0.18em;
  text-transform: uppercase;
  color: var(--primary);
}}
.brand::before {{
  content: '';
  width: 10px; height: 10px;
  border-radius: 50%;
  background: var(--primary);
  box-shadow: 0 0 0 4px rgba(159, 64, 45, 0.12);
}}
.site-bar .source-pill {{
  display: inline-flex;
  align-items: center;
  gap: 8px;
  padding: 8px 16px;
  border-radius: var(--r-full);
  background: var(--surface-container);
  border: 1px solid var(--outline-variant);
  font-family: var(--font-display);
  font-weight: 600;
  font-size: 13px;
  color: var(--on-surface-variant);
}}
.site-bar .source-pill:hover {{
  background: var(--surface-container-high);
  text-decoration: none;
}}

/* ---------- Article ---------- */
article {{
  max-width: 720px;
  margin: 0 auto;
  padding: var(--space-lg) var(--space-md) var(--space-xl);
}}

.post-hero {{
  margin-bottom: var(--space-xl);
}}
.eyebrow {{
  display: inline-flex;
  align-items: center;
  gap: 8px;
  padding: 6px 14px;
  border-radius: var(--r-full);
  background: rgba(254, 172, 103, 0.20);
  color: var(--on-secondary-container);
  font-family: var(--font-display);
  font-weight: 600;
  font-size: 11px;
  letter-spacing: 0.14em;
  text-transform: uppercase;
  margin: 0 0 var(--space-md);
}}
.post-title {{
  font-family: var(--font-display);
  font-weight: 700;
  font-size: 40px;
  line-height: 1.15;
  letter-spacing: -0.02em;
  color: var(--on-surface);
  margin: 0 0 var(--space-md);
  text-wrap: balance;
}}
@media (max-width: 640px) {{
  .post-title {{ font-size: 30px; }}
}}
.post-meta {{
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 10px var(--space-sm);
  font-family: var(--font-display);
  font-size: 13px;
  color: var(--on-surface-variant);
}}
.post-meta .dot {{
  width: 4px; height: 4px;
  border-radius: 50%;
  background: var(--outline);
  opacity: 0.5;
}}
.post-meta a {{
  color: var(--primary);
  border-bottom: 1px solid var(--outline-variant);
  transition: border-color .2s;
}}
.post-meta a:hover {{ border-color: var(--primary); text-decoration: none; }}

/* ---------- Body ---------- */
.post-body {{
  /* CSS counters could be used for footnotes here */
}}
.post-body p {{
  margin: 0 0 var(--space-md);
  color: var(--on-surface);
}}
.post-body p.lead {{
  font-size: 22px;
  line-height: 1.55;
  color: var(--on-surface-variant);
  font-weight: 500;
  margin-bottom: var(--space-lg);
}}
.post-body p.lead::first-letter {{
  font-family: var(--font-display);
  font-weight: 700;
  font-size: 64px;
  line-height: 0.9;
  float: left;
  margin: 6px 12px 0 0;
  color: var(--primary);
}}
.post-body h2 {{
  font-family: var(--font-display);
  font-weight: 700;
  font-size: 26px;
  line-height: 1.25;
  letter-spacing: -0.01em;
  color: var(--on-surface);
  margin: var(--space-xl) 0 var(--space-md);
  text-wrap: balance;
}}
.post-body h3 {{
  font-family: var(--font-display);
  font-weight: 600;
  font-size: 20px;
  line-height: 1.35;
  color: var(--on-surface);
  margin: var(--space-lg) 0 var(--space-sm);
}}
.post-body blockquote {{
  margin: var(--space-lg) 0;
  padding: var(--space-md) var(--space-md) var(--space-md) var(--space-lg);
  border-left: 3px solid var(--primary-container);
  background: var(--surface-container-low);
  border-radius: 0 var(--r-md) var(--r-md) 0;
  font-style: italic;
  color: var(--on-surface-variant);
}}
.post-body ul, .post-body ol {{
  margin: 0 0 var(--space-md);
  padding-left: 1.4em;
}}
.post-body li {{ margin: 0.3em 0; }}
.post-body code {{
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 0.92em;
  padding: 2px 6px;
  border-radius: var(--r-sm);
  background: var(--surface-container);
  color: var(--on-primary-container);
}}

/* Decorative section divider — three soft terracotta pellets */
.post-body .divider,
.post-body hr.divider {{
  border: 0;
  display: flex;
  justify-content: center;
  gap: 12px;
  margin: var(--space-xl) 0;
  height: 8px;
}}
.post-body hr.divider {{
  /* Single 8 px pellet centred horizontally; the other two pellets are
     painted with box-shadow offsets, so one <hr> = three dots. */
  width: 8px; height: 8px;
  border-radius: 50%;
  background: var(--primary-container);
  margin: var(--space-xl) auto;
  box-shadow: -20px 0 0 var(--primary-container), 20px 0 0 var(--primary-container);
  opacity: 0.55;
  display: block;
}}

/* ---------- Figures ---------- */
figure {{
  margin: var(--space-lg) 0;
  padding: 0;
}}
@media (min-width: 760px) {{
  /* let figures breathe slightly wider than the reading column */
  figure {{ margin-left: -32px; margin-right: -32px; }}
}}
figure a.image-wrap {{
  display: block;
  border-radius: var(--r-lg);
  overflow: hidden;
  box-shadow: var(--shadow-2);
  background: var(--surface-container);
  transition: transform .35s cubic-bezier(.2,.7,.2,1), box-shadow .35s;
}}
figure a.image-wrap:hover {{
  transform: translateY(-2px);
  box-shadow: 0 8px 24px rgba(159, 64, 45, 0.12), 0 18px 48px rgba(159, 64, 45, 0.08);
}}
figure img {{
  display: block;
  width: 100%;
  height: auto;
}}
figcaption {{
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-sm);
  margin: var(--space-sm) var(--space-md) 0;
  font-family: var(--font-display);
  font-size: 13px;
  color: var(--on-surface-variant);
}}
figcaption .caption-text {{
  flex: 1;
  font-style: normal;
}}
.ts-chip {{
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 5px 12px;
  border-radius: var(--r-full);
  background: rgba(254, 172, 103, 0.22);
  color: var(--on-secondary-container);
  font-family: var(--font-display);
  font-weight: 600;
  font-size: 12px;
  letter-spacing: 0.02em;
  white-space: nowrap;
  transition: background .2s;
}}
.ts-chip:hover {{
  background: rgba(254, 172, 103, 0.36);
  text-decoration: none;
}}
.ts-chip::before {{
  content: '▶';
  font-size: 9px;
  opacity: 0.7;
}}

/* ---------- Figure row (gallery, magazine breakout) ---------- */
/* When several frames land in the same paragraph, stacking them vertically
   wastes space. A grid arranges 2-3 side-by-side. Inside the 720px reading
   column they'd squish to ~240 px each — unreadable for UI screenshots —
   so the row breaks OUT of the article column into the viewport's wider
   space (magazine "pull-out" pattern). The body keeps its narrow line
   length for reading comfort; only the gallery uses the side whitespace.

   The trick: position: relative + left: 50% + translateX(-50%) re-centers
   the row on the article's centerline (which equals viewport center),
   then `width: min(<row-max>, calc(100vw - gutter))` clamps it.

   On mobile (<640 px) the grid collapses to 1 column. */
.figure-row {{
  display: grid;
  gap: var(--space-md);
  margin: var(--space-lg) auto;
  /* Centered breakout: article is centered in viewport, so re-positioning
     on article's centerline puts the row on viewport's centerline too. */
  position: relative;
  left: 50%;
  transform: translateX(-50%);
}}
.figure-row > figure {{
  margin: 0;            /* row owns the spacing */
}}
.figure-row[data-count="2"] {{
  /* 2-up: don't go too wide — each figure shouldn't dwarf body text */
  width: min(960px, calc(100vw - 32px));
  grid-template-columns: repeat(2, minmax(0, 1fr));
}}
.figure-row[data-count="3"] {{
  /* 3-up: spill further into side margins so each cell is ~340 px on
     a 1440 px viewport, vs ~240 px when constrained to the article. */
  width: min(1100px, calc(100vw - 32px));
  grid-template-columns: repeat(3, minmax(0, 1fr));
}}
/* Tighter caption typography inside galleries so 2–3 captions stay
   horizontally balanced without crowding. */
.figure-row figcaption {{
  margin: 10px 6px 0;
  font-size: 12px;
  gap: 8px;
}}
.figure-row .ts-chip {{
  padding: 3px 9px;
  font-size: 11px;
}}
@media (max-width: 640px) {{
  .figure-row,
  .figure-row[data-count="2"],
  .figure-row[data-count="3"] {{
    width: auto;
    left: auto;
    transform: none;
    margin-left: 0;
    margin-right: 0;
    grid-template-columns: 1fr;
  }}
}}

/* ---------- Tail section ---------- */
.tail-section {{
  margin-top: var(--space-xl);
  padding-top: var(--space-lg);
  border-top: 1px dashed var(--outline-variant);
}}
.tail-section h2 {{
  font-family: var(--font-display);
  font-weight: 600;
  font-size: 18px;
  letter-spacing: 0.04em;
  text-transform: uppercase;
  color: var(--on-surface-variant);
  margin: 0 0 var(--space-md);
}}

/* ---------- Footer ---------- */
.site-footer {{
  max-width: 720px;
  margin: 0 auto;
  padding: var(--space-lg) var(--space-md) var(--space-xl);
  text-align: center;
  font-family: var(--font-display);
  font-size: 12px;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: var(--on-surface-variant);
}}
.site-footer .mark {{
  display: inline-flex;
  align-items: center;
  gap: 8px;
}}
.site-footer .mark::before {{
  content: '';
  width: 6px; height: 6px;
  border-radius: 50%;
  background: var(--primary-container);
}}
</style>
</head>
<body>
<header class="site-bar">
  <span class="brand">Full Blog</span>
  <a class="source-pill" href="{source_url}" target="_blank" rel="noopener">▶ {source_label}</a>
</header>

<article>
  <header class="post-hero">
    <p class="eyebrow">YouTube · Full Blog</p>
    <h1 class="post-title">{title}</h1>
    <div class="post-meta">
      <a href="{source_url}" target="_blank" rel="noopener">Watch on YouTube</a>
    </div>
  </header>

  <div class="post-body">
{body}
  </div>
</article>

<footer class="site-footer">
  <span class="mark">Generated by yt-ribosome / full-blog</span>
</footer>
</body>
</html>
"""


def _ts_str(timestamp_s):
    s = int(timestamp_s)
    return f"{s//3600:02d}:{(s%3600)//60:02d}:{s%60:02d}"


def _ts_display(timestamp_s):
    """Human-friendly timestamp: 'H:MM:SS' or 'M:SS' when under an hour."""
    s = int(timestamp_s)
    if s >= 3600:
        return f"{s//3600:d}:{(s%3600)//60:02d}:{s%60:02d}"
    return f"{s//60:d}:{s%60:02d}"


def _figure_block(image_dir, image_filename, timestamp_s, alt, caption, video_id):
    ts = _ts_str(timestamp_s)
    ts_display = _ts_display(timestamp_s)
    deep = f"https://www.youtube.com/watch?v={video_id}&t={int(timestamp_s)}"
    raw_src = f"{image_dir}/{image_filename}" if image_dir else image_filename
    # Percent-encode the src so spaces, Hangul, and other non-ASCII are valid
    # in a strict URL parser. Browsers tolerate raw chars in <img src> but
    # static-site link checkers, S3 path normalisation, and some build tools
    # do not. safe="/" preserves the directory separator.
    src = urllib.parse.quote(raw_src, safe="/")
    deep_esc = html_lib.escape(deep, quote=True)
    return (
        f'<figure data-timestamp="{ts}">'
        f'<a class="image-wrap" href="{deep_esc}" target="_blank" rel="noopener">'
        f'<img src="{html_lib.escape(src, quote=True)}" '
        f'alt="{html_lib.escape(alt)}" loading="lazy">'
        f'</a>'
        f'<figcaption>'
        f'<span class="caption-text">{html_lib.escape(caption)}</span>'
        f'<a class="ts-chip" href="{deep_esc}" target="_blank" rel="noopener">{ts_display}</a>'
        f'</figcaption>'
        f'</figure>'
    )


def _emit_frames(frames, video_id):
    """Emit figure markup, grouping ≥2 adjacent frames into a `.figure-row`.

    One frame -> a single full-width `<figure>` (existing behavior).
    Two or more frames belonging to the same paragraph stack vertically
    in a narrow column and waste reading space; wrapping them in a grid
    row makes them scannable side-by-side. We cap the row at 3 across,
    so 4 frames render as 3+1 (CSS handles the wrap). `data-count` lets
    the stylesheet pick the right grid template per count.
    """
    if not frames:
        return []
    if len(frames) == 1:
        fr = frames[0]
        d, _, fn = fr["path_rel"].rpartition("/")
        return [_figure_block(
            image_dir=d, image_filename=fn,
            timestamp_s=fr["timestamp_s"],
            alt=fr.get("alt", ""), caption=fr.get("caption", ""),
            video_id=video_id,
        )]
    n = min(len(frames), 3)  # CSS template caps at 3-up; wraps beyond that
    inner = []
    for fr in frames:
        d, _, fn = fr["path_rel"].rpartition("/")
        inner.append(_figure_block(
            image_dir=d, image_filename=fn,
            timestamp_s=fr["timestamp_s"],
            alt=fr.get("alt", ""), caption=fr.get("caption", ""),
            video_id=video_id,
        ))
    return [f'<div class="figure-row" data-count="{n}">'] + inner + ['</div>']


def _para_block(para_text, srt_start_s):
    """A flat paragraph with a `data-srt-start` time anchor (seconds).

    The agent uses these anchors when restructuring: it can identify topic
    boundaries and splice in `<h2>` headings between paragraphs without
    needing the SRT file.
    """
    anchor = f' data-srt-start="{int(srt_start_s)}"' if srt_start_s is not None else ''
    return f'<p{anchor}>{html_lib.escape(para_text)}</p>'


def render_html(title, source_url, paragraphs, paragraph_ranges, frames,
                video_id, image_dir=None, lang="en"):
    """Render the final HTML scaffold.

    paragraphs       : list[str], body paragraphs
    paragraph_ranges : output of align_paragraphs_to_srt
    frames           : list[{path_rel, timestamp_s, alt, caption, ...}]
    video_id         : YouTube video id (for deep-link in figures)
    image_dir        : directory prefix for img src (defaults to frame's path_rel basename dir)

    The body contains paragraphs flat (each with `data-srt-start` when known)
    plus figure blocks placed between the paragraphs they belong to. A
    downstream agent rewrites this into a properly sectioned blog by
    inserting `<h2>` / lead paragraphs / dividers via the Edit tool.
    """
    # build a quick lookup of paragraph index -> start time (seconds)
    start_by_p = {r["p_idx"]: r["start"] for r in paragraph_ranges}

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
        parts.append(_para_block(para, start_by_p.get(i)))
        frames_here = sorted(by_p.get(i, []), key=lambda f: f["timestamp_s"])
        parts.extend(_emit_frames(frames_here, video_id))

    if tail:
        parts.append('<section class="tail-section">')
        parts.append('<h2>Additional frames</h2>')
        tail_sorted = sorted(tail, key=lambda f: f["timestamp_s"])
        parts.extend(_emit_frames(tail_sorted, video_id))
        parts.append('</section>')

    # A short source label for the top-bar pill ("youtube.com/watch?v=..." trimmed)
    source_label = source_url
    if source_label.startswith("https://"):
        source_label = source_label[len("https://"):]
    if source_label.startswith("www."):
        source_label = source_label[len("www."):]
    if len(source_label) > 48:
        source_label = source_label[:45] + "…"

    return _HTML_TEMPLATE.format(
        lang=lang,
        title=html_lib.escape(title),
        source_url=html_lib.escape(source_url, quote=True),
        source_label=html_lib.escape(source_label),
        body="\n    ".join(parts),
    )
