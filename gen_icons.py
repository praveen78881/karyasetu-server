"""Generate KaryaSetu PWA icons with Pillow.

Motif: a marigold "setu" (bridge arch) with a rising sun dot on deep indigo —
simple geometry that stays crisp at every size.
"""
import os

from PIL import Image, ImageDraw

INDIGO = (26, 46, 90, 255)       # #1A2E5A
INDIGO_DEEP = (16, 31, 60, 255)  # #101F3C
MARIGOLD = (232, 163, 61, 255)   # #E8A33D
IVORY = (250, 247, 242, 255)     # #FAF7F2

OUT = os.path.join(os.path.dirname(__file__), "static", "icons")


def rounded_bg(size, radius_ratio=0.22):
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    r = int(size * radius_ratio)
    d.rounded_rectangle([0, 0, size - 1, size - 1], radius=r, fill=INDIGO)
    # Subtle top-glow band for depth
    band = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    bd = ImageDraw.Draw(band)
    bd.rounded_rectangle([0, 0, size - 1, int(size * 0.55)], radius=r,
                         fill=(255, 255, 255, 14))
    img = Image.alpha_composite(img, band)
    return img


def draw_motif(img, pad_ratio=0.0):
    """Bridge arch + sun, scaled into the icon with optional extra padding
    (maskable icons need a bigger safe zone)."""
    size = img.width
    d = ImageDraw.Draw(img)
    scale = 1.0 - pad_ratio
    cx = size / 2
    unit = size * scale

    stroke = max(3, int(unit * 0.075))
    # Arch: upper half of an ellipse
    arch_w = unit * 0.62
    arch_h = unit * 0.52
    top = size / 2 - arch_h * 0.28
    bbox = [cx - arch_w / 2, top, cx + arch_w / 2, top + arch_h * 2]
    d.arc(bbox, start=180, end=360, fill=MARIGOLD, width=stroke)
    # Deck line under the arch
    deck_y = top + arch_h * 0.98
    deck_w = unit * 0.74
    d.line([cx - deck_w / 2, deck_y, cx + deck_w / 2, deck_y],
           fill=IVORY, width=max(2, int(stroke * 0.6)))
    # Sun dot above the arch
    sun_r = unit * 0.075
    sun_cy = top - unit * 0.10
    d.ellipse([cx - sun_r, sun_cy - sun_r, cx + sun_r, sun_cy + sun_r],
              fill=MARIGOLD)
    return img


def make(size, name, maskable=False):
    img = rounded_bg(size, radius_ratio=0.0 if maskable else 0.22)
    if maskable:
        # Full-bleed square background; motif inside the 80% safe zone.
        img = Image.new("RGBA", (size, size), INDIGO)
        band = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        bd = ImageDraw.Draw(band)
        bd.rectangle([0, 0, size, int(size * 0.55)], fill=(255, 255, 255, 14))
        img = Image.alpha_composite(img, band)
        draw_motif(img, pad_ratio=0.30)
    else:
        draw_motif(img, pad_ratio=0.14)
    img.save(os.path.join(OUT, name))
    print("wrote", name)


if __name__ == "__main__":
    os.makedirs(OUT, exist_ok=True)
    make(512, "icon-512.png")
    make(192, "icon-192.png")
    make(512, "icon-maskable-512.png", maskable=True)
    make(192, "icon-maskable-192.png", maskable=True)
    make(180, "apple-touch-icon.png")
    # Favicon
    img = rounded_bg(64, radius_ratio=0.22)
    draw_motif(img, pad_ratio=0.06)
    img.save(os.path.join(OUT, "favicon.png"))
    print("wrote favicon.png")
