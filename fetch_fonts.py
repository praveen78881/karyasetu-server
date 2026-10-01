"""Download the app's fonts from Google Fonts for self-hosting (offline PWA).

Fetches latin-subset woff2 files for Poppins, Mukta and Rozha One and writes
static/css/fonts.css. Run once during setup:  python fetch_fonts.py
"""
import os
import re
import urllib.request

FAMILIES = [
    ("Poppins", [400, 500, 600, 700]),
    ("Mukta", [400, 500, 600, 700]),
    ("Rozha One", [400]),
]
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0 Safari/537.36")  # woff2-capable UA

BASE = os.path.dirname(__file__)
FONT_DIR = os.path.join(BASE, "static", "fonts")
CSS_PATH = os.path.join(BASE, "static", "css", "fonts.css")


def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read()


def main():
    os.makedirs(FONT_DIR, exist_ok=True)
    css_out = ["/* Self-hosted Google Fonts (latin subset) — see fetch_fonts.py */"]
    for family, weights in FAMILIES:
        fam_q = family.replace(" ", "+")
        wght = ";".join(str(w) for w in weights)
        url = (f"https://fonts.googleapis.com/css2?family={fam_q}:wght@{wght}"
               f"&display=swap")
        css = fetch(url).decode("utf-8")
        # Split into subset-labelled @font-face blocks and keep the latin ones.
        blocks = re.findall(r"/\*\s*(\S+)\s*\*/\s*(@font-face\s*\{[^}]+\})", css)
        for subset, block in blocks:
            if subset != "latin":
                continue
            weight = re.search(r"font-weight:\s*(\d+)", block).group(1)
            src = re.search(r"url\((https://[^)]+\.woff2)\)", block).group(1)
            slug = family.lower().replace(" ", "-")
            fname = f"{slug}-{weight}.woff2"
            with open(os.path.join(FONT_DIR, fname), "wb") as f:
                f.write(fetch(src))
            local = block.replace(src, f"/static/fonts/{fname}")
            css_out.append(f"/* {family} {weight} latin */\n{local}")
            print("fetched", fname)
    with open(CSS_PATH, "w", encoding="utf-8") as f:
        f.write("\n".join(css_out) + "\n")
    print("wrote static/css/fonts.css")


if __name__ == "__main__":
    main()
