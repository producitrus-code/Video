"""Put a brand title card (cream, brown heavy sans + terracotta serif accent) on a still image.

Usage: python3 title_image.py --image in.png --title "texto com *destaque*" [--label ""] [--top 240] --out out.jpg
The image is scaled to 1080 px wide so the card matches the video templates exactly.
"""
from __future__ import annotations

import argparse
from pathlib import Path

from PIL import Image

from PIL import ImageDraw

from render import (MARGIN_X, ROOT, W, Style, _soft_shadow, build_card, draw_tracked, hex_rgb, sans, serif,
                    tokenize_rich, wrap)

PALETTE = {"brown": "#4E2C22", "terracotta": "#C8665E", "cream": "#F4EFE9",
           "light": "#FBF7F2", "light_accent": "#F2A69C"}


def text_layer(title: str, pal: dict, size: int, center_y: int, light: bool) -> Image.Image:
    """Centered title without a box: heavy sans + serif accent, for use with a soft shadow."""
    plain = Style(sans(size), pal["light" if light else "brown"], -0.055)
    accent = Style(serif(int(size * 1.2)), pal["light_accent" if light else "terracotta"], -0.01)
    space, line_h = size * 0.22, size * 1.0
    lines = wrap(tokenize_rich(title, plain, accent), W - 2 * MARGIN_X, space)
    layer = Image.new("RGBA", (W, round(center_y * 2 + line_h * len(lines))), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    y = center_y - line_h * len(lines) / 2 + size * 0.8
    for line in lines:
        lw = sum(tk.width for tk in line) + space * (len(line) - 1)
        x = (W - lw) / 2
        for tk in line:
            draw_tracked(d, (x, y), tk.text, tk.style)
            x += tk.width + space
        y += line_h
    return layer


def light_glow(layer: Image.Image) -> Image.Image:
    """Soft cream halo — lifts dark text off busy or mid-tone backgrounds."""
    sh = _soft_shadow(layer)
    sh.putalpha(sh.getchannel("A").point(lambda v: int(v * 0.9)))
    glow = Image.new("RGBA", layer.size, (251, 247, 242, 0))
    glow.putalpha(sh.getchannel("A"))
    return glow


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--image", required=True)
    ap.add_argument("--title", required=True, help="wrap accent words in *asterisks*")
    ap.add_argument("--label", default="")
    ap.add_argument("--top", type=int, default=240, help="card top (px, at 1080 width)")
    ap.add_argument("--out", required=True)
    ap.add_argument("--style", choices=["card", "light", "dark"], default="card",
                    help="card: cream box; light: cream text + dark shadow; dark: brown text + soft glow")
    ap.add_argument("--center-y", type=int, default=300, help="vertical center of the text block (no-box styles)")
    ap.add_argument("--size", type=int, default=104)
    a = ap.parse_args()

    src = Image.open(a.image).convert("RGBA")
    img = src.resize((W, round(src.height * W / src.width)), Image.LANCZOS)
    pal = {k: hex_rgb(v) for k, v in PALETTE.items()}
    if a.style == "card":
        card = build_card({"label": a.label, "title": a.title, "hero": True}, pal)
        img.alpha_composite(card.img, (card.x, a.top - 40))
    else:
        layer = text_layer(a.title, pal, a.size, a.center_y, light=a.style == "light")
        canvas = Image.new("RGBA", img.size, (0, 0, 0, 0))
        canvas.alpha_composite(layer.crop((0, 0, W, min(layer.height, img.height))))
        halo = _soft_shadow(canvas) if a.style == "light" else light_glow(canvas)
        img.alpha_composite(halo, (0, 4) if a.style == "light" else (0, 0))
        img.alpha_composite(canvas)
    out = ROOT / a.out
    out.parent.mkdir(parents=True, exist_ok=True)
    img.convert("RGB").save(out, quality=95)
    print(out)


if __name__ == "__main__":
    main()
