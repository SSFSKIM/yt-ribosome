"""Unit tests for render_html.py — pure functions only."""
import os
import sys
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import render_html as rh


def test_parse_srt_simple():
    src = (
        "1\n00:00:00,000 --> 00:00:03,500\nHello world.\n\n"
        "2\n00:00:03,500 --> 00:00:07,000\nThis is a test.\n"
    )
    cues = rh.parse_srt(src)
    assert len(cues) == 2
    assert cues[0]["start"] == 0.0
    assert cues[0]["end"] == 3.5
    assert cues[0]["text"] == "Hello world."
    assert cues[1]["start"] == 3.5
    assert cues[1]["text"] == "This is a test."


def test_parse_srt_multiline_cue():
    src = "1\n00:00:00,000 --> 00:00:05,000\nLine one\nLine two\n\n"
    cues = rh.parse_srt(src)
    assert cues[0]["text"] == "Line one Line two"


def test_align_paragraphs_to_srt_substring_match():
    cues = [
        {"start": 0.0, "end": 3.0, "text": "Hello everyone, welcome."},
        {"start": 3.0, "end": 7.0, "text": "Today we're talking"},
        {"start": 7.0, "end": 10.0, "text": "about full blogs."},
        {"start": 10.0, "end": 14.0, "text": "Now let's get into the details."},
        {"start": 14.0, "end": 18.0, "text": "First, the architecture."},
    ]
    paragraphs = [
        "Hello everyone, welcome. Today we're talking about full blogs.",
        "Now let's get into the details. First, the architecture.",
    ]
    ranges = rh.align_paragraphs_to_srt(paragraphs, cues)
    assert len(ranges) == 2
    assert ranges[0]["p_idx"] == 0
    assert ranges[0]["start"] == 0.0
    assert ranges[0]["end"] == pytest.approx(10.0)
    assert ranges[1]["p_idx"] == 1
    assert ranges[1]["start"] == pytest.approx(10.0)
    assert ranges[1]["end"] == pytest.approx(18.0)


def test_pick_paragraph_for_frame():
    ranges = [
        {"p_idx": 0, "start": 0.0,  "end": 10.0},
        {"p_idx": 1, "start": 10.0, "end": 20.0},
        {"p_idx": 2, "start": 20.0, "end": 30.0},
    ]
    assert rh.pick_paragraph_for_frame(5.0, ranges) == 0
    assert rh.pick_paragraph_for_frame(15.0, ranges) == 1
    assert rh.pick_paragraph_for_frame(25.0, ranges) == 2
    assert rh.pick_paragraph_for_frame(99.0, ranges) == -1
    assert rh.pick_paragraph_for_frame(-1.0, ranges) == -1


def test_figure_block_includes_timestamp_and_alt():
    fig = rh._figure_block(
        image_dir="my video",
        image_filename="00_03_12.jpg",
        timestamp_s=192,
        alt="Speaker showing diagram",
        caption="Bet factory",
        video_id="Uvl-tRga98g",
    )
    assert "00_03_12.jpg" in fig
    assert "Speaker showing diagram" in fig
    assert "Bet factory" in fig
    assert "data-timestamp=\"00:03:12\"" in fig
    assert "t=192" in fig
    fig2 = rh._figure_block("d", "x.jpg", 0, "A & B", "<x>", "id")
    assert "A &amp; B" in fig2
    assert "&lt;x&gt;" in fig2


def test_render_html_inserts_figures_between_paragraphs():
    paragraphs = ["First paragraph.", "Second paragraph.", "Third paragraph."]
    ranges = [
        {"p_idx": 0, "start": 0.0,  "end": 10.0},
        {"p_idx": 1, "start": 10.0, "end": 20.0},
        {"p_idx": 2, "start": 20.0, "end": 30.0},
    ]
    frames = [
        {"path_rel": "vid/05.jpg", "timestamp_s":  5.0, "alt": "F1", "caption": "C1"},
        {"path_rel": "vid/15.jpg", "timestamp_s": 15.0, "alt": "F2", "caption": "C2"},
    ]
    out = rh.render_html(
        title="Test", source_url="https://www.youtube.com/watch?v=abc",
        paragraphs=paragraphs, paragraph_ranges=ranges, frames=frames,
        video_id="abc",
    )
    p1 = out.index("First paragraph.")
    fig1 = out.index("vid/05.jpg")
    p2 = out.index("Second paragraph.")
    fig2 = out.index("vid/15.jpg")
    p3 = out.index("Third paragraph.")
    assert p1 < fig1 < p2 < fig2 < p3


def test_render_html_unmatched_frame_goes_to_tail_section():
    paragraphs = ["Only paragraph."]
    ranges = [{"p_idx": 0, "start": 0.0, "end": 10.0}]
    frames = [
        {"path_rel": "vid/99.jpg", "timestamp_s": 99.0, "alt": "F", "caption": "C"},
    ]
    out = rh.render_html(
        title="T", source_url="https://www.youtube.com/watch?v=abc",
        paragraphs=paragraphs, paragraph_ranges=ranges, frames=frames,
        video_id="abc",
    )
    assert "Additional frames" in out
    assert "vid/99.jpg" in out
    assert out.index("Only paragraph.") < out.index("Additional frames")
