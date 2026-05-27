"""End-to-end test for the full-blog pipeline with Gemini mocked."""
import os
import sys
from unittest.mock import patch

import pytest

HERE = os.path.dirname(__file__)
sys.path.insert(0, os.path.join(HERE, "..", "scripts"))
import frame_extract as fe
import frame_rank as fr
import render_html as rh

FIX = os.path.join(HERE, "fixtures")
SHORT_TALK_MP4 = os.path.join(FIX, "short_talk.mp4")
SHORT_TALK_SRT = os.path.join(FIX, "short_talk.srt")
SHORT_TALK_MD = os.path.join(FIX, "short_talk.md")


def _ensure_fixtures():
    if not os.path.exists(SHORT_TALK_MP4):
        pytest.skip("short_talk.mp4 missing — run integration suite once to download")
    if not (os.path.exists(SHORT_TALK_SRT) and os.path.exists(SHORT_TALK_MD)):
        pytest.skip("committed fixture text files missing")


@pytest.mark.integration
def test_pipeline_end_to_end_with_mocked_ranker(tmp_path):
    _ensure_fixtures()

    # 1. real ffmpeg scene-cut
    th = fe.detect_threshold(SHORT_TALK_MP4)
    assert th in (0.20, 0.30, 0.50)
    frames_dir = tmp_path / "frames"
    pairs = fe.extract_scene_cuts(SHORT_TALK_MP4, th, str(frames_dir))
    assert len(pairs) >= 2

    # 2. real phash dedup
    survivors = fe.dedup_by_phash(pairs)
    assert 1 <= len(survivors) <= len(pairs)

    # 3. mocked Gemini ranker — accept every survivor with stable alt/caption
    with patch("frame_rank._call_gemini") as mock_call:
        def fake_call(model, prompt, image_paths, api_key=None):
            return [{"frame_index": i, "include": True,
                     "alt_text": f"alt-{i}", "caption": f"cap-{i}",
                     "confidence": 0.9}
                    for i in range(len(image_paths))]
        mock_call.side_effect = fake_call
        cues = rh.parse_srt(open(SHORT_TALK_SRT, encoding="utf-8").read())
        ranked = fr.rank_frames(survivors, cues, model="fake", batch_size=10,
                                max_frames_final=5, allow_degrade=False)

    # rank_frames returns all frames with include flags; orchestrator filters.
    # Mock returns all include=True, so all should be present.
    assert len(ranked) >= 1
    assert all(r["include"] for r in ranked)

    # Apply orchestrator-style filter + cap
    kept = [r for r in ranked if r["include"]]
    kept.sort(key=lambda r: (-r["confidence"], r["timestamp_s"]))
    kept = kept[:5]
    assert 1 <= len(kept) <= 5

    # 4. real render
    md_text = open(SHORT_TALK_MD, encoding="utf-8").read()
    paragraphs = [p.strip() for p in md_text.split("\n\n") if p.strip()
                  and not p.startswith("# ") and not p.startswith("[YouTube")]
    assert len(paragraphs) >= 1, "expected at least one body paragraph in fixture md"
    ranges = rh.align_paragraphs_to_srt(paragraphs, cues)
    frames_for_render = [
        {"path_rel": f"short_talk/{os.path.basename(r['path'])}",
         "timestamp_s": r["timestamp_s"], "alt": r["alt_text"],
         "caption": r["caption"]}
        for r in kept
    ]
    html = rh.render_html(
        title="Short Talk", source_url="https://www.youtube.com/watch?v=abc",
        paragraphs=paragraphs, paragraph_ranges=ranges,
        frames=frames_for_render, video_id="abc",
    )
    # Structural assertions (more robust than golden-file diff)
    assert html.startswith("<!DOCTYPE html>")
    assert "<article>" in html
    assert "<h1>Short Talk</h1>" in html
    # Every kept frame produces one <figure
    assert html.count("<figure") == len(kept)
    # Source link present
    assert "https://www.youtube.com/watch?v=abc" in html
