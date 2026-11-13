"""Poster-style Reels cover: plain background, big headline + serif subtitle, photo in a rounded card.

Mirrors the brand carousel layout (headline on a flat neutral background). Built for small/low-res photos:
the photo is shown as a card instead of full-bleed, so upscaling stays modest.

Usage: python3 poster_cover.py --photo source/v3/capa_foto.jpg --title "STOP THE|WEDDING" \
         --subtitle "entenda a trend do momento" --out output/capas/stw-capa-foto.jpg
"""
from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

from render import H, MARGIN_X, ROOT, W, Style, draw_tracked, hex_rgb, sans, serif, text_width

BROWN, TERRACOTTA = hex_rgb("#4E2C22"), hex_rgb("#C8665E")
BG_TOP, BG_BOTTOM = hex_rgb("#E7E3DE"), hex_rgb("#D3CFCA")
GRID_SAFE_TOP = 285


def gradient_bg() -> Image.Image:
    t = np.linspace(0, 1, H, dtype=np.float32)[:, None, None]
    top, bot = np.array(BG_TOP, np.float32), np.array(BG_BOTTOM, np.float32)
    arr = np.broadcast_to(top + (bot - top) * t, (H, W, 3)).astype(np.uint8)
    return Image.fromarray(arr).convert("RGBA")


def fit_size(lines: list[str], max_w: int, start: int = 220) -> int:
    size = start
    while size > 60 and max(text_width(l, Style(sans(size), BROWN, -0.06)) for l in lines) > max_w:
        size -= 4
    return size


def photo_card(path: Path, width: int, radius: int = 34) -> Image.Image:
    src = Image.open(path).convert("RGB")
    h = int(width * src.height / src.width)
    photo = src.resize((width, h), Image.LANCZOS).filter(ImageFilter.UnsharpMask(radius=2, percent=60, threshold=2))
    mask = Image.new("L", (width, h), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, width, h), radius, fill=255)
    pad = 50
    card = Image.new("RGBA", (width + 2 * pad, h + 2 * pad), (0, 0, 0, 0))
    shadow = Image.new("RGBA", card.size, (0, 0, 0, 0))
    ImageDraw.Draw(shadow).rounded_rectangle((pad, pad + 14, pad + width, pad + h + 14), radius, fill=(40, 20, 12, 90))
    card = Image.alpha_composite(card, shadow.filter(ImageFilter.GaussianBlur(22)))
    card.paste(photo, (pad, pad), mask)
    return card


def build(photo: Path, title: str, subtitle: str) -> Image.Image:
    img = gradient_bg()
    d = ImageDraw.Draw(img)
    lines = [l.strip() for l in title.split("|")]
    size = fit_size(lines, W - 2 * MARGIN_X)
    head = Style(sans(size), BROWN, -0.06)
    sub_size = int(size * 0.5)
    while text_width(subtitle, Style(serif(sub_size), TERRACOTTA, -0.01)) > W - 2 * MARGIN_X:
        sub_size -= 2
    sub = Style(serif(sub_size), TERRACOTTA, -0.01)

    y = GRID_SAFE_TOP + 40 + size * 0.74
    for i, line in enumerate(lines):
        draw_tracked(d, (MARGIN_X - size * 0.04, y), line, head)
        if i < len(lines) - 1:
            y += size * 0.88
    y += sub.font.size * 1.15
    draw_tracked(d, (MARGIN_X, y), subtitle, sub)

    card = photo_card(photo, W - 2 * MARGIN_X)
    img.alpha_composite(card, (MARGIN_X - 50, int(y + sub.font.size * 0.55) - 50))
    return img.convert("RGB")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--photo", required=True)
    ap.add_argument("--title", required=True, help="use | to break lines")
    ap.add_argument("--subtitle", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    out = ROOT / a.out
    out.parent.mkdir(parents=True, exist_ok=True)
    build(ROOT / a.photo, a.title, a.subtitle).save(out, quality=95)
    print(out)


if __name__ == "__main__":
    main()
