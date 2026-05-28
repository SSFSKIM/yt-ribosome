---
name: html-to-markdown
version: 0.1.0
description: This skill should be used when the user wants to convert a folder of generated blog HTML files into Markdown, mirroring the folder structure, so they can read/manage the blogs in Obsidian (or any Markdown editor) — "convert the blogs to markdown", "export to obsidian", "make a markdown version", "html을 마크다운으로 변환", "옵시디언에서 보게 마크다운으로", "마크다운으로 미러링". Produces a self-contained `<dir>-md/` vault (HTML→MD plus copied frame images). Pairs with the `full-blog` skill, whose output it converts. Not for browsing HTML in a web UI (use blog-library), creating blogs (full-blog), or translating them (translate).
argument-hint: [blogs-dir] [--out-dir DIR] [--quiet]
allowed-tools: Bash
---

# Convert a blog HTML library to a Markdown (Obsidian) vault

Mirror a folder of generated `.html` blogs into a parallel Markdown tree so the
same content can be read and managed in Obsidian. The `blog-library` skill
serves the HTML in a web UI; this skill produces plain `.md` files instead, for
users who prefer a Markdown editor.

## How it works

Run the bundled converter — it walks the input directory, reproduces its exact
folder structure under `<dir>-md/`, converts each blog `.html` to `.md`, and
copies the frame-image folders verbatim.

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/skills/html-to-markdown/scripts/html_to_md.py" "<BLOGS_DIR>" [--out-dir DIR]
```

- **Self-contained vault.** Images are copied alongside the `.md` (the whole
  blog set is small — tens of MB), so relative image links resolve in Obsidian
  with no path rewriting. Open `<dir>-md/` directly as a vault.
- **Body only.** Only the article body (`div.post-body` from `full-blog`'s
  `render_html`) is converted; the site chrome (top bar, footer) is dropped.
  The blog title and source URL are lifted into YAML frontmatter.
- **Standard library + BeautifulSoup** only (`bs4`, already a `full-blog` dep).

## Steps

1. **Pick the directory** of blogs (the `full-blog` `--out-dir`).
2. **Run the converter.** Default output is a sibling `<dir>-md/`; override with
   `--out-dir`. It prints one line per converted file (use `--quiet` for just
   the summary) and a final `markdown=… images_copied=… failed=…` tally.
3. **Report** the output path and tell the user to open it as an Obsidian vault.

## What the conversion produces

- **Frontmatter**: `title` and `source` (the YouTube URL), then a visible
  `# Title`.
- **Paragraphs / headings**: `<p>`→prose, `<h2>/<h3>`→`##`/`###`. The lead
  paragraph's drop-cap is visual-only and renders as normal prose.
- **Figures**: `![alt](image)` followed by an italic caption line with a
  `[▶ M:SS](youtube-deeplink)` jump link. `figure-row` galleries (a CSS-only
  side-by-side layout) simply stack as consecutive images in Markdown.
- **Lists / blockquotes / inline `code`, links, bold, italic** are preserved.
- **`<hr class="divider">`** → `---`; the trailing "Additional frames" section
  becomes a `## Additional frames` heading.

## Notes

- **Image paths are percent-encoded** (decode-then-encode, so already-encoded
  paths aren't double-encoded). Spaces/Hangul in folder names become `%20…`,
  which Obsidian and any CommonMark renderer decode to find the local file.
  Raw spaces would otherwise truncate a `![]()` link.
- **Idempotent**: re-running overwrites the mirror. Blogs deleted upstream are
  NOT pruned — delete the `-md/` dir and re-run for a clean mirror.
- One unreadable HTML file is reported as `FAIL` and skipped; the run continues.
- Korean/translated blogs convert identically — the parser is content-agnostic.

## Resources

- **`scripts/html_to_md.py`** — the standalone converter (run it).
