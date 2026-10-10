#!/usr/bin/env python3
"""Add a new image to the Instagram publishing catalog.

Usage:
    python add_image.py ruta/foto.jpg [--product olivo] [--caption "..."] [--tags "a,b,c"]

What it does:
1. Validates the source file (exists, <8 MB).
2. Center-crops / resizes to 1080x1350 (4:5) — the ratio that works for
   both Stories and Feed.
3. Saves it into media/ with a unique name (slug + timestamp).
4. Appends the entry to media/playlist.json (rotation order).
5. Adds it to images.json (product + desc + tags) so the AI writer uses it.
6. If the product doesn't exist in products.json yet, creates a placeholder
   for it (fill its "benefits"/"cta" afterwards).
7. Stages the files with `git add` and prints the public CDN URL.

Then you just run: git push
"""
from __future__ import annotations

import argparse
import json
import os
import random
import re
import subprocess
import sys
import time
from pathlib import Path

from PIL import Image

HERE = Path(__file__).resolve().parent
MEDIA = HERE / "media"
PLAYLIST = MEDIA / "playlist.json"
IMAGES = HERE / "images.json"
PRODUCTS = HERE / "products.json"

W, H = 1080, 1350  # 4:5
RATIO = W / H
MAX_BYTES = 8 * 1024 * 1024


def load_json(path: Path, default):
    if path.exists():
        try:
            return json.loads(path.read_text())
        except Exception:
            pass
    return default


def slugify(stem: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", stem.lower()).strip("-")
    return s or "imagen"


def crop_4x5(src: Path, dst: Path) -> None:
    im = Image.open(src).convert("RGB")
    iw, ih = im.size
    if iw / ih > RATIO:  # too wide
        new_w = int(ih * RATIO)
        x = (iw - new_w) // 2
        box = (x, 0, x + new_w, ih)
    else:  # too tall
        new_h = int(iw / RATIO)
        y = (ih - new_h) // 2
        box = (0, y, iw, y + new_h)
    im.crop(box).resize((W, H), Image.LANCZOS).save(dst, "JPEG", quality=88)


def unique_name(stem: str) -> str:
    base = slugify(stem)
    for _ in range(10):
        name = f"{base}-{time.strftime('%H%M%S')}{random.randint(0, 99):02d}.jpg"
        if not (MEDIA / name).exists():
            return name
    return f"{base}-{random.randint(100000, 999999)}.jpg"


def main() -> None:
    parser = argparse.ArgumentParser(description="Add an image to the Instagram catalog.")
    parser.add_argument("source", help="path to the original photo (jpg/png)")
    parser.add_argument("--product", default="olivo", help="product this image belongs to (products.json)")
    parser.add_argument("--caption", default="", help="optional static caption (fallback for feed posts)")
    parser.add_argument("--tags", default="", help="comma separated tags for the AI writer")
    args = parser.parse_args()

    src = Path(args.source)
    if not src.exists():
        sys.exit(f"[ERROR] no existe: {src}")
    if src.stat().st_size > MAX_BYTES:
        sys.exit(f"[ERROR] supera 8 MB ({src.stat().st_size/1024/1024:.1f} MB)")

    MEDIA.mkdir(exist_ok=True)
    name = unique_name(src.stem)
    dst = MEDIA / name
    crop_4x5(src, dst)
    print(f"[ok] imagen lista: media/{name} (1080x1350)")

    playlist = load_json(PLAYLIST, [])
    item = {"file": name}
    if args.caption.strip():
        item["caption"] = args.caption.strip()
    playlist.append(item)
    PLAYLIST.write_text(json.dumps(playlist, ensure_ascii=False, indent=2) + "\n")

    index = load_json(IMAGES, {})
    tags = [t.strip() for t in args.tags.split(",") if t.strip()]
    index[name] = {"product": args.product, "desc": src.stem, "tags": tags}
    IMAGES.write_text(json.dumps(index, ensure_ascii=False, indent=2) + "\n")

    products = load_json(PRODUCTS, {"products": {}})
    if args.product not in products.setdefault("products", {}):
        products["products"][args.product] = {"name": args.product, "benefits": "", "cta": []}
        PRODUCTS.write_text(json.dumps(products, ensure_ascii=False, indent=2) + "\n")
        print(f"[i] producto '{args.product}' creado en products.json — rellena 'benefits' y 'cta'")

    subprocess.run(
        ["git", "add", str(dst), str(PLAYLIST), str(IMAGES), str(PRODUCTS)],
        check=False,
    )

    try:
        from dotenv import load_dotenv
        load_dotenv(HERE / ".env")
        base = os.getenv("PUBLIC_BASE_URL", "").rstrip("/")
        url = f"{base}/{name}" if base else "(PUBLIC_BASE_URL no definido en .env)"
    except Exception:
        url = f"https://cdn.jsdelivr.net/gh/<user>/<repo>@main/media/{name}"

    print(f"[ok] playlist.json + images.json actualizados (producto={args.product}, tags={tags}).")
    print(f"[ok] git add hecho — solo falta: git push")
    print(f"URL publica: {url}")


if __name__ == "__main__":
    main()