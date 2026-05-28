#!/usr/bin/env python3
"""Re-extract a blog's frames at higher resolution, in place.

Use when blogs were generated from a low-res source (e.g. an old yt-dlp that
could only fetch 360p) and you've since fixed the download path. This reads
each blog's `<figure data-timestamp>` + `<img src>`, re-downloads the source
video at up to 1080p, and overwrites ONLY the frame images at their existing
timestamps. Transcripts, rankings, captions, restructuring, and translations
are all preserved — only the pixels change.

Idempotent: frames already >= --min-width are skipped, and a video is
downloaded only if at least one of its frames needs upgrading. Videos are
cached by id, so an EN blog and its KO translation (same video) download once.

Usage:
    python3 upgrade_frames.py <blog-dir-or-html> [--min-width 1920] [--keep-temp]
"""
import argparse
import glob
import os
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.parse
from functools import reduce
from math import gcd

from PIL import Image

_VID_RE = re.compile(r"[?&]v=([A-Za-z0-9_-]{11})")


def hms_to_seconds(s):
    parts = [int(p) for p in s.strip().split(":")]
    while len(parts) < 3:
        parts.insert(0, 0)
    h, m, sec = parts[-3], parts[-2], parts[-1]
    return h * 3600 + m * 60 + sec


def parse_blog(html_path):
    """Return (video_id, [(seconds, abs_img_path), ...]) for a blog HTML."""
    from bs4 import BeautifulSoup
    with open(html_path, encoding="utf-8") as f:
        html = f.read()
    m = _VID_RE.search(html)
    video_id = m.group(1) if m else None
    base = os.path.dirname(os.path.abspath(html_path))
    soup = BeautifulSoup(html, "html.parser")
    frames = []
    for fig in soup.find_all("figure"):
        img = fig.find("img")
        ts = fig.get("data-timestamp")
        if not img or not img.get("src") or not ts:
            continue
        rel = urllib.parse.unquote(img["src"])
        frames.append((hms_to_seconds(ts), os.path.join(base, rel)))
    return video_id, frames


def needs_upgrade(img_path, min_width):
    if not os.path.exists(img_path):
        return True  # missing -> (re)create
    try:
        return Image.open(img_path).size[0] < min_width
    except Exception:
        return True


def download_video(video_id, cache_dir):
    """yt-dlp the VIDEO stream at up to 1080p; cached by id. Returns path/None.

    Video-only on purpose — frame extraction never needs audio, so skipping
    it (and the merge step) roughly halves download size and time. Falls back
    to a muxed format only if no adaptive video-only stream is available.
    """
    out = os.path.join(cache_dir, f"{video_id}.mp4")
    if os.path.exists(out) and os.path.getsize(out) > 1_000_000:
        return out
    url = f"https://www.youtube.com/watch?v={video_id}"
    fmt = "bv*[height<=1080][ext=mp4]/bv*[height<=1080]/b[ext=mp4]/b"
    res = subprocess.run(
        ["yt-dlp", "-f", fmt, "-o", out, url],
        capture_output=True, text=True,
    )
    if res.returncode != 0 or not os.path.exists(out):
        print(f"  !! download failed for {video_id}: {res.stderr.strip()[-160:]}",
              file=sys.stderr)
        return None
    return out


def detect_interval(times):
    """Infer the uniform-sampling interval from kept frame timestamps.

    full-blog names frames at i*interval seconds, so every kept timestamp is
    a multiple of the interval and gcd recovers it. Falls back to 5 (the
    default `--sample-interval`) if there's only a single non-zero timestamp.
    """
    nz = [t for t in times if t > 0]
    if not nz:
        return 5
    return reduce(gcd, nz)


def build_grid(video_path, interval, min_width, out_dir):
    """Replay the pipeline's `fps=1/interval` extraction at min_width.

    Returns a list of frame paths where index k corresponds to k*interval
    seconds — the exact frames the original run produced (just higher-res).
    We must reproduce the filter rather than seek per-timestamp: the `fps`
    filter's sample slots don't line up with a plain `-ss T` seek, so seeking
    can land on a neighbouring scene (e.g. the speaker instead of the slide).
    """
    cmd = [
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
        "-i", video_path,
        "-vf", f"fps=1/{interval},scale='min({min_width},iw)':-1",
        "-q:v", "2", os.path.join(out_dir, "g_%05d.jpg"),
    ]
    if subprocess.run(cmd, capture_output=True).returncode != 0:
        return []
    return sorted(glob.glob(os.path.join(out_dir, "g_*.jpg")))


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("target", help="A blog .html file or a directory of them")
    ap.add_argument("--min-width", type=int, default=1920)
    ap.add_argument("--force", action="store_true",
                    help="Re-extract every frame even if already >= min-width "
                         "(use to repair frames extracted with a buggy seek)")
    ap.add_argument("--keep-temp", action="store_true",
                    help="Keep downloaded videos (default: delete on exit)")
    args = ap.parse_args()

    if os.path.isdir(args.target):
        htmls = sorted(glob.glob(os.path.join(args.target, "**", "*.html"),
                                 recursive=True))
        htmls = [h for h in htmls if os.path.basename(h) != "index.html"]
    elif os.path.isfile(args.target):
        htmls = [args.target]
    else:
        sys.exit(f"Not found: {args.target}")
    if not htmls:
        sys.exit("No .html files found.")

    cache = tempfile.mkdtemp(prefix="upgrade-frames-")
    video_cache = {}  # id -> path|None
    grid_cache = {}   # (id, interval) -> [grid frame paths]
    totals = {"upgraded": 0, "skipped": 0, "failed": 0, "blogs": 0}
    try:
        for html in htmls:
            video_id, frames = parse_blog(html)
            name = os.path.basename(html)
            if not video_id or not frames:
                print(f"SKIP {name}  (no video id or no frames)")
                continue
            pending = [(s, p) for s, p in frames
                       if args.force or needs_upgrade(p, args.min_width)]
            if not pending:
                print(f"OK   {name}  ({len(frames)} frames already >= {args.min_width}px)")
                totals["skipped"] += len(frames)
                totals["blogs"] += 1
                continue
            if video_id not in video_cache:
                video_cache[video_id] = download_video(video_id, cache)
            vpath = video_cache[video_id]
            if not vpath:
                print(f"FAIL {name}  (video {video_id} unavailable)")
                totals["failed"] += len(pending)
                continue
            interval = detect_interval([s for s, _ in frames])
            gkey = (video_id, interval)
            if gkey not in grid_cache:
                gdir = os.path.join(cache, f"{video_id}_grid_{interval}")
                os.makedirs(gdir, exist_ok=True)
                grid_cache[gkey] = build_grid(vpath, interval, args.min_width, gdir)
            grid = grid_cache[gkey]
            up = 0
            for sec, img_path in pending:
                idx = int(sec // interval)
                if 0 <= idx < len(grid):
                    os.makedirs(os.path.dirname(img_path), exist_ok=True)
                    shutil.copy2(grid[idx], img_path)
                    up += 1
                else:
                    totals["failed"] += 1
            totals["upgraded"] += up
            totals["blogs"] += 1
            print(f"UP   {name}  upgraded {up}/{len(frames)} frames "
                  f"(interval={interval}s) @ {args.min_width}px")
    finally:
        if not args.keep_temp:
            shutil.rmtree(cache, ignore_errors=True)

    print(f"\nDONE  blogs={totals['blogs']}  upgraded={totals['upgraded']}  "
          f"skipped={totals['skipped']}  failed={totals['failed']}")


if __name__ == "__main__":
    main()
