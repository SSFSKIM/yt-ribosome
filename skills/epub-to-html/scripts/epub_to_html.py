#!/usr/bin/env python3
"""Convert EPUB books into a folder tree of HTML that mirrors the book's own
table-of-contents hierarchy — browsable in the `blog-library` web UI.

An EPUB is a ZIP of XHTML + CSS + images described by an OPF package (manifest
+ spine) and a navigation document (EPUB3 `nav.xhtml` or EPUB2 `toc.ncx`). The
*reading hierarchy* (unit -> chapter -> topic) lives in the nav, not in the
physical file layout, so this converter:

  1. reads `container.xml -> OPF` for metadata/manifest/spine,
  2. parses the nav into a tree (nav.xhtml preferred, toc.ncx fallback),
  3. reproduces that tree as nested folders: a TOC entry with children becomes
     a folder (its own pre-children content becomes `00. <label>.html`); a leaf
     becomes a `NN. <label>.html` file,
  4. SPLITS chapter files at their `#anchor` targets so topics become separate
     files (the book keeps no giant single-file chapters),
  5. copies all images/CSS/fonts into a hidden `.assets/` folder per book and
     rewrites links, so each page renders with the book's own styling.

Generic by design: never assumes a fixed internal layout, tolerates EPUB2/3,
arbitrary nav depth, anchor- or file-granular TOC entries, and missing navs
(falls back to spine order). Stdlib `zipfile` + `bs4` only.

Usage:
    python3 epub_to_html.py <epub-file-or-dir> [--out-dir DIR]
"""
import argparse
import glob
import os
import posixpath
import re
import sys
import urllib.parse
import zipfile
from xml.etree import ElementTree as ET

from bs4 import BeautifulSoup

_CONTAINER_NS = {"c": "urn:oasis:names:tc:opendocument:xmlns:container"}
# Manifest media-types that are CONTENT (everything else -> copied asset).
_NON_ASSET_TYPES = {
    "application/xhtml+xml", "application/x-dtbncx+xml",
    "application/oebps-package+xml", "text/html",
}

_PAGE_CSS = (
    "html{-webkit-text-size-adjust:100%}"
    "body{max-width:880px;margin:0 auto;padding:28px 22px;line-height:1.6}"
    "img{max-width:100%;height:auto}figure{margin:1.2em 0;text-align:center}"
    "table{border-collapse:collapse;max-width:100%}"
)


def _safe_xml(data):
    """Parse XML from an UNTRUSTED .epub, refusing entity declarations.

    EPUBs are downloaded from the internet, so their OPF/NCX is untrusted XML.
    Both XXE (external-entity) and billion-laughs (internal-entity expansion)
    attacks require an `<!ENTITY ...>` declaration — which legitimate EPUB
    metadata never uses — so we reject any and parse the rest with stdlib ET.
    (CPython 3.7.1+ already disables external-entity *fetching*; this also
    closes the internal-expansion DoS, with no third-party dependency.)
    """
    if isinstance(data, str):
        data = data.encode("utf-8", "replace")
    if b"<!entity" in data.lower():
        raise ValueError("XML entity declaration rejected (possible XXE/DoS)")
    return ET.fromstring(data)


def _lname(tag):
    return tag.rsplit("}", 1)[-1]


def safe_name(s):
    """Filesystem-safe label: drop path/URL-hostile chars, collapse, cap len."""
    s = re.sub(r'[\\/:*?"<>|#%&{}\[\]\x00-\x1f]+', " ", s or "")
    s = re.sub(r"\s+", " ", s).strip().strip(". ")
    return (s or "untitled")[:120]


# ---------------------------------------------------------------- OPF / nav ---

def _read(zf, path):
    return zf.read(path)


def parse_opf(zf):
    """Return (opf_dir, metadata, manifest, spine_paths, nav_path, ncx_path).

    manifest: id -> {href(abs), type, props}; spine_paths: ordered abs hrefs.
    """
    container = _safe_xml(_read(zf, "META-INF/container.xml"))
    opf_path = container.find(".//c:rootfile", _CONTAINER_NS).get("full-path")
    opf_dir = posixpath.dirname(opf_path)
    opf = _safe_xml(_read(zf, opf_path))

    meta = {}
    manifest = {}
    spine_idrefs = []
    nav_id = ncx_id = None
    spine_toc = None
    for el in opf.iter():
        ln = _lname(el.tag)
        if ln in ("title", "creator", "language") and el.text and ln not in meta:
            meta[ln] = el.text.strip()
        elif ln == "item":
            iid = el.get("id")
            href = el.get("href")
            if not iid or not href:
                continue
            absref = posixpath.normpath(posixpath.join(opf_dir, href)) \
                if opf_dir else href
            props = el.get("properties") or ""
            manifest[iid] = {"href": absref, "type": el.get("media-type") or "",
                             "props": props}
            if "nav" in props.split():
                nav_id = iid
        elif ln == "itemref":
            spine_idrefs.append(el.get("idref"))
        elif ln == "spine":
            spine_toc = el.get("toc")

    if spine_toc and spine_toc in manifest:
        ncx_id = spine_toc
    if ncx_id is None:  # fall back: any dtbncx item
        for iid, it in manifest.items():
            if it["type"] == "application/x-dtbncx+xml":
                ncx_id = iid
                break

    spine_paths = [manifest[i]["href"] for i in spine_idrefs if i in manifest]
    nav_path = manifest[nav_id]["href"] if nav_id else None
    ncx_path = manifest[ncx_id]["href"] if ncx_id else None
    return opf_dir, meta, manifest, spine_paths, nav_path, ncx_path


def _resolve(base_dir, href):
    """('OEBPS', 'c1.xhtml#aP2') -> ('OEBPS/c1.xhtml', 'aP2')."""
    raw, _, anchor = (href or "").partition("#")
    raw = urllib.parse.unquote(raw)
    if not raw:
        return None, (anchor or None)
    path = posixpath.normpath(posixpath.join(base_dir, raw)) if base_dir else raw
    return path, (anchor or None)


def parse_nav_xhtml(zf, nav_path):
    """EPUB3 nav.xhtml -> list of TOC nodes {label, file, anchor, children}."""
    base = posixpath.dirname(nav_path)
    soup = BeautifulSoup(_read(zf, nav_path).decode("utf-8", "replace"),
                         "html.parser")
    nav = (soup.find("nav", attrs={"epub:type": "toc"})
           or soup.find("nav", attrs={"role": "doc-toc"})
           or soup.find("nav"))
    if not nav:
        return []
    top = nav.find("ol")
    if not top:
        return []

    def walk(ol):
        out = []
        for li in ol.find_all("li", recursive=False):
            a = li.find(["a", "span"], recursive=False) or li.find(["a", "span"])
            if a is None:
                continue
            label = a.get_text(" ", strip=True)
            f, anchor = _resolve(base, a.get("href")) if a.name == "a" else (None, None)
            sub = li.find("ol", recursive=False)
            out.append({"label": label, "file": f, "anchor": anchor,
                        "children": walk(sub) if sub else []})
        return out

    return walk(top)


def parse_ncx(zf, ncx_path):
    """EPUB2 toc.ncx -> list of TOC nodes (navPoint nesting)."""
    base = posixpath.dirname(ncx_path)
    root = _safe_xml(_read(zf, ncx_path))
    navmap = next((e for e in root.iter() if _lname(e.tag) == "navMap"), None)
    if navmap is None:
        return []

    def text_of(np):
        lbl = next((e for e in np if _lname(e.tag) == "navLabel"), None)
        if lbl is not None:
            t = next((e for e in lbl if _lname(e.tag) == "text"), None)
            if t is not None and t.text:
                return t.text.strip()
        return "(untitled)"

    def walk(parent):
        out = []
        for np in [e for e in parent if _lname(e.tag) == "navPoint"]:
            content = next((e for e in np if _lname(e.tag) == "content"), None)
            src = content.get("src") if content is not None else None
            f, anchor = _resolve(base, src)
            out.append({"label": text_of(np), "file": f, "anchor": anchor,
                        "children": walk(np)})
        return out

    return walk(navmap)


# --------------------------------------------------------- content splitting ---

def _top_child_index(soup, body, top_children, anchor_id):
    """Index into top_children of the body-direct-child holding `anchor_id`."""
    el = soup.find(id=anchor_id)
    if el is None:
        return None
    node = el
    while node.parent is not None and node.parent is not body:
        node = node.parent
    try:
        return top_children.index(node)
    except ValueError:
        return None


def split_file_segments(html_text, anchor_ids):
    """Split a chapter's body into anchor-keyed segments.

    Returns {None: [intro elements], anchor_id: [elements], ...} where each
    anchor owns the run of top-level body blocks from its position up to the
    next anchor (document order). `None` is the content before the first
    anchor (chapter intro). Elements are returned as HTML strings.
    """
    soup = BeautifulSoup(html_text, "html.parser")
    body = soup.body or soup
    top = [c for c in body.children if getattr(c, "name", None)]

    bounds = []
    for aid in anchor_ids:
        idx = _top_child_index(soup, body, top, aid)
        if idx is not None:
            bounds.append((idx, aid))
    bounds.sort()

    segs = {}
    first = bounds[0][0] if bounds else len(top)
    segs[None] = [str(e) for e in top[:first]]
    for i, (idx, aid) in enumerate(bounds):
        nxt = bounds[i + 1][0] if i + 1 < len(bounds) else len(top)
        run = top[idx:nxt] if nxt > idx else top[idx:idx + 1]
        segs[aid] = [str(e) for e in run]
    return segs


# ----------------------------------------------------------------- assets ----

_IMG_TAGS = ("img", "image")  # <image> = SVG raster


def collect_assets(zf, manifest):
    """epub-path -> flat asset filename (basename, de-duplicated on collision)."""
    used = {}
    name_to_src = {}
    for it in manifest.values():
        if it["type"] in _NON_ASSET_TYPES:
            continue
        src = it["href"]
        if src not in zf.namelist():
            continue
        base = posixpath.basename(src)
        if base in name_to_src and name_to_src[base] != src:
            stem, ext = posixpath.splitext(base)
            n = 1
            while f"{stem}_{n}{ext}" in name_to_src:
                n += 1
            base = f"{stem}_{n}{ext}"
        name_to_src[base] = src
        used[src] = base
    return used


def _rewrite_links(doc, file_dir, asset_map, asset_rel, css_names):
    """In a parsed fragment doc: point img/image + add the book CSS links."""
    def fix(tag, attr):
        val = tag.get(attr)
        if not val or val.startswith(("http:", "https:", "data:", "#")):
            return
        raw = urllib.parse.unquote(val.split("#")[0])
        target = posixpath.normpath(posixpath.join(file_dir, raw)) \
            if file_dir else raw
        name = asset_map.get(target)
        if name:
            tag[attr] = f"{asset_rel}/{urllib.parse.quote(name)}"

    for img in doc.find_all("img"):
        fix(img, "src")
    for image in doc.find_all("image"):
        if image.get("xlink:href"):
            fix(image, "xlink:href")
        elif image.get("href"):
            fix(image, "href")


def render_page(title, seg_html_list, lang, file_dir, asset_map,
                asset_rel, css_names):
    frag = "".join(seg_html_list)
    doc = BeautifulSoup(f"<body>{frag}</body>", "html.parser")
    _rewrite_links(doc, file_dir, asset_map, asset_rel, css_names)
    body_inner = doc.decode_contents() if hasattr(doc, "decode_contents") \
        else "".join(str(c) for c in doc.children)
    links = "".join(
        f'<link rel="stylesheet" href="{asset_rel}/{urllib.parse.quote(c)}">'
        for c in css_names)
    from html import escape
    return (
        f'<!DOCTYPE html>\n<html lang="{escape(lang)}">\n<head>\n'
        f'<meta charset="utf-8">\n'
        f'<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        f'<title>{escape(title)}</title>\n{links}\n'
        f'<style>{_PAGE_CSS}</style>\n</head>\n<body>\n{body_inner}\n</body>\n</html>\n'
    )


# ------------------------------------------------------------- emit a book ----

def _anchors_per_file(nodes, acc):
    """Map file-path -> set of anchor ids referenced anywhere in the TOC."""
    for n in nodes:
        if n["file"] and n["anchor"]:
            acc.setdefault(n["file"], set()).add(n["anchor"])
        if n["children"]:
            _anchors_per_file(n["children"], acc)
    return acc


def convert_book(epub_path, out_root):
    zf = zipfile.ZipFile(epub_path)
    opf_dir, meta, manifest, spine, nav_path, ncx_path = parse_opf(zf)
    lang = meta.get("language", "en")[:5] or "en"
    title = meta.get("title") or os.path.splitext(os.path.basename(epub_path))[0]
    book_dir = os.path.join(out_root, safe_name(title))

    toc = []
    if nav_path:
        try:
            toc = parse_nav_xhtml(zf, nav_path)
        except Exception:
            toc = []
    if not toc and ncx_path:
        try:
            toc = parse_ncx(zf, ncx_path)
        except Exception:
            toc = []
    if not toc:  # last resort: flat spine
        toc = [{"label": posixpath.splitext(posixpath.basename(p))[0],
                "file": p, "anchor": None, "children": []} for p in spine]

    # Assets -> .assets/
    asset_map = collect_assets(zf, manifest)
    assets_dir = os.path.join(book_dir, ".assets")
    os.makedirs(assets_dir, exist_ok=True)
    css_names = []
    for src, name in asset_map.items():
        try:
            data = zf.read(src)
        except KeyError:
            continue
        with open(os.path.join(assets_dir, name), "wb") as f:
            f.write(data)
        if manifest_type(manifest, src) == "text/css":
            css_names.append(name)

    # Pre-split every referenced file into anchor segments (cached).
    anchors = _anchors_per_file(toc, {})
    seg_cache = {}

    def segments_for(fpath):
        if fpath not in seg_cache:
            try:
                txt = zf.read(fpath).decode("utf-8", "replace")
                seg_cache[fpath] = split_file_segments(txt, anchors.get(fpath, set()))
            except KeyError:
                seg_cache[fpath] = {None: []}
        return seg_cache[fpath]

    stats = {"pages": 0}

    def seg_html(node):
        if not node["file"]:
            return []
        segs = segments_for(node["file"])
        if node["anchor"] and node["anchor"] in segs:
            return segs[node["anchor"]]
        return segs.get(None, [])  # whole-file / intro

    def asset_rel_for(out_file_path):
        rel = os.path.relpath(assets_dir, os.path.dirname(out_file_path))
        return urllib.parse.quote(rel.replace(os.sep, "/"))

    def file_dir_of(node):
        return posixpath.dirname(node["file"]) if node["file"] else ""

    def emit(nodes, parent_dir):
        width = max(2, len(str(len(nodes))))
        for i, node in enumerate(nodes, 1):
            base = f"{i:0{width}d}. {safe_name(node['label'])}"
            if node["children"]:
                folder = os.path.join(parent_dir, base)
                os.makedirs(folder, exist_ok=True)
                intro = seg_html(node)
                if any(s.strip() for s in intro):
                    out_file = os.path.join(folder, f"00. {safe_name(node['label'])}.html")
                    _write_page(node, intro, out_file)
                emit(node["children"], folder)
            else:
                out_file = os.path.join(parent_dir, base + ".html")
                _write_page(node, seg_html(node), out_file)

    def _write_page(node, seg, out_file):
        os.makedirs(os.path.dirname(out_file), exist_ok=True)
        html = render_page(node["label"] or title, seg, lang,
                           file_dir_of(node), asset_map,
                           asset_rel_for(out_file), css_names)
        with open(out_file, "w", encoding="utf-8") as f:
            f.write(html)
        stats["pages"] += 1

    os.makedirs(book_dir, exist_ok=True)
    emit(toc, book_dir)
    return title, book_dir, stats["pages"], len(asset_map)


def manifest_type(manifest, src):
    for it in manifest.values():
        if it["href"] == src:
            return it["type"]
    return ""


# ----------------------------------------------------------------- CLI -------

def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("target", help="An .epub file or a directory of them")
    ap.add_argument("--out-dir", default=None,
                    help="Output dir (default: <target>-html sibling)")
    args = ap.parse_args()

    target = os.path.abspath(args.target)
    if os.path.isdir(target):
        epubs = sorted(glob.glob(os.path.join(target, "**", "*.epub"),
                                 recursive=True))
        default_out = target.rstrip(os.sep) + "-html"
    elif os.path.isfile(target):
        epubs = [target]
        default_out = os.path.splitext(target)[0] + "-html"
    else:
        sys.exit(f"Not found: {target}")
    if not epubs:
        sys.exit("No .epub files found.")

    out_root = os.path.abspath(args.out_dir) if args.out_dir else default_out
    os.makedirs(out_root, exist_ok=True)
    print(f"Converting {len(epubs)} book(s) -> {out_root}\n")

    total_pages = total_assets = ok = 0
    for ep in epubs:
        try:
            title, book_dir, pages, assets = convert_book(ep, out_root)
            ok += 1
            total_pages += pages
            total_assets += assets
            print(f"OK   {title[:60]}  ({pages} pages, {assets} assets)")
        except Exception as e:
            print(f"FAIL {os.path.basename(ep)}: {type(e).__name__}: {e}",
                  file=sys.stderr)

    print(f"\nDONE  books={ok}/{len(epubs)}  pages={total_pages}  "
          f"assets={total_assets}")
    print(f"Browse with the blog-library skill pointed at {out_root}")


if __name__ == "__main__":
    main()
