#!/usr/bin/env python3
"""full-blog: YouTube URL/playlist -> HTML blog post with frames embedded.

Pipeline per video:
  1. Run transcribe.py (subprocess) to get .md + .srt.
  2. Download the video with yt-dlp to /tmp.
  3. Adaptive threshold sample -> ffmpeg scene-cut.
  4. imagehash phash dedup.
  5. Gemini batched ranker (transcript-context-aware) -> top N frames.
  6. Align frames to paragraphs via srt cues, render HTML.
  7. Copy chosen frames to <out>/<title>/, clean up temp.

Examples:
  python3 full_blog.py "https://www.youtube.com/watch?v=ID"
  python3 full_blog.py "<playlist-url>" --out-dir ./out --max-frames-per-video 20
  python3 full_blog.py "<url>" --ranker-model gemini-2.0-flash

API keys: GEMINI_API_KEY / GOOGLE_API_KEY in env or .env in CWD.
"""
import argparse
import concurrent.futures as cf
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time

# Local modules
HERE = os.path.dirname(__file__)
sys.path.insert(0, HERE)
import frame_extract as fe
import frame_rank as fr
import render_html as rh


PLUGIN_ROOT = os.environ.get("CLAUDE_PLUGIN_ROOT") or os.path.normpath(
    os.path.join(HERE, "..", "..", "..")
)
TRANSCRIBE_PY = os.path.join(PLUGIN_ROOT, "skills", "transcribe", "scripts", "transcribe.py")

_COST_PER_IMAGE_USD = {
    "gemini-2.0-flash": 0.00012,
    "gemini-2.5-flash": 0.00036,
    "gpt-4o":           0.00210,
    "gpt-4o-mini":      0.00400,
    "claude-haiku-4.5": 0.00120,
}


def _estimate_video_cost(num_frames, model):
    per = _COST_PER_IMAGE_USD.get(model, 0.00036)
    return num_frames * per * 1.3   # 30% padding for prompt/text tokens


def load_env():
    path = os.path.join(os.getcwd(), ".env")
    if os.path.isfile(path):
        for line in open(path, encoding="utf-8"):
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())


def safe_name(t):
    return re.sub(r"[/\\:]", "-", t).strip()


def _video_id_from_url(url):
    m = re.search(r"(?:v=|youtu\.be/)([\w\-]{11})", url)
    return m.group(1) if m else None


def _list_playlist_urls(url):
    """If url is a playlist, expand to a list of video URLs; else return [url]."""
    if "list=" not in url:
        return [url]
    res = subprocess.run(
        ["yt-dlp", "--flat-playlist", "--print", "url", url],
        capture_output=True, text=True,
    )
    if res.returncode != 0:
        raise RuntimeError(f"yt-dlp playlist expand failed: {res.stderr[:200]}")
    return [line.strip() for line in res.stdout.splitlines() if line.strip()]


def _run_transcribe(url, work_dir):
    """Run the existing transcribe.py; return (md_path, srt_path, title)."""
    out_dir = os.path.join(work_dir, "_t")
    os.makedirs(out_dir, exist_ok=True)
    res = subprocess.run(
        ["python3", TRANSCRIBE_PY, url, "--out-dir", out_dir],
        capture_output=True, text=True,
    )
    if res.returncode != 0:
        raise RuntimeError(f"transcribe.py failed: {res.stderr[:300]}")
    md_files = [f for f in os.listdir(out_dir) if f.endswith(".md")]
    if not md_files:
        raise RuntimeError("transcribe produced no .md file")
    md_path = os.path.join(out_dir, md_files[0])
    srt_path = md_path[:-3] + ".srt"
    if not os.path.exists(srt_path):
        raise RuntimeError("transcribe produced no .srt — full-blog requires timestamps")
    with open(md_path, encoding="utf-8") as f:
        first_line = f.readline().strip()
    title = first_line.lstrip("# ").strip() or os.path.splitext(md_files[0])[0]
    return md_path, srt_path, title


def _download_video(url, work_dir):
    """yt-dlp the video as mp4 into work_dir/video.mp4."""
    out = os.path.join(work_dir, "video.mp4")
    res = subprocess.run(
        ["yt-dlp", "-f", "best[ext=mp4]/best", "-o", out, url],
        capture_output=True, text=True,
    )
    if res.returncode != 0:
        raise RuntimeError(f"yt-dlp video failed: {res.stderr[:300]}")
    return out


def _parse_markdown_body(md_path):
    """Return list of body paragraphs (skipping H1 and source link)."""
    paragraphs = []
    cur = []
    in_body = False
    for line in open(md_path, encoding="utf-8"):
        line = line.rstrip()
        if not in_body:
            if line.startswith("# "):
                continue
            if line.startswith("[YouTube"):
                continue
            if line == "":
                continue
            in_body = True
        if line == "":
            if cur:
                paragraphs.append(" ".join(cur).strip())
                cur = []
        else:
            cur.append(line)
    if cur:
        paragraphs.append(" ".join(cur).strip())
    return paragraphs


def process_one(url, args):
    """Process a single URL end-to-end; return a dict result."""
    started = time.time()
    video_id = _video_id_from_url(url) or "unknown"
    fixed_temp = f"/tmp/yt-ribosome-blog-{video_id}"
    if args.no_resume:
        work_dir = tempfile.mkdtemp(prefix=f"yt-ribosome-blog-{video_id}-")
        resumed = False
    else:
        resumed = os.path.isdir(fixed_temp) and os.listdir(fixed_temp)
        os.makedirs(fixed_temp, exist_ok=True)
        work_dir = fixed_temp
    try:
        md_path, srt_path, title = _run_transcribe(url, work_dir)
        safe = safe_name(title)
        out_html = os.path.join(args.out_dir, f"{safe}.html")
        out_imgs_dir = os.path.join(args.out_dir, safe)

        if os.path.exists(out_html) and not args.force:
            return {"url": url, "title": title, "status": "skipped",
                    "reason": "output exists (use --force to overwrite)"}

        video_path = os.path.join(work_dir, "video.mp4")
        if not (resumed and os.path.exists(video_path) and os.path.getsize(video_path) > 1_000_000):
            video_path = _download_video(url, work_dir)
        threshold = (args.scene_threshold
                     if args.scene_threshold is not None
                     else fe.detect_threshold(video_path))
        frames_dir = os.path.join(work_dir, "frames")
        pairs = fe.extract_scene_cuts(video_path, threshold, frames_dir)
        survivors = fe.dedup_by_phash(pairs)
        cues = rh.parse_srt(open(srt_path, encoding="utf-8").read())
        est_cost = _estimate_video_cost(len(survivors), args.ranker_model)
        ranked = fr.rank_frames(
            survivors, cues,
            model=args.ranker_model,
            batch_size=args.batch_size,
            max_frames_final=args.max_frames_per_video,
            allow_degrade=True,
            cache_path=os.path.join(work_dir, "ranker_cache.json"),
        )

        # Filter: in non-degraded mode, rank_frames returns all frames
        # (with include=True/False). Only keep included frames. In degraded mode,
        # all returned frames are pre-marked include=True so the filter is a no-op.
        kept = [r for r in ranked if r["include"]]
        # Enforce final cap (rank_frames doesn't enforce it on non-degraded path).
        kept.sort(key=lambda r: (-r["confidence"], r["timestamp_s"]))
        kept = kept[:args.max_frames_per_video]

        os.makedirs(out_imgs_dir, exist_ok=True)
        frames_for_render = []
        for r in kept:
            base = os.path.basename(r["path"])
            dst = os.path.join(out_imgs_dir, base)
            shutil.copy2(r["path"], dst)
            frames_for_render.append({
                "path_rel": f"{safe}/{base}",
                "timestamp_s": r["timestamp_s"],
                "alt": r["alt_text"],
                "caption": r["caption"],
            })

        paragraphs = _parse_markdown_body(md_path)
        ranges = rh.align_paragraphs_to_srt(paragraphs, cues)
        source_url = f"https://www.youtube.com/watch?v={video_id}"
        html = rh.render_html(
            title=title, source_url=source_url, paragraphs=paragraphs,
            paragraph_ranges=ranges, frames=frames_for_render,
            video_id=video_id, image_dir=None,
        )
        os.makedirs(args.out_dir, exist_ok=True)
        with open(out_html, "w", encoding="utf-8") as f:
            f.write(html)

        return {
            "url": url, "title": title, "status": "ok",
            "frames_candidates": len(pairs),
            "frames_after_dedup": len(survivors),
            "frames_final": len(kept),
            "output": out_html,
            "elapsed_s": round(time.time() - started, 1),
            "degraded": any(r.get("degraded") for r in ranked),
            "est_cost_usd": round(est_cost, 4),
        }
    except Exception as e:
        return {"url": url, "status": "failed", "reason": str(e),
                "elapsed_s": round(time.time() - started, 1)}
    finally:
        if not args.keep_temp:
            shutil.rmtree(work_dir, ignore_errors=True)


def main():
    load_env()
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0],
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("url", help="YouTube video or playlist URL")
    ap.add_argument("--out-dir", default="blogs")
    ap.add_argument("--ranker-model", default="gemini-2.5-flash",
                    help="gemini-2.5-flash (default) or gemini-2.0-flash (cheaper)")
    ap.add_argument("--max-frames-per-video", type=int, default=25)
    ap.add_argument("--batch-size", type=int, default=10)
    ap.add_argument("--scene-threshold", type=float, default=None,
                    help="Override adaptive threshold (e.g. 0.3)")
    ap.add_argument("--workers", type=int, default=2)
    ap.add_argument("--keep-temp", action="store_true")
    ap.add_argument("--force", action="store_true",
                    help="Overwrite existing .html outputs")
    ap.add_argument("--max-cost-usd", type=float, default=1.00,
                    help="Print a warning when estimated total Gemini spend exceeds this "
                         "(soft ceiling; does not auto-stop).")
    ap.add_argument("--no-resume", action="store_true",
                    help="Do not reuse existing /tmp/yt-ribosome-blog-* directories.")
    args = ap.parse_args()

    urls = _list_playlist_urls(args.url)
    print(f"full-blog: {len(urls)} video(s)", flush=True)
    results = []
    spent = 0.0
    with cf.ThreadPoolExecutor(max_workers=max(1, args.workers)) as pool:
        futs = {pool.submit(process_one, u, args): u for u in urls}
        for i, fut in enumerate(cf.as_completed(futs), 1):
            r = fut.result()
            results.append(r)
            spent += r.get("est_cost_usd") or 0
            if spent > args.max_cost_usd:
                print(f"!! Estimated spend ${spent:.2f} exceeded --max-cost-usd "
                      f"${args.max_cost_usd:.2f}. Press Ctrl-C to stop or wait for "
                      f"remaining videos to finish.", flush=True)
            tag = r["status"].upper()
            extra = ""
            if r["status"] == "ok":
                extra = (f"  {r['frames_candidates']} -> {r['frames_after_dedup']} -> "
                         f"{r['frames_final']} frames | {r['elapsed_s']}s"
                         f"{' [DEGRADED]' if r['degraded'] else ''}")
            elif r["status"] == "failed":
                extra = f"  reason: {r['reason'][:200]}"
            elif r["status"] == "skipped":
                extra = f"  {r['reason']}"
            print(f"[{i}/{len(urls)}] {tag} {r.get('title') or r['url']}{extra}", flush=True)

    ok = sum(1 for r in results if r["status"] == "ok")
    failed = sum(1 for r in results if r["status"] == "failed")
    skipped = sum(1 for r in results if r["status"] == "skipped")
    print(f"FULL_BLOG_DONE  ok={ok} failed={failed} skipped={skipped}", flush=True)

    summary_path = os.path.join(args.out_dir, "_run_summary.json")
    os.makedirs(args.out_dir, exist_ok=True)
    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main()
