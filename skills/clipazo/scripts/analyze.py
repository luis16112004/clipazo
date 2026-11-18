#!/usr/bin/env python3
"""Score every second of the video and list the most promising moments to clip.

  python analyze.py --workdir W [--top 25] [--min-gap 60] [--keywords "no manches,que locura"]

Signals (each turned into "how unusual is this second compared to the stream around it"):
  audio   - loudness spikes (screams, laughs, explosions)
  chat    - chat speed + laughter/hype messages + Super Chats (shifted back by --chat-lag seconds,
            because chat reacts after the moment happens)
  heat    - YouTube "most replayed" graph, when the video has enough views
  voice   - reaction words/laughter in the streamer's own speech (from the transcript)

Writes candidates.md (read this), candidates.json, signals.json and audio_rms.json (cache).
The list is a starting point for editorial judgment, not a final answer.
"""
from __future__ import annotations

import argparse
import math
import re
import sys
from collections import deque
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import (die, fmt_time, load_chat, load_json, load_meta, load_segments, load_words,  # noqa: E402
                    norm_text, require_bin, run, save_json, say, video_path, warn)

LAUGH = re.compile(r"(?:j+[aeiou]+){2,}|(?:h+[ae]+){2,}|k{4,}|\bx+d+\b|\blo+l\b|\blmf?a+o+\b|\bkek\w*|\brofl\b")
HYPE = re.compile(r"\bno{3,}\b|\bclip\w*\b|\bomg\b|\bwtf\b|\bpog\w*\b|\bgg\b|\bf\b|\bw\b|\bva+mo+s?\b|"
                  r"\bque+e+\b|\bo+mg\b|\bholy\b|\bbruh+\b|\bnooo\w*|\bsi+i{2,}\b|\bgo+a+l+\b|\bque{2,}\b")
EMOJI = set("😂🤣💀😱🔥😭😮🤯👏😳🫢🥶😨🙀‼❗")

VOICE_PHRASES = {
    # es
    "no manches", "no mames", "no puede ser", "que paso", "dios mio", "ay no", "ay wey", "ay guey", "a huevo",
    "vamos", "increible", "que locura", "mira eso", "corre", "madre mia", "no inventes", "chale", "noo",
    "lo hice", "lo logre", "que es eso", "que fue eso", "no no no", "si si si", "puta madre", "verga",
    "chingada", "joder", "hostia", "mierda", "que onda", "nooo", "ostia", "espera", "aguanta", "ayuda",
    "que hago", "me muero", "jajaja", "jaja", "wey", "ya valio", "valio",
    # en
    "oh my god", "what the", "lets go", "let s go", "holy", "dude", "bro", "are you kidding", "wow", "oh no",
    "run", "no way", "what", "yes yes", "fuck", "shit", "insane", "crazy",
    # pt
    "meu deus", "caramba", "nossa", "vai vai", "caralho", "porra",
    # bleeped word in YouTube auto-captions
    "__",
}


# ---------------------------------------------------------------- small numeric helpers (stdlib only)

def prefix(a):
    p = [0.0]
    for x in a:
        p.append(p[-1] + x)
    return p


def movsum(a, w):
    """Centered moving sum over w seconds."""
    p, n, h = prefix(a), len(a), w // 2
    return [p[min(n, i + w - h)] - p[max(0, i - h)] for i in range(n)]


def movavg(a, w):
    p, n, h = prefix(a), len(a), w // 2
    out = []
    for i in range(n):
        lo, hi = max(0, i - h), min(n, i + w - h)
        out.append((p[hi] - p[lo]) / max(1, hi - lo))
    return out


def movmax(a, w):
    n, h, out, dq = len(a), w // 2, [], deque()
    for i in range(n + h):
        if i < n:
            while dq and a[dq[-1]] <= a[i]:
                dq.pop()
            dq.append(i)
        j = i - h
        if j >= 0:
            while dq and dq[0] < j - h:
                dq.popleft()
            out.append(a[dq[0]])
    return out[:n]


def median(xs):
    s = sorted(xs)
    n = len(s)
    if not n:
        return 0.0
    return s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2


def robust_z(x, base_window=600, local=True):
    """(x - local baseline) / robust spread. Local baseline makes a busy late-stream chat comparable to early."""
    base = movavg(x, base_window) if local else [median(x)] * len(x)
    d = [xi - bi for xi, bi in zip(x, base)]
    med = median(d)
    mad = median([abs(v - med) for v in d])
    scale = 1.4826 * mad
    if scale < 1e-6:
        mean = sum(d) / len(d)
        scale = math.sqrt(sum((v - mean) ** 2 for v in d) / len(d)) or 1.0
    return [(v - med) / scale for v in d]


def clamp(v, lo=-2.0, hi=6.0):
    return max(lo, min(hi, v))


# ---------------------------------------------------------------- signals

def audio_signal(video: Path, wd: Path, n: int, force=False):
    cache = wd / "audio_rms.json"
    data = None if force else load_json(cache)
    if not data or len(data) != n:
        say("== Measuring loudness per second (one pass over the audio)")
        txt = wd / "audio_rms.txt"
        af = ("aresample=16000,aformat=channel_layouts=mono,asetnsamples=n=16000:p=0,"
              "astats=metadata=1:reset=1,"
              "ametadata=mode=print:key=lavfi.astats.Overall.RMS_level:file=audio_rms.txt")
        run([require_bin("ffmpeg"), "-hide_banner", "-nostats", "-loglevel", "error", "-i", str(video),
             "-map", "0:a:0", "-af", af, "-f", "null", "-"], cwd=wd)
        data, t = [-70.0] * n, None
        for line in txt.read_text(encoding="utf-8", errors="replace").splitlines():
            if line.startswith("frame:"):
                m = re.search(r"pts_time:([\d.]+)", line)
                t = float(m.group(1)) if m else None
            elif "RMS_level=" in line and t is not None:
                raw = line.split("=", 1)[1].strip()
                try:
                    val = float(raw)
                except ValueError:
                    val = -70.0
                i = int(t)
                if 0 <= i < n and math.isfinite(val):
                    data[i] = max(-70.0, val)
        txt.unlink(missing_ok=True)
        save_json(cache, data, indent=None)
    smooth = movavg(movmax(data, 3), 3)
    return robust_z(smooth, 300)


def chat_signal(msgs, n, lag):
    counts, hype = [0.0] * n, [0.0] * n
    for t, w, text in msgs:
        i = int(t - lag)
        if 0 <= i < n:
            counts[i] += w
            low = text.lower()
            h = len(LAUGH.findall(low)) + len(HYPE.findall(low)) + sum(1 for ch in text if ch in EMOJI)
            hype[i] += min(3, h)
    x = [math.log1p(c + 2 * h) for c, h in zip(movsum(counts, 10), movsum(hype, 10))]
    return robust_z(x, 600)


def heat_signal(heatmap, n):
    x = [0.0] * n
    for h in heatmap:
        for i in range(max(0, int(h["start_time"])), min(n, int(math.ceil(h["end_time"])))):
            x[i] = float(h.get("value") or 0)
    return robust_z(x, local=False)


# Sound tags that YouTube auto-captions (and some manual subs) insert: [risas], [grito], [Laughter]...
SOUND_TAGS = {"risas", "risa", "grito", "gritos", "gritando", "laughter", "laughing", "laughs", "screaming",
              "screams", "scream", "aplausos", "applause", "risos", "gargalhadas", "cheering", "vitores"}


def voice_signal(words, n, extra):
    phrases = VOICE_PHRASES | {norm_text(k) for k in extra if k.strip()}
    toks = [(w["s"], norm_text(w["w"])) for w in words]
    hits = [0.0] * n
    for i, (s, tok) in enumerate(toks):
        if not tok:
            continue
        score = 0.0
        raw = words[i]["w"]
        if raw.startswith("[") and tok.split()[0] in SOUND_TAGS:
            score += 2
        if LAUGH.search(tok) or re.search(r"([a-z])\1{2,}", tok):
            score += 1
        for k in (1, 2, 3):
            if i + k <= len(toks) and " ".join(t for _, t in toks[i:i + k]) in phrases:
                score += 1
        if score and 0 <= int(s) < n:
            hits[int(s)] += score
    # z-score so a streamer who says "wey" every sentence doesn't light up the whole stream
    return robust_z(movsum(hits, 8), 600)


# ---------------------------------------------------------------- output helpers

def excerpt(segments, a, b, max_chars=900):
    lines = [f"  [{fmt_time(s['start'])}] {s['text']}" for s in segments if s["end"] > a and s["start"] < b]
    text = "\n".join(lines)
    return text if len(text) <= max_chars else text[:max_chars] + " ..."


SHORTCUT = re.compile(r":[\w-]+:")


def chat_sample(msgs, a, b, k=8):
    # skip messages that are only custom-emoji shortcuts like ":face-blue-smiling:"
    window = [m for m in msgs if a <= m[0] <= b and SHORTCUT.sub("", m[2]).strip()]
    window.sort(key=lambda m: (-(m[1] > 1), -bool(LAUGH.search(m[2].lower()) or HYPE.search(m[2].lower())), m[0]))
    seen, out = set(), []
    for _, _, text in window:
        text = re.sub(r"\s+", " ", SHORTCUT.sub(" ", text)).strip()
        key = text.lower()[:40]
        if key not in seen:
            seen.add(key)
            out.append(text[:70])
        if len(out) >= k:
            break
    return out


def activity_map(score, width=60):
    """One character per minute; rows of `width` minutes. Lets you see where the stream was alive."""
    levels = " .:-=+*#%@"
    per_min = [max(score[i:i + 60]) for i in range(0, len(score), 60)]
    lo, hi = min(per_min), max(per_min)
    rows = []
    for r in range(0, len(per_min), width):
        chunk = per_min[r:r + width]
        chars = "".join(levels[int((v - lo) / (hi - lo + 1e-9) * (len(levels) - 1))] for v in chunk)
        rows.append(f"  {fmt_time(r * 60):>8} |{chars}|")
    return "\n".join(rows)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--workdir", required=True)
    ap.add_argument("--top", type=int, default=25, help="how many candidates to list (default 25)")
    ap.add_argument("--min-gap", type=float, default=60, help="min seconds between candidates (default 60)")
    ap.add_argument("--chat-lag", type=float, default=8, help="seconds chat lags behind the moment (default 8)")
    ap.add_argument("--pre", type=float, default=25, help="suggested seconds before the peak (default 25)")
    ap.add_argument("--post", type=float, default=12, help="suggested seconds after the peak (default 12)")
    ap.add_argument("--keywords", default="", help="extra comma-separated reaction words/phrases to boost")
    ap.add_argument("--skip-start", type=float, default=60, help="ignore the first N seconds (intro screens)")
    ap.add_argument("--skip-end", type=float, default=180,
                    help="ignore the last N seconds (goodbyes make chat spam 'nooo')")
    ap.add_argument("--force", action="store_true", help="recompute the audio cache")
    args = ap.parse_args()

    wd = Path(args.workdir).expanduser().resolve()
    meta = load_meta(wd)
    n = int(math.ceil(float(meta.get("duration") or 0)))
    if n < 30:
        warn("Video is very short; candidates may not be meaningful.")
    n = max(n, 1)

    signals, weights, used = {}, {}, []
    if meta.get("video") and meta.get("has_audio", True):
        signals["audio"], weights["audio"] = audio_signal(video_path(wd, meta), wd, n, args.force), 1.0
        used.append("audio loudness")

    msgs = load_chat(wd, meta)
    if len(msgs) >= 20:
        signals["chat"] = chat_signal(msgs, n, args.chat_lag)
        weights["chat"] = 1.3 if len(msgs) >= 300 else 0.5  # a tiny chat is mostly noise
        used.append(f"chat ({len(msgs)} messages)")
    elif msgs:
        say(f"   chat has only {len(msgs)} messages - ignoring it as a signal")

    if meta.get("heatmap"):
        signals["heat"], weights["heat"] = heat_signal(meta["heatmap"], n), 0.8
        used.append("most-replayed heatmap")

    words = load_words(wd)
    segments = load_segments(wd)
    if words:
        extra = [k for k in args.keywords.split(",")]
        signals["voice"], weights["voice"] = voice_signal(words, n, extra), 0.6
        used.append(f"voice reactions ({len(words)} transcript words)")
    else:
        warn("No transcript.json - run transcribe.py first for much better picks (and captions).")

    if not signals:
        die("No signals available (no audio, chat, heatmap or transcript).")

    wsum = sum(weights.values())
    raw = [sum(weights[k] * clamp(signals[k][i]) for k in signals) / wsum for i in range(n)]
    score = movavg(raw, 5)

    # only skip intro/outro when this file really contains the stream's start/end (not a --section)
    offset, src_dur = float(meta.get("offset") or 0), float(meta.get("source_duration") or 0)
    has_start = offset == 0
    has_end = not src_dur or offset + n >= src_dur - 5
    skip = int(min(args.skip_start, n * 0.05)) if has_start else 0
    skip_end = int(min(args.skip_end, n * 0.05)) if has_end else 0
    order = sorted(range(skip, n - skip_end), key=lambda i: score[i], reverse=True)
    picks = []
    for i in order:
        if len(picks) >= args.top:
            break
        if all(abs(i - p) >= args.min_gap for p in picks):
            picks.append(i)

    cands = []
    for rank, i in enumerate(picks, 1):
        a, b = max(0, i - args.pre), min(n, i + args.post)
        cands.append({
            "rank": rank, "peak": i, "peak_time": fmt_time(i), "start": round(a, 1), "end": round(b, 1),
            "score": round(score[i], 2),
            "signals": {k: round(signals[k][i], 2) for k in signals},
            "transcript": excerpt(segments, a - 15, b + 5),
            "chat": chat_sample(msgs, i - 2, i + args.chat_lag + 15) if msgs else [],
        })

    save_json(wd / "candidates.json", cands)
    save_json(wd / "signals.json", {"weights": weights, "score": [round(v, 3) for v in score],
                                    **{k: [round(v, 3) for v in s] for k, s in signals.items()}}, indent=None)

    md = [f"# Candidate moments - {meta.get('title') or wd.name}", "",
          f"Duration {fmt_time(n)} | signals: {', '.join(used)}",
          "Score = weighted 'how unusual is this second' (z-score-like; >2 is notable, >4 is a big spike).",
          "Signals are pointers, not verdicts: read the transcript/chat and look at frames before choosing.", ""]
    if meta.get("chapters"):
        md += ["Chapters: " + " | ".join(f"{fmt_time(c['start_time'])} {c.get('title', '')}" for c in meta["chapters"]), ""]
    md += ["Activity map (1 char = 1 minute, darker = more activity):", "```", activity_map(score), "```", ""]
    for c in cands:
        sig = ", ".join(f"{k} {v:+.1f}" for k, v in c["signals"].items())
        md += [f"## #{c['rank']} - peak {c['peak_time']}  (score {c['score']:.1f}: {sig})",
               f"Suggested window: {fmt_time(c['start'])} -> {fmt_time(c['end'])}"]
        if c["transcript"]:
            md += ["Transcript:", c["transcript"]]
        if c["chat"]:
            md += ["Chat: " + " | ".join(c["chat"])]
        md.append("")
    (wd / "candidates.md").write_text("\n".join(md), encoding="utf-8")
    say(f"{len(cands)} candidates -> {wd / 'candidates.md'}")
    say("Next: read candidates.md, then peek.py / frames.py on the promising ones.")


if __name__ == "__main__":
    main()
