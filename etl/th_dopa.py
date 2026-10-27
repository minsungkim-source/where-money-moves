"""
Thailand — DOPA registered population by province (December, yearly).

  python etl/th_dopa.py [--use-cache] [--allow-unreachable]   → data/processed/th_dopa.json

People lens. "Registered" means people whose name is on a house registration (ทะเบียนบ้าน): Thai nationals
and registered foreigners at their *registered* address. It undercounts places people move to without
re-registering (Bangkok, EEC factory towns) and omits most migrant workers, so read it as a conservative signal.

Source (since 2026-10-27): stat.bora.dopa.go.th, the registry's own statistics site. One static UTF-8 text
file per province per December, `new_stat/file/{yy}12/{yy}12cc{TIS}.txt` (yy = Buddhist year, 2 digits):
  · pipe-separated; first row is the province, then registry offices (อำเภอ/เขต, เทศบาล) and sub-districts
  · each row ends with … | male total | female total | grand total | (empty)
  · we keep only the first row's grand total, and require male + female = total
The year pages list one link per province; we follow those links rather than guessing the 77 codes.

Why not the open-data catalog (catalog.dopa.go.th, the previous source): it stops at December 2024 while
this site already has December 2025. For 2024 the two agree exactly (Bangkok 5,455,020) — pinned in
tests/test_etl.py.

District level is not taken from here yet: a district (อำเภอ) row counts only that office's registry, and
municipalities (เทศบาล) are separate rows, so a district total needs a municipality → district map.

Reachability: dopa.go.th hosts time out from GitHub's runners (outside Thailand). The monthly CI run passes
--allow-unreachable: a *connection* failure keeps the committed data and exits 0 with a warning; a *parse*
failure (ParserDriftError) still fails. etl/summary.py --stale flags the data once the next December is overdue.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from datetime import date
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))
from etl import OUT, RAW, HEADERS, ParserDriftError  # noqa: E402

SITE = "https://stat.bora.dopa.go.th/new_stat"
YEAR_PAGE = SITE + "/webPage/statByProvince.php?year={yy}"
FIRST_AD = 2020          # five-year change plus a chart; 6 years × 77 files


def december_years(today: date | None = None) -> list[int]:
    """AD years whose December is already over."""
    today = today or date.today()
    return list(range(FIRST_AD, today.year))


def links_for(session, ad: int) -> dict[str, str]:
    """{tis: url} for December of `ad`, read from that year's download page."""
    yy = (ad + 543) % 100
    page = session.get(YEAR_PAGE.format(yy=yy), headers=HEADERS, timeout=60)
    page.raise_for_status()
    return {m.group(1): f"{SITE}/file/{yy:02d}12/{yy:02d}12cc{m.group(1)}.txt"
            for m in re.finditer(rf'file/{yy:02d}12/{yy:02d}12cc(\d{{2}})\.txt', page.text)}


def parse(text: str, where: str) -> int:
    """Grand total of the province row (first row). Male + female must equal the total."""
    first = text.lstrip("﻿").splitlines()[0].split("|")
    name = first[0].strip()
    if not (name.startswith("จังหวัด") or name.startswith("กรุงเทพ")):
        raise ParserDriftError(f"DOPA {where}: first row is not a province: {name!r}")
    nums = [c.strip() for c in first[1:] if c.strip() != ""]
    try:
        male, female, total = (int(x) for x in nums[-3:])
    except ValueError:
        raise ParserDriftError(f"DOPA {where}: last three cells are not numbers: {nums[-3:]}")
    if male + female != total or total <= 0:
        raise ParserDriftError(f"DOPA {where}: male {male} + female {female} ≠ total {total}")
    return total


def fetch(use_cache: bool) -> dict[int, dict[str, str]]:
    """{ad_year: {tis: text}}. Cached per file in data/raw/dopa-stat/."""
    cache = RAW / "dopa-stat"
    cache.mkdir(parents=True, exist_ok=True)
    s = requests.Session()
    out: dict[int, dict[str, str]] = {}
    for ad in december_years():
        yy = (ad + 543) % 100
        cached = {p.stem[-2:]: p.read_text(encoding="utf-8") for p in cache.glob(f"{yy:02d}12cc??.txt")}
        if use_cache and len(cached) == 77:
            out[ad] = cached
            continue
        links = links_for(s, ad)
        if not links:                                         # December not published yet
            continue
        if len(links) != 77:
            raise ParserDriftError(f"DOPA {ad}: year page lists {len(links)} provinces, expected 77")
        texts = {}
        for tis, url in sorted(links.items()):
            if tis in cached:
                texts[tis] = cached[tis]
                continue
            r = s.get(url, headers=HEADERS, timeout=60)
            r.raise_for_status()
            texts[tis] = r.content.decode("utf-8-sig")
            (cache / f"{yy:02d}12cc{tis}.txt").write_text(texts[tis], encoding="utf-8")
            time.sleep(0.2)                                   # politeness to a government server
        out[ad] = texts
    print(f"  {'cache' if use_cache else 'fetch'}  December {sorted(out)}")
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--use-cache", action="store_true")
    ap.add_argument("--allow-unreachable", action="store_true",
                    help="on a connection failure, keep the committed data and exit 0")
    args = ap.parse_args()
    print("DOPA registered population")
    try:
        raw = fetch(args.use_cache)
    except (requests.ConnectionError, requests.Timeout) as e:
        if not args.allow_unreachable:
            raise
        print(f"::warning title=DOPA unreachable::{type(e).__name__}: kept the committed th_dopa.json. "
              "Run etl/th_dopa.py from a machine in Thailand when the next December is published.")
        return 0
    years = {ad: {tis: parse(t, f"{ad}/{tis}") for tis, t in texts.items()} for ad, texts in raw.items()}
    ys = sorted(years)
    if len(ys) < 2:
        raise ParserDriftError(f"DOPA: only {ys} available, need at least two Decembers")
    out = {
        "source": {"name": "Department of Provincial Administration — registered population by province",
                   "url": "https://stat.bora.dopa.go.th/new_stat/webPage/statByProvince.php",
                   "license": "Open Data Common (DOPA)", "as_of": f"{ys[-1]}-12"},
        "years": ys,
        "provinces": {tis: {str(y): {"population": years[y][tis]} for y in ys} for tis in sorted(years[ys[-1]])},
    }
    OUT.mkdir(parents=True, exist_ok=True)
    json.dump(out, open(OUT / "th_dopa.json", "w"), ensure_ascii=False, indent=0)
    a, b = years[ys[-1]], years[ys[-2]]
    print(f"  {ys[0]}–{ys[-1]}  kingdom {sum(a.values()):,}  {(sum(a.values()) / sum(b.values()) - 1) * 100:+.2f}% (Dec/Dec)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
