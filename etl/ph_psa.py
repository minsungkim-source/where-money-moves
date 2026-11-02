"""
Philippines — provinces from the Philippine Statistics Authority (PSA) OpenSTAT database (PX-Web).

  python etl/ph_psa.py   → data/processed/ph_psa.json

PSA publishes provinces and highly urbanized cities (HUCs) side by side; an HUC is not part of its province in the
statistics, though it sits inside it on the map. We add each HUC to the province around it, and Metro Manila's 17
cities into one unit, so every unit is a place on the map and both lenses stay additive. The HUCs are kept as a
breakdown on the province page.

Lenses (table, unit):
  People      1A/PO_2020/0011A6DPHH0 + 1A/PO_2024/0191A6DTHP8   census population, 1 May 2020 and 1 July 2024
              (annualised growth between the two censuses)
  Jobs        —   no province series (the Labor Force Survey is published nationally)
  Businesses  —   no province series
  Money       2A/PPA/0012A5FPPA0   Provincial Product Accounts: GDP by province and HUC, constant 2018 prices, yearly

Checks before anything is written:
  · every PSA place is mapped to a unit (provinces by name, HUCs through HUC_HOST); nothing unmapped, nothing left over
  · GDP: for every year and price basis, each region's provinces and HUCs add up to the region, and the regions to the
    Philippines, within 0.5%
  · population: the same, for both censuses
"""

from __future__ import annotations

import json
import re
import sys
import time
import unicodedata
import urllib.parse
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))
from etl import OUT, HEADERS, ParserDriftError  # noqa: E402

API = "https://openstat.psa.gov.ph/PXWeb/api/v1/en/DB/"
TABLES = {  # key: (table, {variable: value text to keep})
    "gdp_real": ("2A/PPA/0012A5FPPA0.px", {"Type of Valuation": "At Constant 2018 Prices"}),
    "gdp_nominal": ("2A/PPA/0012A5FPPA0.px", {"Type of Valuation": "At Current Prices"}),
    "pop2020": ("1A/PO_2020/0011A6DPHH0.px", {"*": "Total Population"}),
    "pop2024": ("1A/PO_2024/0191A6DTHP8.px", {"Parameter": "Total Population"}),
}
CENSUS_YEARS = 2024.5 - 2020.33          # 1 May 2020 → 1 July 2024: 4.17 years
TOLERANCE = 0.005

# highly urbanized cities (and Isabela City's neighbours) → the province around them on the map
HUC_HOST = {
    "cityofbaguio": "benguet", "cityofangeles": "pampanga", "cityofolongapo": "zambales", "cityoflucena": "quezon",
    "cityofpuertoprincesa": "palawan", "cityofiloilo": "iloilo", "cityofbacolod": "negros-occidental",
    "cityofcebu": "cebu", "cityoflapulapu": "cebu", "cityofmandaue": "cebu", "cityoftacloban": "leyte",
    "cityofzamboanga": "zamboanga-del-sur", "cityofcagayandeoro": "misamis-oriental", "cityofiligan": "lanao-del-norte",
    "cityofdavao": "davao-del-sur", "cityofgeneralsantos": "south-cotabato", "cityofbutuan": "agusan-del-norte",
}
# PSA names that are not the unit's slug; Maguindanao was split in 2022 but the map (2020) has one shape
ALIASES = {
    "maguindanaodelnorte": "maguindanao", "maguindanaodelsur": "maguindanao",
    "specialgeographicarea": "cotabato", "eight8areaclusters": "cotabato",   # BARMM barangays inside Cotabato's 2020 outline
    "cityofisabela": "city-of-isabela", "samarwesternsamar": "samar", "davaodeorocompostelavalley": "davao-de-oro",
    "cotabatonorthcotabato": "cotabato",
}
UNIT_NAMES = {"metro-manila": "Metro Manila", "city-of-isabela": "Isabela City", "maguindanao": "Maguindanao"}
REGION_SHORT = {  # PSA region label (folded) → short name shown on the site
    "nationalcapitalregionncr": "Metro Manila (NCR)", "cordilleraadministrativeregioncar": "Cordillera (CAR)",
    "regioniilocosregion": "Ilocos Region", "regioniicagayanvalley": "Cagayan Valley", "regioniiicentralluzon": "Central Luzon",
    "regionivacalabarzon": "CALABARZON", "mimaroparegion": "MIMAROPA", "regionvbicolregion": "Bicol Region",
    "regionviwesternvisayas": "Western Visayas", "negrosislandregionnir": "Negros Island Region",
    "regionviicentralvisayas": "Central Visayas", "regionviiieasternvisayas": "Eastern Visayas",
    "regionixzamboangapeninsula": "Zamboanga Peninsula", "regionxnorthernmindanao": "Northern Mindanao",
    "regionxidavaoregion": "Davao Region", "regionxiisoccsksargen": "SOCCSKSARGEN", "regionxiiicaraga": "Caraga",
    "bangsamoroautonomousregioninmuslimmindanaobarmm": "BARMM",
}


def fold(s: str) -> str:
    s = "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")
    return re.sub(r"[^a-z0-9]", "", s.lower())


def clean(label: str) -> tuple[int, str]:
    """'....Negros Occidental 4/*' → (2, 'Negros Occidental'); depth = leading dot pairs (0 national, 1 region, 2 place)"""
    depth = (len(label) - len(label.lstrip("."))) // 2
    name = label.lstrip(".").strip()
    name = re.sub(r"(\s+(\d+/?)?\**|\s+/?[a-z]\d?/?)+$", "", name)           # footnote marks: ' *', ' 4/*', ' 8**', ' a', ' /a', ' 1/'
    name = re.sub(r"\s*\((Not a Province|Opon|Dadiangas)\)", "", name)
    return depth, name.strip()


def slug(s: str) -> str:
    return re.sub(r"-+", "-", re.sub(r"[^a-z0-9]+", "-", s.lower())).strip("-")


def unit_of(name: str, region_key: str) -> str:
    f = fold(name)
    if region_key == "nationalcapitalregionncr":
        return "metro-manila"
    if f in HUC_HOST:
        return HUC_HOST[f]
    if f in ALIASES:
        return ALIASES[f]
    return slug(re.sub(r"\s*\(.*\)", "", name))


def query(table: str, keep: dict) -> tuple[list[tuple[int, str]], dict[str, dict[str, float]]]:
    """→ ([(depth, name)] in table order, {name: {period: value}})"""
    url = API + urllib.parse.quote(table)
    for attempt in range(3):
        try:
            meta = requests.get(url, headers=HEADERS, timeout=60).json()
            break
        except (requests.RequestException, ValueError):
            if attempt == 2:
                raise
            time.sleep(5 * (attempt + 1))
    var = {v["code"]: v for v in meta["variables"]}
    geo = next(v for c, v in var.items() if c.lower().startswith("geo"))
    sel = []
    for code, text in keep.items():
        v = var.get(code) or next((v for c, v in var.items() if text in v.get("valueTexts", [])), None)
        if not v or text not in v["valueTexts"]:
            raise ParserDriftError(f"{table}: '{text}' not offered ({code})")
        sel.append({"code": v["code"], "selection": {"filter": "item", "values": [v["values"][v["valueTexts"].index(text)]]}})
    r = requests.post(url, json={"query": sel, "response": {"format": "json"}}, headers=HEADERS, timeout=120)
    r.raise_for_status()
    data = json.loads(r.content.decode("utf-8-sig"))
    cols = [c["code"] for c in data["columns"] if c["type"] != "c"]
    gi = cols.index(geo["code"])
    yi = next((i for i, c in enumerate(cols) if c.lower() == "year"), None)
    g_text = dict(zip(geo["values"], geo["valueTexts"]))
    places = [clean(t) for t in geo["valueTexts"]]
    out: dict[str, dict[str, float]] = {}
    for row in data["data"]:
        raw = row["values"][0].strip()
        if raw in ("", "..", "-", "…"):
            continue
        name = clean(g_text[row["key"][gi]])[1]
        period = row["key"][yi] if yi is not None else "value"
        if yi is not None:
            period = dict(zip(var["Year"]["values"], var["Year"]["valueTexts"]))[period]
        out.setdefault(name, {})[period] = float(raw)
    return places, out


def walk(places):
    """Table order → (national label or None, [(region key, region label, [place names])]). Levels are told apart by
    name, not indentation: the tables nest them at different depths, and the GDP table has no national row."""
    regions, national = [], None
    for _, name in places:
        f = fold(name)
        if f.startswith("philippines"):
            national = name
        elif f in REGION_SHORT:
            regions.append((f, name, []))
        elif regions:
            regions[-1][2].append(name)
        else:
            raise ParserDriftError(f"place {name!r} before any region")
    if not regions:
        raise ParserDriftError("no regions found")
    return national, regions


def check(table, national, regions, values, periods):
    for p in periods:
        tot = 0.0
        for _, rname, kids in regions:
            reg = values[rname].get(p)
            parts = sum(values[k].get(p, 0) for k in kids)
            if reg and abs(parts - reg) / reg > TOLERANCE:
                raise ParserDriftError(f"{table} {p}: places of {rname} add up to {parts:,.0f}, the region is {reg:,.0f}")
            tot += reg or 0
        nat = values[national].get(p) if national else None       # the GDP table has no national row
        if nat and abs(tot - nat) / nat > TOLERANCE:
            raise ParserDriftError(f"{table} {p}: regions add up to {tot:,.0f}, the Philippines is {nat:,.0f}")


def build(fetched: dict) -> dict:
    units: dict[str, dict] = {}
    for key, (places, values) in fetched.items():
        national, regions = walk(places)
        periods = sorted({p for v in values.values() for p in v})
        check(TABLES[key][0], national, regions, values, periods)
        for rkey, rname, kids in regions:
            if rkey not in REGION_SHORT:
                raise ParserDriftError(f"{TABLES[key][0]}: unknown region {rname!r}")
            for k in kids:
                u = unit_of(k, rkey)
                rec = units.setdefault(u, {"slug": u, "name": UNIT_NAMES.get(u), "region": None, "parts": {}, "series": {}})
                if key == "gdp_real":                     # PSA's current regions (NIR, Sulu in IX) come with the newest table
                    rec["region"] = REGION_SHORT[rkey]
                    if slug(k) == u:
                        rec["name"] = rec["name"] or k
                ser = rec["series"].setdefault(key, {})
                part = rec["parts"].setdefault(k, {})
                for p, v in values.get(k, {}).items():
                    ser[p] = ser.get(p, 0) + v
                    part.setdefault(key, {})[p] = v
    for u, rec in units.items():
        missing = [k for k in TABLES if not rec["series"].get(k)]
        if missing or not rec["region"] or not rec["name"]:
            raise ParserDriftError(f"{u}: no {missing or 'region/name'} (a place was renamed, split or moved)")
        rec["series"]["pop2020"] = rec["series"]["pop2020"]["value"]
        rec["series"]["pop2024"] = rec["series"]["pop2024"]["value"]
        # the places a unit is made of (HUCs, Metro Manila's cities, the two Maguindanaos), not the unit itself
        # one entry per place whatever each table calls it ('Davao de Oro (Compostela Valley)', 'Cagayan De Oro')
        parts, label = {}, {}
        for k, v in rec["parts"].items():
            if fold(k) in ALIASES and ALIASES[fold(k)] == "cotabato":
                continue                                 # census-only fragments, no GDP of their own
            base = re.sub(r"\s*\(.*\)", "", k)
            if u == "maguindanao" and fold(base) == "maguindanao":
                continue                                 # the undivided province of the 2020 census is the unit itself
            name = label.setdefault(fold(base), re.sub(r"^City of ", "", base) + (" City" if base.startswith("City of ") else ""))
            pp = parts.setdefault(name, {})
            for key, ser in v.items():
                pp[key] = ser.get("value") if key.startswith("pop") else ser
        rec["parts"] = parts if len(parts) > 1 else {}
    return {
        "source": {"name": "Philippine Statistics Authority (PSA) — OpenSTAT", "url": "https://openstat.psa.gov.ph/",
                   "license": "Public statistics, attribution required"},
        "units": {"gdp_real": "PHP thousand, constant 2018 prices", "gdp_nominal": "PHP thousand, current prices",
                  "pop2020": "persons, 1 May 2020", "pop2024": "persons, 1 July 2024"},
        "census_years": CENSUS_YEARS,
        "tables": {k: v[0] for k, v in TABLES.items()},
        "provinces": dict(sorted(units.items())),
    }


def main() -> int:
    print("Philippines PSA OpenSTAT")
    fetched = {}
    for k, (table, keep) in TABLES.items():
        fetched[k] = query(table, keep)
        print(f"  {table:<28} {k:<12} {len(fetched[k][1])} places")
        time.sleep(0.5)
    out = build(fetched)
    OUT.mkdir(parents=True, exist_ok=True)
    json.dump(out, open(OUT / "ph_psa.json", "w"), ensure_ascii=False, indent=0)
    mm = out["provinces"]["metro-manila"]["series"]
    print(f"  {len(out['provinces'])} units  Metro Manila pop {mm['pop2024']:,.0f}  real GDP {max(mm['gdp_real'].items())}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
