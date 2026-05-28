#!/usr/bin/env python3
"""Mirror a folder of generated blog HTML into a Markdown (Obsidian) vault.

Walks an input directory (e.g. `yt-ribosome-blogs/`), reproduces its exact
folder structure into an output directory (default `<input>-md/`), converts
every blog `.html` into a `.md`, and copies the frame-image folders verbatim
so the result is a self-contained Obsidian vault — relative image links
resolve with no path-rewriting.

Only the article body (`div.post-body` produced by full-blog's render_html)
is converted; the site chrome (top bar, footer) is dropped. The blog title
and source URL are lifted into YAML frontmatter so Obsidian shows them.

Usage:
    python3 html_to_md.py <blogs-dir> [--out-dir DIR] [--quiet]

Idempotent: re-running overwrites the mirror. Stale files from blogs deleted
upstream are NOT pruned (delete the -md dir and re-run for a clean mirror).
"""
import argparse
import os
import re
import shutil
import sys
import urllib.parse

from bs4 import BeautifulSoup, NavigableString

# Editor/OS/tool clutter never mirrored. `index.html` is the library landing
# page (blog-library output), not a blog; `_run_summary.json` is run metadata.
_SKIP_NAMES = {".obsidian", ".playwright-cli", ".DS_Store", ".git",
               "__pycache__", "_run_summary.json", "index.html"}

_WS_RE = re.compile(r"\s+")


def _skip(name):
    return name in _SKIP_NAMES or name.startswith(".")


def _collapse(s):
    return _WS_RE.sub(" ", s).strip()


def _inline_md(node):
    """Convert a node's inline children to a Markdown string.

    Handles the inline tags full-blog can emit (a/code/strong/em/br); anything
    else is recursed through so unknown wrappers don't drop their text.
    """
    out = []
    for child in node.children:
        if isinstance(child, NavigableString):
            out.append(str(child))
            continue
        tag = child.name
        if tag in ("strong", "b"):
            out.append(f"**{_inline_md(child)}**")
        elif tag in ("em", "i"):
            out.append(f"*{_inline_md(child)}*")
        elif tag == "code":
            out.append(f"`{child.get_text()}`")
        elif tag == "a":
            txt = _inline_md(child)
            href = child.get("href", "")
            out.append(f"[{txt}]({href})" if href else txt)
        elif tag == "br":
            out.append("\n")
        else:
            out.append(_inline_md(child))
    return "".join(out)


def _figure_md(fig):
    """`<figure>` -> an image line plus an italic caption / timestamp line."""
    img = fig.find("img")
    if not img or not img.get("src"):
        return ""
    # alt is a long description; strip brackets/newlines so it can't break the
    # `![ ... ]( )` image syntax.
    alt = _collapse(img.get("alt", "")).replace("[", "(").replace("]", ")")
    # Normalise the path to percent-encoding: decode first so an already-encoded
    # src isn't double-encoded, then re-quote so raw spaces/Hangul become %20…
    # — Obsidian (and any CommonMark renderer) decodes these to resolve the
    # relative file. Raw spaces would otherwise truncate a `![]()` link.
    src = urllib.parse.quote(urllib.parse.unquote(img["src"]), safe="/")
    line = f"![{alt}]({src})"

    cap_el = fig.select_one(".caption-text")
    caption = _collapse(cap_el.get_text()) if cap_el else ""
    chip = fig.select_one("a.ts-chip")
    ts = _collapse(chip.get_text()) if chip else ""
    deep = chip.get("href", "") if chip else ""

    bits = []
    if caption:
        bits.append(caption)
    if ts:
        bits.append(f"[▶ {ts}]({deep})" if deep else f"▶ {ts}")
    return line + (f"\n*{' — '.join(bits)}*" if bits else "")


def _list_md(el):
    ordered = el.name == "ol"
    lines = []
    for i, li in enumerate(el.find_all("li", recursive=False), 1):
        marker = f"{i}." if ordered else "-"
        lines.append(f"{marker} {_collapse(_inline_md(li))}")
    return "\n".join(lines)


def _block_md(el):
    """One body-level element -> a list of Markdown blocks (usually one)."""
    name = el.name
    if name == "p":
        text = _collapse(_inline_md(el))
        return [text] if text else []
    if name in ("h2", "h3", "h4"):
        level = {"h2": "##", "h3": "###", "h4": "####"}[name]
        return [f"{level} {_collapse(_inline_md(el))}"]
    if name == "blockquote":
        text = _collapse(_inline_md(el))
        return ["\n".join(f"> {ln}" for ln in text.split("\n"))] if text else []
    if name in ("ul", "ol"):
        return [_list_md(el)]
    if name == "hr":
        return ["---"]
    if name == "figure":
        md = _figure_md(el)
        return [md] if md else []
    if name == "div" and "figure-row" in (el.get("class") or []):
        return [m for f in el.find_all("figure", recursive=False)
                if (m := _figure_md(f))]
    if name == "section":  # tail-section: heading + leftover figures
        out = []
        for child in el.find_all(recursive=False):
            out.extend(_block_md(child))
        return out
    # Unknown wrapper: recurse so its content isn't silently dropped.
    text = _collapse(_inline_md(el))
    return [text] if text else []


def html_to_markdown(html_text):
    soup = BeautifulSoup(html_text, "html.parser")

    title_el = soup.select_one("h1.post-title") or soup.title
    title = _collapse(title_el.get_text()) if title_el else "Untitled"
    src_el = soup.select_one(".post-meta a[href]") or soup.select_one("a.source-pill[href]")
    source = src_el.get("href", "") if src_el else ""

    blocks = []
    body = soup.select_one(".post-body")
    if body:
        for el in body.find_all(recursive=False):
            blocks.extend(_block_md(el))
    blocks = [b for b in blocks if b.strip()]

    fm = ["---", f'title: "{title.replace(chr(34), chr(39))}"']
    if source:
        fm.append(f"source: {source}")
    fm.append("---")

    parts = ["\n".join(fm), f"# {title}"]
    parts.extend(blocks)
    return "\n\n".join(parts) + "\n"


def convert_tree(in_dir, out_dir, quiet=False):
    in_dir = os.path.abspath(in_dir)
    out_dir = os.path.abspath(out_dir)
    stats = {"md": 0, "copied": 0, "skipped": 0, "failed": 0}

    for root, dirs, files in os.walk(in_dir):
        dirs[:] = sorted(d for d in dirs if not _skip(d))
        rel = os.path.relpath(root, in_dir)
        dest_root = out_dir if rel == "." else os.path.join(out_dir, rel)

        for name in sorted(files):
            if _skip(name):
                stats["skipped"] += 1
                continue
            src = os.path.join(root, name)
            os.makedirs(dest_root, exist_ok=True)
            if name.lower().endswith(".html"):
                try:
                    with open(src, encoding="utf-8") as f:
                        md = html_to_markdown(f.read())
                    dest = os.path.join(dest_root, name[:-5] + ".md")
                    with open(dest, "w", encoding="utf-8") as f:
                        f.write(md)
                    stats["md"] += 1
                    if not quiet:
                        print(f"MD   {os.path.relpath(dest, out_dir)}")
                except Exception as e:  # one bad file shouldn't abort the run
                    stats["failed"] += 1
                    print(f"FAIL {os.path.relpath(src, in_dir)}: {e}",
                          file=sys.stderr)
            else:  # image / asset -> copy verbatim (keeps relative links valid)
                shutil.copy2(src, os.path.join(dest_root, name))
                stats["copied"] += 1
    return stats


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("blogs_dir", help="Directory of generated blog .html files")
    ap.add_argument("--out-dir", default=None,
                    help="Output dir (default: <blogs-dir>-md as a sibling)")
    ap.add_argument("--quiet", action="store_true",
                    help="Only print the final summary")
    args = ap.parse_args()

    in_dir = os.path.abspath(args.blogs_dir)
    if not os.path.isdir(in_dir):
        sys.exit(f"Not a directory: {in_dir}")
    out_dir = os.path.abspath(args.out_dir) if args.out_dir \
        else in_dir.rstrip(os.sep) + "-md"
    if os.path.realpath(out_dir) == os.path.realpath(in_dir):
        sys.exit("Output dir must differ from input dir.")

    print(f"Converting {in_dir}\n        -> {out_dir}\n")
    stats = convert_tree(in_dir, out_dir, quiet=args.quiet)
    print(f"\nDONE  markdown={stats['md']}  images_copied={stats['copied']}  "
          f"skipped={stats['skipped']}  failed={stats['failed']}")
    print(f"Open {out_dir} as a vault in Obsidian.")


if __name__ == "__main__":
    main()
