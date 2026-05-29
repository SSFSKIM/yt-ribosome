"""Unit tests for epub_to_html.py.

Builds tiny in-memory EPUBs (nav.xhtml and toc.ncx variants) so parsing,
anchor-splitting, recursion, asset rewriting, and XML hardening are all
exercised without depending on real book files.
"""
import io
import os
import sys
import zipfile

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import epub_to_html as e2h


CONTAINER = (
    '<?xml version="1.0"?><container version="1.0" '
    'xmlns="urn:oasis:names:tc:opendocument:xmlns:container">'
    '<rootfiles><rootfile full-path="OEBPS/content.opf" '
    'media-type="application/oebps-package+xml"/></rootfiles></container>'
)

CH1 = (
    '<?xml version="1.0"?><html xmlns="http://www.w3.org/1999/xhtml"><head>'
    '<link rel="stylesheet" href="style.css"/></head><body>'
    '<h1>Chapter One</h1><p>Intro text before any topic.</p>'
    '<h2 id="t1">Topic One</h2><p>Body of topic one.</p>'
    '<img src="img/p.png" alt="pic"/>'
    '<h2 id="t2">Topic Two</h2><p>Body of topic two.</p>'
    '</body></html>'
)

OPF_NAV = (
    '<?xml version="1.0"?><package xmlns="http://www.idpf.org/2007/opf" '
    'version="3.0" unique-identifier="id"><metadata '
    'xmlns:dc="http://purl.org/dc/elements/1.1/">'
    '<dc:title>My Test Book</dc:title><dc:creator>An Author</dc:creator>'
    '<dc:language>en</dc:language></metadata><manifest>'
    '<item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>'
    '<item id="ch1" href="ch1.xhtml" media-type="application/xhtml+xml"/>'
    '<item id="css" href="style.css" media-type="text/css"/>'
    '<item id="img" href="img/p.png" media-type="image/png"/>'
    '</manifest><spine><itemref idref="ch1"/></spine></package>'
)

NAV = (
    '<?xml version="1.0"?><html xmlns="http://www.w3.org/1999/xhtml" '
    'xmlns:epub="http://www.idpf.org/2007/ops"><body>'
    '<nav epub:type="toc"><ol>'
    '<li><a href="ch1.xhtml">Chapter One</a><ol>'
    '<li><a href="ch1.xhtml#t1">Topic One</a></li>'
    '<li><a href="ch1.xhtml#t2">Topic Two</a></li>'
    '</ol></li></ol></nav></body></html>'
)

# 1x1 PNG
PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4"
    "890000000d49444154789c6360000002000154a24f600000000049454e44ae426082"
)


def _make_epub(path, files):
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("mimetype", "application/epub+zip")
        z.writestr("META-INF/container.xml", CONTAINER)
        for name, data in files.items():
            z.writestr(name, data)


@pytest.fixture
def nav_epub(tmp_path):
    p = tmp_path / "book.epub"
    _make_epub(str(p), {
        "OEBPS/content.opf": OPF_NAV,
        "OEBPS/nav.xhtml": NAV,
        "OEBPS/ch1.xhtml": CH1,
        "OEBPS/style.css": "body{color:#222}",
        "OEBPS/img/p.png": PNG,
    })
    return str(p)


# ---- pure helpers ----

def test_safe_name_strips_hostile_chars():
    assert e2h.safe_name("A/B: C? #x") == "A B C x"
    assert e2h.safe_name("") == "untitled"
    assert e2h.safe_name("...trim...") == "trim"


def test_split_file_segments_intro_and_topics():
    segs = e2h.split_file_segments(CH1, {"t1", "t2"})
    assert set(segs) == {None, "t1", "t2"}
    assert "Intro text" in "".join(segs[None])
    assert "Chapter One" in "".join(segs[None])  # h1 lives in intro
    assert "Topic One" in "".join(segs["t1"])
    assert "Body of topic one" in "".join(segs["t1"])
    assert "Topic Two" not in "".join(segs["t1"])  # boundary respected
    assert "Topic Two" in "".join(segs["t2"])


def test_split_no_anchors_all_intro():
    segs = e2h.split_file_segments(CH1, set())
    assert set(segs) == {None}
    assert "Topic Two" in "".join(segs[None])  # everything in one segment


def test_safe_xml_rejects_entity_declaration():
    evil = b'<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "boom">]><x>&a;</x>'
    with pytest.raises(ValueError):
        e2h._safe_xml(evil)


def test_safe_xml_parses_clean():
    root = e2h._safe_xml(b'<?xml version="1.0"?><r><c>hi</c></r>')
    assert root.find("c").text == "hi"


# ---- nav.xhtml parsing + full conversion ----

def test_parse_opf_and_nav(nav_epub):
    z = zipfile.ZipFile(nav_epub)
    opf_dir, meta, manifest, spine, nav_path, ncx_path = e2h.parse_opf(z)
    assert meta["title"] == "My Test Book"
    assert meta["creator"] == "An Author"
    assert nav_path == "OEBPS/nav.xhtml"
    assert spine == ["OEBPS/ch1.xhtml"]
    toc = e2h.parse_nav_xhtml(z, nav_path)
    assert len(toc) == 1
    assert toc[0]["label"] == "Chapter One"
    assert len(toc[0]["children"]) == 2
    assert toc[0]["children"][0]["anchor"] == "t1"


def test_convert_book_structure(nav_epub, tmp_path):
    out = tmp_path / "out"
    title, book_dir, pages, assets = e2h.convert_book(nav_epub, str(out))
    assert title == "My Test Book"
    # Chapter One has children -> it's a folder with an intro + 2 topic files
    chap = os.path.join(book_dir, "01. Chapter One")
    assert os.path.isdir(chap)
    names = sorted(os.listdir(chap))
    assert names == ["00. Chapter One.html", "01. Topic One.html", "02. Topic Two.html"]
    # assets copied + hidden
    assert os.path.isfile(os.path.join(book_dir, ".assets", "style.css"))
    assert os.path.isfile(os.path.join(book_dir, ".assets", "p.png"))
    assert pages == 3 and assets == 2


def test_image_and_css_links_rewritten(nav_epub, tmp_path):
    out = tmp_path / "out"
    _, book_dir, _, _ = e2h.convert_book(nav_epub, str(out))
    topic = os.path.join(book_dir, "01. Chapter One", "01. Topic One.html")
    html = open(topic, encoding="utf-8").read()
    # the topic page holds the image; src must point into ../.assets
    assert "../.assets/p.png" in html
    assert "img/p.png" not in html  # original path rewritten away
    assert "../.assets/style.css" in html


def test_intro_excludes_topic_content(nav_epub, tmp_path):
    out = tmp_path / "out"
    _, book_dir, _, _ = e2h.convert_book(nav_epub, str(out))
    intro = open(os.path.join(book_dir, "01. Chapter One", "00. Chapter One.html"),
                 encoding="utf-8").read()
    assert "Intro text before any topic" in intro
    assert "Body of topic one" not in intro


# ---- toc.ncx (EPUB2) fallback ----

OPF_NCX = (
    '<?xml version="1.0"?><package xmlns="http://www.idpf.org/2007/opf" '
    'version="2.0" unique-identifier="id"><metadata '
    'xmlns:dc="http://purl.org/dc/elements/1.1/">'
    '<dc:title>NCX Book</dc:title><dc:language>en</dc:language></metadata>'
    '<manifest>'
    '<item id="ncx" href="toc.ncx" media-type="application/x-dtbncx+xml"/>'
    '<item id="ch1" href="ch1.xhtml" media-type="application/xhtml+xml"/>'
    '</manifest><spine toc="ncx"><itemref idref="ch1"/></spine></package>'
)

NCX = (
    '<?xml version="1.0"?><ncx xmlns="http://www.daisy.org/z3986/2005/ncx/" '
    'version="2005-1"><navMap>'
    '<navPoint id="n1" playOrder="1"><navLabel><text>Chapter One</text></navLabel>'
    '<content src="ch1.xhtml"/>'
    '<navPoint id="n2" playOrder="2"><navLabel><text>Topic One</text></navLabel>'
    '<content src="ch1.xhtml#t1"/></navPoint>'
    '</navPoint></navMap></ncx>'
)


def test_ncx_fallback(tmp_path):
    p = tmp_path / "ncxbook.epub"
    _make_epub(str(p), {
        "OEBPS/content.opf": OPF_NCX,
        "OEBPS/toc.ncx": NCX,
        "OEBPS/ch1.xhtml": CH1,
    })
    z = zipfile.ZipFile(str(p))
    opf_dir, meta, manifest, spine, nav_path, ncx_path = e2h.parse_opf(z)
    assert nav_path is None and ncx_path == "OEBPS/toc.ncx"
    toc = e2h.parse_ncx(z, ncx_path)
    assert toc[0]["label"] == "Chapter One"
    assert toc[0]["children"][0]["label"] == "Topic One"
    assert toc[0]["children"][0]["anchor"] == "t1"
    # full conversion via the ncx path
    out = tmp_path / "out"
    title, book_dir, pages, _ = e2h.convert_book(str(p), str(out))
    assert title == "NCX Book"
    assert os.path.isdir(os.path.join(book_dir, "01. Chapter One"))


def test_no_toc_falls_back_to_spine(tmp_path):
    opf = OPF_NAV.replace('properties="nav"', '').replace(
        '<item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" />', '')
    p = tmp_path / "flat.epub"
    _make_epub(str(p), {
        "OEBPS/content.opf": opf,
        "OEBPS/ch1.xhtml": CH1,
        "OEBPS/style.css": "body{}",
        "OEBPS/img/p.png": PNG,
    })
    out = tmp_path / "out"
    title, book_dir, pages, _ = e2h.convert_book(str(p), str(out))
    # no nav, no ncx -> one leaf per spine item
    assert pages == 1
    assert any(n.endswith(".html") for n in os.listdir(book_dir))
