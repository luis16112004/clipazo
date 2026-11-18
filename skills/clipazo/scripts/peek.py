#!/usr/bin/env python3
"""Print what was said (and what chat said) around a moment - for choosing exact cut points.

  python peek.py --workdir W --at 1:23:45                  # 45 s before .. 20 s after
  python peek.py --workdir W --from 1:23:10 --to 1:24:05
  python peek.py --workdir W --at 1:23:45 --before 8 --after 8 --words   # word-level timings
  python peek.py --workdir W --grep "no manches|avion"     # find lines in the whole transcript
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import fmt_time, load_chat, load_meta, load_segments, load_words, parse_time, say  # noqa: E402


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--workdir", required=True)
    ap.add_argument("--at", help="center time")
    ap.add_argument("--from", dest="start", help="window start")
    ap.add_argument("--to", dest="end", help="window end")
    ap.add_argument("--before", type=float, default=45)
    ap.add_argument("--after", type=float, default=20)
    ap.add_argument("--words", action="store_true", help="print every word with start/end times")
    ap.add_argument("--no-chat", action="store_true")
    ap.add_argument("--grep", help="regex to search the whole transcript (case-insensitive)")
    args = ap.parse_args()

    wd = Path(args.workdir).expanduser().resolve()
    meta = load_meta(wd)

    if args.grep:
        rx = re.compile(args.grep, re.I)
        hits = [s for s in load_segments(wd) if rx.search(s["text"])]
        for s in hits[:200]:
            say(f"[{fmt_time(s['start'])}] {s['text']}")
        say(f"-- {len(hits)} matching lines" + (" (first 200 shown)" if len(hits) > 200 else ""))
        return

    if args.at:
        c = parse_time(args.at)
        a, b = c - args.before, c + args.after
    elif args.start and args.end:
        a, b = parse_time(args.start), parse_time(args.end)
    else:
        ap.error("give --at, or --from and --to, or --grep")
    a = max(0.0, a)

    say(f"== Transcript {fmt_time(a, 1)} -> {fmt_time(b, 1)}")
    if args.words:
        for w in load_words(wd):
            if w["e"] > a and w["s"] < b:
                say(f"  {fmt_time(w['s'], 2):>11}  {fmt_time(w['e'], 2):>11}  {w['w']}")
    else:
        for s in load_segments(wd):
            if s["end"] > a and s["start"] < b:
                say(f"  [{fmt_time(s['start'], 1)}] {s['text']}")

    if not args.no_chat:
        msgs = [m for m in load_chat(wd, meta) if a <= m[0] <= b + 15 and m[2]]
        if msgs:
            say(f"== Chat {fmt_time(a)} -> {fmt_time(b + 15)} ({len(msgs)} messages; chat reacts a few seconds late)")
            for t, w, text in msgs[:80]:
                say(f"  [{fmt_time(t)}]{' $' if w > 1 else ''} {text[:100]}")


if __name__ == "__main__":
    main()
