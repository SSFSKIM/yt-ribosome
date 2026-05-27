"""Unit tests for frame_rank.py with the Gemini client mocked."""
import json
import os
import sys
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import frame_rank as fr


def test_window_transcript_text_concats_overlapping_cues():
    cues = [
        {"start": 0.0,  "end": 5.0,  "text": "A"},
        {"start": 5.0,  "end": 10.0, "text": "B"},
        {"start": 10.0, "end": 15.0, "text": "C"},
    ]
    out = fr._window_transcript(cues, win_start=4.0, win_end=11.0)
    assert "A" in out and "B" in out and "C" in out
    out2 = fr._window_transcript(cues, win_start=11.0, win_end=12.0)
    assert out2.strip() == "C"


def test_batch_frames_by_size():
    pairs = [(float(i), f"/tmp/{i}.jpg") for i in range(25)]
    batches = list(fr._batch(pairs, size=10))
    assert len(batches) == 3
    assert len(batches[0]) == 10
    assert len(batches[1]) == 10
    assert len(batches[2]) == 5


def test_parse_ranker_response_strict_json():
    raw = '[{"frame_index":0,"include":true,"alt_text":"a","caption":"c","confidence":0.9}]'
    parsed = fr._parse_response(raw, expected_len=1)
    assert parsed[0]["include"] is True
    assert parsed[0]["alt_text"] == "a"


def test_parse_ranker_response_strips_code_fence():
    raw = '```json\n[{"frame_index":0,"include":false,"alt_text":"","caption":"","confidence":0.1}]\n```'
    parsed = fr._parse_response(raw, expected_len=1)
    assert parsed[0]["include"] is False


def test_parse_ranker_response_raises_on_length_mismatch():
    raw = '[{"frame_index":0,"include":true,"alt_text":"a","caption":"c","confidence":0.5}]'
    with pytest.raises(ValueError):
        fr._parse_response(raw, expected_len=2)


@patch("frame_rank._call_gemini")
def test_rank_frames_happy_path(mock_call):
    mock_call.return_value = [
        {"frame_index": 0, "include": True,  "alt_text": "slide A", "caption": "A", "confidence": 0.9},
        {"frame_index": 1, "include": False, "alt_text": "head",    "caption": "",  "confidence": 0.8},
    ]
    pairs = [(1.0, "/tmp/a.jpg"), (3.0, "/tmp/b.jpg")]
    cues = [{"start": 0, "end": 10, "text": "talking about A"}]
    out = fr.rank_frames(pairs, cues, model="fake", batch_size=10)
    assert len(out) == 2
    assert out[0]["include"] is True
    assert out[1]["include"] is False
    mock_call.assert_called_once()


@patch("frame_rank._call_gemini")
def test_rank_frames_graceful_degrade_on_all_failures(mock_call):
    mock_call.side_effect = RuntimeError("rate limit forever")
    pairs = [(float(i), f"/tmp/{i}.jpg") for i in range(20)]
    cues = [{"start": 0, "end": 30, "text": "..."}]
    out = fr.rank_frames(pairs, cues, model="fake", batch_size=10,
                         max_frames_final=6, allow_degrade=True,
                         _retry_base_delay=0.0)
    assert len(out) == 6
    assert all(o["include"] is True for o in out)
    assert all(o.get("degraded") for o in out)
