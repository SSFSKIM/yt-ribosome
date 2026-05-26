#!/usr/bin/env python3
"""Transcribe a YouTube video or playlist into Markdown.

Pipeline per video:
  1. Try the original-language auto-caption (the YouTube ".*-orig" ASR track) or
     a manual subtitle via yt-dlp. Parse to clean, de-duplicated segments.
  2. If no caption exists and audio fallback is enabled, download the audio,
     split it into <=24MB chunks, and transcribe with the OpenAI API
     (gpt-4o-transcribe by default, whisper-1 optional).
  3. Write `NN - Title.md` (title + source link + paragraphed body). When a
     caption with timestamps was used, also write `NN - Title.srt` unless
     --no-srt is given.

Transcripts are produced in the video's ORIGINAL language (no translation here).

Examples:
  python3 transcribe.py "https://www.youtube.com/watch?v=ID"
  python3 transcribe.py "<playlist-url>" --out-dir ./out --workers 6
  python3 transcribe.py "<url>" --fallback-model whisper-1 --audio-language en

Requires: yt-dlp, ffmpeg (system); `openai` (only when the audio fallback runs).
API key: OPENAI_API_KEY from the environment, or a .env file in the CWD.
"""
import argparse
import concurrent.futures as cf
import glob
import json
import os
import re
import subprocess
import sys
import tempfile
import textwrap

YDLP_BASE = ["yt-dlp", "--no-warnings", "--remote-components", "ejs:github"]


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def load_env():
    """Make .env values available via os.environ (does not overwrite real env)."""
    path = os.path.join(os.getcwd(), ".env")
    if os.path.isfile(path):
        for line in open(path, encoding="utf-8"):
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())


def safe_name(title):
    return re.sub(r"[/\\:]", "-", title).strip()


def ms_to_ts(ms):
    h, ms = divmod(int(ms), 3600000)
    m, ms = divmod(ms, 60000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def paragraphs(segments, per=4, max_chars=700):
    """Group segment texts into readable Markdown paragraphs.

    Groups ~`per` sentences per paragraph, capping at `max_chars`. Captions
    often lack punctuation (no sentence breaks); such long runs are split by
    word count so the output is still paragraphed rather than one wall of text.
    """
    text = re.sub(r"\s+", " ", " ".join(segments)).strip()
    pieces = []
    for s in re.split(r"(?<=[.!?。！？])\s+", text):
        if len(s) <= max_chars:
            pieces.append(s)
            continue
        cur = ""
        for w in s.split():
            if cur and len(cur) + len(w) + 1 > max_chars:
                pieces.append(cur)
                cur = w
            else:
                cur = f"{cur} {w}".strip()
        if cur:
            pieces.append(cur)
    out, cur, clen = [], [], 0
    for p in pieces:
        cur.append(p)
        clen += len(p)
        if len(cur) >= per or clen >= max_chars:
            out.append(" ".join(cur))
            cur, clen = [], 0
    if cur:
        out.append(" ".join(cur))
    return out


# --------------------------------------------------------------------------- #
# caption path
# --------------------------------------------------------------------------- #
def list_entries(url):
    """Return [(index, id, title)] for a video or playlist URL."""
    res = subprocess.run(
        YDLP_BASE + ["--flat-playlist", "--print", "%(id)s\t%(title)s", url],
        capture_output=True, text=True,
    )
    entries = []
    for i, line in enumerate(res.stdout.strip().splitlines(), 1):
        if "\t" in line:
            vid, title = line.split("\t", 1)
            entries.append((i, vid, title))
    return entries


def download_caption(url, dest_dir, vid):
    """Download the original-language caption track; return a file path or None."""
    subprocess.run(
        YDLP_BASE + [
            "--skip-download", "--write-subs", "--write-auto-subs",
            "--sub-langs", ".*-orig,.*", "--sub-format", "json3/vtt",
            "-o", os.path.join(dest_dir, "%(id)s.%(ext)s"), url,
        ],
        capture_output=True, text=True,
    )
    cands = glob.glob(os.path.join(dest_dir, f"{vid}.*"))
    vtt = [c for c in cands if c.endswith(".vtt")]
    orig = [c for c in cands if c.endswith("-orig.json3")]
    j3 = [c for c in cands if c.endswith(".json3")]
    return (orig or vtt or j3 or [None])[0]


def parse_json3(path):
    data = json.load(open(path, encoding="utf-8"))
    segs = []
    for e in data.get("events", []):
        if e.get("aAppend") == 1 or not e.get("segs"):
            continue
        txt = re.sub(r"\s+", " ", "".join(s.get("utf8", "") for s in e["segs"])).strip()
        if txt:
            start = int(e.get("tStartMs", 0))
            segs.append([start, start + int(e.get("dDurationMs", 0)), txt])
    return segs


def parse_vtt(path):
    ts = re.compile(r"(\d{2}):(\d{2}):(\d{2})[.,](\d{3})\s*-->\s*(\d{2}):(\d{2}):(\d{2})[.,](\d{3})")
    segs = []
    for block in re.split(r"\n\s*\n", open(path, encoding="utf-8").read()):
        m, lines = None, []
        for ln in block.strip().split("\n"):
            hit = ts.search(ln)
            if hit:
                m = hit
            elif m is not None:
                lines.append(ln)
        if not m:
            continue
        start = (int(m[1]) * 3600 + int(m[2]) * 60 + int(m[3])) * 1000 + int(m[4])
        end = (int(m[5]) * 3600 + int(m[6]) * 60 + int(m[7])) * 1000 + int(m[8])
        txt = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", " ".join(lines))).strip()
        if txt and not (segs and segs[-1][2] == txt):
            segs.append([start, end, txt])
    return segs


def write_srt(segments, path):
    out = []
    for i, (start, end, txt) in enumerate(segments, 1):
        if i < len(segments):
            end = min(end, segments[i][0])
        out += [str(i), f"{ms_to_ts(start)} --> {ms_to_ts(end)}", txt, ""]
    open(path, "w", encoding="utf-8").write("\n".join(out))


# --------------------------------------------------------------------------- #
# audio fallback path (OpenAI)
# --------------------------------------------------------------------------- #
def transcribe_audio(url, vid, model, language, tmp):
    audio = os.path.join(tmp, f"{vid}.mp3")
    subprocess.run(
        YDLP_BASE + ["-f", "bestaudio", "-x", "--audio-format", "mp3",
                     "--audio-quality", "5", "-o", os.path.join(tmp, f"{vid}.%(ext)s"), url],
        capture_output=True, text=True,
    )
    if not os.path.isfile(audio):
        raise RuntimeError("audio download failed")
    chunk_dir = os.path.join(tmp, "chunks")
    os.makedirs(chunk_dir, exist_ok=True)
    subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", audio,
         "-ar", "16000", "-ac", "1", "-b:a", "48k",
         "-f", "segment", "-segment_time", "600",
         os.path.join(chunk_dir, "c_%03d.mp3")],
        check=True,
    )
    from openai import OpenAI
    client = OpenAI()
    parts = []
    for chunk in sorted(glob.glob(os.path.join(chunk_dir, "c_*.mp3"))):
        kwargs = dict(model=model, response_format="text", file=open(chunk, "rb"))
        if language:
            kwargs["language"] = language
        parts.append(client.audio.transcriptions.create(**kwargs).strip())
    return " ".join(p for p in parts if p)


# --------------------------------------------------------------------------- #
# per-video orchestration
# --------------------------------------------------------------------------- #
def process_video(idx, vid, title, args):
    url = f"https://www.youtube.com/watch?v={vid}"
    base = os.path.join(args.out_dir, f"{idx:02d} - {safe_name(title)}")
    if os.path.exists(base + ".md") and not args.overwrite:
        return f"skip (exists): {idx:02d} {title[:50]}"
    with tempfile.TemporaryDirectory() as tmp:
        cap = download_caption(url, tmp, vid)
        if cap:
            segs = parse_json3(cap) if cap.endswith(".json3") else parse_vtt(cap)
            source = "caption"
            if segs and not args.no_srt:
                write_srt(segs, base + ".srt")
            body = paragraphs([s[2] for s in segs])
        elif args.no_audio_fallback:
            return f"NO CAPTION, fallback disabled: {idx:02d} {title[:50]}"
        else:
            text = transcribe_audio(url, vid, args.fallback_model, args.audio_language, tmp)
            source = f"audio:{args.fallback_model}"
            body = paragraphs([text])
    md = [f"# {idx:02d}. {title}", "", f"[YouTube]({url})", ""] + "\n\n".join(body).split("\n")
    open(base + ".md", "w", encoding="utf-8").write("\n".join(md).rstrip() + "\n")
    return f"done [{source}]: {idx:02d} {title[:50]} ({sum(len(b) for b in body)} chars)"


def main():
    ap = argparse.ArgumentParser(description="Transcribe a YouTube video/playlist to Markdown.")
    ap.add_argument("url", help="YouTube video or playlist URL")
    ap.add_argument("--out-dir", default="transcripts", help="output directory (default: transcripts)")
    ap.add_argument("--fallback-model", default="gpt-4o-transcribe",
                    choices=["gpt-4o-transcribe", "gpt-4o-mini-transcribe", "whisper-1"],
                    help="OpenAI model when no caption exists (default: gpt-4o-transcribe)")
    ap.add_argument("--audio-language", default=None,
                    help="ISO code to force for audio transcription (avoids mis-detection)")
    ap.add_argument("--no-audio-fallback", action="store_true",
                    help="caption-only; skip the OpenAI audio fallback")
    ap.add_argument("--no-srt", action="store_true", help="do not write .srt even when timestamps exist")
    ap.add_argument("--workers", type=int, default=4, help="parallel videos (default: 4)")
    ap.add_argument("--overwrite", action="store_true", help="re-process even if .md exists")
    args = ap.parse_args()

    load_env()
    os.makedirs(args.out_dir, exist_ok=True)
    entries = list_entries(args.url)
    if not entries:
        sys.exit("No videos found for that URL.")
    print(f"{len(entries)} video(s) -> {args.out_dir}", flush=True)
    with cf.ThreadPoolExecutor(max_workers=max(1, args.workers)) as pool:
        futs = {pool.submit(process_video, i, v, t, args): v for i, v, t in entries}
        for fut in cf.as_completed(futs):
            try:
                print(fut.result(), flush=True)
            except Exception as e:
                print(f"FAILED {futs[fut]}: {e}", flush=True)
    print("TRANSCRIBE_DONE", flush=True)


if __name__ == "__main__":
    main()
