# translate.py — usage reference

## Command

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/skills/translate/scripts/translate.py" <FILE-OR-DIR> --to "<language>" [options]
```

| Option | Default | Meaning |
|--------|---------|---------|
| `--to LANG` | (required) | target language: name (`Korean`, `日本語`), or code (`ko`, `ja`) |
| `--provider P` | `openai` | `openai` or `gemini` |
| `--model M` | per provider | override (default `gpt-5.4-2026-03-05` / `gemini-3.5-flash`) |
| `--out-dir DIR` | `<input>-<lang>` | output directory |
| `--openai-effort L` | `high` | `minimal`/`low`/`medium`/`high` reasoning effort (OpenAI reasoning models) |
| `--gemini-thinking L` | `low` | `minimal`/`low`/`medium`/`high` (Gemini 3.x only) |
| `--no-skip-detect` | off | translate even files already in the target language |
| `--workers N` | `8` | parallel files |
| `--overwrite` | off | re-translate even if the output file exists |

## Providers & authentication

| Provider | Package | Key (env or `.env`) | Default model |
|----------|---------|---------------------|---------------|
| openai | `openai` | `OPENAI_API_KEY` | `gpt-5.4-2026-03-05` (reasoning, effort `high`) |
| gemini | `google-genai` | `GEMINI_API_KEY` or `GOOGLE_API_KEY` | `gemini-3.5-flash` |

**OpenAI reasoning models** (`gpt-5.x`, `o1`/`o3`/`o4`): the script sends `reasoning_effort`
(`--openai-effort`, default `high`) and uses `max_completion_tokens` (reasoning tokens count
toward it). Custom `temperature` is not supported by these models and is omitted. Non-reasoning
models (e.g. `gpt-4o`, `gpt-4.1`) use `temperature=0.3` + `max_tokens`.

**Gemini key auto-detection:** a key starting with `AQ.` is treated as a **Vertex AI Express**
key (`genai.Client(vertexai=True, api_key=...)`); anything else (e.g. `AIza...`) uses the
standard Gemini API (`genai.Client(api_key=...)`). For Express keys the Gemini API must be
enabled on the associated Google Cloud project.

## Output paths

- **Directory input** → writes one file per source into `<input>-<lang>/` (override `--out-dir`),
  keeping original filenames.
- **Single file** → writes `name.<lang>.ext` beside the source (or into `--out-dir`).

Existing outputs are skipped unless `--overwrite`, so re-runs resume.

## Chunking & structure preservation

Files are split on blank lines (paragraph boundaries), accumulating blocks up to ~6,000 chars
per request. This keeps Markdown headings, lists, and `[text](url)` links inside a single chunk
and within model output limits. The system prompt instructs the model to preserve all Markdown
and URLs and translate only natural-language text. If a chunk is still truncated
(`finish_reason` length / MAX_TOKENS), it is split in half and retried (up to 4 levels).

## "Already in target" skip

Whole-file script detection (Hangul, Kana/Han, Cyrillic, Arabic, Latin) decides whether a file
is already in the target language; such files are copied through unchanged. Detection covers
ko/ja/zh/ru/ar/en — for any other target, files are always translated. Disable with
`--no-skip-detect`.

## Cost / limits

- OpenAI: the default `gpt-5.4-2026-03-05` is a reasoning model — `effort high` spends extra
  reasoning tokens before the translation, so it is slower and pricier per chunk but higher
  quality. Lower `--openai-effort` (or use `--model gpt-4o`) for faster/cheaper runs. The
  `max_completion_tokens` budget (reasoning + output) is set generously; truncated chunks are
  auto-split and retried.
- Gemini 3.5 Flash allows 65,536 output tokens; thinking level affects cost/latency — `low` is
  a good default for translation, raise to `medium`/`high` for nuanced or literary material.
- Parallelism (`--workers`) can trigger provider rate limits; the script retries with
  exponential backoff.

## Troubleshooting

- **`PERMISSION_DENIED` / API disabled (Gemini Express)** — enable the Gemini API on the
  Cloud project tied to the `AQ.` key.
- **Empty/short output** — likely a safety block or truncation; the retry/split logic handles
  most cases. Try a different `--model` or lower `--workers`.
- **Markdown got mangled** — ensure the input really is Markdown; very long single paragraphs
  may be split mid-way — prefer transcripts produced by the `transcribe` skill.
