#!/usr/bin/env python3
"""Extract every image from an EPUB with its location + context — raw material
for an agent to classify and organize. Makes NO keep/drop/figure decisions.

This is a thin, deterministic helper for the `epub-image-index` skill. It does
only the mechanical work an agent shouldn't redo by hand:

  - container.xml -> OPF -> nav.xhtml/toc.ncx  (EPUB2 + EPUB3)
  - a `breadcrumb` (TOC path) for every image, from the nearest preceding anchor
  - the surrounding context (nearest heading, prev/next paragraph, caption)
  - raw markup signals (in_figure, css class, role/epub:type) + pixel dimensions
  - copies each referenced image out once

What it deliberately does NOT do (that's the agent's job, per SKILL.md): decide
whether an image is a figure vs inline math vs decorative, drop anything, tag
types, or pick thresholds. It emits ALL images with the signals; the agent
inspects the book, chooses a per-book rule, tags, and writes the final index.

Output: `<out>/<Book Title>/extract.json` + `<out>/<Book Title>/images/`.

Usage:
    python3 epub_extract.py <epub-or-dir> [--out-dir DIR]
"""
import argparse
import glob
import io
import json
import os
import posixpath
import re
import sys
import urllib.parse
import zipfile
from collections import OrderedDict
from html.parser import HTMLParser
from xml.etree import ElementTree as ET

from bs4 import BeautifulSoup

try:
    from PIL import Image
except ImportError:
    Image = None

_CONTAINER_NS = {"c": "urn:oasis:names:tc:opendocument:xmlns:container"}
_WS = re.compile(r"\s+")


def _safe_xml(data):
    """Parse untrusted EPUB XML, rejecting entity declarations (XXE / DoS)."""
    if isinstance(data, str):
        data = data.encode("utf-8", "replace")
    if b"<!entity" in data.lower():
        raise ValueError("XML entity declaration rejected (possible XXE/DoS)")
    return ET.fromstring(data)


def _lname(tag):
    return tag.rsplit("}", 1)[-1]


def safe_name(s):
    s = re.sub(r'[\\/:*?"<>|#%&{}\[\]\x00-\x1f]+', " ", s or "")
    s = _WS.sub(" ", s).strip().strip(". ")
    return (s or "untitled")[:120]


def _collapse(s):
    return _WS.sub(" ", s or "").strip()


def parse_opf(zf):
    container = _safe_xml(zf.read("META-INF/container.xml"))
    opf_path = container.find(".//c:rootfile", _CONTAINER_NS).get("full-path")
    opf_dir = posixpath.dirname(opf_path)
    opf = _safe_xml(zf.read(opf_path))

    meta, manifest, spine_idrefs = {}, {}, []
    nav_id = ncx_id = spine_toc = None
    for el in opf.iter():
        ln = _lname(el.tag)
        if ln in ("title", "creator", "language") and el.text and ln not in meta:
            meta[ln] = el.text.strip()
        elif ln == "item":
            iid, href = el.get("id"), el.get("href")
            if not iid or not href:
                continue
            absref = posixpath.normpath(posixpath.join(opf_dir, href)) if opf_dir else href
            props = el.get("properties") or ""
            manifest[iid] = {"href": absref, "type": el.get("media-type") or ""}
            if "nav" in props.split():
                nav_id = iid
        elif ln == "itemref":
            spine_idrefs.append(el.get("idref"))
        elif ln == "spine":
            spine_toc = el.get("toc")

    if spine_toc and spine_toc in manifest:
        ncx_id = spine_toc
    if ncx_id is None:
        for iid, it in manifest.items():
            if it["type"] == "application/x-dtbncx+xml":
                ncx_id = iid
                break

    spine_paths = [manifest[i]["href"] for i in spine_idrefs if i in manifest]
    nav_path = manifest[nav_id]["href"] if nav_id else None
    ncx_path = manifest[ncx_id]["href"] if ncx_id else None
    return meta, spine_paths, nav_path, ncx_path


def _resolve(base_dir, href):
    raw, _, anchor = (href or "").partition("#")
    raw = urllib.parse.unquote(raw)
    if not raw:
        return None, (anchor or None)
    path = posixpath.normpath(posixpath.join(base_dir, raw)) if base_dir else raw
    return path, (anchor or None)


def parse_nav_xhtml(zf, nav_path):
    base = posixpath.dirname(nav_path)
    soup = BeautifulSoup(zf.read(nav_path).decode("utf-8", "replace"), "html.parser")
    nav = (soup.find("nav", attrs={"epub:type": "toc"})
           or soup.find("nav", attrs={"role": "doc-toc"}) or soup.find("nav"))
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
            f, anchor = _resolve(base, a.get("href")) if a.name == "a" else (None, None)
            sub = li.find("ol", recursive=False)
            out.append({"label": a.get_text(" ", strip=True), "file": f,
                        "anchor": anchor, "children": walk(sub) if sub else []})
        return out

    return walk(top)


def parse_ncx(zf, ncx_path):
    base = posixpath.dirname(ncx_path)
    root = _safe_xml(zf.read(ncx_path))
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
            f, anchor = _resolve(base, content.get("src") if content is not None else None)
            out.append({"label": text_of(np), "file": f, "anchor": anchor,
                        "children": walk(np)})
        return out

    return walk(navmap)


def flatten_toc(nodes, parent=None, out=None):
    out = [] if out is None else out
    parent = parent or []
    for n in nodes:
        bc = parent + [n["label"]]
        out.append({"file": n.get("file"), "anchor": n.get("anchor"), "breadcrumb": bc})
        if n.get("children"):
            flatten_toc(n["children"], bc, out)
    return out


def toc_to_json(nodes):
    out = []
    for n in nodes:
        entry = {"label": n["label"]}
        if n.get("children"):
            entry["children"] = toc_to_json(n["children"])
        out.append(entry)
    return out


class ImageWalker(HTMLParser):
    """Walk one chapter's XHTML, emitting a raw event per <img>/<image> with its
    breadcrumb (advances as anchor ids pass), nearest heading, figure caption,
    raw markup signals, and the paragraphs immediately before/after. No
    judgement about whether the image is a figure.
    """
    _HEADINGS = {"h1", "h2", "h3", "h4", "h5", "h6"}
    _CAPTURE = _HEADINGS | {"p", "figcaption", "li"}

    def __init__(self, anchor_breadcrumb, initial_breadcrumb):
        super().__init__(convert_charrefs=True)
        self.anchor_breadcrumb = anchor_breadcrumb
        self.cur_bc = list(initial_breadcrumb)
        self.events = []
        self._buf = []
        self._cap_tag = None
        self._last_heading = ""
        self._paras = []
        self._pending = []
        self._fig_depth = 0
        self._fig_text = []
        self._figcaption = None
        self._fig_imgs = []

    def handle_starttag(self, tag, attrs):
        a = {k: (v or "") for k, v in attrs}
        aid = a.get("id")
        if aid and aid in self.anchor_breadcrumb:
            self.cur_bc = self.anchor_breadcrumb[aid]
        if tag == "figure":
            if self._fig_depth == 0:
                self._fig_text, self._figcaption, self._fig_imgs = [], None, []
            self._fig_depth += 1
        if tag in self._CAPTURE:
            self._cap_tag = tag
            self._buf = []
        if tag in ("img", "image"):
            self._on_image(a)

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)

    def _on_image(self, a):
        src = a.get("src") or a.get("xlink:href") or a.get("href")
        if not src:
            return
        ev = {
            "src": src,
            "alt": a.get("alt", ""),
            "css_class": a.get("class", ""),
            "role": a.get("role", "") or a.get("epub:type", ""),
            "breadcrumb": list(self.cur_bc),
            "nearest_heading": self._last_heading,
            "in_figure": self._fig_depth > 0,
            "caption": "",
            "context_before": self._paras[-1] if self._paras else "",
            "context_after": "",
        }
        self.events.append(ev)
        idx = len(self.events) - 1
        self._pending.append(idx)
        if self._fig_depth > 0:
            self._fig_imgs.append(idx)

    def handle_data(self, data):
        if self._cap_tag:
            self._buf.append(data)
        if self._fig_depth > 0:
            self._fig_text.append(data)

    def handle_endtag(self, tag):
        if self._cap_tag == tag:
            text = _collapse("".join(self._buf))
            self._cap_tag = None
            self._buf = []
            if tag in self._HEADINGS:
                if text:
                    self._last_heading = text
            elif tag == "figcaption":
                self._figcaption = text
            elif tag in ("p", "li"):
                if text:
                    self._paras.append(text)
                    if len(self._paras) > 4:
                        self._paras.pop(0)
                    for i in self._pending:
                        if not self.events[i]["context_after"]:
                            self.events[i]["context_after"] = text
                    self._pending = []
        if tag == "figure" and self._fig_depth > 0:
            self._fig_depth -= 1
            if self._fig_depth == 0:
                cap = self._figcaption or _collapse("".join(self._fig_text))
                for i in self._fig_imgs:
                    if not self.events[i]["caption"]:
                        self.events[i]["caption"] = cap
                self._fig_text, self._figcaption, self._fig_imgs = [], None, []


def _resolve_src(file_path, src):
    raw = urllib.parse.unquote((src or "").split("#")[0])
    if not raw:
        return None
    d = posixpath.dirname(file_path)
    return posixpath.normpath(posixpath.join(d, raw)) if d else raw


def extract(epub_path, out_root):
    """Extract all images + context from one EPUB. Returns a stats dict."""
    zf = zipfile.ZipFile(epub_path)
    meta, spine, nav_path, ncx_path = parse_opf(zf)
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

    flat = flatten_toc(toc)
    anchors_by_file, file_level_bc, first_bc = {}, {}, {}
    for e in flat:
        f = e["file"]
        if not f:
            continue
        first_bc.setdefault(f, e["breadcrumb"])
        if e["anchor"]:
            anchors_by_file.setdefault(f, {})[e["anchor"]] = e["breadcrumb"]
        else:
            file_level_bc.setdefault(f, e["breadcrumb"])

    def initial_bc(f):
        if f in file_level_bc:
            return file_level_bc[f]
        bc = first_bc.get(f)
        if bc:
            return bc[:-1] if len(bc) > 1 else bc
        return []

    dim_cache = {}

    def dims(path):
        if Image is None or not path:
            return (None, None)
        if path not in dim_cache:
            try:
                with Image.open(io.BytesIO(zf.read(path))) as im:
                    dim_cache[path] = im.size
            except Exception:
                dim_cache[path] = (None, None)
        return dim_cache[path]

    # Group every image occurrence by resolved source path (identical bytes =
    # one image, but keep every place it appears). No filtering.
    images = OrderedDict()
    occurrence_count = 0
    for sidx, fpath in enumerate(spine, 1):
        try:
            html = zf.read(fpath).decode("utf-8", "replace")
        except KeyError:
            continue
        walker = ImageWalker(anchors_by_file.get(fpath, {}), initial_bc(fpath))
        try:
            walker.feed(html)
        except Exception:
            continue
        for ev in walker.events:
            resolved = _resolve_src(fpath, ev["src"])
            if not resolved:
                continue
            occurrence_count += 1
            occ = {
                "breadcrumb": ev["breadcrumb"],
                "nearest_heading": ev["nearest_heading"],
                "in_figure": ev["in_figure"],
                "css_class": ev["css_class"],
                "role": ev["role"],
                "alt": ev["alt"],
                "caption": ev["caption"],
                "context_before": ev["context_before"][:400],
                "context_after": ev["context_after"][:400],
                "source_file": fpath,
                "spine_index": sidx,
            }
            if resolved in images:
                images[resolved]["occurrences"].append(occ)
            else:
                w, h = dims(resolved)
                images[resolved] = {"source_image": resolved, "width": w,
                                    "height": h, "occurrences": [occ]}

    # Copy each referenced image out once (mechanical; the agent prunes/keeps).
    images_dir = os.path.join(book_dir, "images")
    os.makedirs(images_dir, exist_ok=True)
    used = {}
    out_images = []
    for resolved, rec in images.items():
        base = posixpath.basename(resolved)
        if base in used and used[base] != resolved:
            stem, ext = posixpath.splitext(base)
            n = 1
            while f"{stem}_{n}{ext}" in used:
                n += 1
            base = f"{stem}_{n}{ext}"
        used[base] = resolved
        try:
            with open(os.path.join(images_dir, base), "wb") as f:
                f.write(zf.read(resolved))
        except KeyError:
            continue
        rec["image"] = f"images/{base}"
        out_images.append(rec)

    in_fig = sum(1 for r in out_images for o in r["occurrences"] if o["in_figure"])
    with_cap = sum(1 for r in out_images
                   if any(o["caption"] for o in r["occurrences"]))
    payload = {
        "book": {"title": title, "creator": meta.get("creator", ""),
                 "language": meta.get("language", ""),
                 "source_epub": os.path.basename(epub_path)},
        "toc": toc_to_json(toc),
        "image_count": len(out_images),
        "occurrence_count": occurrence_count,
        "images": out_images,
    }
    os.makedirs(book_dir, exist_ok=True)
    with open(os.path.join(book_dir, "extract.json"), "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)

    return {"title": title, "book_dir": book_dir, "images": len(out_images),
            "occurrences": occurrence_count, "in_figure": in_fig,
            "with_caption": with_cap}


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("target", help="An .epub file or a directory of them")
    ap.add_argument("--out-dir", default=None,
                    help="Output dir (default: <target>-extract sibling)")
    args = ap.parse_args()

    target = os.path.abspath(args.target)
    if os.path.isdir(target):
        epubs = sorted(glob.glob(os.path.join(target, "**", "*.epub"), recursive=True))
        default_out = target.rstrip(os.sep) + "-extract"
    elif os.path.isfile(target):
        epubs = [target]
        default_out = os.path.splitext(target)[0] + "-extract"
    else:
        sys.exit(f"Not found: {target}")
    if not epubs:
        sys.exit("No .epub files found.")
    if Image is None:
        print("!! Pillow missing — image dimensions will be null.", file=sys.stderr)

    out_root = os.path.abspath(args.out_dir) if args.out_dir else default_out
    os.makedirs(out_root, exist_ok=True)
    print(f"Extracting images from {len(epubs)} book(s) -> {out_root}\n")

    ok = 0
    for ep in epubs:
        try:
            s = extract(ep, out_root)
            ok += 1
            # A quick profile to help the agent choose a per-book tagging rule.
            print(f"OK   {s['title'][:48]}")
            print(f"       {s['images']} unique images / {s['occurrences']} occurrences"
                  f"  |  {s['in_figure']} in <figure>  |  {s['with_caption']} captioned")
        except Exception as e:
            print(f"FAIL {os.path.basename(ep)}: {type(e).__name__}: {e}", file=sys.stderr)

    print(f"\nDONE  books={ok}/{len(epubs)}")
    print("Next (agent): read each <book>/extract.json, decide per-book how to "
          "tag images (figure/equation/photo/decorative), keep all, and write "
          "index.json. See SKILL.md.")


if __name__ == "__main__":
    main()
