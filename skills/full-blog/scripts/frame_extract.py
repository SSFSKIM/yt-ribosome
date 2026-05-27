#!/usr/bin/env python3
"""Frame extraction for full-blog skill.

Public functions:
  - detect_threshold(video_path) -> float   (samples 60s mid-video, runs ffmpeg)
  - extract_scene_cuts(video_path, threshold, output_dir) -> list[(ts_s, path)]
  - dedup_by_phash(pairs, max_distance=5) -> list[(ts_s, path)]
"""
import os
import re
import subprocess
import tempfile

import imagehash
from PIL import Image


# ---- pure helpers ---- #

def _threshold_for_cuts(cuts):
    """Map a 60-second sample's cut count to a content-aware threshold."""
    if cuts <= 5:
        return 0.20
    if cuts <= 20:
        return 0.30
    return 0.50


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


# ---- subprocess wrappers ---- #

def _run(cmd, capture=False):
    """Wrapper around subprocess.run with consistent error messages."""
    res = subprocess.run(cmd, capture_output=capture, text=True)
    if res.returncode != 0:
        stderr = res.stderr if capture else ""
        raise RuntimeError(f"command failed ({res.returncode}): {' '.join(cmd)}\n{stderr}")
    return res


def _ffprobe_duration(video_path):
    res = _run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", video_path],
        capture=True,
    )
    return float(res.stdout.strip())


def _count_cuts_in_sample(video_path, start_s, length_s, threshold=0.3):
    """Run ffmpeg scene-cut on a short sample; return how many cuts it detects.

    Uses scale=320:-1 (cheaper than full-res) since we only need the cut COUNT
    here, not the frames themselves. Errors are intentionally swallowed: ffmpeg
    can return non-zero on very short samples while still emitting valid
    pts_time lines; a zero count safely degrades to the slide-talk threshold.
    """
    cmd = [
        "ffmpeg", "-hide_banner", "-loglevel", "info", "-y",
        "-ss", str(start_s), "-i", video_path, "-t", str(length_s),
        "-vf", f"select='gt(scene,{threshold})',scale=320:-1,showinfo",
        "-an", "-f", "null", "-",
    ]
    res = subprocess.run(cmd, capture_output=True, text=True)
    return len(re.findall(r"pts_time:\d", res.stderr))


def detect_threshold(video_path):
    """Sample a 60-second clip from the video's middle and pick a threshold."""
    duration = _ffprobe_duration(video_path)
    sample_start = max(0.0, duration / 2 - 30)
    sample_len = min(60.0, duration - sample_start)
    if sample_len <= 0:
        return 0.30
    cuts = _count_cuts_in_sample(video_path, sample_start, sample_len, threshold=0.3)
    return _threshold_for_cuts(cuts)


def extract_scene_cuts(video_path, threshold, output_dir):
    """Run ffmpeg scene-cut over the whole video, dump frames to output_dir.

    Returns list[(timestamp_s, frame_path)] in chronological order.
    """
    os.makedirs(output_dir, exist_ok=True)
    pattern = os.path.join(output_dir, "raw_%05d.jpg")
    metafile = os.path.join(output_dir, "_pts.txt")
    # scale=720:-1 keeps enough detail for ranker/alt-text without bloating disk
    # (typical 60-min talk: 150 frames * ~50KB ≈ 7.5MB temp).
    cmd = [
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
        "-i", video_path,
        "-vf", (
            f"select='gt(scene,{threshold})',scale=720:-1,"
            f"metadata=print:file={metafile},showinfo"
        ),
        "-vsync", "vfr", "-q:v", "2", pattern,
    ]
    subprocess.run(cmd, check=True, capture_output=True)
    pts = []
    if os.path.exists(metafile):
        with open(metafile, encoding="utf-8") as f:
            for line in f:
                m = re.search(r"pts_time=([\d.]+)", line)
                if m:
                    pts.append(float(m.group(1)))
    raw_files = sorted(
        f for f in os.listdir(output_dir) if f.startswith("raw_") and f.endswith(".jpg")
    )
    pairs = []
    for i, raw in enumerate(raw_files):
        ts = pts[i] if i < len(pts) else float(i)
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
    if os.path.exists(metafile):
        os.remove(metafile)
    return pairs
