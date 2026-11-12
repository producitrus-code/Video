"""Generate a Reels cover (1080x1920) from a video frame, in the same type system as render.py.

Usage: python3 cover.py --config projects/docinhos.json --time 51.5 \
         --label "mesa de doces" --title "o doce que *não pode* faltar no seu casamento" --out output/capa.jpg

The title stays inside the 4:5 grid-safe area (y 285–1635) so the profile grid crop keeps it whole.
"""
from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

from PIL import Image

from render import H, ROOT, W, build_card, hex_rgb

GRID_SAFE_BOTTOM = 1635


def grab_frame(video: Path, t: float) -> Image.Image:
    raw = subprocess.run(["ffmpeg", "-v", "error", "-ss", str(t), "-i", str(video), "-frames:v", "1",
                          "-f", "rawvideo", "-pix_fmt", "rgba", "-"], capture_output=True, check=True).stdout
    return Image.frombytes("RGBA", (W, H), raw)


def build_cover(cfg: dict, t: float, label: str, title: str) -> Image.Image:
    """Frame + brand title card (cream, brown heavy sans, terracotta serif accent) at the grid-safe bottom."""
    pal = {k: hex_rgb(v) for k, v in cfg["palette"].items()}
    img = grab_frame(ROOT / cfg["video"], t)
    card = build_card({"label": label, "title": title, "hero": True}, pal)
    shadow_pad = 40
    y = GRID_SAFE_BOTTOM - 40 - (card.img.height - shadow_pad)
    img.alpha_composite(card.img, (card.x, y))
    return img.convert("RGB")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True)
    ap.add_argument("--time", type=float, required=True)
    ap.add_argument("--label", required=True)
    ap.add_argument("--title", required=True, help="wrap accent words in *asterisks*")
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    cfg = json.loads((ROOT / a.config).read_text())
    out = ROOT / a.out
    out.parent.mkdir(parents=True, exist_ok=True)
    build_cover(cfg, a.time, a.label, a.title).save(out, quality=95)
    print(out)


if __name__ == "__main__":
    main()
