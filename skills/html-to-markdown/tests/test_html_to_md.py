"""Unit tests for html_to_md.py — the HTML→Markdown conversion (pure)."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import html_to_md as h2m


def _wrap(body):
    """Minimal full-blog-shaped HTML around a post-body fragment."""
    return (
        '<html><head><title>T</title></head><body>'
        '<article><header class="post-hero">'
        '<h1 class="post-title">My Title</h1>'
        '<div class="post-meta">'
        '<a href="https://youtu.be/abc">Watch on YouTube</a></div>'
        '</header><div class="post-body">' + body + '</div></article></body></html>'
    )


def test_frontmatter_and_title():
    md = h2m.html_to_markdown(_wrap("<p>Hello.</p>"))
    assert md.startswith('---\ntitle: "My Title"\nsource: https://youtu.be/abc\n---')
    assert "\n# My Title\n" in md
    assert "Hello." in md


def test_headings_and_paragraph():
    md = h2m.html_to_markdown(_wrap("<h2>Sec</h2><p>Body text.</p><h3>Sub</h3>"))
    assert "## Sec" in md
    assert "### Sub" in md
    assert "Body text." in md


def test_inline_formatting():
    body = '<p>a <strong>b</strong> <em>c</em> <code>d</code> <a href="u">e</a></p>'
    md = h2m.html_to_markdown(_wrap(body))
    assert "a **b** *c* `d` [e](u)" in md


def test_ordered_list_with_bold():
    body = "<ol><li><strong>One</strong> first</li><li>Two</li></ol>"
    md = h2m.html_to_markdown(_wrap(body))
    assert "1. **One** first" in md
    assert "2. Two" in md


def test_unordered_list():
    md = h2m.html_to_markdown(_wrap("<ul><li>a</li><li>b</li></ul>"))
    assert "- a" in md
    assert "- b" in md


def test_divider_and_blockquote():
    body = '<hr class="divider"><blockquote>quoted line</blockquote>'
    md = h2m.html_to_markdown(_wrap(body))
    assert "\n---\n" in md
    assert "> quoted line" in md


def _figure(src, ts="0:05", deep="https://y/?t=5", cap="Cap", alt="Alt"):
    return (
        f'<figure data-timestamp="00:00:05">'
        f'<a class="image-wrap" href="{deep}"><img src="{src}" alt="{alt}"></a>'
        f'<figcaption><span class="caption-text">{cap}</span>'
        f'<a class="ts-chip" href="{deep}">{ts}</a></figcaption></figure>'
    )


def test_figure_image_and_caption():
    md = h2m.html_to_markdown(_wrap(_figure("dir/00_00_05.jpg")))
    assert "![Alt](dir/00_00_05.jpg)" in md
    assert "*Cap — [▶ 0:05](https://y/?t=5)*" in md


def test_raw_spaces_get_percent_encoded():
    md = h2m.html_to_markdown(_wrap(_figure("My Folder/00_00_05.jpg")))
    assert "![Alt](My%20Folder/00_00_05.jpg)" in md
    assert "My Folder/" not in md  # raw space must not survive


def test_already_encoded_path_not_double_encoded():
    md = h2m.html_to_markdown(_wrap(_figure("My%20Folder/00_00_05.jpg")))
    assert "My%20Folder/00_00_05.jpg" in md
    assert "%2520" not in md  # no double-encoding


def test_alt_brackets_neutralised():
    md = h2m.html_to_markdown(_wrap(_figure("d/f.jpg", alt="see [x] and [y]")))
    assert "![see (x) and (y)](d/f.jpg)" in md


def test_figure_row_stacks_both_images():
    body = ('<div class="figure-row" data-count="2">'
            + _figure("d/a.jpg", cap="A") + _figure("d/b.jpg", cap="B") + '</div>')
    md = h2m.html_to_markdown(_wrap(body))
    assert "![Alt](d/a.jpg)" in md
    assert "![Alt](d/b.jpg)" in md
    assert "*A — " in md and "*B — " in md


def test_tail_section_heading():
    body = ('<section class="tail-section"><h2>Additional frames</h2>'
            + _figure("d/z.jpg") + '</section>')
    md = h2m.html_to_markdown(_wrap(body))
    assert "## Additional frames" in md
    assert "![Alt](d/z.jpg)" in md


def test_missing_source_omits_frontmatter_line():
    html = ('<html><body><div class="post-body"><p>x</p></div></body></html>')
    md = h2m.html_to_markdown(html)
    assert "source:" not in md
    assert md.startswith("---\n")
