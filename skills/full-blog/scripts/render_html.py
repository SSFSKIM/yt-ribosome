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
        f'<a href="{html_lib.escape(deep, quote=True)}"><img src="{html_lib.escape(src, quote=True)}" '
        f'alt="{html_lib.escape(alt)}" loading="lazy"></a>'
        f'<figcaption>{html_lib.escape(caption)} '
        f'<a class="ts-link" href="{html_lib.escape(deep, quote=True)}">({ts})</a></figcaption>'
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
