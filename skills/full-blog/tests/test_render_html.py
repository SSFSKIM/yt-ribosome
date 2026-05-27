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
