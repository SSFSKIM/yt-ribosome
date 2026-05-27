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
