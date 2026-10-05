#!/usr/bin/env python3
"""Prepare brand images for Instagram: center-crop to 4:5 (1080x1350).

4:5 is accepted by BOTH Stories and Feed through the Graph API, so a single
crop covers the whole pipeline. Originals live in stories/originals/ and this
writes the ready-to-publish files into stories/ with a -v2 suffix (fresh CDN
cache).

Usage:
    python prepare.py
"""
from pathlib import Path

from PIL import Image

HERE = Path(__file__).resolve().parent
SRC = HERE / "stories" / "originals"
DST = HERE / "stories"
W, H = 1080, 1350  # 4:5
RATIO = W / H

if not SRC.exists():
    raise SystemExit("[ERROR] stories/originals/ not found")

ok = 0
for img in sorted(SRC.iterdir()):
    if img.suffix.lower() not in (".jpg", ".jpeg", ".png"):
        continue
    im = Image.open(img).convert("RGB")
    iw, ih = im.size
    if iw / ih > RATIO:  # too wide -> crop width
        new_w = int(ih * RATIO)
        x = (iw - new_w) // 2
        box = (x, 0, x + new_w, ih)
    else:                # too tall -> crop height (center)
        new_h = int(iw / RATIO)
        y = (ih - new_h) // 2
        box = (0, y, iw, y + new_h)
    cropped = im.crop(box).resize((W, H), Image.LANCZOS)
    out = DST / f"{img.stem}-v2.jpg"
    cropped.save(out, "JPEG", quality=88)
    print(f"{img.name} ({iw}x{ih}) -> {out.name} (1080x1350)")
    ok += 1

print(f"\nPreparadas {ok} imágenes en stories/")
print("Actualiza stories/playlist.json con los nombres -v2 y haz push.")