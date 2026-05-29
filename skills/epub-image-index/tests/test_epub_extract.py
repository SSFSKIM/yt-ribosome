"""Unit + integration tests for epub_extract.py.

The extractor is deterministic and makes NO keep/drop decisions, so the tests
assert plumbing only: parsing, breadcrumb mapping, context capture, dimensions,
occurrence grouping, and that EVERY image survives (nothing is filtered).
"""
import io
import json
import os
import sys
import zipfile

import pytest
from PIL import Image

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import epub_extract as ex


def _png(w, h):
    buf = io.BytesIO()
    Image.new("RGB", (w, h), (200, 120, 90)).save(buf, "PNG")
    return buf.getvalue()


CONTAINER = (
    '<?xml version="1.0"?><container version="1.0" '
    'xmlns="urn:oasis:names:tc:opendocument:xmlns:container"><rootfiles>'
    '<rootfile full-path="OEBPS/content.opf" '
    'media-type="application/oebps-package+xml"/></rootfiles></container>'
)


def _opf(items, spine_ids):
    man = "".join(items)
    spn = "".join(f'<itemref idref="{i}"/>' for i in spine_ids)
    return (
        '<?xml version="1.0"?><package xmlns="http://www.idpf.org/2007/opf" '
        'version="3.0" unique-identifier="id"><metadata '
        'xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:title>Test Book'
        '</dc:title><dc:language>en</dc:language></metadata>'
        f'<manifest>{man}</manifest><spine>{spn}</spine></package>'
    )


NAV = (
    '<?xml version="1.0"?><html xmlns="http://www.w3.org/1999/xhtml" '
    'xmlns:epub="http://www.idpf.org/2007/ops"><body><nav epub:type="toc"><ol>'
    '<li><a href="cover.xhtml">Cover</a></li>'
    '<li><a href="ch1.xhtml">Ch 1</a><ol>'
    '<li><a href="ch1.xhtml#tA">Topic A</a></li></ol></li>'
    '</ol></nav></body></html>'
)

COVER = '<html><body><img src="images/coverimg.png" alt=""/></body></html>'

_FIGS = "".join(
    f'<figure><img src="images/img{n}.png" alt=""/>'
    f'<figcaption>Figure 1.{n} Example {n}</figcaption></figure>'
    for n in range(1, 6)
)
CH1 = (
    '<html><body>'
    '<h1>Ch 1</h1><p>Intro paragraph.</p>'
    + _FIGS +
    '<img src="images/largebare.png" alt=""/><p>just prose, no caption.</p>'
    '<img src="images/tiny.png" alt="" class="inline"/>'
    '<h2 id="tA">Topic A</h2>'
    '<figure><img src="images/img1.png" alt=""/><figcaption>Figure 1.1 again</figcaption></figure>'
    '<img src="images/capbare.png" alt=""/><p>Figure 9 A captioned diagram.</p>'
    '</body></html>'
)


@pytest.fixture
def book(tmp_path):
    imgs = {
        "coverimg": _png(600, 800), "largebare": _png(400, 300),
        "tiny": _png(16, 16), "capbare": _png(350, 250),
        **{f"img{n}": _png(300, 200) for n in range(1, 6)},
    }
    items = [
        '<item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>',
        '<item id="cover" href="cover.xhtml" media-type="application/xhtml+xml"/>',
        '<item id="ch1" href="ch1.xhtml" media-type="application/xhtml+xml"/>',
    ] + [f'<item id="{k}" href="images/{k}.png" media-type="image/png"/>' for k in imgs]
    p = tmp_path / "b.epub"
    with zipfile.ZipFile(str(p), "w") as z:
        z.writestr("mimetype", "application/epub+zip")
        z.writestr("META-INF/container.xml", CONTAINER)
        z.writestr("OEBPS/content.opf", _opf(items, ["cover", "ch1"]))
        z.writestr("OEBPS/nav.xhtml", NAV)
        z.writestr("OEBPS/cover.xhtml", COVER)
        z.writestr("OEBPS/ch1.xhtml", CH1)
        for k, data in imgs.items():
            z.writestr(f"OEBPS/images/{k}.png", data)
    return str(p)


# ---- pure helpers ----

def test_safe_xml_rejects_entity():
    with pytest.raises(ValueError):
        ex._safe_xml(b'<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "x">]><x/>')


def test_safe_name():
    assert ex.safe_name("A/B: C?") == "A B C"
    assert ex.safe_name("") == "untitled"


def test_flatten_toc_breadcrumbs():
    toc = [{"label": "Ch 1", "file": "c1", "anchor": None,
            "children": [{"label": "Topic A", "file": "c1", "anchor": "tA", "children": []}]}]
    flat = ex.flatten_toc(toc)
    assert flat[0]["breadcrumb"] == ["Ch 1"]
    assert flat[1]["breadcrumb"] == ["Ch 1", "Topic A"]


def test_parse_opf_and_nav(book):
    z = zipfile.ZipFile(book)
    meta, spine, nav_path, ncx_path = ex.parse_opf(z)
    assert meta["title"] == "Test Book"
    assert nav_path == "OEBPS/nav.xhtml"
    assert spine == ["OEBPS/cover.xhtml", "OEBPS/ch1.xhtml"]
    toc = ex.parse_nav_xhtml(z, nav_path)
    assert toc[1]["label"] == "Ch 1"
    assert toc[1]["children"][0]["anchor"] == "tA"


# ---- integration: nothing dropped, signals + context correct ----

def test_extract_keeps_everything_with_signals(book, tmp_path):
    out = tmp_path / "out"
    stats = ex.extract(book, str(out))
    assert stats["title"] == "Test Book"
    data = json.load(open(os.path.join(stats["book_dir"], "extract.json"), encoding="utf-8"))
    by_src = {os.path.basename(r["source_image"]): r for r in data["images"]}

    # EVERY referenced image survives — nothing filtered (the whole point).
    assert set(by_src) == {"coverimg.png", "tiny.png", "largebare.png", "capbare.png",
                           "img1.png", "img2.png", "img3.png", "img4.png", "img5.png"}
    assert data["image_count"] == 9
    assert data["occurrence_count"] == 10           # img1 appears twice

    # Raw markup signals are recorded (not acted on).
    assert by_src["img2.png"]["occurrences"][0]["in_figure"] is True
    assert by_src["tiny.png"]["occurrences"][0]["in_figure"] is False
    assert by_src["tiny.png"]["occurrences"][0]["css_class"] == "inline"
    assert by_src["img2.png"]["occurrences"][0]["caption"] == "Figure 1.2 Example 2"

    # Dimensions captured.
    assert by_src["tiny.png"]["width"] == 16 and by_src["tiny.png"]["height"] == 16
    assert by_src["largebare.png"]["width"] == 400

    # Breadcrumb mapping: capbare is after the Topic A anchor; img2 before it.
    assert by_src["capbare.png"]["occurrences"][0]["breadcrumb"] == ["Ch 1", "Topic A"]
    assert by_src["img2.png"]["occurrences"][0]["breadcrumb"] == ["Ch 1"]
    # capbare's caption line is left in context (extractor does NOT promote it).
    assert by_src["capbare.png"]["occurrences"][0]["caption"] == ""
    assert by_src["capbare.png"]["occurrences"][0]["context_after"].startswith("Figure 9")

    # img1 occurs twice with both locations preserved.
    bcs = [o["breadcrumb"] for o in by_src["img1.png"]["occurrences"]]
    assert ["Ch 1"] in bcs and ["Ch 1", "Topic A"] in bcs

    # All images physically copied.
    assert len(os.listdir(os.path.join(stats["book_dir"], "images"))) == 9
    # toc present.
    assert [t["label"] for t in data["toc"]] == ["Cover", "Ch 1"]
