---
name: epub-to-html
version: 0.1.0
description: This skill should be used when the user wants to convert/ingest EPUB e-books into a folder tree of HTML that mirrors the book's chapter hierarchy, so the book can be browsed in the blog-library web UI — "convert this epub", "turn my epub into html", "ingest these ebooks", "view epub in the library", "epub 변환", "이펍을 html로", "전자책을 라이브러리에 넣어줘". Reproduces the book's table-of-contents tree as nested folders (unit→chapter→topic), splitting chapters at their anchors. Handles EPUB2 (toc.ncx) and EPUB3 (nav.xhtml). Pairs with blog-library (which browses the output). Not for creating blogs (full-blog) or Markdown export (html-to-markdown).
argument-hint: [epub-file-or-dir] [--out-dir DIR]
allowed-tools: Bash
---

# Convert EPUB books to a browsable HTML library

Turn `.epub` e-books into a folder tree of HTML pages that **mirrors the book's
own table-of-contents hierarchy**, so they can be read in the `blog-library`
web UI alongside generated blogs. An EPUB is a ZIP of XHTML + CSS + images; this
skill unpacks it, follows the navigation document, and lays the content out as
nested folders.

## How it works

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/skills/epub-to-html/scripts/epub_to_html.py" "<EPUB_OR_DIR>" [--out-dir DIR]
```

The converter:

1. Reads `META-INF/container.xml → OPF` for metadata, manifest, and spine.
2. Parses the navigation tree — **EPUB3 `nav.xhtml` preferred, EPUB2 `toc.ncx`
   fallback**, and finally flat spine order if neither exists.
3. Reproduces that tree as **nested folders**: a TOC entry with children → a
   folder (its own pre-children content becomes `00. <label>.html`); a leaf →
   a `NN. <label>.html` file. Numbering follows reading order.
4. **Splits chapter files at their `#anchor` targets** so each topic is its own
   page rather than one giant chapter file.
5. Copies all images/CSS/fonts into a hidden **`.assets/`** folder per book and
   rewrites links, so each page keeps the book's own styling.

Stdlib `zipfile` + `bs4` only — no new pip packages, no EPUB library needed.

## Steps

1. **Pick the input**: a single `.epub` or a directory of them (recursed).
2. **Run the converter.** Default output is `<input>-html/` (sibling); override
   with `--out-dir`. It prints one `OK`/`FAIL` line per book and a final tally.
3. **Browse it**: point the `blog-library` skill at the output directory.
4. **Report** the output path and the book/page counts.

## Output layout

```
<out>/
  <Book Title>/
    01. Cover.html                      ← leaf chapter (no children)
    11. Unit 1 Biological Bases/        ← TOC node with children → folder
      01. Chapter 4 .../               ← deeper nesting mirrors the nav
        00. Chapter 4 ....html         ← chapter intro (pre-topic content)
        01. <topic>.html               ← split out at its #anchor
    .assets/   (css + images; hidden from the library sidebar, served to pages)
```

## Notes

- **Generic by design.** No assumption of a fixed internal layout; tolerates
  EPUB2/3, arbitrary nav depth, and TOC entries that point at whole files or at
  `#anchors` within a shared file. Chapters with flat bodies (the common case,
  topics as `<h_ id>` headings) split cleanly at the heading boundaries.
- **Fidelity.** The book's own CSS is preserved, so pages look close to the
  original reader. Math/figures that the book stores as images render normally.
- **`blog-library` integration.** Chapter folders show in the sidebar; the
  `.assets/` dotfolder is hidden from the tree but still served to the iframe,
  so relative image/CSS links resolve.
- **Security.** EPUBs are untrusted downloaded files, so the OPF/NCX XML is
  parsed with an entity-declaration guard (rejects `<!ENTITY …>`) to block XXE
  and billion-laughs attacks — no third-party parser required.
- **Idempotent**: re-running overwrites a book's output; stale files from a
  removed book are not pruned (delete the `-html/` dir to start clean).
- One unreadable book is reported as `FAIL` and skipped; other books continue.

## Resources

- **`scripts/epub_to_html.py`** — the standalone converter (run it).
