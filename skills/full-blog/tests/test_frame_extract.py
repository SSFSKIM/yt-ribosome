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
def test_extract_uniform_frames_real_video(tmp_path):
    """A 90s fixture sampled every 10s should yield ~9 frames at expected
    timestamps (0, 10, 20, ...). The exact count tolerates ffmpeg ±1
    rounding on the trailing frame."""
    _ensure_fixture_mp4()
    pairs = fe.extract_uniform_frames(SHORT_TALK_MP4, str(tmp_path), interval_s=10)
    assert 8 <= len(pairs) <= 10, f"expected ~9 frames, got {len(pairs)}"
    # Timestamps are deterministic: i * interval
    for i, (ts, path) in enumerate(pairs):
        assert ts == float(i * 10)
        assert os.path.exists(path)


def test_extract_uniform_frames_timestamps_are_deterministic(tmp_path, monkeypatch):
    """Without spinning up ffmpeg: stub the subprocess call, drop fake raw
    files in the output dir, and verify the rename/timestamp logic produces
    the right sequence."""
    import subprocess
    called = {}

    def fake_run(cmd, **kw):
        called["cmd"] = cmd
        # Simulate ffmpeg producing 3 frames
        for i in range(1, 4):
            with open(os.path.join(str(tmp_path), f"raw_{i:05d}.jpg"), "wb") as f:
                f.write(b"\xff\xd8\xff\xe0")  # JPEG magic, content irrelevant
        class R: returncode = 0
        return R()

    monkeypatch.setattr(subprocess, "run", fake_run)
    pairs = fe.extract_uniform_frames("ignored.mp4", str(tmp_path), interval_s=7)
    assert [ts for ts, _ in pairs] == [0.0, 7.0, 14.0]
    # File names use HH_MM_SS form
    assert os.path.basename(pairs[0][1]) == "00_00_00.jpg"
    assert os.path.basename(pairs[1][1]) == "00_00_07.jpg"
    assert os.path.basename(pairs[2][1]) == "00_00_14.jpg"
    # ffmpeg cmd uses fps=1/N filter
    assert any("fps=1/7" in arg for arg in called["cmd"])
