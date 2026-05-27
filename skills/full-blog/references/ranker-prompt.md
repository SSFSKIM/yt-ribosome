# Gemini ranker prompt (tunable)

This prompt is loaded by `frame_rank.py` and rendered with the batch's
transcript window. Edit the prose freely; the JSON output schema must remain.

---

You are selecting frames for a video-to-blog conversion. The blog will be the
transcript with selected frames embedded as `<figure>` blocks.

FRAMES below span timestamps [{window_start} – {window_end}] of the source
video. TRANSCRIPT for that window:

"""
{transcript_window}
"""

For EACH attached frame, decide:

- `include` (boolean): true if the frame adds visual information the transcript
  cannot convey on its own. YES for slides, diagrams, charts, code on screen,
  process demonstrations, data visualizations. NO for talking-head shots,
  generic backgrounds, motion blur, or near-duplicates of nearby frames.
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
