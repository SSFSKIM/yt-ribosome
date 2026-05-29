---
name: epub-image-index
version: 0.2.0
description: This skill should be used when the user wants to extract an EPUB's images and build a tutor-agent-facing index that maps each image to its place in the book and its surrounding context — so a teaching agent can surface the right visual while explaining a topic. Trigger on "index the figures in this epub", "extract textbook images for the tutor", "build an image map", "map epub images to chapters/topics", "epub 그림 추출/인덱싱", "튜터가 쓸 textbook figure 맵". This is an AGENTIC skill: a thin script does the deterministic extraction, and you (the agent) inspect each book and decide how to tag/organize. Not for human-browsable HTML (use epub-to-html) or Markdown (use html-to-markdown).
argument-hint: [epub-or-dir] [--out-dir DIR]
allowed-tools: Bash, Read, Write, Edit
---

# Index an EPUB's images for a tutor agent

Build a tutor-facing index that maps every meaningful image in a book to **where
it lives** (a navigation breadcrumb) and **what surrounds it** (caption, heading,
nearby text), so a teaching agent can pull the right visual when explaining a
topic.

This is an **agentic skill**, not a one-shot program. A thin script
(`epub_extract.py`) does only the deterministic plumbing; **you** — the agent —
do the judgment: inspect how *this particular book* marks its images, choose a
tagging rule, and write the final index. EPUBs vary enormously (textbooks,
novels, manga, papers), so a fixed classifier would be brittle. You have the
book in front of you — adapt to it.

## Core policy: keep everything, tag don't drop

EPUB extraction gives structure for **free** — every image already carries its
breadcrumb and context. So there is no cost to keeping an image as long as it's
well organized, and dropping risks losing something the tutor wanted.

**Do not filter images out. Tag each with a `type` and keep them all.** Even
inline math images are worth keeping as exact references (a faithful equation
image can beat a re-typeset LaTeX that transcribes wrong). The tutor agent
filters by `type` at use-time; that's a softer, reversible decision than
deleting at extraction time.

## Workflow

1. **Run the extractor** (deterministic; no judgment):
   ```bash
   python3 "${CLAUDE_PLUGIN_ROOT}/skills/epub-image-index/scripts/epub_extract.py" "<EPUB_OR_DIR>" [--out-dir DIR]
   ```
   For each book it writes `<out>/<Book Title>/extract.json` + `images/` (every
   referenced image copied once) and prints a one-line profile per book:
   *N unique images / M occurrences | K in `<figure>` | C captioned.*

2. **Inspect how this book marks images.** Read the profile and skim a few
   `extract.json` entries. Decide which signals are reliable *for this book*:
   - Does it wrap figures in `<figure>` (K large)? Then `in_figure` is your
     gold signal and bare `<img>` is mostly math/decoration.
   - Or does it use bare `<img>` (K≈0)? Then lean on **dimensions** and
     **captions** instead.
   - Look at the dimension spread of `in_figure` vs not, and at sample
     captions, to pick any size threshold you need.

3. **Tag every image** with a `type` — e.g. `figure` / `equation` / `photo` /
   `diagram` / `decorative` / `cover`. Apply a per-book *rule* in bulk (read
   `extract.json`, write a tiny snippet, or extend the extractor) — you are not
   classifying images one by one, you are choosing the rule after seeing the
   book. **Keep all images**; tagging organizes, it doesn't delete.

4. **Write the tutor-facing `index.json`** next to `extract.json`, keyed for
   topic lookup (see schema). Organize by breadcrumb — it's free.

5. If the extractor errors on an unusual EPUB, it's a starting point, not
   sacred — inspect the file and adapt inline. Errors here are small and
   recoverable; handle them as you go.

## Signals the extractor gives you (per image)

`source_image`, `image` (copied path), `width`/`height`, and `occurrences[]` —
each occurrence has: `breadcrumb` (TOC path), `nearest_heading`, `in_figure`,
`css_class`, `role` (`epub:type`), `alt`, `caption`, `context_before`,
`context_after`, `source_file`, `spine_index`. Plus top-level `book` + `toc`.

## Lessons from real textbooks (apply as judgment, not hardcoded rules)

- **Math equations usually sit in `<div>`/`<p>`, not `<figure>`.** When a book
  wraps real figures in `<figure>`, that's the cleanest figure signal and bare
  images are mostly equations/decoration. Don't assume every book does this.
- **A real caption *line begins with* "Figure N" / "Table N" / "그림 N".** Prose
  that merely *mentions* "…as shown in Figure 2.3…" is not a caption — don't
  promote an image just because nearby prose name-drops a figure.
- **Inline math is short; figures/photos are larger.** Median heights differ
  sharply (e.g. ~29px vs ~276px in one physics book) — but the right threshold
  is per-book, so read the profile rather than reusing a number.
- **`breadcrumb` is authoritative location**; the nearest DOM heading is a
  finer hint that can differ from the TOC. Both are provided.
- **Front-matter** (cover/title/copyright/contents) carries non-teaching
  images — tag them `cover`/`frontmatter`, don't mix them into topic figures.

## Target `index.json` schema (tutor-facing)

Top level: `book`, `toc`, `figure_count` (or `image_count`), and `images[]`.
Each image: `id`, `image` (path), `type` (your tag), `breadcrumb`,
`chapter`/`section` (convenience), `nearest_heading`, `caption`, `alt`,
`description` (caption → alt → context snippet), `context_before/after`,
`width`/`height`, `occurrences`. Optionally a `by_topic`/`by_breadcrumb` reverse
index so the tutor can look up visuals for a topic quickly.

## How the tutor agent uses the result

1. Student asks about a topic → match it against `breadcrumb` / `caption` /
   `context` (or a reverse index), filtering by `type` (e.g. skip `equation`
   unless a visual is wanted).
2. Show `images/<file>` and narrate with the caption + breadcrumb
   ("Here's Figure 3.1 from Chapter 3 → Descriptive Statistics…").

## Notes

- **Security.** The extractor parses EPUB XML with an entity-declaration guard
  (rejects `<!ENTITY>`) to block XXE / billion-laughs — no third-party parser.
- **General, not publisher-specific.** No curated topic taxonomy, no `fig*.jpg`
  filename assumptions, no fixed CSS classes — you supply the per-book judgment.
- Pairs with `epub-to-html` (human reading); this skill targets the agent.

## Resources

- **`scripts/epub_extract.py`** — thin deterministic extractor (run it). It is
  an example/starting point, not a do-everything program: adapt it per book.
