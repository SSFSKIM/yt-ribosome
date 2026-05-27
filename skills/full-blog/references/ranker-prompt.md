# Gemini ranker prompt (tunable)

This prompt is loaded by `frame_rank.py` and rendered with the batch's
transcript window. Edit the prose freely; the JSON output schema must remain.

---

You are selecting frames for a video-to-blog conversion. The blog will be the
transcript with selected frames embedded as `<figure>` blocks.

Frames arrive from UNIFORM SAMPLING (one every few seconds), so most of them
will be redundant or low-value — your main job is **aggressive filtering**.
Aim to mark ~20–30% of frames `include:true`; the rest should be `false`.

FRAMES below span timestamps [{window_start} – {window_end}] of the source
video. TRANSCRIPT for that window:

"""
{transcript_window}
"""

For EACH attached frame, decide:

- `include` (boolean): true ONLY if the frame adds visual information the
  transcript cannot convey on its own. The bar is high. Use these rules:

  INCLUDE (true) when the frame shows:
    • Code (any language, in an editor or terminal)
    • Slides with text, bullets, diagrams, or titles
    • Charts, graphs, data visualizations
    • UI screenshots (websites, apps, dashboards, documentation)
    • Demos, process steps, before/after comparisons
    • Anatomical/architectural diagrams the speaker references

  EXCLUDE (false) when the frame shows:
    • A talking head / speaker on camera with NO visual aid behind them
    • A near-duplicate of an adjacent frame (same slide, minor change) —
      keep only ONE representative per held visual; mark the rest false
    • Animated transitions, motion blur, intermediate frames during a slide swap
    • Generic backgrounds, logos, intro/outro cards, sponsor reads
    • Cartoon/avatar characters alone without supporting visual context

  When in doubt about a talking-head shot, the answer is FALSE. A blog reader
  doesn't need to see the speaker's face — they need to see what the speaker
  is pointing at.

- `alt_text` (string ≤ 60 words): factual description of what is visually shown.
- `caption` (string ≤ 15 words): short caption to display under the figure.
- `confidence` (float 0.0–1.0): how confident the `include` decision is.

Output STRICT JSON array of objects, ONE PER INPUT FRAME, in the same order as
inputs. No surrounding markdown or commentary. Schema:

```json
[
  {"frame_index": 0, "include": true,  "alt_text": "...", "caption": "...", "confidence": 0.0},
  ...
]
```
