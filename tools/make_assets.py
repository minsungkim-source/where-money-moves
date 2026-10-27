"""Icon PNGs and the link-preview (OG) image in static/. Run after the data changes enough to matter.

  python tools/make_assets.py

The OG image carries no numbers, so a new month of data never leaves a stale figure on a link card.
The map is coloured by the current Momentum rank, which only shifts slowly.
Text is drawn by tools/text_png.swift (macOS CoreText): this PIL has no libraqm, which Thai
and other complex scripts need.
"""

import json
import math
import subprocess
import sys
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent.parent
STATIC = ROOT / "static"
TOOLS = Path(__file__).resolve().parent
INK, PAPER, SEA, LAND, CURRENT = (23, 33, 43), (246, 247, 244), (213, 226, 232), (230, 232, 225), (15, 123, 133)
RAMP = [(240, 231, 207), (216, 224, 198), (174, 210, 193), (127, 189, 180), (81, 161, 162), (42, 129, 136), (13, 93, 104)]


def icon(size: int) -> Image.Image:
    s = size / 64
    im = Image.new("RGBA", (size, size), INK + (255,))
    d = ImageDraw.Draw(im)
    for x, y, h, c in ((12, 36, 16, RAMP[2]), (27.5, 27, 25, RAMP[4]), (43, 17, 35, (255, 255, 255))):
        d.rounded_rectangle([x * s, y * s, (x + 9) * s, (y + h) * s], radius=2 * s, fill=c)
    return im


def text_layers(lines, tmp):
    specs = [{"text": t, "size": sz, "bold": b, "color": c, "out": f"{tmp}/{i}.png"} for i, (t, sz, b, c, _) in enumerate(lines)]
    Path(tmp, "specs.json").write_text(json.dumps(specs, ensure_ascii=False), encoding="utf-8")
    subprocess.run(["swift", str(TOOLS / "text_png.swift"), f"{tmp}/specs.json"], check=True)
    return [Image.open(f"{tmp}/{i}.png").convert("RGBA") for i in range(len(lines))]


def og():
    sys.path.insert(0, str(ROOT))
    import build                                     # reuse the site's own model for the map colours
    geo = json.load(open(ROOT / "data" / "reference" / "sea.geo.json"))
    R = build.region_model(json.load(open(ROOT / "data" / "processed" / "sea_wb.json")))

    W, H = 1200, 630
    im = Image.new("RGB", (W, H), PAPER)
    d = ImageDraw.Draw(im)
    mx0, mw, mh = 640, 560, 630                      # right: the sea chart
    d.rectangle([mx0, 0, W, H], fill=SEA)
    lon0, lon1, lat0, lat1 = 91.0, 142.0, -12.0, 29.0
    k = math.cos(math.radians(8))
    sc = min(mw / ((lon1 - lon0) * k), mh / (lat1 - lat0))
    P = lambda lon, lat: (mx0 + (lon - lon0) * k * sc, (lat1 - lat) * sc + 10)
    for lon in range(95, 145, 5):
        d.line([P(lon, lat1), P(lon, lat0 - 3)], fill=(195, 211, 219), width=1)
    for lat in range(-10, 30, 5):
        d.line([P(lon0, lat), P(lon1 + 3, lat)], fill=(195, 211, 219), width=1)
    for f in geo["features"]:
        col = LAND
        if f["sea"]:
            s = R[f["iso3"]]["score"]
            col = RAMP[min(6, int((s or 0) / (100 / 7)))]
        for ring in f["rings"]:
            d.polygon([P(x, y) for x, y in ring], fill=col, outline=PAPER)
    d.rectangle([0, 0, mx0, H], fill=PAPER)
    im.paste(icon(84), (64, 64), icon(84))
    lines = [("Where Money Moves", 54, True, "17212b", (64, 182)),
             ("See where people, jobs,", 32, False, "17212b", (66, 270)),
             ("businesses and money are moving", 32, False, "17212b", (66, 314)),
             ("across Southeast Asia.", 32, False, "17212b", (66, 358)),
             ("11 countries, 77 Thai provinces, 264 districts", 24, False, "5b6670", (66, 520))]
    with tempfile.TemporaryDirectory() as tmp:
        for layer, (*_, xy) in zip(text_layers(lines, tmp), lines):
            im.paste(layer, xy, layer)
    d.rectangle([66, 456, 66 + 120, 460], fill=CURRENT)
    im.save(STATIC / "og.png", optimize=True)


if __name__ == "__main__":
    icon(192).save(STATIC / "icon-192.png")
    icon(512).save(STATIC / "icon-512.png")
    og()
    for old in ("og-th.png", "og-en.png"):
        (STATIC / old).unlink(missing_ok=True)
    print("static/: icon-192.png icon-512.png og.png")
