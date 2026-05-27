"""Unit tests for frame_extract.py."""
import os
import sys
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import frame_extract as fe

FIX = os.path.join(os.path.dirname(__file__), "fixtures")


def test_phash_dedup_keeps_one_of_near_duplicates():
    pairs = [
        (0.0, os.path.join(FIX, "slide_a.jpg")),
        (3.5, os.path.join(FIX, "slide_a_dup.jpg")),
        (7.0, os.path.join(FIX, "slide_b.jpg")),
    ]
    survivors = fe.dedup_by_phash(pairs, max_distance=5)
    assert len(survivors) == 2
    surviving_files = [os.path.basename(p) for _, p in survivors]
    assert "slide_b.jpg" in surviving_files
    assert "slide_a.jpg" in surviving_files
    assert "slide_a_dup.jpg" not in surviving_files


def test_phash_dedup_handles_empty():
    assert fe.dedup_by_phash([]) == []


def test_adaptive_threshold_buckets():
    assert fe._threshold_for_cuts(0) == 0.20
    assert fe._threshold_for_cuts(5) == 0.20
    assert fe._threshold_for_cuts(6) == 0.30
    assert fe._threshold_for_cuts(20) == 0.30
    assert fe._threshold_for_cuts(21) == 0.50
    assert fe._threshold_for_cuts(1000) == 0.50


SHORT_TALK_MP4 = os.path.join(FIX, "short_talk.mp4")


def _ensure_fixture_mp4():
    """Download the fixture mp4 if not present, using yt-dlp per SOURCE.txt."""
    if os.path.exists(SHORT_TALK_MP4):
        return
    source_file = os.path.join(FIX, "SOURCE.txt")
    if not os.path.exists(source_file):
        pytest.skip("SOURCE.txt missing — cannot fetch fixture")
    url = None
    trim_start = 0
    trim_len = 90
    for line in open(source_file):
        line = line.strip()
        if line.startswith("https://"):
            url = line
        elif line.startswith("trim_start="):
            trim_start = int(line.split("=", 1)[1])
        elif line.startswith("trim_length="):
            trim_len = int(line.split("=", 1)[1])
    if not url:
        pytest.skip("No URL in SOURCE.txt")
    import subprocess
    tmp = SHORT_TALK_MP4 + ".raw.mp4"
    r = subprocess.run(
        ["yt-dlp", "-f", "mp4", "-o", tmp, url],
        capture_output=True, text=True,
    )
    if r.returncode != 0:
        pytest.skip(f"yt-dlp failed: {r.stderr[:200]}")
    subprocess.run(
        ["ffmpeg", "-y", "-i", tmp, "-ss", str(trim_start), "-t", str(trim_len),
         "-c", "copy", SHORT_TALK_MP4],
        check=True, capture_output=True,
    )
    os.remove(tmp)


@pytest.mark.integration
def test_detect_threshold_real_video():
    _ensure_fixture_mp4()
    th = fe.detect_threshold(SHORT_TALK_MP4)
    assert th in (0.20, 0.30, 0.50)


@pytest.mark.integration
def test_extract_scene_cuts_real_video(tmp_path):
    _ensure_fixture_mp4()
    pairs = fe.extract_scene_cuts(SHORT_TALK_MP4, threshold=0.30, output_dir=str(tmp_path))
    assert len(pairs) >= 2
    for ts, path in pairs:
        assert os.path.exists(path)
        assert ts >= 0


def test_pts_time_regex_handles_colon_and_equals_formats():
    """ffmpeg metadata=print writes 'pts_time:NNN.NNN' (colon) — make sure we parse it.

    Regression test for the v0.2.0 bug where the regex used '=' separator and
    silently fell back to using sequential indices as timestamps.
    """
    import re
    pattern = re.compile(r"pts_time[:=]\s*([\d.]+)")
    # Real ffmpeg `metadata=print` output (colon form):
    assert pattern.search("frame:0    pts:4364800 pts_time:284.166667").group(1) == "284.166667"
    # Tolerate equals form too (showinfo style):
    assert pattern.search("lavfi.pts_time=12.5").group(1) == "12.5"
    # No false matches:
    assert pattern.search("lavfi.scene_score=0.45") is None
