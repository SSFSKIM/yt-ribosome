#!/usr/bin/env python3
"""Local web library for browsing generated blog HTML files.

Serves an Obsidian-like file-tree sidebar + content pane over HTTP so the
generated `full-blog` output (or any folder of `.html` files) can be browsed
in a browser. Live: the tree is re-scanned from the filesystem on every
request, so newly added blogs show up on refresh.

Usage:
    python3 blog_browser.py [ROOT_DIR] [--port 8800] [--no-open]

ROOT_DIR defaults to the current directory. Ctrl-C to stop.

Why a server (not a static index.html): browsers block file:// iframes from
loading sibling file:// documents, which breaks the content viewer. A tiny
local HTTP server sidesteps that and reflects filesystem changes live.
"""
import argparse
import html
import json
import mimetypes
import os
import posixpath
import sys
import threading
import urllib.parse
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

# Names never shown in the tree (editor/OS/tool clutter + machine artifacts).
_HIDDEN_NAMES = {".obsidian", ".playwright-cli", ".DS_Store", ".git",
                 "__pycache__", "_run_summary.json", "index.html"}


def _is_hidden(name):
    return name in _HIDDEN_NAMES or name.startswith(".")


def build_tree(abs_dir, rel_dir=""):
    """Recursively build a tree of folders and .html files.

    Asset folders are hidden: a directory `X` is skipped when a sibling
    `X.html` exists, because that folder only holds the blog's images.

    Returns a list of nodes: {name, type: 'dir'|'file', path, children?}.
    """
    try:
        entries = sorted(os.listdir(abs_dir), key=str.lower)
    except OSError:
        return []

    html_stems = {
        os.path.splitext(e)[0]
        for e in entries
        if e.lower().endswith(".html") and not _is_hidden(e)
    }

    nodes = []
    for name in entries:
        if _is_hidden(name):
            continue
        abs_path = os.path.join(abs_dir, name)
        rel_path = posixpath.join(rel_dir, name) if rel_dir else name

        if os.path.isdir(abs_path):
            # Skip the image/asset folder that backs a sibling <name>.html
            if name in html_stems:
                continue
            children = build_tree(abs_path, rel_path)
            if children:  # omit empty folders
                nodes.append({"name": name, "type": "dir",
                              "path": rel_path, "children": children})
        elif name.lower().endswith(".html"):
            nodes.append({"name": name, "type": "file", "path": rel_path})

    # Folders first, then files; each group alphabetical (already sorted).
    nodes.sort(key=lambda n: (n["type"] != "dir", n["name"].lower()))
    return nodes


class Handler(BaseHTTPRequestHandler):
    root = "."  # set in main()

    def log_message(self, *args):
        pass  # quiet

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = urllib.parse.unquote(parsed.path)

        if path == "/":
            self._send_bytes(_SPA.encode("utf-8"), "text/html; charset=utf-8")
            return
        if path == "/api/tree":
            tree = build_tree(self.root)
            payload = json.dumps(
                {"root": os.path.basename(os.path.abspath(self.root)) or "/",
                 "tree": tree},
                ensure_ascii=False,
            ).encode("utf-8")
            self._send_bytes(payload, "application/json; charset=utf-8")
            return

        self._serve_file(path.lstrip("/"))

    def _serve_file(self, rel_path):
        # Resolve and confine to root (no path traversal).
        root_real = os.path.realpath(self.root)
        target = os.path.realpath(os.path.join(root_real, rel_path))
        if not (target == root_real or target.startswith(root_real + os.sep)):
            self.send_error(403, "Forbidden")
            return
        if not os.path.isfile(target):
            self.send_error(404, "Not found")
            return
        ctype = mimetypes.guess_type(target)[0] or "application/octet-stream"
        try:
            with open(target, "rb") as f:
                data = f.read()
        except OSError:
            self.send_error(500, "Read error")
            return
        self._send_bytes(data, ctype)

    def _send_bytes(self, data, ctype):
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


_SPA = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Blog Library</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Literata:wght@400;500;700&family=Plus+Jakarta+Sans:wght@500;600;700;800&display=swap" rel="stylesheet">
<style>
  :root {
    --surface:#fbf9f8; --surface-container-low:#f6f3f2; --surface-container:#f0eded;
    --surface-container-high:#eae7e7; --on-surface:#1b1c1c; --on-surface-variant:#56423e;
    --outline:#89726d; --outline-variant:#ddc0ba; --primary:#9f402d;
    --primary-container:#e2725b; --secondary-container:#feac67; --on-secondary-container:#773e00;
    --sidebar-w: 320px;
  }
  * { box-sizing:border-box; }
  html,body { margin:0; height:100%; }
  body {
    font-family:'Plus Jakarta Sans',system-ui,sans-serif;
    color:var(--on-surface); background:var(--surface);
    display:flex; height:100vh; overflow:hidden;
  }
  /* ---------- Sidebar ---------- */
  .sidebar {
    width:var(--sidebar-w); min-width:var(--sidebar-w);
    background:var(--surface-container-low);
    border-right:1px solid var(--outline-variant);
    display:flex; flex-direction:column; height:100%;
  }
  .sb-head { padding:18px 18px 10px; }
  .brand {
    font-weight:800; font-size:12px; letter-spacing:.16em; text-transform:uppercase;
    color:var(--primary); display:inline-flex; align-items:center; gap:9px; margin-bottom:14px;
  }
  .brand::before { content:''; width:9px; height:9px; border-radius:50%;
    background:var(--primary); box-shadow:0 0 0 4px rgba(159,64,45,.12); }
  .filter {
    width:100%; padding:9px 12px; border-radius:9px; font-size:13px;
    font-family:inherit; color:var(--on-surface);
    background:#fff; border:1.5px solid var(--outline-variant); outline:none;
    transition:border-color .15s;
  }
  .filter:focus { border-color:var(--primary); }
  .tree { flex:1; overflow-y:auto; padding:6px 8px 24px; }
  .node-children { margin-left:14px; border-left:1px solid var(--outline-variant); padding-left:6px; }
  .row {
    display:flex; align-items:center; gap:6px; padding:5px 8px; border-radius:7px;
    cursor:pointer; font-size:13px; line-height:1.3; user-select:none;
    color:var(--on-surface);
  }
  .row:hover { background:var(--surface-container-high); }
  .row.active { background:var(--secondary-container); color:var(--on-secondary-container); font-weight:600; }
  .row .twist { width:12px; font-size:10px; color:var(--outline); transition:transform .12s; flex:none; }
  .row.collapsed .twist { transform:rotate(-90deg); }
  .row .ico { flex:none; font-size:13px; opacity:.85; }
  .row .label { overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
  .folder-row { font-weight:700; color:var(--on-surface-variant); }
  .count { margin-left:auto; font-size:10px; color:var(--outline); font-weight:600; flex:none; }
  .hidden { display:none !important; }
  /* ---------- Content ---------- */
  .main { flex:1; display:flex; flex-direction:column; height:100%; }
  .topbar {
    height:46px; min-height:46px; display:flex; align-items:center; gap:10px;
    padding:0 18px; border-bottom:1px solid var(--outline-variant);
    background:var(--surface); font-size:13px; color:var(--on-surface-variant);
  }
  .topbar .crumb { overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
  .topbar a.open-raw {
    margin-left:auto; flex:none; color:var(--primary); text-decoration:none;
    font-weight:600; font-size:12px; padding:5px 11px; border-radius:9999px;
    background:var(--surface-container);
  }
  .topbar a.open-raw:hover { background:var(--surface-container-high); }
  iframe { flex:1; width:100%; border:0; background:#fff; }
  .empty {
    flex:1; display:flex; align-items:center; justify-content:center;
    color:var(--outline); font-size:14px; text-align:center; padding:40px;
  }
</style>
</head>
<body>
  <aside class="sidebar">
    <div class="sb-head">
      <div class="brand" id="brand">Blog Library</div>
      <input class="filter" id="filter" type="search" placeholder="Filter by name…" autocomplete="off">
    </div>
    <div class="tree" id="tree"></div>
  </aside>
  <main class="main">
    <div class="topbar">
      <span class="crumb" id="crumb">Select a blog from the left</span>
      <a class="open-raw hidden" id="openRaw" target="_blank" rel="noopener">Open in new tab ↗</a>
    </div>
    <div class="empty" id="empty">Pick a file in the sidebar to read it here.</div>
    <iframe id="viewer" class="hidden" title="blog content"></iframe>
  </main>
<script>
const treeEl = document.getElementById('tree');
const filterEl = document.getElementById('filter');
const viewer = document.getElementById('viewer');
const emptyEl = document.getElementById('empty');
const crumbEl = document.getElementById('crumb');
const openRaw = document.getElementById('openRaw');
let activeRow = null;

function countFiles(nodes){
  let n=0; for(const x of nodes){ if(x.type==='file') n++; else n+=countFiles(x.children||[]); } return n;
}
function makeRow(node, depth){
  const wrap = document.createElement('div');
  const row = document.createElement('div');
  row.className = 'row' + (node.type==='dir' ? ' folder-row' : '');
  row.dataset.name = node.name.toLowerCase();
  row.dataset.path = node.path;

  if(node.type==='dir'){
    const tw = document.createElement('span'); tw.className='twist'; tw.textContent='▾';
    const ic = document.createElement('span'); ic.className='ico'; ic.textContent='📁';
    const lb = document.createElement('span'); lb.className='label'; lb.textContent=node.name;
    const ct = document.createElement('span'); ct.className='count'; ct.textContent=countFiles(node.children||[]);
    row.append(tw,ic,lb,ct);
    const kids = document.createElement('div'); kids.className='node-children';
    for(const c of node.children||[]) kids.appendChild(makeRow(c, depth+1));
    row.addEventListener('click', ()=>{
      row.classList.toggle('collapsed');
      kids.classList.toggle('hidden');
    });
    wrap.append(row, kids);
  } else {
    const sp = document.createElement('span'); sp.className='twist'; sp.textContent='';
    const ic = document.createElement('span'); ic.className='ico'; ic.textContent='📄';
    const lb = document.createElement('span'); lb.className='label';
    lb.textContent = node.name.replace(/\.html$/i,'').replace(/^01\.\s*/,'');
    row.append(sp,ic,lb);
    row.addEventListener('click', ()=>open(node));
    wrap.append(row);
  }
  wrap.dataset.kind = node.type;
  return wrap;
}
function open(node){
  if(activeRow) activeRow.classList.remove('active');
  const url = '/' + node.path.split('/').map(encodeURIComponent).join('/');
  viewer.src = url;
  viewer.classList.remove('hidden');
  emptyEl.classList.add('hidden');
  crumbEl.textContent = node.path;
  openRaw.href = url; openRaw.classList.remove('hidden');
  // mark active
  for(const r of treeEl.querySelectorAll('.row')) if(r.dataset.path===node.path){ r.classList.add('active'); activeRow=r; }
}
function applyFilter(q){
  q = q.trim().toLowerCase();
  const wraps = treeEl.querySelectorAll(':scope div'); // all wrappers
  // Show/hide file rows by match; then reveal ancestor folders of any visible file.
  const fileWraps = [...treeEl.querySelectorAll('div')].filter(d=>d.dataset.kind==='file');
  for(const fw of fileWraps){
    const row = fw.querySelector('.row');
    const match = !q || row.dataset.name.includes(q) || row.querySelector('.label').textContent.toLowerCase().includes(q);
    fw.classList.toggle('hidden', !match);
  }
  // For each folder wrapper, hide if it has no visible file descendant.
  const dirWraps = [...treeEl.querySelectorAll('div')].filter(d=>d.dataset.kind==='dir');
  for(const dw of dirWraps){
    const anyVisible = [...dw.querySelectorAll('div')].some(d=>d.dataset.kind==='file' && !d.classList.contains('hidden'));
    dw.classList.toggle('hidden', q && !anyVisible);
    if(q && anyVisible){ // force-expand matching folders
      const row = dw.querySelector('.row'); const kids = dw.querySelector('.node-children');
      row.classList.remove('collapsed'); if(kids) kids.classList.remove('hidden');
    }
  }
}
filterEl.addEventListener('input', e=>applyFilter(e.target.value));

fetch('/api/tree').then(r=>r.json()).then(data=>{
  document.getElementById('brand').textContent = data.root || 'Blog Library';
  document.title = (data.root||'Blog') + ' · Library';
  treeEl.textContent='';
  if(!data.tree.length){ const d=document.createElement('div'); d.className='empty'; d.textContent='No .html files found.'; treeEl.appendChild(d); return; }
  for(const n of data.tree) treeEl.appendChild(makeRow(n,0));
}).catch(e=>{ const d=document.createElement('div'); d.className='empty'; d.textContent='Failed to load tree: '+e; treeEl.textContent=''; treeEl.appendChild(d); });
</script>
</body>
</html>
"""


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("root", nargs="?", default=".",
                    help="Directory of blogs to browse (default: current dir)")
    ap.add_argument("--port", type=int, default=8800)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--no-open", action="store_true",
                    help="Don't auto-open the browser")
    args = ap.parse_args()

    root = os.path.abspath(args.root)
    if not os.path.isdir(root):
        sys.exit(f"Not a directory: {root}")
    Handler.root = root

    httpd = ThreadingHTTPServer((args.host, args.port), Handler)
    url = f"http://{args.host}:{args.port}/"
    n = len(build_tree(root))
    print(f"Blog Library serving {root}")
    print(f"  {url}  (Ctrl-C to stop)")
    if not args.no_open:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped.")
        httpd.shutdown()


if __name__ == "__main__":
    main()
