#!/usr/bin/env python3
"""Frame extraction for full-blog skill.

Public functions:
  - extract_uniform_frames(video_path, output_dir, interval_s=5)
        -> list[(timestamp_s, frame_path)]
  - dedup_by_phash(pairs, max_distance=5) -> list[(ts_s, path)]

Why uniform sampling (not scene-cut)?
  ffmpeg's `select='gt(scene,X)'` filter compares consecutive-frame pixel
  histograms. For slide-heavy content — code screens, lecture slides where
  the next slide reuses the same template + one line of text — the per-pixel
  delta is well under 0.05, so even the most sensitive threshold misses
  most slide transitions. A 7-minute talk produced 0 cuts in its first
  4 minutes despite showing ~14 distinct slides.
  Uniform sampling + phash dedup is dumber but actually covers the content:
  any held slide collapses to 1 representative; any rapid transition is
  picked up within `interval_s` seconds.
"""
import os
import subprocess

import imagehash
from PIL import Image


# ---- pure helpers ---- #

def dedup_by_phash(pairs, max_distance=5):
    """Keep one representative per cluster of phash-similar frames.

    pairs: list of (timestamp_s, image_path) in chronological order.
    Returns the same shape with duplicates removed.

    Algorithm: O(n^2) scan; for each frame, compare to all already-kept frames;
    drop if Hamming distance to any kept frame is <= max_distance.
    """
    kept = []
    kept_hashes = []
    for ts, path in pairs:
        try:
            h = imagehash.phash(Image.open(path))
        except Exception:
            continue
        is_dup = any((h - kh) <= max_distance for kh in kept_hashes)
        if not is_dup:
            kept.append((ts, path))
            kept_hashes.append(h)
    return kept


# ---- extraction ---- #

def extract_uniform_frames(video_path, output_dir, interval_s=5):
    """Sample one frame every `interval_s` seconds.

    Returns list[(timestamp_s, frame_path)] in chronological order. Files are
    named `HH_MM_SS.jpg` (with `_N` suffix on collisions). Source resolution
    is preserved up to 1920 px wide — see frame_extract history for why
    earlier 720x405 output was unreadable in the rendered blog.

    `fps=1/N` is the simplest possible "give me one frame every N seconds"
    filter. We don't need scene-cut metadata: timestamps are computed
    deterministically as `i * interval_s`. phash dedup downstream collapses
    held slides into a single representative.
    """
    os.makedirs(output_dir, exist_ok=True)
    pattern = os.path.join(output_dir, "raw_%05d.jpg")
    cmd = [
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
        "-i", video_path,
        "-vf", f"fps=1/{interval_s},scale='min(1920,iw)':-1",
        "-q:v", "2", pattern,
    ]
    subprocess.run(cmd, check=True, capture_output=True)
    raw_files = sorted(
        f for f in os.listdir(output_dir) if f.startswith("raw_") and f.endswith(".jpg")
    )
    pairs = []
    for i, raw in enumerate(raw_files):
        ts = float(i * interval_s)
        ts_int = int(ts)
        new = f"{ts_int//3600:02d}_{(ts_int%3600)//60:02d}_{ts_int%60:02d}.jpg"
        old_path = os.path.join(output_dir, raw)
        new_path = os.path.join(output_dir, new)
        suffix = 0
        while os.path.exists(new_path):
            suffix += 1
            stem, ext = os.path.splitext(new)
            new_path = os.path.join(output_dir, f"{stem}_{suffix}{ext}")
        os.rename(old_path, new_path)
        pairs.append((ts, new_path))
    return pairs
