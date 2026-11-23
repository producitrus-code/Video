"""Put a brand title card (cream, brown heavy sans + terracotta serif accent) on a still image.

Usage: python3 title_image.py --image in.png --title "texto com *destaque*" [--label ""] [--top 240] --out out.jpg
The image is scaled to 1080 px wide so the card matches the video templates exactly.
"""
from __future__ import annotations

import argparse
from pathlib import Path

from PIL import Image

from render import ROOT, W, build_card, hex_rgb

PALETTE = {"brown": "#4E2C22", "terracotta": "#C8665E", "cream": "#F4EFE9"}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--image", required=True)
    ap.add_argument("--title", required=True, help="wrap accent words in *asterisks*")
    ap.add_argument("--label", default="")
    ap.add_argument("--top", type=int, default=240, help="card top (px, at 1080 width)")
    ap.add_argument("--out", required=True)
    a = ap.parse_args()

    src = Image.open(a.image).convert("RGBA")
    img = src.resize((W, round(src.height * W / src.width)), Image.LANCZOS)
    pal = {k: hex_rgb(v) for k, v in PALETTE.items()}
    card = build_card({"label": a.label, "title": a.title, "hero": True}, pal)
    img.alpha_composite(card.img, (card.x, a.top - 40))
    out = ROOT / a.out
    out.parent.mkdir(parents=True, exist_ok=True)
    img.convert("RGB").save(out, quality=95)
    print(out)


if __name__ == "__main__":
    main()
