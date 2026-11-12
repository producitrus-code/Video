"""Render animated captions + topic cards over the source video.

Usage: python3 render.py [--preview SECONDS ...]
Usage: python3 render.py [--config edit.json] [--preview SECONDS ...]
Each project config (JSON) points to its video, transcript, cards and keywords.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = Path(__file__).parent
W, H, FPS = 1080, 1920, 30
MARGIN_X = 72
CARD_TOP = 230
FONT_SANS = ROOT / "fonts/InterTight-Variable.ttf"
FONT_SERIF = ROOT / "fonts/InstrumentSerif-Italic.ttf"


# ---------- helpers ----------
def hex_rgb(h: str) -> tuple[int, int, int]:
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def ease_out_cubic(t: float) -> float:
    t = min(max(t, 0.0), 1.0)
    return 1 - (1 - t) ** 3


def ease_out_back(t: float, s: float = 1.6) -> float:
    t = min(max(t, 0.0), 1.0) - 1
    return 1 + t * t * ((s + 1) * t + s)


@lru_cache(maxsize=None)
def sans(size: int, weight: int = 900) -> ImageFont.FreeTypeFont:
    f = ImageFont.truetype(str(FONT_SANS), size)
    f.set_variation_by_axes([weight])
    return f


@lru_cache(maxsize=None)
def serif(size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(FONT_SERIF), size)


@dataclass
class Style:
    font: ImageFont.FreeTypeFont
    color: tuple[int, int, int]
    tracking: float = 0.0  # em fraction (negative = tighter)


def text_width(text: str, st: Style) -> float:
    size = st.font.size
    return st.font.getlength(text) + st.tracking * size * max(len(text) - 1, 0)


def draw_tracked(draw: ImageDraw.ImageDraw, xy, text: str, st: Style, alpha: int = 255):
    """Draw text on its baseline with custom tracking while keeping kerning."""
    x0, y = xy
    trk = st.tracking * st.font.size
    for i, ch in enumerate(text):
        x = x0 + st.font.getlength(text[:i]) + trk * i
        draw.text((x, y), ch, font=st.font, fill=(*st.color, alpha), anchor="ls")


# ---------- rich text layout (segments marked with *serif*) ----------
@dataclass
class Token:
    text: str
    style: Style
    width: float = 0.0


def tokenize_rich(title: str, plain: Style, accent: Style) -> list[Token]:
    tokens: list[Token] = []
    for i, part in enumerate(re.split(r"\*", title)):
        st = accent if i % 2 else plain
        for word in part.split():
            tokens.append(Token(word, st, text_width(word, st)))
    return tokens


def wrap(tokens: list[Token], max_w: float, space: float) -> list[list[Token]]:
    lines: list[list[Token]] = [[]]
    cur = 0.0
    for tk in tokens:
        add = tk.width + (space if lines[-1] else 0)
        if lines[-1] and cur + add > max_w:
            lines.append([tk])
            cur = tk.width
        else:
            lines[-1].append(tk)
            cur += add
    return lines


# ---------- layers ----------
@dataclass
class Layer:
    img: Image.Image
    x: int
    y: int


def rounded_card(w: int, h: int, color, radius: int, shadow: bool = True) -> tuple[Image.Image, int]:
    pad = 40 if shadow else 0
    im = Image.new("RGBA", (w + pad * 2, h + pad * 2), (0, 0, 0, 0))
    if shadow:
        sh = Image.new("RGBA", im.size, (0, 0, 0, 0))
        ImageDraw.Draw(sh).rounded_rectangle((pad, pad + 10, pad + w, pad + h + 10), radius, fill=(40, 20, 12, 70))
        im = Image.alpha_composite(im, sh.filter(ImageFilter.GaussianBlur(18)))
    ImageDraw.Draw(im).rounded_rectangle((pad, pad, pad + w, pad + h), radius, fill=(*color, 240))
    return im, pad


def build_card(card: dict, pal: dict) -> Layer:
    hero = card.get("hero", False)
    size = 96 if hero else 84
    plain = Style(sans(size), pal["brown"], -0.055)
    accent = Style(serif(int(size * 1.18)), pal["terracotta"], -0.01)
    label = Style(serif(46 if hero else 42), pal["brown"], 0.0)

    inner_w = W - 2 * MARGIN_X - 2 * 52
    lines = wrap(tokenize_rich(card["title"], plain, accent), inner_w, size * 0.22)
    line_h = size * 0.98
    pad_x, pad_top, pad_bot = 52, 46, 56
    label_h = label.font.size * 1.15
    h = int(pad_top + label_h + line_h * len(lines) + pad_bot - size * 0.12)
    w = W - 2 * MARGIN_X

    im, pad = rounded_card(w, h, pal["cream"], 38)
    d = ImageDraw.Draw(im)
    base_y = pad + pad_top + label.font.size * 0.8
    draw_tracked(d, (pad + pad_x, base_y), card["label"], label)
    y = base_y + label_h * 0.35 + line_h
    for line in lines:
        x = pad + pad_x
        for tk in line:
            draw_tracked(d, (x, y), tk.text, tk.style)
            x += tk.width + size * 0.22
        y += line_h
    return Layer(im, MARGIN_X - pad, CARD_TOP - pad)


def build_pill(text: str, pal: dict) -> Layer:
    st = Style(sans(44, 700), pal["brown"], -0.02)
    tw = text_width(text, st)
    w, h = int(tw + 2 * 46), 92
    im, pad = rounded_card(w, h, pal["pill"], h // 2)
    draw_tracked(ImageDraw.Draw(im), (pad + 46, pad + h / 2 + 15), text, st)
    return Layer(im, W - MARGIN_X - w - pad, 1430 - pad)


# ---------- captions ----------
@dataclass
class Word:
    text: str
    start: float
    end: float
    key: bool = False


@dataclass
class Chunk:
    words: list[Word] = field(default_factory=list)
    start: float = 0.0
    end: float = 0.0


def build_chunks(cfg: dict) -> list[Chunk]:
    segs = json.loads((ROOT / cfg["transcript"]).read_text())
    skip_seg = {round(s, 2) for s in cfg.get("skip_segments_starting", [])}
    fixes = {round(float(k), 2): v for k, v in cfg.get("corrections", {}).items()}
    keys = {k.lower() for k in cfg["keywords"]}
    skip_words = {w.lower() for w in cfg.get("skip_words", [])}

    chunks: list[Chunk] = []
    for seg in segs:
        if round(seg["start"], 2) in skip_seg:
            continue
        words, skip_next = [], False
        for w in seg["words"]:
            raw = w["w"].strip()
            clean = re.sub(r"[,.!?;:]+$", "", raw)
            if skip_next:
                skip_next = False
                continue
            if clean.lower() in skip_words:
                skip_next = True  # also drop the number after "número"
                continue
            text = fixes.get(round(w["s"], 2), clean)
            text = text if text == "B" else text.lower()
            parts = text.split()
            for j, part in enumerate(parts):
                last = j == len(parts) - 1
                words.append((Word(part, w["s"], w["e"], clean.lower() in keys), last and raw[-1] in ",.!?"))

        cur = Chunk()
        for word, punct in words:
            chars = sum(len(x.text) + 1 for x in cur.words) + len(word.text)
            if cur.words and (len(cur.words) >= 4 or chars > cfg.get("max_chars", 24) or word.key and any(x.key for x in cur.words)):
                chunks.append(cur)
                cur = Chunk()
            cur.words.append(word)
            if punct:
                chunks.append(cur)
                cur = Chunk()
        if cur.words:
            chunks.append(cur)

    for ch in chunks:
        ch.start = ch.words[0].start
    for i, ch in enumerate(chunks):
        nxt = chunks[i + 1].start if i + 1 < len(chunks) else ch.words[-1].end + 0.8
        ch.end = min(nxt, ch.words[-1].end + 0.8)
        later_cards = [c["start"] for c in cfg["cards"] if c["start"] > ch.start]
        if later_cards:
            ch.end = min(ch.end, min(later_cards))
    return chunks


class CaptionRenderer:
    SIZE = 80

    def __init__(self, pal: dict, top_of: callable):
        self.plain = Style(sans(self.SIZE), pal["caption"], -0.045)
        self.accent = Style(serif(int(self.SIZE * 1.22)), pal["caption_accent"], -0.005)
        self.pal = pal
        self.top_of = top_of

    def render(self, frame: Image.Image, ch: Chunk, t: float):
        size = self.SIZE
        space = size * 0.24
        toks = [(w, self.accent if w.key else self.plain) for w in ch.words]
        widths = [text_width(w.text, st) for w, st in toks]
        max_w = W - 2 * MARGIN_X - 2 * 40
        lines, cur = [[]], 0.0
        for i, (w, st) in enumerate(toks):
            add = widths[i] + (space if lines[-1] else 0)
            if lines[-1] and cur + add > max_w:
                lines.append([i]); cur = widths[i]
            else:
                lines[-1].append(i); cur += add

        line_h = size * 1.05
        block_h = int(line_h * len(lines) + 44)
        top = self.top_of(t)
        appear = ease_out_cubic((t - ch.start) / 0.18)

        txt = Image.new("RGBA", (W, block_h + 60), (0, 0, 0, 0))
        d = ImageDraw.Draw(txt)
        y = 22 + size * 0.82
        for ln in lines:
            lw = sum(widths[i] for i in ln) + space * (len(ln) - 1)
            x = (W - lw) / 2
            for i in ln:
                w, st = toks[i]
                p = (t - w.start + 0.05) / 0.16
                if p > 0:
                    a = ease_out_cubic(p)
                    dy = (1 - ease_out_back(p)) * 14
                    draw_tracked(d, (x, y + dy), w.text, st, int(255 * a))
                x += widths[i] + space
            y += line_h
        _blit(frame, _soft_shadow(txt), 0, top + 4, appear)
        _blit(frame, txt, 0, top, appear)


def _soft_shadow(layer: Image.Image) -> Image.Image:
    """Dark diffuse shadow from the text alpha — keeps light text legible on busy footage."""
    alpha = layer.getchannel("A")
    tight = alpha.filter(ImageFilter.GaussianBlur(2.5)).point(lambda v: int(min(255, v * 0.8)))
    wide = alpha.filter(ImageFilter.GaussianBlur(18)).point(lambda v: int(min(255, v * 1.1)))
    a = Image.fromarray(np.maximum(np.array(tight), np.array(wide)))
    sh = Image.new("RGBA", layer.size, (28, 14, 8, 0))
    sh.putalpha(a)
    return sh


def _blit(frame: Image.Image, img: Image.Image, x: int, y: int, alpha: float = 1.0):
    if alpha <= 0:
        return
    if alpha < 1:
        arr = np.array(img)
        arr[..., 3] = (arr[..., 3] * alpha).astype(np.uint8)
        img = Image.fromarray(arr)
    frame.alpha_composite(img, (max(x, 0), max(y, 0)), (max(-x, 0), max(-y, 0)))


# ---------- timeline ----------
class Timeline:
    IN, OUT = 0.32, 0.2

    def __init__(self, cfg: dict):
        pal = {k: hex_rgb(v) for k, v in cfg["palette"].items()}
        self.cards = [(c, build_card(c, pal)) for c in cfg["cards"]]
        self.pills = {i: build_pill(c["cta"], pal) for i, (c, _) in enumerate(self.cards) if c.get("cta")}
        self.chunks = build_chunks(cfg)
        self.caption_top = cfg.get("caption_top", CARD_TOP)
        self.captions = CaptionRenderer(pal, self._caption_top)

    def _active_card(self, t: float):
        for i, (c, layer) in enumerate(self.cards):
            if c["start"] <= t < c["end"]:
                return i, c, layer
        return None

    def _caption_top(self, t: float) -> int:
        act = self._active_card(t)
        if not act:
            return self.caption_top
        layer = act[2]
        return layer.y + layer.img.height - 40 + 28

    def frame(self, t: float) -> Image.Image:
        fr = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        act = self._active_card(t)
        if act:
            i, c, layer = act
            p_in = ease_out_cubic((t - c["start"]) / self.IN)
            nxt_start = self.cards[i + 1][0]["start"] if i + 1 < len(self.cards) else 1e9
            gap = nxt_start - c["end"] > 0.05 or i + 1 == len(self.cards)
            p_out = ease_out_cubic((c["end"] - t) / self.OUT) if gap else 1.0
            a = min(p_in, p_out)
            _blit(fr, layer.img, layer.x - int((1 - p_in) * 40), layer.y, a)
            if i in self.pills:
                pill = self.pills[i]
                pp = ease_out_back((t - c["start"] - 0.6) / 0.4)
                if pp > 0:
                    _blit(fr, pill.img, pill.x, pill.y + int((1 - pp) * 30), min(1.0, max(pp, 0)))
        for ch in self.chunks:
            if ch.start - 0.02 <= t < ch.end:
                self.captions.render(fr, ch, t)
                break
        return fr


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--preview", type=float, nargs="*", help="render still frames at these times")
    ap.add_argument("--config", default="edit.json", help="project config, relative to repo root")
    args = ap.parse_args()
    cfg = json.loads((ROOT / args.config).read_text())
    tl = Timeline(cfg)
    src = ROOT / cfg["video"]

    if args.preview:
        out = ROOT / "output/preview" / Path(args.config).stem
        out.mkdir(parents=True, exist_ok=True)
        for t in args.preview:
            bg = subprocess.run(["ffmpeg", "-v", "error", "-ss", str(t), "-i", str(src), "-frames:v", "1",
                                 "-f", "rawvideo", "-pix_fmt", "rgba", "-"], capture_output=True, check=True).stdout
            img = Image.frombytes("RGBA", (W, H), bg)
            img.alpha_composite(tl.frame(t))
            img.convert("RGB").save(out / f"t{t:05.2f}.jpg", quality=88)
        return

    duration = float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0",
                                     str(src)], capture_output=True, text=True, check=True).stdout)
    dst = ROOT / cfg["output"]
    dst.parent.mkdir(parents=True, exist_ok=True)
    cmd = ["ffmpeg", "-v", "error", "-y", "-i", str(src),
           "-f", "rawvideo", "-pix_fmt", "rgba", "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-",
           "-filter_complex", "[0:v]fps=30,format=yuv420p[b];[b][1:v]overlay=format=auto:shortest=1,format=yuv420p[v]",
           "-map", "[v]", "-map", "0:a", "-c:v", "libx264", "-preset", "slow", "-crf", "18",
           "-profile:v", "high", "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", str(dst)]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    n = int(duration * FPS)
    for f in range(n):
        proc.stdin.write(tl.frame(f / FPS).tobytes())
        if f % 150 == 0:
            print(f"frame {f}/{n}", flush=True)
    proc.stdin.close()
    proc.wait()
    print("done ->", dst)


if __name__ == "__main__":
    main()
