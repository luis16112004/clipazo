"""Shared helpers for the clipazo scripts. Standard library only."""
from __future__ import annotations

import importlib.util
import json
import math
import os
import re
import shutil
import subprocess
import sys
import unicodedata
from pathlib import Path

# Windows consoles default to a legacy code page; stream text (Spanish, emoji) must not crash prints.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

SCRIPTS_DIR = Path(__file__).resolve().parent
SKILL_DIR = SCRIPTS_DIR.parent

# Where people get the paid add-on. Set to the real link when publishing.
PRO_URL = "https://github.com/luis16112004/clipazo#-clipazo-pro"


def pro_dirs() -> list[Path]:
    """Places the Clipazo PRO add-on can live. ~/.clipazo/pro survives plugin updates."""
    dirs = [os.environ.get("CLIPAZO_PRO_DIR"), SCRIPTS_DIR / "pro", Path.home() / ".clipazo" / "pro"]
    return [Path(d) for d in dirs if d]


def load_pro():
    """Load the Clipazo PRO engine if installed, else None. The free version works fully without it."""
    for d in pro_dirs():
        engine = d / "engine.py"
        if engine.exists():
            sys.path.insert(0, str(d))
            spec = importlib.util.spec_from_file_location("clipazo_pro_engine", engine)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            mod.PRO_DIR = d
            return mod
    return None


# ---------------------------------------------------------------- output / errors

def die(msg: str, code: int = 1):
    print(f"ERROR: {msg}", file=sys.stderr, flush=True)
    sys.exit(code)


def say(msg: str = ""):
    print(msg, flush=True)


def warn(msg: str):
    print(f"WARNING: {msg}", file=sys.stderr, flush=True)


# ---------------------------------------------------------------- time

def parse_time(value) -> float:
    """83.5, "83.5", "1:23", "1:02:03.5" -> seconds."""
    if isinstance(value, (int, float)):
        return float(value)
    s = str(value).strip()
    if not s:
        raise ValueError("empty time value")
    parts = s.split(":")
    if len(parts) > 3:
        raise ValueError(f"bad time value: {value!r}")
    total = 0.0
    for p in parts:
        total = total * 60 + float(p)
    return total


def fmt_time(t: float, decimals: int = 0) -> str:
    """Seconds -> "M:SS" or "H:MM:SS" (optionally with decimals)."""
    t = max(0.0, float(t))
    if decimals:
        q = 10 ** decimals
        t = math.floor(t * q) / q
    h = int(t // 3600)
    m = int((t % 3600) // 60)
    s = t - h * 3600 - m * 60
    sec = f"{s:0{3 + decimals}.{decimals}f}" if decimals else f"{int(s):02d}"
    return f"{h}:{m:02d}:{sec}" if h else f"{m}:{sec}"


# ---------------------------------------------------------------- files

def load_json(path, default=None):
    path = Path(path)
    if not path.exists():
        return default
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def save_json(path, data, indent=2):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=indent)
    os.replace(tmp, path)


def resolve_in(workdir: Path, p) -> Path | None:
    if not p:
        return None
    p = Path(p)
    return p if p.is_absolute() else Path(workdir) / p


def rel_to(workdir: Path, p: Path) -> str:
    try:
        return str(Path(p).resolve().relative_to(Path(workdir).resolve())).replace("\\", "/")
    except ValueError:
        return str(Path(p).resolve())


def slugify(text: str, max_len: int = 40) -> str:
    text = unicodedata.normalize("NFKD", str(text)).encode("ascii", "ignore").decode()
    text = re.sub(r"[^a-zA-Z0-9]+", "-", text).strip("-").lower()
    return (text[:max_len].rstrip("-")) or "clip"


# ---------------------------------------------------------------- processes

def which(name: str):
    return shutil.which(name)


def require_bin(name: str) -> str:
    path = shutil.which(name)
    if not path:
        die(f"'{name}' was not found on PATH. Run scripts/doctor.py for install instructions.")
    return path


def _quote(arg: str) -> str:
    arg = str(arg)
    return f'"{arg}"' if (" " in arg or not arg) else arg


def run(cmd, cwd=None, capture=False, check=True, quiet=False):
    cmd = [str(c) for c in cmd]
    if not quiet:
        shown = " ".join(_quote(c) for c in cmd)
        say("$ " + (shown if len(shown) < 600 else shown[:600] + " ..."))
    try:
        res = subprocess.run(
            cmd, cwd=cwd, text=True, encoding="utf-8", errors="replace",
            stdout=subprocess.PIPE if capture else None,
            stderr=subprocess.PIPE if capture else None,
        )
    except FileNotFoundError:
        die(f"command not found: {cmd[0]}")
    if check and res.returncode != 0:
        if capture and res.stderr:
            print(res.stderr[-4000:], file=sys.stderr)
        die(f"command failed (exit {res.returncode}): {Path(cmd[0]).name} ...")
    return res


def ytdlp_base() -> list[str]:
    """Prefer the yt-dlp Python module (keeps it in sync with pip), else a yt-dlp binary."""
    if importlib.util.find_spec("yt_dlp") is not None:
        return [sys.executable, "-m", "yt_dlp"]
    exe = shutil.which("yt-dlp")
    if exe:
        return [exe]
    die('yt-dlp is not installed. Install it with:  python -m pip install -U "yt-dlp[default]"')


def _rate(value) -> float:
    try:
        num, _, den = str(value).partition("/")
        num, den = float(num), float(den or 1)
        return num / den if den else 0.0
    except ValueError:
        return 0.0


def probe(path) -> dict:
    ffprobe = require_bin("ffprobe")
    res = run([ffprobe, "-v", "error", "-print_format", "json", "-show_format", "-show_streams", str(path)],
              capture=True, quiet=True)
    data = json.loads(res.stdout or "{}")
    streams = data.get("streams") or []
    v = next((s for s in streams if s.get("codec_type") == "video"
              and not (s.get("disposition") or {}).get("attached_pic")), None)
    a = next((s for s in streams if s.get("codec_type") == "audio"), None)
    if v is None:
        die(f"no video stream found in {path}")
    dur = float((data.get("format") or {}).get("duration") or v.get("duration") or 0)
    fps = _rate(v.get("avg_frame_rate")) or _rate(v.get("r_frame_rate")) or 30.0
    return {
        "duration": round(dur, 3),
        "width": int(v.get("width") or 0),
        "height": int(v.get("height") or 0),
        "fps": round(fps, 3),
        "has_audio": a is not None,
    }


# ---------------------------------------------------------------- work folder data

def load_meta(workdir) -> dict:
    meta = load_json(Path(workdir) / "meta.json")
    if not meta:
        die(f"No meta.json in {workdir}. Run fetch.py first.")
    return meta


def video_path(workdir, meta) -> Path:
    p = resolve_in(Path(workdir), meta.get("video"))
    if not p or not p.exists():
        die("The video file for this work folder is missing. Run fetch.py (without --no-video) "
            "or pass --video-file.")
    return p


def load_words(workdir) -> list[dict]:
    """Flat, time-sorted word list [{s, e, w}] from transcript.json (video timeline)."""
    tr = load_json(Path(workdir) / "transcript.json")
    if not tr:
        return []
    words = [w for seg in tr.get("segments", []) for w in seg.get("words", [])]
    words.sort(key=lambda w: w["s"])
    return words


def load_segments(workdir) -> list[dict]:
    tr = load_json(Path(workdir) / "transcript.json")
    return (tr or {}).get("segments", [])


def norm_text(s: str) -> str:
    """lowercase, accents stripped, punctuation -> spaces (for keyword matching)."""
    s = unicodedata.normalize("NFKD", s.lower())
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    return re.sub(r"[^\w\s]", " ", s).strip()


# ---------------------------------------------------------------- YouTube live chat replay

CHAT_WEIGHTS = {
    "liveChatTextMessageRenderer": 1.0,
    "liveChatPaidMessageRenderer": 4.0,       # Super Chat
    "liveChatPaidStickerRenderer": 3.0,       # Super Sticker
    "liveChatMembershipItemRenderer": 2.0,    # new member
    "liveChatSponsorshipsGiftPurchaseAnnouncementRenderer": 3.0,
}


def _runs_text(runs) -> str:
    out = []
    for r in runs or []:
        if "text" in r:
            out.append(r["text"])
        elif "emoji" in r:
            e = r["emoji"]
            if e.get("isCustomEmoji"):
                sc = e.get("shortcuts") or []
                out.append(sc[0] if sc else "")
            else:
                out.append(e.get("emojiId", ""))
    return "".join(out).strip()


def load_chat(workdir, meta) -> list[list]:
    """[[t_seconds, weight, text], ...] on the video timeline. Cached in chat_messages.json."""
    workdir = Path(workdir)
    cache = workdir / "chat_messages.json"
    chat_file = resolve_in(workdir, meta.get("chat"))
    if not chat_file or not chat_file.exists():
        return []
    offset = float(meta.get("offset") or 0)
    if cache.exists() and cache.stat().st_mtime >= chat_file.stat().st_mtime:
        cached = load_json(cache, {})
        if isinstance(cached, dict) and cached.get("offset") == offset:
            return cached.get("msgs", [])
    msgs = []
    with open(chat_file, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            rep = obj.get("replayChatItemAction") or {}
            off = rep.get("videoOffsetTimeMsec")
            if off is None:
                continue
            t = int(off) / 1000.0 - offset
            for act in rep.get("actions") or []:
                item = (act.get("addChatItemAction") or {}).get("item") or {}
                for kind, r in item.items():
                    w = CHAT_WEIGHTS.get(kind)
                    if w is None:
                        continue
                    text = _runs_text((r.get("message") or {}).get("runs"))
                    msgs.append([round(t, 2), w, text])
    msgs.sort(key=lambda m: m[0])
    save_json(cache, {"offset": offset, "msgs": msgs}, indent=None)
    return msgs
