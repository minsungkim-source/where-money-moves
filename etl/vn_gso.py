"""
Vietnam — four lenses for the 34 provinces (2025 boundaries), from the National Statistics Office (NSO, formerly GSO)
PX-Web database.

  python etl/vn_gso.py   → data/processed/vn_gso.json

NSO still publishes by the 63 pre-merger provinces. Every 2025 merger joined whole provinces, so we add the old
provinces up into the new 34 with data/reference/vn_provinces_2025.csv and keep the old ones as a breakdown.

Lenses (table id, unit) — latest year is usually preliminary ("Sơ bộ"):
  People      V02.03-07  average population, thousand persons        + V02.21-23 net migration rate, ‰
  Jobs        V02.45     employed workers, thousand persons
  Businesses  V05.02     newly registered enterprises, number        + V05.04 active enterprises at 31 Dec
  Money       V05.23     net revenue of active enterprises, billion dong (nominal)

Checks before anything is written:
  · each table's province list must contain all 63 crosswalk names (exact, after folding diacritics)
  · for every year, the 63 provinces must add up to the national row (CẢ NƯỚC) within 0.5%
    (enterprise revenue: provinces + "Không xác định"/unallocated must add up)
  · migration rates are combined weighted by population: net migrants = rate × population / 1000
"""

from __future__ import annotations

import csv
import json
import re
import sys
import time
import unicodedata
import urllib.parse
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))
from etl import OUT, REF, HEADERS, ParserDriftError  # noqa: E402

API = "https://pxweb.nso.gov.vn/api/v1/vi/"
POP_DB, ENT_DB = "Dân số và lao động", "Doanh nghiệp"
TABLES = {  # key: (db, table, extra fixed selection {variable: value text})
    "pop": (POP_DB, "V02.03-07.px", {"Dân số trung bình": "Tổng số"}),
    "netmig": (POP_DB, "V02.21-23.px", {"Tỷ suất": "Tỷ suất di cư thuần"}),
    "employed": (POP_DB, "V02.45.px", {}),
    "new_firms": (ENT_DB, "V05.02.px", {}),
    "firms": (ENT_DB, "V05.04.px", {}),
    "revenue": (ENT_DB, "V05.23.px", {}),
}
NATIONAL, UNALLOCATED = "canuoc", "khongxacdinh"
FIRST_YEAR = 2010   # Hà Tây was a separate province until 2008, so earlier years do not add up to 63
TOLERANCE = 0.005


def fold(s: str) -> str:
    s = s.replace("Đ", "D").replace("đ", "d").replace("Ð", "D")
    s = "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")
    return re.sub(r"[^a-z0-9]", "", s.lower())


def names(r) -> list[str]:
    """Folded GSO labels for one old province (alternates separated by '|')."""
    return [fold(re.sub(r"^TP\.?\s*", "", n)) for n in r["gso_name"].split("|")]


def label(r) -> str:
    """Display name of an old province (Vietnamese, the pre-2025 name)."""
    n = r["gso_name"].split("|")[-1]
    return n.replace("TP. ", "Thành phố ")


def crosswalk():
    rows = list(csv.DictReader(l for l in open(REF / "vn_provinces_2025.csv", encoding="utf-8") if not l.startswith("#")))
    if len(rows) != 63 or len({r["new_slug"] for r in rows}) != 34:
        raise ParserDriftError(f"crosswalk has {len(rows)} old / {len({r['new_slug'] for r in rows})} new provinces, expected 63 / 34")
    return rows


def query(db: str, table: str, fixed: dict) -> tuple[dict[str, dict[int, float]], dict[int, bool]]:
    """→ ({folded province name: {year: value}}, {year: preliminary?})"""
    url = API + urllib.parse.quote(f"{db}/{table}")
    for attempt in range(3):
        try:
            meta = requests.get(url, headers=HEADERS, timeout=60).json()
            break
        except (requests.RequestException, ValueError):
            if attempt == 2:
                raise
            time.sleep(5 * (attempt + 1))
    var = {v["code"]: v for v in meta["variables"]}
    prov = next(v for c, v in var.items() if fold(c).startswith("tinh"))
    year = next(v for c, v in var.items() if fold(c) == "nam")
    sel = []
    for code, text in fixed.items():
        v = var[code]
        if text not in v["valueTexts"]:
            raise ParserDriftError(f"{table}: '{text}' not in {code} {v['valueTexts']}")
        sel.append({"code": code, "selection": {"filter": "item", "values": [v["values"][v["valueTexts"].index(text)]]}})
    body = {"query": sel, "response": {"format": "json"}}
    r = requests.post(url, json=body, headers=HEADERS, timeout=120)
    r.raise_for_status()
    data = json.loads(r.content.decode("utf-8-sig"))
    cols = [c["code"] for c in data["columns"] if c["type"] != "c"]
    pi, yi = cols.index(prov["code"]), cols.index(year["code"])
    p_text = dict(zip(prov["values"], prov["valueTexts"]))
    y_text = dict(zip(year["values"], year["valueTexts"]))
    out: dict[str, dict[int, float]] = {}
    prelim: dict[int, bool] = {}
    for row in data["data"]:
        raw = row["values"][0].strip()
        if raw in ("", "..", "-", "…"):
            continue
        yt = y_text[row["key"][yi]]
        m = re.search(r"(\d{4})", yt)
        if not m:
            raise ParserDriftError(f"{table}: unreadable year label {yt!r}")
        y = int(m.group(1))
        if y < FIRST_YEAR:
            continue
        prelim[y] = "sơ bộ" in yt.lower()
        name = fold(re.sub(r"^TP\.?\s*", "", p_text[row["key"][pi]]))
        out.setdefault(name, {})[y] = float(raw)
    return out, prelim


def main() -> int:
    print("Vietnam NSO PX-Web")
    cw = crosswalk()
    key = {names(r)[0]: r for r in cw}          # canonical folded name per old province
    raw, prelim = {}, {}
    for k, (db, table, fixed) in TABLES.items():
        got, prelim[k] = query(db, table, fixed)
        # re-key every old province under its canonical name, whichever alternate label this table uses
        raw[k] = {n: v for n, v in got.items() if n in (NATIONAL, UNALLOCATED)}
        missing = []
        for r in cw:
            hit = [n for n in names(r) if n in got]
            if len(hit) != 1:
                missing.append(r["gso_name"])
            else:
                raw[k][names(r)[0]] = got[hit[0]]
        if missing:
            raise ParserDriftError(f"{table}: provinces missing or ambiguous {missing}")
        years = sorted({y for o in key for y in raw[k][o]})      # national net migration is empty (it nets to ~0)
        print(f"  {table:<14} {k:<10} {years[0]}–{years[-1]}{' (p)' if prelim[k].get(years[-1]) else ''}")
        time.sleep(0.5)

    # national checks (rates are not additive; checked through net migrants below)
    for k in ("pop", "employed", "new_firms", "firms", "revenue"):
        for y, nat in raw[k][NATIONAL].items():
            parts = [raw[k][o].get(y) for o in key]
            if any(p is None for p in parts):
                continue
            total = sum(parts) + (raw[k].get(UNALLOCATED, {}).get(y, 0) if k == "revenue" else 0)
            if nat and abs(total - nat) / nat > TOLERANCE:
                raise ParserDriftError(f"{TABLES[k][1]} {y}: 63 provinces sum to {total:,.0f}, national is {nat:,.0f}")

    new = {}
    for r in cw:
        n = new.setdefault(r["new_slug"], {"slug": r["new_slug"], "name": r["new_name_en"], "native": r["new_name_vi"],
                                           "former": [], "series": {k: {} for k in TABLES}})
        n["former"].append(label(r))
    for slug, n in new.items():
        olds = [names(r)[0] for r in cw if r["new_slug"] == slug]
        for k in ("pop", "employed", "new_firms", "firms", "revenue"):
            years = set.intersection(*(set(raw[k][o]) for o in olds))
            n["series"][k] = {str(y): round(sum(raw[k][o][y] for o in olds), 3) for y in sorted(years)}
        years = set.intersection(*(set(raw["netmig"][o]) & set(raw["pop"][o]) for o in olds))
        n["series"]["netmig"] = {str(y): round(1000 * sum(raw["netmig"][o][y] * raw["pop"][o][y] / 1000 for o in olds)
                                              / sum(raw["pop"][o][y] for o in olds), 3) for y in sorted(years)}
        n["former_detail"] = {
            label(r): {k: {str(y): v for y, v in sorted(raw[k][names(r)[0]].items())[-2:]}
                       for k in ("pop", "employed", "new_firms", "revenue")}
            for r in cw if r["new_slug"] == slug}
    out = {
        "source": {"name": "National Statistics Office of Viet Nam (formerly GSO) — PX-Web database",
                   "url": "https://pxweb.nso.gov.vn/", "license": "Public statistics, attribution required"},
        "units": {"pop": "thousand persons", "employed": "thousand persons", "netmig": "per 1,000 people",
                  "new_firms": "enterprises", "firms": "enterprises", "revenue": "billion dong"},
        "tables": {k: v[1] for k, v in TABLES.items()},
        "preliminary": {k: sorted(y for y, p in v.items() if p) for k, v in prelim.items()},
        "provinces": dict(sorted(new.items())),
    }
    OUT.mkdir(parents=True, exist_ok=True)
    json.dump(out, open(OUT / "vn_gso.json", "w"), ensure_ascii=False, indent=0)
    hcm = new["ho-chi-minh-city"]["series"]
    print(f"  34 provinces  HCMC pop {max(hcm['pop'].items())}  new firms {max(hcm['new_firms'].items())}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
