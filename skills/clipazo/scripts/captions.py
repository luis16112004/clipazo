"""ASS subtitle helpers shared by render.py and the Clipazo PRO add-on (caption styles)."""
from __future__ import annotations

import platform
import re

DEFAULT_FONT = "Arial Black" if platform.system() in ("Windows", "Darwin") else "DejaVu Sans"

STYLE_FORMAT = ("Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, "
                "Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, "
                "Alignment, MarginL, MarginR, MarginV, Encoding")


def ass_color(hexrgb: str, alpha: int = 0) -> str:
    """RRGGBB -> &HAABBGGRR (style colour)."""
    h = hexrgb.lstrip("#")
    return f"&H{alpha:02X}{h[4:6]}{h[2:4]}{h[0:2]}".upper()


def ass_inline(hexrgb: str) -> str:
    """RRGGBB -> &HBBGGRR& (for \\c override tags)."""
    h = hexrgb.lstrip("#")
    return f"&H{h[4:6]}{h[2:4]}{h[0:2]}&".upper()


def ass_time(t: float) -> str:
    cs = int(round(max(0.0, t) * 100))
    return f"{cs // 360000}:{cs // 6000 % 60:02d}:{cs // 100 % 60:02d}.{cs % 100:02d}"


def ass_escape(text: str) -> str:
    return text.replace("\\", "").replace("{", "(").replace("}", ")").replace("\n", " ")


def style_line(name, font, size, color, outline, align, outline_color="000000", back="000000", back_alpha=0x78,
               border_style=1, shadow=3, margin=70, bold=True) -> str:
    return (f"Style: {name},{font},{size},{ass_color(color)},&H000000FF,{ass_color(outline_color)},"
            f"{ass_color(back, back_alpha)},{-1 if bold else 0},0,0,0,100,100,0,0,{border_style},{outline},{shadow},"
            f"{align},{margin},{margin},0,1")


def caption_tokens(words, upper: bool):
    """Drop sound tags like [risas] / [grito de alegría] / [Music]; show bleeped words as ****."""
    out, inside = [], False
    for w in words:
        t = w["w"]
        if t == "[__]":
            out.append((w, "****"))
            continue
        if t.startswith("[") or inside:
            inside = not t.endswith("]")
            continue
        t = ass_escape(t)
        out.append((w, t.upper() if upper else t))
    return out


def chunk_words(words, dur, upper=True, max_words=3, max_chars=16, gap=0.6):
    """Group clip-relative words into on-screen chunks: [[start, end, shown_text, raw_text], ...] lists."""
    toks = []
    for w, t in caption_tokens(words, upper):
        s, e = w["s"], w["e"]
        shown = re.sub(r"[,.;:…]+$", "", t)  # trailing commas/periods look cluttered on screen; keep ?!
        if not shown or e <= 0 or s >= dur:
            continue
        toks.append([max(0.0, s), max(min(dur, e), s + 0.08), shown, t])
    chunks, cur = [], []
    for tk in toks:
        if cur:
            chars = sum(len(x[2]) + 1 for x in cur) + len(tk[2])
            if len(cur) >= max_words or chars > max_chars or tk[0] - cur[-1][1] > gap:
                chunks.append(cur)
                cur = []
        cur.append(tk)
        if re.search(r"[.,!?…]$", tk[3]):  # break at punctuation so phrases don't straddle chunks
            chunks.append(cur)
            cur = []
    if cur:
        chunks.append(cur)
    return chunks


def chunk_end(chunks, ci, dur, hold=0.5):
    nxt = chunks[ci + 1][0][0] if ci + 1 < len(chunks) else dur
    return min(nxt, chunks[ci][-1][1] + hold)


def karaoke_events(words, dur, st, W, H, y_frac):
    """Free style: 2-3 words at a time, the spoken word highlighted, a small pop when a chunk appears."""
    chunks = chunk_words(words, dur, st["uppercase"], st["max_words"], st["max_chars"])
    hi, base = ass_inline(st["highlight"]), ass_inline(st["color"])
    x, y = W // 2, int(H * y_frac)
    events = []
    for ci, ch in enumerate(chunks):
        ch_end = chunk_end(chunks, ci, dur)
        for wi, tk in enumerate(ch):
            ws = ch[0][0] if wi == 0 else tk[0]
            we = ch[wi + 1][0] if wi + 1 < len(ch) else ch_end
            if we - ws < 0.04:
                continue
            words_txt = " ".join(f"{{\\c{hi}}}{t[2]}{{\\c{base}}}" if k == wi else t[2] for k, t in enumerate(ch))
            pop = "\\fscx112\\fscy112\\t(0,90,\\fscx100\\fscy100)" if wi == 0 else ""
            events.append((ws, we, "Cap", f"{{\\an5\\pos({x},{y}){pop}}}{words_txt}"))
    return events


def write_ass(path, W, H, style_lines, events):
    lines = ["[Script Info]", "ScriptType: v4.00+", f"PlayResX: {W}", f"PlayResY: {H}", "WrapStyle: 0",
             "ScaledBorderAndShadow: yes", "", "[V4+ Styles]", STYLE_FORMAT, *style_lines, "",
             "[Events]", "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text"]
    layer = {"Cap": 0}
    for s, e, style, text in sorted(events, key=lambda ev: ev[0]):
        lines.append(f"Dialogue: {layer.get(style, 1)},{ass_time(s)},{ass_time(e)},{style},,0,0,0,,{text}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
