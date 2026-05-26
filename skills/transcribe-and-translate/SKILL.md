---
name: transcribe-and-translate
version: 0.1.0
description: This skill should be used when the user wants a YouTube video or playlist transcribed AND translated in one step — e.g. "transcribe this playlist and translate it to Korean", "이 영상 받아서 한국어로 번역까지 해줘", "get the transcript in English and also a Japanese version". Runs the transcribe pipeline (yt-dlp captions with OpenAI fallback) then the translate pipeline (OpenAI or Gemini) end-to-end. For transcription only, use transcribe; for translating files that already exist, use translate.
argument-hint: <youtube-url> --to <language> [--provider openai|gemini] [--fallback-model M] [--audio-language xx]
allowed-tools: Bash, Read, Write, Edit
---

# Transcribe and Translate (end-to-end)

Chain the `transcribe` and `translate` skills: take a YouTube URL, produce original-language
Markdown transcripts, then translate them into the requested language.

## When to use

Use when the user wants both steps at once: "transcribe this and translate to Korean",
"영상 전사하고 번역까지", "give me English transcript plus a Japanese translation". For
transcription only, use `transcribe`; for translating existing files, use `translate`.

## Workflow

Run the two bundled scripts in sequence. Remember the principle: **transcription always comes
first and is in the original language**; translation is a second pass over those files.

### Step 1 — Transcribe (original language)

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/skills/transcribe/scripts/transcribe.py" "<URL>" \
  --out-dir transcripts [--fallback-model gpt-4o-transcribe] [--audio-language xx]
```

Produces `transcripts/NN - Title.md` (and `.srt` when captioned). Report what was produced and
whether any videos used the audio fallback.

### Step 2 — Translate into the target language

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/skills/translate/scripts/translate.py" transcripts \
  --to "<language>" [--provider openai|gemini] [--model M]
```

Writes `transcripts-<lang>/NN - Title.md`. Files already in the target language are copied
through unchanged (so a playlist mixing, e.g., English and Korean videos yields a fully
target-language folder).

## Steps for Claude

1. **Parse the request** into a URL and a target language; pick provider (default openai) and
   fallback model (default gpt-4o-transcribe).
2. **Check prerequisites**: `yt-dlp` + `ffmpeg`; `OPENAI_API_KEY` for the audio fallback and/or
   openai translation; `GEMINI_API_KEY`/`GOOGLE_API_KEY` for gemini translation. Keys come from
   the environment or a `.env` in the current directory.
3. **Run Step 1**, wait for `TRANSCRIBE_DONE`, summarize results.
4. **Run Step 2** against the transcript directory, wait for `TRANSLATE_DONE`, summarize.
5. **Report** both output directories and any per-video/file failures.

## Notes

- Large playlists with no captions can be slow and incur OpenAI cost (audio fallback); warn the
  user first.
- The two underlying skills own the detailed flags — see the reference files below.

## Resources

This skill bundles no scripts of its own; it orchestrates the other two skills' scripts:

- **`${CLAUDE_PLUGIN_ROOT}/skills/transcribe/scripts/transcribe.py`** — step 1 (transcription).
- **`${CLAUDE_PLUGIN_ROOT}/skills/translate/scripts/translate.py`** — step 2 (translation).
- **`${CLAUDE_PLUGIN_ROOT}/skills/transcribe/references/usage.md`** — transcribe options.
- **`${CLAUDE_PLUGIN_ROOT}/skills/translate/references/usage.md`** — translate options.
