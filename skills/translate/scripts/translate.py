#!/usr/bin/env python3
"""Translate transcript files into a target language with OpenAI or Gemini.

Input is a single file or a directory of `.md`/`.txt` files. Each file is
translated into `--to <language>` and written to the output directory. Markdown
structure, headings, and URLs are preserved; only natural-language text is
translated. The translator is told the source is an auto-generated transcript so
it silently corrects obvious speech-to-text errors (e.g. "Cloud" -> Claude).

Providers:
  - openai (default): chat.completions, default model gpt-4o
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
class OpenAIProvider:
    def __init__(self, model):
        from openai import OpenAI
        self.client = OpenAI()
        self.model = model or "gpt-4o"

    def run(self, text, system):
        r = self.client.chat.completions.create(
            model=self.model, temperature=0.3, max_tokens=16384,
            messages=[{"role": "system", "content": system},
                      {"role": "user", "content": text}],
        )
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
def translate_file(provider, src, dst, target, skip_detect):
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
    ap.add_argument("--model", default=None, help="override model (default: gpt-4o / gemini-3.5-flash)")
    ap.add_argument("--out-dir", default=None, help="output dir (default: <input>-<lang>)")
    ap.add_argument("--gemini-thinking", default="low", choices=["minimal", "low", "medium", "high"],
                    help="Gemini 3.x thinking level (default: low)")
    ap.add_argument("--no-skip-detect", action="store_true",
                    help="translate even files already in the target language")
    ap.add_argument("--workers", type=int, default=8, help="parallel files (default: 8)")
    ap.add_argument("--overwrite", action="store_true")
    args = ap.parse_args()

    load_env()
    if args.provider == "openai":
        provider = OpenAIProvider(args.model)
    else:
        provider = GeminiProvider(args.model, args.gemini_thinking)

    # resolve inputs + output paths
    if os.path.isdir(args.input):
        files = sorted(glob.glob(os.path.join(args.input, "*.md")) +
                       glob.glob(os.path.join(args.input, "*.txt")))
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
        sys.exit("No .md/.txt files found in input.")
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
