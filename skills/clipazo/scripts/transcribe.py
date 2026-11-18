#!/usr/bin/env python3
"""Build a word-timed transcript for the work folder.

  python transcribe.py --workdir W                 # YouTube captions if present, else faster-whisper
  python transcribe.py --workdir W --whisper       # force local transcription (better punctuation/slang)
  python transcribe.py --workdir W --whisper --model medium --lang es

Writes
  transcript.json  {"source", "lang", "segments": [{start, end, text, words: [{s, e, w}]}]}
  transcript.txt   one "[H:MM:SS] text" line per phrase - the file to read/grep when looking for moments

Times are on the downloaded video's timeline (fetch.py --section offsets are already applied).
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import (die, fmt_time, load_meta, probe, require_bin, resolve_in, save_json, say,  # noqa: E402
                    video_path, warn)

CENSORED = re.compile(r"\[\s*_+\s*\]")  # YouTube auto-captions write bleeped words as "[ __ ]"
TIME_RE = re.compile(r"(?:(\d+):)?(\d{1,2}):(\d{2})[.,](\d{1,3})")
TAG_RE = re.compile(r"<[^>]+>")


def finalize(words: list[dict], max_word=1.0) -> list[dict]:
    words.sort(key=lambda w: w["s"])
    out, seen = [], set()
    for w in words:
        key = (round(w["s"], 2), w["w"])
        if key not in seen:
            seen.add(key)
            out.append(w)
    for i, w in enumerate(out):
        nxt = out[i + 1]["s"] if i + 1 < len(out) else w["s"] + max_word
        end = w.get("e") or min(nxt, w["s"] + max_word)
        w["s"] = round(w["s"], 3)
        w["e"] = round(max(w["s"] + 0.05, min(end, nxt if nxt > w["s"] else end)), 3)
    return out


def parse_json3(path: Path) -> list[dict]:
    data = json.loads(path.read_text(encoding="utf-8"))
    words = []
    for ev in data.get("events") or []:
        segs = ev.get("segs")
        if not segs:
            continue
        t0 = ev.get("tStartMs", 0) / 1000.0
        ev_end = t0 + ev.get("dDurationMs", 0) / 1000.0
        starts = [t0 + sg.get("tOffsetMs", 0) / 1000.0 for sg in segs]
        for i, sg in enumerate(segs):
            text = CENSORED.sub("[__]", sg.get("utf8") or "")
            pieces = text.split()
            if not pieces:
                continue
            s0 = starts[i]
            s1 = starts[i + 1] if i + 1 < len(starts) else max(ev_end, s0 + 0.3 * len(pieces))
            step = max(0.0, s1 - s0) / len(pieces)
            for k, p in enumerate(pieces):
                words.append({"s": s0 + k * step, "w": p})
    return finalize(words)


def _ts(m) -> float:
    h, mi, s, frac = m.groups()
    return int(h or 0) * 3600 + int(mi) * 60 + int(s) + int(frac.ljust(3, "0")) / 1000.0


def parse_vtt_srt(path: Path) -> list[dict]:
    """Cue-level captions; words are spread evenly over each cue. Rolling duplicate lines are dropped."""
    words, prev_lines = [], set()
    for block in re.split(r"\n\s*\n", path.read_text(encoding="utf-8", errors="replace").replace("\r", "")):
        lines = block.strip().split("\n")
        idx = next((i for i, l in enumerate(lines) if "-->" in l), None)
        if idx is None:
            continue
        times = list(TIME_RE.finditer(lines[idx]))
        if len(times) < 2:
            continue
        start, end = _ts(times[0]), _ts(times[1])
        text_lines = [TAG_RE.sub("", l).strip() for l in lines[idx + 1:]]
        text_lines = [l for l in text_lines if l]
        new = [l for l in text_lines if l not in prev_lines]
        prev_lines = set(text_lines)
        pieces = CENSORED.sub("[__]", " ".join(new)).split()
        if not pieces:
            continue
        step = max(0.05, end - start) / len(pieces)
        for k, p in enumerate(pieces):
            words.append({"s": start + k * step, "e": start + (k + 1) * step, "w": p})
    return finalize(words)


WHISPER_CHUNK = 1800  # seconds of audio decoded at a time (~115 MB of float32) - keeps RAM bounded


def _pcm16k(ffmpeg, media, start, dur):
    """Decode a window of audio to 16 kHz mono float32 with ffmpeg. (We don't let faster-whisper decode
    files itself: its PyAV dependency breaks between versions, and it would load hours of audio into RAM.)"""
    import numpy as np
    cmd = [ffmpeg, "-hide_banner", "-loglevel", "error", "-ss", f"{start:.3f}", "-t", f"{dur:.3f}",
           "-i", str(media), "-map", "0:a:0", "-vn", "-ac", "1", "-ar", "16000", "-f", "f32le", "-"]
    res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if res.returncode != 0:
        raise RuntimeError(f"ffmpeg could not decode audio: {res.stderr.decode(errors='replace')[-500:]}")
    return np.frombuffer(res.stdout, dtype=np.float32)


def whisper_words(media: Path, lang=None, model_name="small", start=None, end=None, progress=True) -> list[dict]:
    """Transcribe with faster-whisper. With start/end, only that window (times returned on the full timeline)."""
    try:
        from faster_whisper import WhisperModel
    except ImportError:
        raise RuntimeError("faster-whisper is not installed:  python -m pip install -U faster-whisper")
    ffmpeg = require_bin("ffmpeg")
    t0 = float(start or 0.0)
    t1 = float(end) if end is not None else probe(media)["duration"]

    device = "cpu"
    try:
        import ctranslate2
        if ctranslate2.get_cuda_device_count() > 0:
            device = "cuda"
    except Exception:
        pass

    def make_model(dev):
        return WhisperModel(model_name, device=dev, compute_type="float16" if dev == "cuda" else "int8")

    model = make_model(device)
    words, cs = [], t0
    while cs < t1 - 0.05:
        dur = min(WHISPER_CHUNK, t1 - cs)
        audio = _pcm16k(ffmpeg, media, cs, dur)

        def run_chunk(m):
            segs, _ = m.transcribe(audio, language=lang or None, word_timestamps=True, vad_filter=True)
            out = []
            for seg in segs:
                for w in seg.words or []:
                    t = CENSORED.sub("[__]", w.word.strip())
                    if t:
                        out.append({"s": w.start + cs, "e": w.end + cs, "w": t})
            return out

        try:
            words += run_chunk(model)
        except Exception as e:  # CUDA present but cuDNN/cuBLAS missing, etc.
            if device != "cuda":
                raise
            warn(f"GPU transcription failed ({e}); continuing on CPU.")
            device, model = "cpu", make_model("cpu")
            words += run_chunk(model)
        cs += dur
        if progress and t1 - t0 > WHISPER_CHUNK:
            say(f"   whisper: {(cs - t0) / (t1 - t0):5.1%} ({fmt_time(cs - t0)} / {fmt_time(t1 - t0)})")
    return finalize(words)


def build_segments(words, max_gap=1.0, max_len=12.0, max_chars=140):
    segs, cur = [], []

    def flush():
        if cur:
            segs.append({"start": cur[0]["s"], "end": cur[-1]["e"],
                         "text": " ".join(w["w"] for w in cur), "words": list(cur)})
            cur.clear()

    for w in words:
        if cur and (w["s"] - cur[-1]["e"] > max_gap or w["e"] - cur[0]["s"] > max_len
                    or sum(len(x["w"]) + 1 for x in cur) > max_chars):
            flush()
        cur.append(w)
        if re.search(r"[.!?]$", w["w"]) and w["e"] - cur[0]["s"] > 2.5:
            flush()
    flush()
    return segs


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--workdir", required=True)
    ap.add_argument("--whisper", action="store_true", help="transcribe locally even if captions exist")
    ap.add_argument("--model", default="small", help="faster-whisper model: tiny/base/small/medium/large-v3")
    ap.add_argument("--lang", help="spoken language code (default: from meta.json / auto)")
    args = ap.parse_args()

    wd = Path(args.workdir).expanduser().resolve()
    meta = load_meta(wd)
    lang = args.lang or meta.get("language")
    offset = float(meta.get("offset") or 0)
    dur = float(meta.get("duration") or 0)
    subs = resolve_in(wd, meta.get("subs"))

    words, source = [], None
    if subs and subs.exists() and not args.whisper:
        say(f"== Parsing captions {subs.name}")
        words = parse_json3(subs) if subs.suffix == ".json3" else parse_vtt_srt(subs)
        source = f"youtube-{meta.get('subs_kind') or 'captions'}"
        for w in words:
            w["s"], w["e"] = round(w["s"] - offset, 3), round(w["e"] - offset, 3)
        words = [w for w in words if w["e"] > 0 and (not dur or w["s"] < dur)]
    else:
        video = video_path(wd, meta)
        say(f"== Transcribing locally with faster-whisper ({args.model}). "
            f"On CPU this can take a long time for multi-hour streams.")
        try:
            words = whisper_words(video, lang, args.model)
        except RuntimeError as e:
            die(str(e))
        source = f"whisper-{args.model}"

    if not words:
        die("The transcript came out empty (no speech found or captions were empty).")

    segs = build_segments(words)
    for s in segs:
        for w in s["words"]:
            w["s"], w["e"] = round(w["s"], 2), round(w["e"], 2)
        s["start"], s["end"] = round(s["start"], 2), round(s["end"], 2)
    save_json(wd / "transcript.json", {"source": source, "lang": lang, "segments": segs}, indent=None)
    with open(wd / "transcript.txt", "w", encoding="utf-8") as f:
        for s in segs:
            f.write(f"[{fmt_time(s['start'])}] {s['text']}\n")
    say(f"Transcript: {len(words)} words in {len(segs)} lines ({source}) -> transcript.txt")
    say("Next: python analyze.py --workdir " + f'"{wd}"')


if __name__ == "__main__":
    main()
