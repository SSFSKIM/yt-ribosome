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
