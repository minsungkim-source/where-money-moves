"""
Thailand — Social Security Office: enterprises and Section 33 insured persons by province (December).

  python etl/th_sso.py [--use-cache]   → data/processed/th_sso.json

Two lenses from one table:
  · Jobs        = Section 33 insured persons (formal private-sector employees)
  · Businesses  = enterprises registered with SSO (employers with ≥1 employee) — a PROXY for
                  business activity. Thailand's company register (DBD) has no clean province
                  series in open data; every employer must register with SSO, so this is the
                  closest monthly-maintained count of operating businesses by province.

Source: catalog.sso.go.th dataset ee936249-… (Open Data Common), one xlsx per Buddhist year.

Sheet layout (2026-10-27): row 1 English title "… AS OF DECEMBER 2025", row 5 'Whole Kingdom',
row 6 Bangkok total followed by 'Bangkok Area Social Security Office N' sub-rows (skipped),
then numbered provinces with the English name in column 3. Footer 'Source: …'.
"""

from __future__ import annotations

import argparse
import io
import json
import re
import sys
from pathlib import Path

import openpyxl
import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))
from etl import (OUT, RAW, HEADERS, ParserDriftError, _num, build_province_index,  # noqa: E402
                 load_reference, match_province)

PACKAGE = "https://catalog.sso.go.th/api/3/action/package_show?id=ee936249-501c-479f-8e8d-4e2a76805d38"


def fetch(use_cache: bool) -> dict[int, bytes]:
    RAW.mkdir(parents=True, exist_ok=True)
    cached = {int(p.stem.split("-")[-1]): p.read_bytes() for p in RAW.glob("sso-t11-*.xlsx")}
    if use_cache and cached:
        print(f"  cache  {sorted(cached)}")
        return cached
    meta = requests.get(PACKAGE, headers=HEADERS, timeout=60).json()["result"]
    out = {}
    for r in meta["resources"]:
        m = re.search(r"(25\d\d)\.xlsx$", r["url"])
        if not m:
            continue
        be = int(m.group(1))
        body = requests.get(r["url"], headers=HEADERS, timeout=120).content
        if not body.startswith(b"PK"):
            raise ParserDriftError(f"SSO {be}: response is not an xlsx")
        (RAW / f"sso-t11-{be}.xlsx").write_bytes(body)
        out[be] = body
    print(f"  fetch  {sorted(out)}")
    return out


def parse(body: bytes, be: int, pidx) -> dict:
    ws = openpyxl.load_workbook(io.BytesIO(body), read_only=True, data_only=True).worksheets[0]
    rows = list(ws.iter_rows(max_row=200, max_col=6, values_only=True))
    title = " ".join(str(c) for r in rows[:3] for c in r if c)
    m = re.search(r"DECEMBER\s+(\d{4})", title, re.I)
    if not m or int(m.group(1)) != be - 543:
        raise ParserDriftError(f"SSO {be}: title does not say December {be-543}: {title[:120]!r}")
    if "enterprise" not in " ".join(str(c) for c in rows[4] if c).lower():
        raise ParserDriftError(f"SSO {be}: row 5 header changed: {rows[4]}")

    total, provs = None, {}
    for r in rows[5:]:
        en = str(r[3] or "").strip()
        if not en:
            continue
        if en.lower().startswith("source"):
            break
        ent, ins = _num(r[1]), _num(r[2])
        if en.lower() == "whole kingdom":
            total = (ent, ins)
            continue
        if "social security office" in en.lower():         # Bangkok area offices
            continue
        if not re.match(r"^\d+\.", en) and "bangkok" not in en.lower():
            continue                                         # region subtotals ('Vicinity', 'Central', …)
        name = re.sub(r"^\d+\.\s*", "", en).replace("Metropolis", "").strip()
        tis = match_province(name, pidx)
        if tis in provs:
            raise ParserDriftError(f"SSO {be}: province {tis} appears twice ('{en}')")
        if ent is None or ins is None:
            raise ParserDriftError(f"SSO {be}: '{en}' has empty cells")
        provs[tis] = {"enterprises": int(ent), "insured": int(ins)}
    if len(provs) != 77:
        raise ParserDriftError(f"SSO {be}: {len(provs)} provinces, expected 77")
    se, si = sum(v["enterprises"] for v in provs.values()), sum(v["insured"] for v in provs.values())
    # Bangkok area offices can carry blank enterprise cells, so allow a small gap on enterprises
    if total and (abs(si - total[1]) > total[1] * 0.002 or abs(se - total[0]) > total[0] * 0.01):
        raise ParserDriftError(f"SSO {be}: provinces sum ({se}, {si}) ≠ Whole Kingdom {total}")
    return provs


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--use-cache", action="store_true")
    args = ap.parse_args()
    print("SSO enterprises & insured (S33)")
    provs, _, _ = load_reference()
    pidx = build_province_index(provs)
    years = {be - 543: parse(b, be, pidx) for be, b in sorted(fetch(args.use_cache).items())}
    ys = sorted(years)
    out = {
        "source": {"name": "Social Security Office — enterprises and Section 33 insured persons by province",
                   "url": "https://catalog.sso.go.th/dataset/ee936249-501c-479f-8e8d-4e2a76805d38",
                   "license": "Open Data Common", "as_of": f"{ys[-1]}-12"},
        "years": ys,
        "provinces": {tis: {str(y): years[y][tis] for y in ys} for tis in sorted(years[ys[-1]])},
    }
    OUT.mkdir(parents=True, exist_ok=True)
    json.dump(out, open(OUT / "th_sso.json", "w"), ensure_ascii=False, indent=0)
    a, b = years[ys[-1]], years[ys[-2]]
    ti = sum(v["insured"] for v in a.values()) / sum(v["insured"] for v in b.values()) - 1
    te = sum(v["enterprises"] for v in a.values()) / sum(v["enterprises"] for v in b.values()) - 1
    print(f"  {ys[0]}–{ys[-1]}  national insured {ti*100:+.2f}%  enterprises {te*100:+.2f}% (Dec/Dec)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
