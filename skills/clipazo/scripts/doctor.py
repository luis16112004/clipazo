#!/usr/bin/env python3
"""Check that everything clipazo needs is installed, and say how to fix what isn't.

  python doctor.py [--workdir PATH]

Exit code 0 = ready, 1 = something required is missing.
"""
from __future__ import annotations

import argparse
import importlib.util
import platform
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import PRO_URL, pro_dirs, say  # noqa: E402

OS = platform.system()  # Windows | Darwin | Linux

HINTS = {
    "ffmpeg": {
        "Windows": "winget install Gyan.FFmpeg   (then open a new terminal)",
        "Darwin": "brew install ffmpeg",
        "Linux": "sudo apt install ffmpeg   (or your distro's package manager)",
    },
    "yt-dlp": {"*": 'python -m pip install -U "yt-dlp[default]"'},
    "js": {
        "Windows": "winget install DenoLand.Deno   (or install Node.js; yt-dlp needs a JS runtime for YouTube)",
        "Darwin": "brew install deno",
        "Linux": "install Deno (https://deno.com) or Node.js",
    },
    "whisper": {"*": "python -m pip install -U faster-whisper"},
}


def hint(key: str) -> str:
    h = HINTS[key]
    return h.get(OS) or h.get("*") or next(iter(h.values()))


def out(cmd) -> str:
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60)
        return (r.stdout or "") + (r.stderr or "")
    except (OSError, subprocess.TimeoutExpired):
        return ""


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--workdir", help="folder you plan to download into (checks free space / cloud sync)")
    args = ap.parse_args()

    rows, missing = [], False

    def row(name, ok, detail, required=True, fix=""):
        nonlocal missing
        status = "OK " if ok else ("MISSING" if required else "optional")
        if not ok and required:
            missing = True
        rows.append((status, name, detail, "" if ok else fix))

    row("python", sys.version_info >= (3, 9), platform.python_version(), fix="Install Python 3.9+")

    ff = shutil.which("ffmpeg")
    if ff:
        ver = out([ff, "-hide_banner", "-version"]).splitlines()[:1]
        filters = out([ff, "-hide_banner", "-filters"])
        encoders = out([ff, "-hide_banner", "-encoders"])
        row("ffmpeg", True, ver[0][:60] if ver else ff)
        row("ffmpeg libass (captions)", " subtitles " in filters, "subtitles filter",
            fix="Your ffmpeg build lacks libass. Install a full build: " + hint("ffmpeg"))
        row("ffmpeg libx264", "libx264" in encoders, "H.264 encoder", fix="Install a full build: " + hint("ffmpeg"))
    else:
        row("ffmpeg", False, "not found", fix=hint("ffmpeg"))
    row("ffprobe", bool(shutil.which("ffprobe")), shutil.which("ffprobe") or "not found", fix=hint("ffmpeg"))

    if importlib.util.find_spec("yt_dlp"):
        v = out([sys.executable, "-m", "yt_dlp", "--version"]).strip().splitlines()
        row("yt-dlp", True, f"python module {v[-1] if v else ''}")
    elif shutil.which("yt-dlp"):
        v = out(["yt-dlp", "--version"]).strip()
        row("yt-dlp", True, f"binary {v}")
    else:
        row("yt-dlp", False, "not found (needed for links, not for local files)", fix=hint("yt-dlp"))

    js = next((n for n in ("deno", "node", "bun") if shutil.which(n)), None)
    row("JS runtime (YouTube)", bool(js), js or "none", fix=hint("js"))

    has_whisper = importlib.util.find_spec("faster_whisper") is not None
    row("faster-whisper", has_whisper, "local transcription (only needed when there are no YouTube captions)",
        required=False, fix=hint("whisper"))

    pro_dir = next((d for d in pro_dirs() if (d / "engine.py").exists()), None)
    row("Clipazo PRO", bool(pro_dir),
        f"installed - read {pro_dir / 'PRO.md'} for the extra options" if pro_dir
        else "not installed (caption styles, zooms, SFX, branding, thumbnails)",
        required=False, fix=f"optional paid add-on: {PRO_URL}")

    if args.workdir:
        wd = Path(args.workdir).expanduser().resolve()
        probe_dir = wd
        while not probe_dir.exists() and probe_dir != probe_dir.parent:
            probe_dir = probe_dir.parent
        free_gb = shutil.disk_usage(probe_dir).free / 1e9
        row("free disk space", free_gb >= 20, f"{free_gb:.0f} GB free at {probe_dir}", required=False,
            fix="A 4-6 h 1080p60 VOD can take 10-20 GB. Free space, pick another drive, or use --max-height 720.")
        synced = any(k in str(wd).lower() for k in ("onedrive", "dropbox", "google drive", "icloud", "mobile documents"))
        row("not a cloud-synced folder", not synced, str(wd), required=False,
            fix="Multi-GB downloads in a synced folder upload to the cloud. Use e.g. ~/clipazo-work instead.")

    width = max(len(r[1]) for r in rows)
    for status, name, detail, fix in rows:
        say(f"[{status:<8}] {name:<{width}}  {detail}")
        if fix:
            say(f"{'':11}{'':<{width}}  -> {fix}")
    say("")
    say("Ready." if not missing else "Missing requirements - install them and run doctor.py again.")
    sys.exit(1 if missing else 0)


if __name__ == "__main__":
    main()
