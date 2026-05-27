#!/usr/bin/env python3
"""Gemini-based frame ranker for full-blog skill.

Public functions:
  - rank_frames(pairs, cues, model, batch_size, max_frames_final, allow_degrade,
                api_key=None, cache_path=None, _retry_base_delay=2.0) -> list of dicts
                (timestamp_s, path, include, alt_text, caption, confidence, degraded?)
  - load_prompt_template() -> str

Tests mock _call_gemini; in production it uses google-genai.
"""
import imagehash
import json
import os
import re
import time
from PIL import Image


PROMPT_PATH = os.path.join(
    os.path.dirname(__file__), "..", "references", "ranker-prompt.md"
)


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
        return path


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


def _call_gemini(model, prompt, image_paths, api_key=None, timeout_s=60):
    """Real Gemini call — separated so tests can mock it.

    Detects Vertex AI Express keys (prefix "AQ.") and routes them through the
    Vertex client; standard Gemini API keys ("AIza...") use the default client.

    The call is wrapped in a thread-based timeout because the google-genai
    SDK doesn't enforce a default request timeout — when Google's server
    holds the TCP connection open without responding, the SDK call blocks
    forever. Live test caught this: a subagent's pipeline hung for 5+ hours
    on a Gemini batch with file descriptor stuck in TCP ESTABLISHED state
    to 1e100.net. Threading is SDK-version-agnostic; the abandoned future
    eventually loses its TCP socket and gets GC'd.
    """
    from google import genai

    key = api_key or os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    # "AQ." == Vertex AI Express key; "AIza" == standard Gemini API key
    if key and key.startswith("AQ."):
        client = genai.Client(vertexai=True, api_key=key)
    else:
        client = genai.Client(api_key=key)
    parts = [prompt]
    for p in image_paths:
        with open(p, "rb") as f:
            parts.append(genai.types.Part.from_bytes(data=f.read(), mime_type="image/jpeg"))

    import concurrent.futures as _cf
    with _cf.ThreadPoolExecutor(max_workers=1) as ex:
        fut = ex.submit(
            client.models.generate_content,
            model=model,
            contents=parts,
            config={"response_mime_type": "application/json"},
        )
        resp = fut.result(timeout=timeout_s)
    return _parse_response(resp.text, expected_len=len(image_paths))


def _ranker_call_with_retries(model, prompt, image_paths, max_attempts=5,
                              base_delay=2.0, api_key=None):
    import concurrent.futures as _cf
    last_err = None
    for attempt in range(max_attempts):
        try:
            return _call_gemini(model, prompt, image_paths, api_key=api_key)
        except _cf.TimeoutError as e:
            # Timeout means the API call is structurally hung, not transient
            # (the SDK held a TCP socket open with no response). Retrying the
            # same large batch is unlikely to help — bisect smaller and try
            # again immediately.
            last_err = e
            break
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
                cache_path=None, _retry_base_delay=2.0):
    """Rank frames with Gemini; return ordered results matching pairs.

    pairs      : list[(timestamp_s, path)]
    cues       : list[{start, end, text}]
    cache_path : optional path to JSON cache file; keyed by phash of frame image.
    """
    prompt_tmpl = load_prompt_template()
    cache = _load_cache(cache_path)
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

        # Split batch into cache hits and misses
        keys = [_phash_key(p) for p in paths]
        miss_indices = [i for i, k in enumerate(keys) if k not in cache]
        miss_paths = [paths[i] for i in miss_indices]

        if miss_paths:
            try:
                miss_results = _ranker_call_with_retries(
                    model, prompt, miss_paths, api_key=api_key,
                    base_delay=_retry_base_delay,
                )
                # Store new results in cache
                for local_miss_i, item in enumerate(miss_results):
                    cache[keys[miss_indices[local_miss_i]]] = item
                _save_cache(cache_path, cache)
            except Exception:
                if not allow_degrade:
                    raise
                degraded_run = True
                for local_miss_i in range(len(miss_paths)):
                    cache[keys[miss_indices[local_miss_i]]] = {
                        "frame_index": miss_indices[local_miss_i],
                        "include": True, "alt_text": "",
                        "caption": "", "confidence": 0.0,
                        "_degraded": True,
                    }

        # Reconstruct parsed list for full batch using cache
        parsed = [cache[k] for k in keys]
        if any(p.get("_degraded") for p in parsed):
            degraded_run = True

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
