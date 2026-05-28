---
name: translate
version: 0.1.2
description: This skill should be used when the user asks to "translate this transcript", "translate these markdown files to Korean/Japanese/English", "트랜스크립트 번역해줘", "이 문서들 한국어로 번역", "한국어로 번역해줘", or wants transcript/Markdown text localized into another language. Operates on existing files (a file or directory) and does NOT download from YouTube — to fetch a video first, use transcribe or transcribe-and-translate. Uses OpenAI (default) or Gemini, preserves Markdown structure and URLs, corrects auto-transcription errors, runs files in parallel, and skips files already written in the target writing-script.
argument-hint: <file-or-dir> --to <language> [--provider openai|gemini] [--model M] [--out-dir DIR]
allowed-tools: Bash, Read, Write, Edit
---

# Translate Transcripts

Translate transcript files (Markdown or plain text) into any target language. Designed to run
after the `transcribe` skill, but works on any `.md`/`.txt`. Accepts a single file or a
directory; does not fetch from YouTube.

## How it works

Run the bundled script — it handles chunking, provider calls, parallelism, and
structure-preserving output deterministically. Do NOT translate large files inline yourself.

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/skills/translate/scripts/translate.py" <FILE-OR-DIR> --to "<language>" [options]
```

The script:
1. Splits each file on paragraph boundaries into ~6,000-char chunks so Markdown headings,
   links, and URLs stay intact, and so output never exceeds model token limits.
2. Translates each chunk with the chosen provider, telling the model the source is an
   auto-generated transcript so it silently corrects speech-to-text errors.
3. Recursively splits any chunk that still gets truncated, then writes the joined result.
4. Skips files already in the target language (script-based detection) and copies them through.

## Providers

- **openai (default)** — `chat.completions`, default model `gpt-5.4-2026-03-05` with
  `reasoning_effort=high` (set `--openai-effort`). Needs `OPENAI_API_KEY`.
- **gemini** — `google-genai`, default model `gemini-3.5-flash`. Needs `GEMINI_API_KEY` or
  `GOOGLE_API_KEY`. Auto-detects a Vertex AI Express key (`AQ.` prefix) vs a standard key.

Select with `--provider`; override the model with `--model`.

## Steps

1. **Pick the provider** (default openai) and confirm the matching API key is available
   (environment or a `.env` in the current directory).
2. **Determine the target language** from the user (`--to "Korean"`, `--to ja`, etc.).
3. **Choose output**: directory input defaults to `<input>-<lang>/`; a single file defaults to
   `name.<lang>.ext`. Override with `--out-dir`.
4. **Run the script**. Tune `--workers` (default 8) for parallelism, `--openai-effort`
   (default `high`; reasoning effort for OpenAI reasoning models), `--gemini-thinking`
   (default `low`; raise for harder material), `--no-skip-detect` to force translating files
   already in the target language.
5. **Report** the per-file results (translated vs copied, char counts, failures) and output path.

## Notes

- Output preserves Markdown structure and URLs; only natural-language text is translated.
- Korean/Japanese/Chinese/Russian/Arabic/English are auto-detected for the "already in target"
  skip; other targets are always translated.
- For options, provider details, and cost/limit notes, read `references/usage.md`.

## Resources

- **`scripts/translate.py`** — the full translation pipeline (run it; don't reimplement).
- **`references/usage.md`** — options, provider/auth details, chunking, troubleshooting.
