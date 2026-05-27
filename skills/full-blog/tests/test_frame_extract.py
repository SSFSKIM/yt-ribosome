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
