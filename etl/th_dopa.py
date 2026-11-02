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

District level: a district (อำเภอ/เขต) row counts only that office's own registry; each municipality (เทศบาล,
เมืองพัทยา) is a separate row followed by the tambons it covers. A district's population is its office row plus
the municipal parts of its tambons. Which district a municipality's tambon lies in comes from
data/reference/th_registry_tambon.csv (etl/th_dopa_xwalk.py, from the DOPA catalog's coded tambon file), falling back
to the tambon's name when it is unique in the province. Districts must add up to the province exactly; anything we
cannot place is counted and reported, and leaves the districts it could belong to without a figure that year.
Checked against the catalog's coded tambon file for December 2024: 926 of 928 districts are exact; Mueang Kanchanaburi
and Tha Muang differ by 1,301 people, because stat.bora reports Kanchanaburi town's part of Tha Lo inside Tha Makham
(tests/test_etl.py pins two Phatthalung districts that an office-row shortcut used to get wrong).

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
from etl import OUT, RAW, REF, HEADERS, ParserDriftError  # noqa: E402

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


MUNI = re.compile(r"^(เทศบาล|เมืองพัทยา|ทต\.|ทม\.|ทน\.)")
ABBR = {"ทต.": "เทศบาลตำบล", "ทม.": "เทศบาลเมือง", "ทน.": "เทศบาลนคร"}


def squash(s: str) -> str:
    """Spacing, hyphens and dots differ between sources (สุไหงโกลก / สุไหงโก-ลก)."""
    return re.sub(r"[\s\-.]+", "", s)


def references():
    """(district code by Thai name per province, tambon → districts per province, municipality crosswalk)"""
    import csv
    dname: dict[str, dict[str, str]] = {}
    for d in csv.DictReader(open(REF / "thailand-adm2-districts-v1.0.0.csv", encoding="utf-8")):
        dname.setdefault(d["parent_province_tis1099_code"], {})[squash(d["name_th"])] = d["tis1099_district_code"]
    tname: dict[str, dict[str, set[str]]] = {}
    for t in csv.DictReader(open(REF / "thailand-adm3-subdistricts-v1.0.0.csv", encoding="utf-8")):
        tname.setdefault(t["parent_province_tis1099_code"], {}).setdefault(squash(t["name_th"]), set()).add(t["parent_district_tis1099_code"])
    xw = {(r["province"], squash(r["registry"]), int(r["nth"]), squash(r["tambon"])): r["district"]
          for r in csv.DictReader(l for l in open(REF / "th_registry_tambon.csv", encoding="utf-8") if not l.startswith("#"))}
    # the same municipality under its bare name, whatever its rank (ตำบล → เมือง → นคร upgrades rename it)
    bare: dict[tuple[str, str, str], set[str]] = {}
    tams: dict[tuple[str, str, int], dict[str, str]] = {}          # one municipality's tambons → district
    for (p, reg, k, tam), d in xw.items():
        tams.setdefault((p, reg, k), {})[tam] = d
        bare.setdefault((p, base(reg), tam), set()).add(d)
        bare.setdefault((p, base(reg), "*"), set()).add(d)
    return dname, tname, xw, bare, tams


def base(reg: str) -> str:
    return re.sub(r"^เทศบาล(ตำบล|เมือง|นคร)", "", reg)


def districts(text: str, tis: str, refs, where: str) -> tuple[dict[str, int], list[tuple[int, set[str]]]]:
    """→ ({district code: registered population}, [(people we could not place, districts they could be in)]).

    Office rows go to their district, except a listed tambon that lies in another district (a newer district still
    served by its old office). Municipal rows are placed per municipality block: by the crosswalk (under the
    municipality's name, or its bare name if it was renamed on upgrade); then, if exactly one row is left and exactly
    one of the municipality's known tambons is unused, those two are the same place (stat.bora sometimes labels a
    tambon differently from the coded catalog, or masks it as 'ตำบล--'); then by the tambon's name when unique in the
    province; then by the one district the municipality is known in."""
    dname, tname, xw, bare, tams = refs
    rows = [l.split("|") for l in text.lstrip("\ufeff").splitlines() if l.strip()]
    total = int(rows[0][-2])
    out: dict[str, int] = {}
    unplaced: list[tuple[int, set[str]]] = []
    blocks: list[tuple[tuple[str, int], list[tuple[str, int]]]] = []
    office, nth = None, {}

    def add(code, v):
        out[code] = out.get(code, 0) + v

    for r in rows[1:]:
        name, v = r[0].strip(), int(r[-2])
        tam = squash(re.sub(r"^(ตำบล|แขวง)", "", name))
        if name.startswith("อำเภอ") or name.startswith("เขต"):
            office = dname.get(tis, {}).get(squash(re.sub(r"^(อำเภอ|เขต)", "", name)))
            if not office:
                raise ParserDriftError(f"DOPA {where}: district office {name!r} is not a district of {tis}")
            add(office, v)
        elif MUNI.match(name):
            office = None
            for a, full in ABBR.items():
                name = name.replace(a, full, 1) if name.startswith(a) else name
            m = squash(name)
            nth[m] = nth.get(m, 0) + 1
            blocks.append(((m, nth[m]), []))
        elif name.startswith("ตำบล") or name.startswith("แขวง"):
            if office:
                cands = tname.get(tis, {}).get(tam, set())
                if office not in cands and len(cands) == 1:
                    add(office, -v)
                    add(next(iter(cands)), v)
            elif blocks:
                blocks[-1][1].append((tam, v))
    for (m, k), parts in blocks:
        known = tams.get((tis, m, k)) or {}
        if not known:                       # renamed on upgrade: the same municipality under its bare name
            alts = [d for (p, reg, kk), d in tams.items() if p == tis and kk == k and base(reg) == base(m)]
            known = alts[0] if len(alts) == 1 else {}
        left = [(t, v) for t, v in parts if t not in known]
        unused = [t for t in known if t not in {t for t, _ in parts}]
        for t, v in parts:
            code = known.get(t)
            if not code and len(left) == 1 and len(unused) == 1:
                code = known[unused[0]]
            if not code and len(tname.get(tis, {}).get(t, ())) == 1:
                code = next(iter(tname[tis][t]))
            if not code and len(set(known.values())) == 1:
                code = next(iter(known.values()))
            if code:
                add(code, v)
            else:
                unplaced.append((v, set(tname.get(tis, {}).get(t, set())) | set(known.values())))
    lost = sum(v for v, _ in unplaced)
    if sum(out.values()) + lost != total:
        raise ParserDriftError(f"DOPA {where}: districts {sum(out.values()):,} + unplaced {lost:,} ≠ province {total:,}")
    return out, unplaced


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
    refs = references()
    dist: dict[str, dict[str, int | None]] = {}
    for ad, texts in sorted(raw.items()):
        lost = 0
        for tis, t in sorted(texts.items()):
            got, unplaced = districts(t, tis, refs, f"{ad}/{tis}")
            lost += sum(v for v, _ in unplaced)
            # people we could not place leave every district they might belong to without a figure that year
            # (no candidates at all: the whole province)
            blank = set().union(*(c or set(got) for _, c in unplaced)) if unplaced else set()
            for code, v in got.items():
                dist.setdefault(code, {})[str(ad)] = None if code in blank else v
        print(f"  districts {ad}: {sum(1 for d in dist.values() if d.get(str(ad)) is not None)} placed"
              + (f", {lost:,} people unplaced" if lost else ""))
    ys = sorted(years)
    if len(ys) < 2:
        raise ParserDriftError(f"DOPA: only {ys} available, need at least two Decembers")
    out = {
        "source": {"name": "Department of Provincial Administration — registered population by province",
                   "url": "https://stat.bora.dopa.go.th/new_stat/webPage/statByProvince.php",
                   "license": "Open Data Common (DOPA)", "as_of": f"{ys[-1]}-12"},
        "years": ys,
        "provinces": {tis: {str(y): {"population": years[y][tis]} for y in ys} for tis in sorted(years[ys[-1]])},
        "districts": dict(sorted(dist.items())),
    }
    OUT.mkdir(parents=True, exist_ok=True)
    json.dump(out, open(OUT / "th_dopa.json", "w"), ensure_ascii=False, indent=0)
    a, b = years[ys[-1]], years[ys[-2]]
    print(f"  {ys[0]}–{ys[-1]}  kingdom {sum(a.values()):,}  {(sum(a.values()) / sum(b.values()) - 1) * 100:+.2f}% (Dec/Dec)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
