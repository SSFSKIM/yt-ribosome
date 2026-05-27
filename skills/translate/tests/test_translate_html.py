"""Tests for the HTML path of translate.py (no LLM call — _translate_html_nodes mocked)."""
import os
import sys
from unittest.mock import patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import translate as tr


HTML_SAMPLE = """<!DOCTYPE html>
<html lang="en">
<head><title>My Talk</title></head>
<body>
<article>
<h1>Welcome</h1>
<p class="source"><a href="https://www.youtube.com/watch?v=abc">▶ Watch on YouTube</a></p>
<p>Hello everyone.</p>
<figure data-timestamp="00:00:15">
  <a href="https://www.youtube.com/watch?v=abc&t=15">
    <img src="My Talk/00_00_15.jpg" alt="Speaker showing a slide" loading="lazy">
  </a>
  <figcaption>Intro slide <a class="ts-link" href="https://www.youtube.com/watch?v=abc&t=15">(00:15)</a></figcaption>
</figure>
<p>Some <code>code</code> here should not be translated.</p>
</article>
</body>
</html>
"""


def test_extract_translatable_nodes():
    nodes = tr._extract_html_nodes(HTML_SAMPLE)
    kinds = [n["kind"] for n in nodes]
    texts = [n["text"] for n in nodes]
    assert "title" in kinds
    assert any(t == "Welcome" for t in texts)
    assert any(t == "Hello everyone." for t in texts)
    assert any(t == "Speaker showing a slide" for t in texts)
    assert not any(t == "code" for t in texts)


@patch("translate._call_html_batch")
def test_translate_html_full_roundtrip(mock_call):
    def fake_call(nodes_json, *args, **kwargs):
        import json as _j
        nodes = _j.loads(nodes_json)
        translated = []
        for n in nodes:
            t = n["text"]
            if t == "Welcome":               t = "환영합니다"
            elif t == "Hello everyone.":     t = "안녕하세요 여러분."
            elif "Speaker showing" in t:     t = "슬라이드를 보여주는 발표자"
            elif "Intro slide" in t:         t = "도입부 슬라이드"
            translated.append({"id": n["id"], "kind": n["kind"], "text": t})
        return translated
    mock_call.side_effect = fake_call

    out = tr._translate_html(HTML_SAMPLE, "Korean")
    assert "환영합니다" in out
    assert "안녕하세요 여러분." in out
    assert 'alt="슬라이드를 보여주는 발표자"' in out
    assert "https://www.youtube.com/watch?v=abc" in out
    assert "My Talk/00_00_15.jpg" in out
