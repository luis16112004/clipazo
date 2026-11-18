#!/usr/bin/env python3
"""Grab frames so you can SEE a moment (the transcript can't tell you what's on screen).

  python frames.py --workdir W --candidates 1,4,7         # one contact sheet per candidate
  python frames.py --workdir W --at 1:23:45 --span 30     # sheet of 8 frames centered on a time
  python frames.py --workdir W --full 1:23:45 --grid      # one full frame + 10% grid (find the facecam box)
  python frames.py --video clips/01-x-vertical.mp4 --full 3   # check a rendered clip

Prints the path of each image and which time each tile shows (tiles are numbered left->right, top->bottom).
"""
from __future__ import annotations

import argparse
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import (die, fmt_time, load_json, load_meta, parse_time, probe, require_bin, run,  # noqa: E402
                    say, video_path)


def grab(ffmpeg, video, t, out, vf=None):
    cmd = [ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-ss", f"{max(0.0, t):.3f}", "-i", str(video),
           "-frames:v", "1", "-q:v", "3"]
    if vf:
        cmd += ["-vf", vf]
    run(cmd + [str(out)], quiet=True)


def sheet(ffmpeg, video, start, end, out, count=8, cols=4, width=400):
    span = max(0.5, end - start)
    times = [start + (k + 0.5) * span / count for k in range(count)]
    rows = (count + cols - 1) // cols
    tmp = Path(tempfile.mkdtemp(prefix="sc-frames-"))
    try:
        for k, t in enumerate(times):
            grab(ffmpeg, video, t, tmp / f"f{k:03d}.jpg", f"scale={width}:-2")
        run([ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-framerate", "1", "-i", str(tmp / "f%03d.jpg"),
             "-vf", f"tile={cols}x{rows}:padding=4:color=white", "-frames:v", "1", "-q:v", "3", str(out)], quiet=True)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    say(f"{out}")
    say("   tiles: " + "  ".join(f"{k + 1}={fmt_time(t)}" for k, t in enumerate(times)))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--workdir")
    ap.add_argument("--video", help="any video file (default: the work folder's video)")
    ap.add_argument("--candidates", help="comma-separated candidate ranks from candidates.json")
    ap.add_argument("--at", help="center time for a contact sheet")
    ap.add_argument("--span", type=float, default=30, help="seconds covered by an --at sheet")
    ap.add_argument("--full", help="time of a single full-resolution frame")
    ap.add_argument("--grid", action="store_true", help="draw a grid every 10%% on --full frames")
    ap.add_argument("--count", type=int, default=8)
    ap.add_argument("--cols", type=int, default=4)
    ap.add_argument("--width", type=int, default=400, help="tile width in px")
    ap.add_argument("--out", help="output image path")
    args = ap.parse_args()

    ffmpeg = require_bin("ffmpeg")
    wd = Path(args.workdir).expanduser().resolve() if args.workdir else None
    if args.video:
        video = Path(args.video).expanduser()
        if not video.is_absolute() and wd and (wd / video).exists():
            video = wd / video
    elif wd:
        video = video_path(wd, load_meta(wd))
    else:
        die("give --workdir or --video")
    outdir = (wd or Path(video).parent) / "frames"
    outdir.mkdir(parents=True, exist_ok=True)

    if args.full is not None:
        t = parse_time(args.full)
        out = Path(args.out) if args.out else outdir / f"full-{int(t)}.jpg"
        vf = "drawgrid=w=iw/10:h=ih/10:t=2:c=red@0.8," if args.grid else ""
        info = probe(video)
        vf += "scale='min(1280,iw)':-2"
        grab(ffmpeg, video, t, out, vf)
        say(f"{out}")
        say(f"   source frame {info['width']}x{info['height']}" + (" - red lines every 10% of width/height" if args.grid else ""))
        return

    if args.candidates:
        cands = {c["rank"]: c for c in load_json(wd / "candidates.json", [])} if wd else {}
        if not cands:
            die("no candidates.json - run analyze.py first")
        ranks = sorted(cands) if args.candidates == "all" else [int(x) for x in args.candidates.split(",") if x.strip()]
        for r in ranks:
            c = cands.get(r)
            if not c:
                say(f"(no candidate #{r})")
                continue
            sheet(ffmpeg, video, c["start"], c["end"], outdir / f"cand-{r:02d}.jpg", args.count, args.cols, args.width)
        return

    if args.at:
        c = parse_time(args.at)
        out = Path(args.out) if args.out else outdir / f"sheet-{int(c)}.jpg"
        sheet(ffmpeg, video, c - args.span / 2, c + args.span / 2, out, args.count, args.cols, args.width)
        return

    ap.error("give --candidates, --at or --full")


if __name__ == "__main__":
    main()
