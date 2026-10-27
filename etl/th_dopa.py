"""
Thailand — DOPA registered population and households by province (December, yearly).

  python etl/th_dopa.py [--use-cache]   → data/processed/th_dopa.json

People lens. "Registered" means people whose name is on a house registration (ทะเบียนบ้าน):
Thai nationals and registered foreigners at their *registered* address. It undercounts places
people move to without re-registering (Bangkok, EEC factory towns) and omits most migrant
workers, so it is a conservative signal of where people are moving.

Source: catalog.dopa.go.th dataset 221a73a3-… (Open Data Common). One zip per Buddhist year;
we read only `stat_c{yy}.xls`, which is actually a UTF-8 HTML table (not Excel):
  row 0 header · row 1 'ทั่วประเทศ' (whole kingdom) · then 77 provinces keyed by TIS-1099 code.
  'ปีเดือน' is YYMM in Buddhist years — 6712 = December 2024.
"""

from __future__ import annotations

import argparse
import html
import io
import json
import re
import sys
import zipfile
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))
from etl import OUT, RAW, HEADERS, ParserDriftError  # noqa: E402

PACKAGE = "https://catalog.dopa.go.th/api/3/action/package_show?id=221a73a3-2223-4fdc-a79e-6738ff40bb57"
FIRST_BE = 2562          # 2019 — five-year window plus a spare year
EXPECT_HEADER = ["ปีเดือน", "รหัสจังหวัด", "ชื่อจังหวัด"]


def fetch(use_cache: bool) -> dict[int, str]:
    """→ {buddhist_year: stat_c html}. Only the small province file is kept from each zip."""
    RAW.mkdir(parents=True, exist_ok=True)
    out = {int(p.stem.split("-")[-1]): p.read_text(encoding="utf-8") for p in RAW.glob("dopa-c-*.html")}
    if use_cache and out:
        print(f"  cache  {sorted(out)}")
        return out
    meta = requests.get(PACKAGE, headers=HEADERS, timeout=60).json()["result"]
    for r in meta["resources"]:
        m = re.search(r"stat_(\d\d)\.zip$", r["url"])
        if not m or 2500 + int(m.group(1)) < FIRST_BE:
            continue
        be = 2500 + int(m.group(1))
        if be in out:
            continue
        body = requests.get(r["url"], headers=HEADERS, timeout=300).content
        zf = zipfile.ZipFile(io.BytesIO(body))
        name = next((n for n in zf.namelist() if re.search(r"stat_c\d\d( \(\d\))?\.xls$", n)), None)
        if not name:
            raise ParserDriftError(f"DOPA {be}: no stat_c file in zip ({zf.namelist()})")
        text = zf.read(name).decode("utf-8-sig")
        (RAW / f"dopa-c-{be}.html").write_text(text, encoding="utf-8")
        out[be] = text
    print(f"  fetch  {sorted(out)}")
    return out


def parse(text: str, be: int) -> dict:
    rows = [[html.unescape(re.sub(r"<[^>]+>", "", c)).strip().lstrip("﻿")
             for c in re.findall(r"<td[^>]*>(.*?)</td>", r, re.S)]
            for r in re.findall(r"<tr[^>]*>(.*?)</tr>", text, re.S)]
    if rows[0][:3] != EXPECT_HEADER or len(rows[0]) != 13:
        raise ParserDriftError(f"DOPA {be}: header changed: {rows[0][:5]}")
    # 2566's file carries the same table twice. Accept repeats only if they are identical.
    starts = [i for i, r in enumerate(rows) if r[:1] == ["ปีเดือน"]] + [len(rows)]
    blocks = [rows[a:b] for a, b in zip(starts, starts[1:])]
    if any(b != blocks[0] for b in blocks[1:]):
        raise ParserDriftError(f"DOPA {be}: {len(blocks)} tables in one file and they differ")
    rows = blocks[0]
    num = lambda s: int(s.replace(",", ""))
    out, total = {}, None
    for r in rows[1:]:
        if r[0][:2] != str(be)[2:] or r[0][2:] != "12":
            raise ParserDriftError(f"DOPA {be}: period {r[0]!r} is not December {be}")
        code = r[1].zfill(2)
        rec = {"population": num(r[11]), "households": num(r[12])}
        if code == "00":
            total = rec
        else:
            out[code] = rec
    if len(out) != 77 or total is None:
        raise ParserDriftError(f"DOPA {be}: {len(out)} provinces")
    if sum(v["population"] for v in out.values()) != total["population"]:
        raise ParserDriftError(f"DOPA {be}: provinces do not add up to the kingdom total")
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--use-cache", action="store_true")
    args = ap.parse_args()
    print("DOPA registered population")
    years = {be - 543: parse(t, be) for be, t in sorted(fetch(args.use_cache).items())}
    ys = sorted(years)
    out = {
        "source": {"name": "Department of Provincial Administration — registered population by province",
                   "url": "https://catalog.dopa.go.th/dataset/221a73a3-2223-4fdc-a79e-6738ff40bb57",
                   "license": "Open Data Common", "as_of": f"{ys[-1]}-12"},
        "years": ys,
        "provinces": {tis: {str(y): years[y][tis] for y in ys} for tis in sorted(years[ys[-1]])},
    }
    OUT.mkdir(parents=True, exist_ok=True)
    json.dump(out, open(OUT / "th_dopa.json", "w"), ensure_ascii=False, indent=0)
    a, b = years[ys[-1]], years[ys[-2]]
    g = sum(v["population"] for v in a.values()) / sum(v["population"] for v in b.values()) - 1
    print(f"  {ys[0]}–{ys[-1]}  national registered population {g*100:+.2f}% (Dec/Dec)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
