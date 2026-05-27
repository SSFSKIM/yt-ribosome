#!/usr/bin/env python3
"""Gemini-based frame ranker for full-blog skill.

Public functions:
  - rank_frames(pairs, cues, model, batch_size, max_frames_final, allow_degrade,
                api_key=None, _retry_base_delay=2.0) -> list of dicts
                (timestamp_s, path, include, alt_text, caption, confidence, degraded?)
  - load_prompt_template() -> str

Tests mock _call_gemini; in production it uses google-genai.
"""
import json
import os
import re
import time


PROMPT_PATH = os.path.join(
    os.path.dirname(__file__), "..", "references", "ranker-prompt.md"
)


def load_prompt_template():
    with open(PROMPT_PATH, encoding="utf-8") as f:
        text = f.read()
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
                max_frames_final=25, allow_degrade=True, api_key=None,
                _retry_base_delay=2.0):
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
        def _ts(s):
            s = int(s)
            return f"{s//3600:02d}:{(s%3600)//60:02d}:{s%60:02d}"

        prompt = (prompt_tmpl
                  .replace("{window_start}", _ts(win_start))
                  .replace("{window_end}", _ts(win_end))
                  .replace("{transcript_window}",
                           _window_transcript(cues, win_start, win_end)))
        try:
            parsed = _ranker_call_with_retries(
                model, prompt, paths, api_key=api_key,
                base_delay=_retry_base_delay,
            )
        except Exception:
            if not allow_degrade:
                raise
            degraded_run = True
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
        sampled = _even_sample(out, max_frames_final)
        for r in sampled:
            r["include"] = True
            r["degraded"] = True
        return sampled

    out.sort(key=lambda r: (-r["confidence"], r["timestamp_s"]))
    return out
