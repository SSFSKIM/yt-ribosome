---
name: blog-library
version: 0.1.0
description: This skill should be used when the user wants to browse, read, or manage a folder of generated blog HTML files in a local web UI — "open the blog library", "browse my blogs", "view the generated blogs", "블로그 라이브러리 열어줘", "생성된 블로그 목록 웹으로 보여줘", "옵시디언처럼 블로그 관리". Serves an Obsidian-style file-tree sidebar plus an HTML content viewer over a local HTTP server. Pairs with the `full-blog` skill, whose output it is designed to browse. Not for creating blogs (use full-blog) or translating them (use translate).
argument-hint: [blogs-dir] [--port N] [--no-open]
allowed-tools: Bash
---

# Browse a blog library in a local web UI

Serve a folder of generated `.html` blogs as an Obsidian-like web app: a
collapsible file-tree sidebar on the left, a content viewer on the right.
Designed to browse `full-blog` output, but works on any directory of HTML.

## How it works

Run the bundled server — it scans the directory and serves a single-page UI.

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/skills/blog-library/scripts/blog_browser.py" "<BLOGS_DIR>" [--port 8800]
```

- The file tree is rebuilt from the filesystem on **every** request, so blogs
  added after the server starts appear on refresh — no regeneration step.
- A tiny local HTTP server (not a static file) is used on purpose: browsers
  block `file://` iframes from loading sibling `file://` documents, which
  would break the content viewer. Serving over HTTP sidesteps that and lets
  relative image paths resolve.
- Python standard library only — no pip install.

## Steps

1. **Pick the directory** to browse (default: current directory). For
   `full-blog` output this is the `--out-dir` you rendered into.
2. **Run the server.** It prints the URL and opens the browser automatically
   (`--no-open` to suppress). Pass `--port N` if 8800 is taken.
3. **Report the URL** to the user and note that Ctrl-C stops the server.

## What the UI shows

- **Sidebar**: folders (collapsible, with a file count) and `.html` files.
  File labels strip a leading `NN. ` index and the `.html` extension.
- **Filter box**: live client-side filter by name; matching folders
  auto-expand.
- **Viewer**: the selected blog rendered in an iframe with full CSS and
  images, plus an "Open in new tab" link and a path breadcrumb.

## Tree rules (noise removal)

- **Asset folders are hidden.** A folder `X` is omitted when a sibling
  `X.html` exists — that directory only holds the blog's frame images, so
  showing it would double every entry. (This matches `full-blog`'s output
  layout: `Title.html` + `Title/` image folder.)
- **Clutter is skipped**: dotfiles/dirs (`.obsidian`, `.git`,
  `.playwright-cli`, `.DS_Store`), `__pycache__`, `_run_summary.json`, and a
  top-level `index.html`.
- **Empty folders are omitted.**

## Notes

- The server confines file serving to the root directory (no path traversal).
- Korean/translated blogs (from the `translate` skill) render the same way —
  the viewer is content-agnostic.
- To browse a different folder, stop the server (Ctrl-C) and re-run with a new
  path argument.

## Resources

- **`scripts/blog_browser.py`** — the standalone server + inline SPA (run it).
