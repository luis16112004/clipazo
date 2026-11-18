#!/usr/bin/env python3
"""Render the clips described in clips.json: vertical 9:16 (Shorts/Reels/TikTok) and/or horizontal 16:9,
with burned-in word-by-word captions, a hook title, loudness normalization, covers and posts.md.

  python render.py --workdir W                     # everything in W/clips.json
  python render.py --workdir W --only 2,5          # re-render some clips
  python render.py --workdir W --fast              # quick low-quality drafts for checking
  python render.py --workdir W --compilation       # also a horizontal best-of video with chapters

Plan format: references/clip-plan.md. Output goes to W/clips/.
If the Clipazo PRO add-on is installed, its extra options in clips.json are applied automatically.
"""
from __future__ import annotations

import argparse
import copy
import datetime as dt
import importlib.util
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from captions import DEFAULT_FONT, ass_escape, karaoke_events, style_line, write_ass  # noqa: E402
from common import (PRO_URL, die, fmt_time, load_json, load_meta, load_pro, load_words, parse_time,  # noqa: E402
                    probe, require_bin, run, say, slugify, video_path, warn)

PRO = load_pro()

BUILTIN = {
    "layout": "blur",              # blur | crop | facecam
    "formats": ["vertical"],       # vertical and/or horizontal
    "captions": True,
    "hook": None,
    "zoom": 1.2,                   # blur layout: >1 zooms the gameplay (crops the sides)
    "crop_x": 0.5,                 # crop layout: horizontal center of the crop (0 = left, 1 = right)
    "game_x": 0.5,                 # facecam layout: horizontal center of the gameplay crop
    "facecam": None,               # {"x","y","w","h"} as fractions of the source frame
    "cam_height": "auto",          # facecam layout: share of the 1920 px height for the camera (or "auto")
    "caption": {"style": "karaoke", "font": DEFAULT_FONT, "size": 86, "color": "FFFFFF", "highlight": "FFE81F",
                "outline": 8, "y": 0.73, "uppercase": True, "max_words": 3, "max_chars": 16},
    "hook_style": {"font": DEFAULT_FONT, "size": 74, "color": "FFFFFF", "outline": 8, "y": 0.12,
                   "uppercase": True, "duration": None},
    "horizontal": {"captions": True, "hook": False, "caption_size": 58, "caption_y": 0.86},
}
VERT = (1080, 1920)
HORZ = (1920, 1080)
PRO_KEYS = ("punch_ins", "progress_bar", "brand", "sfx", "thumbnail", "end_card")


def deep_merge(base: dict, over: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in (over or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def even(x) -> int:
    return max(2, int(round(float(x) / 2)) * 2)


def feven(x) -> int:
    """Round DOWN to even - for crop sizes, which must never exceed the source."""
    return max(2, int(float(x)) // 2 * 2)


def pro_features_used(cfg) -> list[str]:
    used = [k for k in PRO_KEYS if cfg.get(k)]
    if (cfg.get("caption") or {}).get("style", "karaoke") != "karaoke":
        used.append(f"caption style '{cfg['caption']['style']}'")
    return used


# ---------------------------------------------------------------- video layouts (numbers computed here,
# so the filtergraph never needs escaped expressions)

def g_blur(W, H, sw, sh, zoom):
    fg_w = even(W * max(1.0, zoom))
    fg_h = even(fg_w * sh / sw)
    if fg_h > H:
        fg_h, fg_w = H, even(H * sw / sh)
    cw = min(fg_w, W)
    bw, bh = W // 4, H // 4
    return (f"[0:v]split=2[bgs][fgs];"
            f"[bgs]scale={bw}:{bh}:force_original_aspect_ratio=increase,crop={bw}:{bh},boxblur=10:2,"
            f"scale={W}:{H},eq=brightness=-0.07[bg];"
            f"[fgs]scale={fg_w}:{fg_h},crop={cw}:{fg_h}[fg];"
            f"[bg][fg]overlay=(W-w)/2:(H-h)/2[base]")


def g_crop(W, H, sw, sh, cx):
    sc_h, sc_w = H, even(sw * H / sh)
    if sc_w < W:
        sc_w, sc_h = W, max(H, even(sh * W / sw))
    x = int((sc_w - W) * min(1.0, max(0.0, cx)))
    y = int((sc_h - H) / 2)
    return f"[0:v]scale={sc_w}:{sc_h},crop={W}:{H}:{x}:{y}[base]"


def g_facecam(W, H, sw, sh, cam, cam_ratio, gx):
    fx = min(max(float(cam["x"]), 0.0), 0.98)
    fy = min(max(float(cam["y"]), 0.0), 0.98)
    px, py = int(fx * sw), int(fy * sh)
    pw = feven(min(float(cam["w"]) * sw, sw - px))
    ph = feven(min(float(cam["h"]) * sh, sh - py))
    if cam_ratio in (None, "auto"):
        # size the camera band to the box's shape so the face isn't over-cropped (16:9 cam -> ~32 %,
        # square avatar -> 45 % cap); the gameplay keeps at least 55 % of the height
        cam_ratio = min(0.45, max(0.25, (W * ph / pw) / H))
    cam_h = even(H * float(cam_ratio))
    game_h = H - cam_h
    aspect = W / game_h
    if sw / sh > aspect:
        cw, ch = feven(sh * aspect), feven(sh)
    else:
        cw, ch = feven(sw), feven(sw / aspect)
    gxp = int((sw - cw) * min(1.0, max(0.0, gx)))
    gyp = int((sh - ch) / 2)
    return (f"[0:v]split=2[cs][gs];"
            f"[cs]crop={pw}:{ph}:{px}:{py},scale={W}:{cam_h}:force_original_aspect_ratio=increase,"
            f"crop={W}:{cam_h}[cam];"
            f"[gs]crop={cw}:{ch}:{gxp}:{gyp},scale={W}:{game_h}[game];"
            f"[cam][game]vstack=inputs=2[base]"), cam_h


def g_horizontal(W, H):
    return (f"[0:v]scale={W}:{H}:force_original_aspect_ratio=decrease,"
            f"pad={W}:{H}:(ow-iw)/2:(oh-ih)/2:color=black[base]")


# ---------------------------------------------------------------- words for a clip

_whisper_ok = importlib.util.find_spec("faster_whisper") is not None


def clip_words(wd, meta, all_words, start, end, force_whisper, model):
    if not force_whisper and all_words:
        return [{"s": w["s"] - start, "e": w["e"] - start, "w": w["w"]}
                for w in all_words if w["e"] > start and w["s"] < end]
    if _whisper_ok:
        from transcribe import whisper_words
        say("   transcribing this clip with faster-whisper...")
        ws = whisper_words(video_path(wd, meta), meta.get("language"), model, start, end, progress=False)
        return [{"s": w["s"] - start, "e": w["e"] - start, "w": w["w"]} for w in ws]
    return None  # no transcript and no whisper


# ---------------------------------------------------------------- render one output

def layout_frame(ffmpeg, src, info, t, fmt, cfg, out_path):
    """One clean frame (layout only: no captions/overlays) at source time t - used for thumbnails."""
    graph = layout_graph(info, fmt, cfg)[0]
    run([ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-ss", f"{max(0.0, t):.3f}", "-i", str(src),
         "-filter_complex", graph + ";[base]setsar=1[v]", "-map", "[v]", "-frames:v", "1", "-q:v", "2",
         str(out_path)], quiet=True)
    return out_path


def layout_graph(info, fmt, cfg):
    """-> (graph ending in [base], W, H, hook_anchor, layout)"""
    sw, sh = info["width"], info["height"]
    if fmt == "vertical":
        W, H = VERT
        layout = cfg["layout"]
        hook_anchor = (8, int(H * cfg["hook_style"]["y"]))
        if layout == "facecam":
            if not cfg.get("facecam"):
                die("layout 'facecam' needs a facecam box: {\"x\":..,\"y\":..,\"w\":..,\"h\":..} (fractions)")
            graph, cam_h = g_facecam(W, H, sw, sh, cfg["facecam"], cfg["cam_height"], cfg["game_x"])
            hook_anchor = (5, cam_h)  # title sits on the seam between camera and gameplay
        elif layout == "crop":
            graph = g_crop(W, H, sw, sh, cfg["crop_x"])
        elif layout == "blur":
            graph = g_blur(W, H, sw, sh, cfg["zoom"])
        else:
            die(f"unknown layout {layout!r} (use blur, crop or facecam)")
        return graph, W, H, hook_anchor, layout
    W, H = HORZ
    return g_horizontal(W, H), W, H, (8, int(H * 0.06)), "horizontal"


def render_one(ffmpeg, src, info, start, dur, fmt, cfg, words, out_path, preset, crf, hook_text,
               wd=None, use_pro=True):
    fps = info["fps"]
    graph, W, H, hook_anchor, layout = layout_graph(info, fmt, cfg)
    if fmt == "vertical":
        cap_size, cap_y = cfg["caption"]["size"], cfg["caption"]["y"]
        use_caps, use_hook = cfg["captions"], bool(hook_text)
    else:
        hz = cfg["horizontal"]
        cap_size, cap_y = hz["caption_size"], hz["caption_y"]
        use_caps, use_hook = cfg["captions"] and hz["captions"], bool(hook_text) and hz["hook"]

    tmp = Path(tempfile.mkdtemp(prefix="clipazo-"))
    try:
        cap = {**cfg["caption"], "size": cap_size}
        # --- Clipazo PRO hooks (caption styles, punch-ins, SFX, progress bar, branding...)
        pro = {}
        if PRO and use_pro:
            pro = PRO.prepare({"W": W, "H": H, "dur": dur, "fps": fps, "fmt": fmt, "layout": layout, "cfg": cfg,
                               "cap": cap, "cap_y": cap_y, "words": words if use_caps else [], "start": start,
                               "hook_anchor": hook_anchor, "tmp": tmp, "workdir": wd, "first_input": 1,
                               "has_audio": info["has_audio"]}) or {}
        if pro.get("video"):
            graph += ";" + pro["video"]          # reads [base], writes [pbase]
            vlabel = "[pbase]"
        else:
            vlabel = "[base]"

        styles = [style_line("Cap", cap["font"], cap_size, cap["color"], cap["outline"], 5),
                  style_line("Hook", cfg["hook_style"]["font"], cfg["hook_style"]["size"], cfg["hook_style"]["color"],
                             cfg["hook_style"]["outline"], 8)]
        events = []
        if use_caps and words:
            if pro.get("caption_events"):
                ev, extra_styles = pro["caption_events"](words, dur, cap, W, H, cap_y)
                events += ev
                styles += extra_styles
            else:
                events += karaoke_events(words, dur, cap, W, H, cap_y)
        n_caps = len(events)
        if use_hook:
            hs = cfg["hook_style"]
            txt = ass_escape(hook_text)
            txt = txt.upper() if hs.get("uppercase") else txt
            an, hy = hook_anchor
            hook_end = min(dur, float(hs.get("duration") or dur), float(pro.get("hook_until") or dur))
            events.append((0.0, hook_end, "Hook",
                           f"{{\\an{an}\\pos({W // 2},{hy})\\fad(150,0)}}{txt}"))
        events += pro.get("ass_events", [])
        styles += pro.get("ass_styles", [])

        post = []
        if fps > 60.5:
            post.append("fps=60")
        if events:
            write_ass(tmp / "sub.ass", W, H, styles, events)
            post.append("subtitles=sub.ass")
        post += ["setsar=1", "format=yuv420p"]
        graph += f";{vlabel}{','.join(post)}[v]"
        maps = ["-map", "[v]"]
        if info["has_audio"]:
            fade_out = max(0.0, dur - 0.25)
            graph += (f";[0:a:0]loudnorm=I=-14:TP=-1.5:LRA=11,aresample=48000,"
                      f"afade=t=in:d=0.12,afade=t=out:st={fade_out:.3f}:d=0.25[a0]")
            alabel = "[a0]"
            if pro.get("audio"):
                graph += ";" + pro["audio"]      # reads [a0], writes [a1]
                alabel = "[a1]"
            maps += ["-map", alabel, "-c:a", "aac", "-b:a", "192k", "-ar", "48000"]
        gop = int(round(min(fps, 60) * 2))
        cmd = [ffmpeg, "-hide_banner", "-loglevel", "error", "-stats", "-y",
               "-ss", f"{start:.3f}", "-t", f"{dur:.3f}", "-i", str(src), *pro.get("inputs", []),
               "-filter_complex", graph, *maps, "-t", f"{dur:.3f}",
               "-c:v", "libx264", "-preset", preset, "-crf", str(crf), "-profile:v", "high", "-g", str(gop),
               "-movflags", "+faststart", str(out_path.resolve())]
        run(cmd, cwd=tmp, quiet=True)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return n_caps


# ---------------------------------------------------------------- posts.md

def post_block(c, files, dur, meta):
    yt, ig = c.get("youtube") or {}, c.get("instagram") or {}
    off = float(meta.get("offset") or 0)
    out = [f"## {c['_num']:02d} - {c.get('hook') or c['_slug']}  ({fmt_time(dur)})", "",
           f"Files: {', '.join(f'`{f}`' for f in files)}",
           f"Source: {fmt_time(c['_start'] + off)} -> {fmt_time(c['_end'] + off)} of the VOD"]
    if meta.get("id") and "youtu" in str(meta.get("source", "")):
        out.append(f"Moment in the full stream: https://youtu.be/{meta['id']}?t={int(c['_start'] + off)}")
    if c.get("notes"):
        out.append(f"Notes: {c['notes']}")
    if yt:
        out += ["", "### YouTube Shorts", f"**Title:** {yt.get('title', '')}", "", "**Description:**", "",
                yt.get("description", "")]
        if yt.get("tags"):
            out += ["", f"**Tags:** {', '.join(yt['tags'])}"]
    if ig:
        tags = " ".join(h if h.startswith("#") else f"#{h}" for h in ig.get("hashtags", []))
        out += ["", "### Instagram Reels", "**Caption:**", "", ig.get("caption", "") + (f"\n\n{tags}" if tags else "")]
    if c.get("tiktok"):
        out += ["", "### TikTok", c["tiktok"].get("caption", "")]
    for extra in c.get("_pro_post", []):
        out += ["", extra]
    return out + ["", "---", ""]


# ---------------------------------------------------------------- main

def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--workdir", required=True)
    ap.add_argument("--plan", help="plan file (default W/clips.json)")
    ap.add_argument("--only", help="comma-separated clip ids/numbers to render")
    ap.add_argument("--fast", action="store_true", help="quick drafts (ultrafast, lower quality)")
    ap.add_argument("--compilation", action="store_true", help="also build a horizontal best-of with chapters")
    ap.add_argument("--whisper-captions", action="store_true",
                    help="transcribe each clip with faster-whisper for the captions (more accurate)")
    ap.add_argument("--model", default="small", help="faster-whisper model for --whisper-captions")
    ap.add_argument("--out", help="output folder (default W/clips)")
    args = ap.parse_args()

    ffmpeg = require_bin("ffmpeg")
    wd = Path(args.workdir).expanduser().resolve()
    meta = load_meta(wd)
    src = video_path(wd, meta)
    info = probe(src)
    plan_path = Path(args.plan).expanduser() if args.plan else wd / "clips.json"
    plan = load_json(plan_path)
    if not plan or not plan.get("clips"):
        die(f"No clips in {plan_path}. Write the plan first (see references/clip-plan.md).")
    defaults = deep_merge(BUILTIN, plan.get("defaults") or {})
    out_dir = Path(args.out).expanduser().resolve() if args.out else wd / "clips"
    out_dir.mkdir(parents=True, exist_ok=True)
    preset, crf = ("ultrafast", 28) if args.fast else ("fast", 20)
    all_words = load_words(wd)
    if not all_words and not _whisper_ok:
        warn("No transcript.json and faster-whisper isn't installed: clips will have no captions.")
    say(f"Clipazo PRO: {'active' if PRO else 'not installed'}")

    only = {s.strip() for s in args.only.split(",")} if args.only else None
    clips = []
    for idx, c in enumerate(plan["clips"], 1):
        c = dict(c)
        c["_num"] = int(c["id"]) if str(c.get("id", "")).isdigit() else idx
        c["_slug"] = slugify(c.get("slug") or c.get("hook") or f"clip-{idx}")
        c["_start"], c["_end"] = parse_time(c["start"]), parse_time(c["end"])
        if c["_end"] <= c["_start"]:
            die(f"clip {c['_num']}: end must be after start")
        if c["_end"] > info["duration"] + 0.5:
            die(f"clip {c['_num']}: ends at {fmt_time(c['_end'])} but the video is {fmt_time(info['duration'])}")
        clips.append(c)

    summary, post_lines, missing_pro = [], [], set()
    title = meta.get("title") or wd.name
    post_lines += [f"# Clips - {title}", "", f"Source: {meta.get('source')}  |  rendered "
                   f"{dt.datetime.now():%Y-%m-%d %H:%M}", "", "---", ""]
    for c in clips:
        dur = c["_end"] - c["_start"]
        cfg = deep_merge(defaults, {k: v for k, v in c.items() if not k.startswith("_")})
        if not PRO:
            missing_pro.update(pro_features_used(cfg))
        base = f"{c['_num']:02d}-{c['_slug']}"
        files = []
        selected = only is None or str(c.get("id")) in only or str(c["_num"]) in only
        if dur > 180:
            warn(f"clip {c['_num']} is {dur:.0f} s - Shorts and Reels cap at 3 minutes.")
        if selected:
            say(f"== Clip {c['_num']:02d} {c['_slug']}  {fmt_time(c['_start'], 1)} -> {fmt_time(c['_end'], 1)} "
                f"({dur:.1f} s, {cfg['layout']})")
            words = clip_words(wd, meta, all_words, c["_start"], c["_end"], args.whisper_captions, args.model) \
                if cfg["captions"] else []
            if cfg["captions"] and words is None:
                warn("no transcript for this clip (run transcribe.py or install faster-whisper) - no captions")
                words = []
        for fmt in cfg["formats"]:
            out = out_dir / f"{base}-{fmt}.mp4"
            files.append(out.name)
            if selected:
                n = render_one(ffmpeg, src, info, c["_start"], dur, fmt, cfg, words, out, preset, crf,
                               cfg.get("hook"), wd=wd)
                say(f"   -> {out.name}  ({n} caption events)")
        cover = out_dir / f"{base}-cover.jpg"
        if selected and files:
            first = out_dir / files[0]
            cover_t = parse_time(c["cover_at"]) - c["_start"] if c.get("cover_at") else dur * 0.4
            cover_t = max(0.0, min(dur - 0.1, cover_t))
            run([ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-ss", f"{cover_t:.3f}",
                 "-i", str(first), "-frames:v", "1", "-q:v", "2", str(cover)], quiet=True)
            if PRO and hasattr(PRO, "after_clip"):
                clean = {fmt: (lambda f=fmt: layout_frame(ffmpeg, src, info, c["_start"] + cover_t, f, cfg,
                                                          out_dir / f".{base}-{f}-clean.jpg"))
                         for fmt in cfg["formats"]}  # lazily rendered clean frames for thumbnails
                c["_pro_files"] = PRO.after_clip({"cfg": cfg, "clip": c, "out_dir": out_dir, "base": base,
                                                  "files": [out_dir / f for f in files], "cover": cover,
                                                  "clean_frame": clean, "cover_t": cover_t, "dur": dur,
                                                  "ffmpeg": ffmpeg}) or []
                for f in out_dir.glob(f".{base}-*-clean.jpg"):
                    f.unlink(missing_ok=True)
        files.append(cover.name)
        files += [Path(p).name for p in c.get("_pro_files", [])]
        post_lines += post_block(c, files, dur, meta)
        summary.append((c["_num"], c["_slug"], dur, files))

    if args.compilation:
        build_compilation(ffmpeg, src, info, clips, defaults, plan, out_dir, preset, crf, all_words, wd, meta,
                          args, post_lines)

    (out_dir / "posts.md").write_text("\n".join(post_lines), encoding="utf-8")
    say("")
    for num, slug, dur, files in summary:
        say(f"  {num:02d} {slug:<32} {dur:5.1f} s  {', '.join(files)}")
    say(f"\nOutput: {out_dir}\nCopy for each post: {out_dir / 'posts.md'}")
    if missing_pro:
        say(f"\n* These options need Clipazo PRO and were skipped: {', '.join(sorted(missing_pro))}.\n"
            f"  Get PRO: {PRO_URL}")


def build_compilation(ffmpeg, src, info, clips, defaults, plan, out_dir, preset, crf, all_words, wd, meta,
                      args, post_lines):
    comp = plan.get("compilation") or {}
    order = sorted(clips, key=lambda c: c["_start"]) if comp.get("order", "chronological") == "chronological" else clips
    parts_dir = out_dir / "_parts"
    parts_dir.mkdir(exist_ok=True)
    cfg = deep_merge(defaults, {"captions": bool(comp.get("captions", False)), "horizontal": {"hook": False}})
    say("== Compilation")
    names, chapters, t = [], [], 0.0
    for c in order:
        dur = c["_end"] - c["_start"]
        part = parts_dir / f"part-{c['_num']:02d}.mp4"
        words = clip_words(wd, meta, all_words, c["_start"], c["_end"], False, args.model) if cfg["captions"] else []
        render_one(ffmpeg, src, info, c["_start"], dur, "horizontal", cfg, words or [], part, preset, crf, None,
                   wd=wd, use_pro=False)
        real = probe(part)["duration"]
        chapters.append(f"{fmt_time(t)} {(c.get('youtube') or {}).get('title') or c.get('hook') or c['_slug']}")
        names.append(part.name)
        t += real
    (parts_dir / "list.txt").write_text("".join(f"file '{n}'\n" for n in names), encoding="utf-8")
    out = out_dir / f"{slugify(comp.get('slug') or 'compilation')}.mp4"
    run([ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-f", "concat", "-safe", "0", "-i", "list.txt",
         "-c", "copy", "-movflags", "+faststart", str(out.resolve())], cwd=parts_dir, quiet=True)
    shutil.rmtree(parts_dir, ignore_errors=True)
    say(f"   -> {out.name} ({fmt_time(t)})")
    post_lines += ["## Compilation (YouTube, horizontal)", "", f"File: `{out.name}`  ({fmt_time(t)})", "",
                   f"**Title:** {comp.get('title', '')}", "", "**Description:**", "", comp.get("description", ""), "",
                   "Chapters (paste into the description; YouTube needs the first at 0:00):", "", *chapters, "", "---", ""]


if __name__ == "__main__":
    main()
