#!/usr/bin/env python3
"""Translate transcript files into a target language with OpenAI or Gemini.

Input is a single file or a directory of `.md`/`.txt` files. Each file is
translated into `--to <language>` and written to the output directory. Markdown
structure, headings, and URLs are preserved; only natural-language text is
translated. The translator is told the source is an auto-generated transcript so
it silently corrects obvious speech-to-text errors (e.g. "Cloud" -> Claude).

Providers:
  - openai (default): chat.completions, default model gpt-5.4-2026-03-05 with
    reasoning_effort=high (reasoning models drop custom temperature and use
    max_completion_tokens); override with --model / --openai-effort
  - gemini: google-genai, default model gemini-3.5-flash; auto-detects a Vertex
    AI Express key ("AQ." prefix) vs a standard Gemini API key

Files already written in the target language (detected by script) are copied
unchanged unless --no-skip-detect is set. Files are translated in parallel.

Examples:
  python3 translate.py ./transcripts --to Korean
  python3 translate.py talk.md --to "日本語" --provider gemini
  python3 translate.py ./transcripts --to English --provider openai --model gpt-4o

API keys (env or a .env in CWD): OPENAI_API_KEY, or GEMINI_API_KEY/GOOGLE_API_KEY.
"""
import argparse
import concurrent.futures as cf
import glob
import os
import re
import sys
import time

CHUNK_CHARS = 6000

SYSTEM_TMPL = """You are a professional translator localizing text into {target}.

The source is often an AUTOMATICALLY GENERATED transcript (speech-to-text) of spoken tech talks. It may contain minor recognition errors — e.g. "Claude" heard as "Cloud"/"Clawd", "Anthropic" as "Enthropic", misspelled names/products, missing punctuation, and spoken fillers ("uh", "um").

Rules:
1. Translate into natural, fluent {target}.
2. Silently CORRECT obvious transcription errors from context — translate the intended meaning, not the literal mistake.
3. PRESERVE all Markdown formatting exactly: headings (#), lists, emphasis, and especially URLs and link targets. Do not alter code, identifiers, or links.
4. Keep widely-used technical/product names in their common form (Claude, Anthropic, MCP, API, LLM, Docker, Kubernetes, ...).
5. Do not summarize, omit, or add content. Smooth out spoken fillers.
6. If the text is ALREADY in {target}, return it unchanged.
7. Output ONLY the translation — no notes, no preamble, no code fences around the whole answer."""

# minimal target-language -> Unicode test, for the "already in target" skip
SCRIPT_TESTS = {
    "ko": lambda c: "가" <= c <= "힣",
    "ja": lambda c: ("぀" <= c <= "ヿ") or ("一" <= c <= "鿿"),
    "zh": lambda c: "一" <= c <= "鿿",
    "ru": lambda c: "Ѐ" <= c <= "ӿ",
    "ar": lambda c: "؀" <= c <= "ۿ",
    "en": lambda c: ("a" <= c.lower() <= "z"),
}
LANG_ALIASES = {
    "korean": "ko", "한국어": "ko", "ko": "ko", "kr": "ko",
    "japanese": "ja", "日本語": "ja", "ja": "ja", "jp": "ja",
    "chinese": "zh", "中文": "zh", "zh": "zh",
    "russian": "ru", "ru": "ru",
    "arabic": "ar", "ar": "ar",
    "english": "en", "en": "en",
}


# --------------------------------------------------------------------------- #
def load_env():
    path = os.path.join(os.getcwd(), ".env")
    if os.path.isfile(path):
        for line in open(path, encoding="utf-8"):
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())


def target_code(target):
    return LANG_ALIASES.get(target.strip().lower())


def already_target(text, target):
    code = target_code(target)
    test = SCRIPT_TESTS.get(code)
    if not test:
        return False                       # unknown target -> always translate
    hits = sum(1 for c in text if test(c))
    letters = sum(1 for c in text if c.isalpha() or test(c))
    return letters > 0 and hits / letters > 0.5


def chunk_markdown(text, limit=CHUNK_CHARS):
    """Group blank-line-separated blocks up to `limit` chars (keeps structure)."""
    blocks = re.split(r"\n\s*\n", text.strip())
    chunks, cur = [], ""
    for b in blocks:
        b = b.strip()
        if not b:
            continue
        if cur and len(cur) + len(b) + 2 > limit:
            chunks.append(cur)
            cur = b
        else:
            cur = f"{cur}\n\n{b}" if cur else b
    if cur:
        chunks.append(cur)
    return chunks or [""]


def split_half(text):
    blocks = re.split(r"\n\s*\n", text.strip())
    if len(blocks) >= 2:
        h = len(blocks) // 2
        return ["\n\n".join(blocks[:h]), "\n\n".join(blocks[h:])]
    mid = len(text) // 2
    return [text[:mid], text[mid:]]


# --------------------------------------------------------------------------- #
# providers
# --------------------------------------------------------------------------- #
REASONING_RE = re.compile(r"^(gpt-5|o[1-4])", re.I)   # reasoning models: gpt-5.x, o1/o3/o4


class OpenAIProvider:
    def __init__(self, model, effort):
        from openai import OpenAI
        self.client = OpenAI()
        self.model = model or "gpt-5.4-2026-03-05"
        self.effort = effort
        self.reasoning = bool(REASONING_RE.match(self.model))

    def run(self, text, system):
        msgs = [{"role": "system", "content": system},
                {"role": "user", "content": text}]
        if self.reasoning:
            # reasoning models: use reasoning_effort + max_completion_tokens (reasoning
            # tokens count toward it, so keep it generous); custom temperature is rejected.
            kw = dict(reasoning_effort=self.effort, max_completion_tokens=32000)
        else:
            kw = dict(temperature=0.3, max_tokens=16384)
        r = self.client.chat.completions.create(model=self.model, messages=msgs, **kw)
        ch = r.choices[0]
        return ch.message.content, (ch.finish_reason == "length")


class GeminiProvider:
    def __init__(self, model, thinking):
        from google import genai
        from google.genai import types
        self.types = types
        key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
        if not key:
            raise SystemExit("GEMINI_API_KEY / GOOGLE_API_KEY not set")
        # "AQ." == Vertex AI Express key; "AIza" == standard Gemini API key
        self.client = genai.Client(vertexai=True, api_key=key) if key.startswith("AQ.") \
            else genai.Client(api_key=key)
        self.model = model or "gemini-3.5-flash"
        self.thinking = thinking

    def run(self, text, system):
        cfg = dict(system_instruction=system, temperature=0.3, max_output_tokens=65536)
        try:
            cfg["thinking_config"] = self.types.ThinkingConfig(thinking_level=self.thinking)
        except Exception:
            pass
        r = self.client.models.generate_content(
            model=self.model, contents=text,
            config=self.types.GenerateContentConfig(**cfg),
        )
        fr = r.candidates[0].finish_reason if r.candidates else None
        return r.text, (str(fr).endswith("MAX_TOKENS"))


def translate_text(provider, text, system, depth=0):
    for attempt in range(5):
        try:
            out, truncated = provider.run(text, system)
            break
        except Exception as e:
            wait = 2 ** attempt
            print(f"      retry {attempt+1}/5 in {wait}s: {str(e)[:90]}", flush=True)
            time.sleep(wait)
    else:
        raise RuntimeError("translation failed after retries")
    if truncated and depth < 4 and len(text) > 800:
        return "\n\n".join(translate_text(provider, p, system, depth + 1) for p in split_half(text))
    return (out or "").strip()


# --------------------------------------------------------------------------- #
# HTML translation path (v0.2.0)
# --------------------------------------------------------------------------- #

_HTML_SKIP_TAGS = {"code", "pre", "script", "style"}
_HTML_TEXT_TAGS = {"p", "li", "h1", "h2", "h3", "h4", "h5", "h6",
                   "figcaption", "title", "blockquote", "em", "strong", "a"}
_STOCK_LINK_TEXTS = {"▶ Watch on YouTube"}


def _extract_html_nodes(html_text):
    """Return (soup, list[{id, kind, text}]) of translatable text in source order.

    Skips <code>, <pre>, <script>, <style>. Walks <img alt> attributes too.
    Elements are tagged with data-tr-id / data-tr-alt-id so write-back is exact.

    Public API returns only the node list; soup is discarded by callers that
    only need the list. _translate_html calls the internal helper directly.
    """
    try:
        from bs4 import BeautifulSoup, NavigableString
    except ImportError:
        raise RuntimeError("beautifulsoup4 required for HTML translation: pip install beautifulsoup4")
    soup = BeautifulSoup(html_text, "html.parser")
    nodes = []
    nid = 0

    for el in soup.find_all(True):
        if el.name in _HTML_SKIP_TAGS:
            continue
        if el.name in _HTML_TEXT_TAGS:
            parts = []
            for child in el.children:
                if isinstance(child, NavigableString):
                    parts.append(str(child))
                else:
                    if child.name in _HTML_SKIP_TAGS:
                        parts.append("")
            text = "".join(parts).strip()
            if text and text not in _STOCK_LINK_TEXTS:
                el["data-tr-id"] = str(nid)
                nodes.append({"id": nid, "kind": el.name, "text": text})
                nid += 1
        if el.name == "img":
            alt = el.get("alt", "").strip()
            if alt and alt not in _STOCK_LINK_TEXTS:
                el["data-tr-alt-id"] = str(nid)
                nodes.append({"id": nid, "kind": "alt", "text": alt})
                nid += 1
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
            model=model or "gpt-4o",
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
        )
        text = resp.choices[0].message.content
        data = _j.loads(text)
        if isinstance(data, dict) and "items" in data:
            data = data["items"]
        if isinstance(data, dict) and "translations" in data:
            data = data["translations"]
    else:
        from google import genai
        client = genai.Client(api_key=os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY"))
        resp = client.models.generate_content(
            model=model or "gemini-2.5-flash",
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
    """Translate text nodes in HTML, preserving all attributes, hrefs, srcs."""
    import json as _j
    try:
        from bs4 import BeautifulSoup, NavigableString
    except ImportError:
        raise RuntimeError("beautifulsoup4 required: pip install beautifulsoup4")

    # Re-parse to get a soup with data-tr-id / data-tr-alt-id annotations.
    # We call the internals of _extract_html_nodes directly on a fresh soup
    # so we get back the annotated soup alongside the node list.
    soup = BeautifulSoup(html_text, "html.parser")
    nodes = []
    nid = 0
    for el in soup.find_all(True):
        if el.name in _HTML_SKIP_TAGS:
            continue
        if el.name in _HTML_TEXT_TAGS:
            parts = []
            for child in el.children:
                if isinstance(child, NavigableString):
                    parts.append(str(child))
                else:
                    if child.name in _HTML_SKIP_TAGS:
                        parts.append("")
            text = "".join(parts).strip()
            if text and text not in _STOCK_LINK_TEXTS:
                el["data-tr-id"] = str(nid)
                nodes.append({"id": nid, "kind": el.name, "text": text})
                nid += 1
        if el.name == "img":
            alt = el.get("alt", "").strip()
            if alt and alt not in _STOCK_LINK_TEXTS:
                el["data-tr-alt-id"] = str(nid)
                nodes.append({"id": nid, "kind": "alt", "text": alt})
                nid += 1

    if not nodes:
        return html_text

    # Translate in batches
    translated_all = {}
    for i in range(0, len(nodes), batch_size):
        batch = nodes[i:i + batch_size]
        items = _call_html_batch(_j.dumps(batch, ensure_ascii=False),
                                 target, provider, model)
        for it in items:
            translated_all[it["id"]] = it["text"]

    # Write translations back using the stable data-tr-id markers
    for el in soup.find_all(True, attrs={"data-tr-id": True}):
        node_id = int(el["data-tr-id"])
        del el["data-tr-id"]
        if node_id not in translated_all:
            continue
        new_text = translated_all[node_id]
        # Replace direct NavigableString children with translated text
        str_children = [c for c in list(el.children) if isinstance(c, NavigableString) and str(c).strip()]
        if str_children:
            str_children[0].replace_with(NavigableString(new_text))
            for extra in str_children[1:]:
                extra.replace_with(NavigableString(""))

    for el in soup.find_all("img", attrs={"data-tr-alt-id": True}):
        node_id = int(el["data-tr-alt-id"])
        del el["data-tr-alt-id"]
        if node_id in translated_all:
            el["alt"] = translated_all[node_id]

    return str(soup)


# --------------------------------------------------------------------------- #
def translate_file(provider, src, dst, target, skip_detect):
    if src.lower().endswith(".html"):
        with open(src, encoding="utf-8") as f:
            html_text = f.read()
        out = _translate_html(html_text, target, provider=provider.provider if hasattr(provider, "provider") else ("gemini" if isinstance(provider, GeminiProvider) else "openai"), model=None)
        with open(dst, "w", encoding="utf-8") as f:
            f.write(out)
        return f"translated {os.path.basename(src)} -> {os.path.basename(dst)}"
    text = open(src, encoding="utf-8").read()
    if skip_detect and already_target(text, target):
        open(dst, "w", encoding="utf-8").write(text if text.endswith("\n") else text + "\n")
        return f"copied (already {target}): {os.path.basename(src)}"
    system = SYSTEM_TMPL.format(target=target)
    parts = [translate_text(provider, ch, system) for ch in chunk_markdown(text)]
    open(dst, "w", encoding="utf-8").write("\n\n".join(parts).strip() + "\n")
    return f"done: {os.path.basename(src)} ({len(text)} -> {sum(len(p) for p in parts)} chars)"


def slug(target):
    return target_code(target) or re.sub(r"\s+", "-", target.strip().lower())


def main():
    ap = argparse.ArgumentParser(description="Translate transcript files into a target language.")
    ap.add_argument("input", help="a file or a directory of .md/.txt files")
    ap.add_argument("--to", required=True, help='target language, e.g. "Korean", "ko", "日本語"')
    ap.add_argument("--provider", default="openai", choices=["openai", "gemini"])
    ap.add_argument("--model", default=None,
                    help="override model (default: gpt-5.4-2026-03-05 / gemini-3.5-flash)")
    ap.add_argument("--out-dir", default=None, help="output dir (default: <input>-<lang>)")
    ap.add_argument("--openai-effort", default="high", choices=["minimal", "low", "medium", "high"],
                    help="reasoning effort for OpenAI reasoning models (default: high)")
    ap.add_argument("--gemini-thinking", default="low", choices=["minimal", "low", "medium", "high"],
                    help="Gemini 3.x thinking level (default: low)")
    ap.add_argument("--no-skip-detect", action="store_true",
                    help="translate even files already in the target language")
    ap.add_argument("--workers", type=int, default=8, help="parallel files (default: 8)")
    ap.add_argument("--overwrite", action="store_true")
    args = ap.parse_args()

    load_env()
    if args.provider == "openai":
        provider = OpenAIProvider(args.model, args.openai_effort)
    else:
        provider = GeminiProvider(args.model, args.gemini_thinking)

    # resolve inputs + output paths
    if os.path.isdir(args.input):
        files = sorted(glob.glob(os.path.join(args.input, "*.md")) +
                       glob.glob(os.path.join(args.input, "*.txt")) +
                       glob.glob(os.path.join(args.input, "*.html")))
        out_dir = args.out_dir or (args.input.rstrip("/\\") + "-" + slug(args.to))
        os.makedirs(out_dir, exist_ok=True)
        jobs = [(f, os.path.join(out_dir, os.path.basename(f))) for f in files]
    else:
        files = [args.input]
        if args.out_dir:
            os.makedirs(args.out_dir, exist_ok=True)
            dst = os.path.join(args.out_dir, os.path.basename(args.input))
        else:
            stem, ext = os.path.splitext(args.input)
            dst = f"{stem}.{slug(args.to)}{ext}"
        jobs = [(args.input, dst)]

    if not files:
        sys.exit("No .md/.txt/.html files found in input.")
    jobs = [(s, d) for s, d in jobs if args.overwrite or not (os.path.exists(d) and os.path.getsize(d) > 0)]
    print(f"translating {len(jobs)} file(s) -> {args.to} via {args.provider}", flush=True)

    skip_detect = not args.no_skip_detect
    with cf.ThreadPoolExecutor(max_workers=max(1, args.workers)) as pool:
        futs = {pool.submit(translate_file, provider, s, d, args.to, skip_detect): s for s, d in jobs}
        for fut in cf.as_completed(futs):
            try:
                print(fut.result(), flush=True)
            except Exception as e:
                print(f"FAILED {os.path.basename(futs[fut])}: {e}", flush=True)
    print("TRANSLATE_DONE", flush=True)


if __name__ == "__main__":
    main()
