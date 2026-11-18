#!/usr/bin/env python3
"""Download a stream VOD plus its metadata, captions and chat replay into a work folder.

Examples
  python fetch.py "https://www.youtube.com/watch?v=VIDEO_ID" --workdir ~/clipazo-work/day1
  python fetch.py "https://youtu.be/VIDEO_ID" --workdir W --video-file "D:/Downloads/stream.mp4"
  python fetch.py "D:/OBS/2026-11-19 20-00-00.mkv" --workdir W
  python fetch.py URL --workdir W --section 1:00:00-1:30:00      (only part of a long VOD)

Writes into the work folder
  meta.json            everything later steps need (paths, duration, fps, offset, heatmap...)
  info.json            trimmed yt-dlp metadata
  video.mp4            the video (unless --video-file / local source / --no-video)
  subs.<lang>.json3    YouTube captions with word timings, when available
  chat.live_chat.json  YouTube live chat replay, when available
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import (die, load_json, parse_time, probe, rel_to, run, save_json, say,  # noqa: E402
                    warn, ytdlp_base)

INFO_KEYS = ["id", "title", "description", "channel", "uploader", "upload_date", "duration", "language",
             "was_live", "live_status", "webpage_url", "extractor_key", "width", "height", "fps",
             "heatmap", "chapters", "view_count"]
VIDEO_EXTS = (".mp4", ".mkv", ".webm", ".mov")


def ytdlp_extra_args(args) -> list[str]:
    extra = []
    if args.cookies_from_browser:
        extra += ["--cookies-from-browser", args.cookies_from_browser]
    if args.cookies:
        extra += ["--cookies", args.cookies]
    # Since late 2025 yt-dlp needs a JavaScript runtime for YouTube. It enables Deno by default;
    # if only Node/Bun is installed it has to be told explicitly.
    if not shutil.which("deno"):
        for rt in ("node", "bun"):
            if shutil.which(rt):
                help_text = run(ytdlp_base() + ["--help"], capture=True, check=False, quiet=True).stdout or ""
                if "--js-runtimes" in help_text:
                    extra += ["--js-runtimes", rt]
                break
    return extra


def pick_caption_track(info: dict, want_lang: str | None):
    """Return (track_code, kind, lang). Prefer manual subs, then the original-language auto captions."""
    manual = [l for l in info.get("subtitle_langs", []) if l != "live_chat"]
    auto = info.get("auto_caption_langs", [])
    orig = [l for l in auto if l.endswith("-orig")]
    lang = want_lang or (info.get("language") or "").split("-")[0] or (orig[0][:-5] if orig else None)

    def matches(code):
        return lang and (code == lang or code.startswith(lang + "-"))

    m = [c for c in manual if matches(c)]
    if m:
        return m[0], "manual", lang
    if lang and f"{lang}-orig" in auto:
        return f"{lang}-orig", "auto", lang
    if lang and lang in auto:
        return lang, "auto", lang
    if orig:
        return orig[0], "auto", orig[0][:-5]
    if manual:
        return manual[0], "manual", manual[0].split("-")[0]
    return None, None, lang


def find_one(wd: Path, pattern: str, exts=None):
    hits = [p for p in wd.glob(pattern) if not p.name.endswith((".part", ".ytdl", ".tmp"))
            and (exts is None or p.suffix.lower() in exts)]
    hits.sort(key=lambda p: p.stat().st_size, reverse=True)
    return hits[0] if hits else None


def shift_ranges(items, offset, duration, start_key, end_key):
    out = []
    for it in items or []:
        s = float(it.get(start_key) or 0) - offset
        e = float(it.get(end_key) or s) - offset
        if e <= 0 or s >= duration:
            continue
        d = dict(it)
        d[start_key], d[end_key] = round(max(0.0, s), 3), round(min(duration, e), 3)
        out.append(d)
    return out


def fetch_url(url: str, wd: Path, args) -> dict:
    base = ytdlp_base() + ytdlp_extra_args(args)

    # 1. metadata
    info_path = wd / "info.json"
    info = None if args.force else load_json(info_path)
    if not info:
        say("== Reading video metadata")
        res = run(base + ["-J", "--no-playlist", url], capture=True, check=False)
        if res.returncode != 0:
            print((res.stderr or "")[-3000:], file=sys.stderr)
            die("yt-dlp could not read this link. See references/troubleshooting.md "
                "(private video? bot check -> --cookies-from-browser chrome).")
        full = json.loads(res.stdout)
        info = {k: full.get(k) for k in INFO_KEYS}
        info["subtitle_langs"] = sorted((full.get("subtitles") or {}).keys())
        info["auto_caption_langs"] = sorted((full.get("automatic_captions") or {}).keys())
        save_json(info_path, info)
    say(f"   {info.get('title')!r}  ({info.get('duration')} s, live_status={info.get('live_status')})")
    if info.get("live_status") == "is_live":
        die("This stream is still live. Wait until it ends and YouTube finishes processing the VOD.")
    if info.get("live_status") == "post_live":
        warn("YouTube is still processing this VOD (post_live). Downloads may be incomplete; "
             "captions and full quality usually appear a few hours after the stream ends.")

    offset = 0.0
    section = None
    section_end = float(info.get("duration") or 0) or None
    if args.section:
        a, _, b = args.section.partition("-")
        offset = parse_time(a)
        if b.strip():
            section_end = min(parse_time(b), section_end or float("inf"))
        section = f"*{a}-{b}"

    # 2. captions (separate call so a caption error can't kill the video download)
    subs_file, subs_kind, lang = None, None, args.lang
    if not args.no_subs:
        code, subs_kind, lang = pick_caption_track(info, args.lang)
        subs_file = None if args.force else find_one(wd, "subs.*")
        if code and not subs_file:
            say(f"== Downloading captions ({subs_kind}: {code})")
            cmd = base + ["--skip-download", "--no-playlist", "--sub-langs", code,
                          "--sub-format", "json3/vtt/srt/best", "-o", str(wd / "subs.%(ext)s")]
            cmd += ["--write-subs"] if subs_kind == "manual" else ["--write-auto-subs"]
            run(cmd + [url], check=False)
            subs_file = find_one(wd, "subs.*")
        if not code:
            warn("No captions on YouTube for this video (yet). transcribe.py can use faster-whisper instead.")
        elif not subs_file:
            warn("Caption download failed (often a temporary HTTP 429). Re-run fetch.py later, or use whisper.")

    # 3. live chat replay
    chat_file = None
    if not args.no_chat and "live_chat" in info.get("subtitle_langs", []):
        chat_file = None if args.force else find_one(wd, "chat.live_chat.*")
        if not chat_file:
            say("== Downloading chat replay (long streams take a few minutes)")
            run(base + ["--skip-download", "--no-playlist", "--write-subs", "--sub-langs", "live_chat",
                        "-o", str(wd / "chat.%(ext)s"), url], check=False)
            chat_file = find_one(wd, "chat.live_chat.*")
        if not chat_file:
            warn("Chat replay download failed; continuing without the chat signal.")
    elif not args.no_chat:
        say("   (no chat replay for this video - normal for regular uploads and Twitch)")

    def build_meta(video):
        meta = {
            "source": url,
            "id": info.get("id"),
            "title": info.get("title"),
            "channel": info.get("channel") or info.get("uploader"),
            "upload_date": info.get("upload_date"),
            "was_live": info.get("was_live"),
            "language": lang,
            "offset": offset,
            "source_duration": info.get("duration"),
        }
        if video:
            meta.update(probe(video))
            meta["video"] = rel_to(wd, video)
        else:
            meta["video"] = None
            meta["duration"] = max(0.0, (section_end or 0) - offset)
        dur = float(meta["duration"])
        meta["subs"] = rel_to(wd, subs_file) if subs_file else None
        meta["subs_kind"] = subs_kind if subs_file else None
        meta["chat"] = rel_to(wd, chat_file) if chat_file else None
        meta["heatmap"] = shift_ranges(info.get("heatmap"), offset, dur, "start_time", "end_time")
        meta["chapters"] = shift_ranges(info.get("chapters"), offset, dur, "start_time", "end_time")
        return meta

    # 4. video
    video = None
    if not args.no_video and not args.video_file and not find_one(wd, "video.*", VIDEO_EXTS):
        # Write meta.json now so transcribe.py / analyze.py can start on captions + chat
        # while the (long) video download runs. Re-run analyze.py afterwards to add the audio signal.
        save_json(wd / "meta.json", build_meta(None))
        say("   meta.json written (no video yet) - transcribe.py and analyze.py can already run.")
    if args.video_file:
        video = Path(args.video_file).expanduser().resolve()
        if not video.exists():
            die(f"--video-file not found: {video}")
        if args.section:
            die("--section can't be combined with --video-file (the local file can't be cut remotely).")
    elif not args.no_video:
        video = None if args.force else find_one(wd, "video.*", VIDEO_EXTS)
        if not video:
            say(f"== Downloading video (max {args.max_height}p)")
            cmd = base + ["--no-playlist", "-f", "bv*+ba/b", "-S", f"res:{args.max_height},fps",
                          "--merge-output-format", "mp4", "-N", "4", "-o", str(wd / "video.%(ext)s")]
            if section:
                cmd += ["--download-sections", section]
            run(cmd + [url])
            video = find_one(wd, "video.*", VIDEO_EXTS)
            if not video:
                die("yt-dlp finished but no video file was found in the work folder.")

    return build_meta(video)


def fetch_local(path: Path, wd: Path, args) -> dict:
    path = path.expanduser().resolve()
    meta = {"source": str(path), "id": None, "title": path.stem, "channel": None, "upload_date": None,
            "was_live": None, "language": args.lang, "offset": 0.0, "source_duration": None,
            "video": rel_to(wd, path), "subs": None, "subs_kind": None, "chat": None,
            "heatmap": [], "chapters": []}
    meta.update(probe(path))
    if args.subs:
        meta["subs"] = str(Path(args.subs).expanduser().resolve())
        meta["subs_kind"] = "manual"
    if args.chat:
        meta["chat"] = str(Path(args.chat).expanduser().resolve())
    return meta


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("source", help="YouTube/Twitch/any yt-dlp URL, or a local video file")
    ap.add_argument("--workdir", required=True, help="folder for this video's files")
    ap.add_argument("--video-file", help="use this already-downloaded file instead of downloading the video")
    ap.add_argument("--max-height", type=int, default=1080, help="max video height to download (default 1080)")
    ap.add_argument("--lang", help="spoken language code (es, en, pt...). Default: auto-detect")
    ap.add_argument("--section", help="only download START-END of the video, e.g. 1:00:00-1:30:00")
    ap.add_argument("--no-chat", action="store_true", help="skip the chat replay")
    ap.add_argument("--no-subs", action="store_true", help="skip captions")
    ap.add_argument("--no-video", action="store_true", help="metadata, captions and chat only")
    ap.add_argument("--subs", help="(local files) a .srt/.vtt/.json3 captions file to use")
    ap.add_argument("--chat", help="(local files) a YouTube live_chat.json file to use")
    ap.add_argument("--cookies-from-browser", help="e.g. chrome, firefox, edge - for bot checks / members-only")
    ap.add_argument("--cookies", help="cookies.txt file (Netscape format)")
    ap.add_argument("--force", action="store_true", help="re-download even if files already exist")
    args = ap.parse_args()

    wd = Path(args.workdir).expanduser().resolve()
    wd.mkdir(parents=True, exist_ok=True)
    local = Path(args.source).expanduser()
    meta = fetch_local(local, wd, args) if local.exists() else fetch_url(args.source, wd, args)
    save_json(wd / "meta.json", meta)

    say("")
    say(f"Work folder : {wd}")
    say(f"Video       : {meta.get('video') or '(none)'}  "
        f"{meta.get('width', '?')}x{meta.get('height', '?')} @ {meta.get('fps', '?')} fps, "
        f"{meta.get('duration', 0):.0f} s" + (f", starts at {meta['offset']:.0f} s of the VOD" if meta["offset"] else ""))
    say(f"Captions    : {meta.get('subs') or 'none'}")
    say(f"Chat replay : {meta.get('chat') or 'none'}")
    say(f"Heatmap     : {'yes' if meta.get('heatmap') else 'no'} (YouTube 'most replayed')")
    say("Next: python transcribe.py --workdir " + f'"{wd}"')


if __name__ == "__main__":
    main()
