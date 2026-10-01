"""Generate Android launcher icons from the PWA icon."""
import os

from PIL import Image

BASE = os.path.dirname(__file__)
SRC = os.path.join(BASE, "..", "static", "icons", "icon-512.png")
SIZES = {"mdpi": 48, "hdpi": 72, "xhdpi": 96, "xxhdpi": 144, "xxxhdpi": 192}

img = Image.open(SRC)
for density, size in SIZES.items():
    out_dir = os.path.join(BASE, "res", f"mipmap-{density}")
    os.makedirs(out_dir, exist_ok=True)
    img.resize((size, size), Image.LANCZOS).save(os.path.join(out_dir, "ic_launcher.png"))
    print(f"mipmap-{density}/ic_launcher.png ({size}px)")
