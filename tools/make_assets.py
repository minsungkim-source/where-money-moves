"""아이콘 PNG와 링크 미리보기(OG) 이미지를 static/에 만든다. 데이터와 무관하므로 한 번만 돌리면 된다.

  python tools/make_assets.py

OG 이미지에 숫자를 넣지 않는다 — 새 달 데이터가 나와도 낡은 숫자가 링크 카드에 남지 않게.
글자는 tools/text_png.swift(macOS CoreText, Thonburi)가 그린다 — 이 PIL에는 libraqm이 없어
태국어 모음·성조 기호를 제자리에 얹지 못하고 점선 원으로 깨뜨린다.
"""

import json
import subprocess
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw

STATIC = Path(__file__).resolve().parent.parent / "static"
GREEN, MINT, BG = (11, 122, 85), (159, 240, 200), (11, 31, 26)
TOOLS = Path(__file__).resolve().parent


def icon(size: int) -> Image.Image:
    s = size / 64
    im = Image.new("RGBA", (size, size), GREEN + (255,))
    d = ImageDraw.Draw(im)
    for x, y, h in ((12, 36, 16), (27.5, 27, 25), (43, 17, 35)):
        d.rounded_rectangle([x * s, y * s, (x + 9) * s, (y + h) * s], radius=2 * s, fill="white")
    w = max(2, round(4 * s))
    d.line([(12 * s, 27 * s), (28 * s, 16 * s), (36 * s, 21 * s), (50 * s, 10 * s)], fill=MINT, width=w, joint="curve")
    d.line([(42 * s, 9 * s), (51 * s, 9 * s), (51 * s, 18 * s)], fill=MINT, width=w, joint="curve")
    return im


def og(lang: str):
    W, H = 1200, 630
    im = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(im)
    # 바닥의 막대들 — 사이트의 순차 램프
    ramp = [(27, 44, 38), (29, 63, 51), (30, 88, 67), (31, 116, 84), (40, 146, 103), (65, 179, 127), (116, 226, 170)]
    for i in range(24):
        h = 60 + (i * 37 % 170) + i * 6
        d.rounded_rectangle([60 + i * 46, H - 40 - h, 60 + i * 46 + 34, H - 40], radius=6, fill=ramp[min(6, i * 7 // 24)])
    im.paste(icon(96), (60, 56), icon(96))
    lines = {
        "th": [("เงินไหลไปไหน", 74, True, "ffffff", (180, 52)),
               ("Where Money Moves · Thailand", 34, False, "9ff0c8", (182, 150)),
               ("อำเภอไหนเงินฝากและสินเชื่อโตเร็วที่สุด", 36, False, "e8f2ee", (60, 214)),
               ("ข้อมูลธนาคารแห่งประเทศไทย รายเดือน", 32, False, "9db5ab", (60, 268))],
        "en": [("Where Money Moves", 70, True, "ffffff", (180, 58)),
               ("Thailand · เงินไหลไปไหน", 34, False, "9ff0c8", (182, 150)),
               ("Which districts are growing deposits and credit fastest", 36, False, "e8f2ee", (60, 214)),
               ("Monthly Bank of Thailand data, by district", 32, False, "9db5ab", (60, 268))],
    }[lang]
    with tempfile.TemporaryDirectory() as tmp:
        specs = [{"text": t, "size": sz, "bold": b, "color": c, "out": f"{tmp}/{i}.png"}
                 for i, (t, sz, b, c, _) in enumerate(lines)]
        Path(tmp, "specs.json").write_text(json.dumps(specs, ensure_ascii=False), encoding="utf-8")
        subprocess.run(["swift", str(TOOLS / "text_png.swift"), f"{tmp}/specs.json"], check=True)
        for i, (*_, xy) in enumerate(lines):
            layer = Image.open(f"{tmp}/{i}.png").convert("RGBA")
            im.paste(layer, xy, layer)
    im.save(STATIC / f"og-{lang}.png", optimize=True)


if __name__ == "__main__":
    icon(192).save(STATIC / "icon-192.png")
    icon(512).save(STATIC / "icon-512.png")
    og("th")
    og("en")
    print("static/: icon-192.png icon-512.png og-th.png og-en.png")
