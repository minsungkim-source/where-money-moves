"""
Malaysia — the 16 states and federal territories, and the districts under them, from OpenDOSM
(Department of Statistics Malaysia, open data at storage.dosm.gov.my, CC BY 4.0).

  python etl/my_dosm.py   → data/processed/my_dosm.json

Lenses (dataset, unit):
  People      population_state         population, thousand persons, yearly (the latest year is an estimate)
  Jobs        lfs_qtr_state            employed persons, thousand, quarterly (same quarter a year earlier as the base)
  Businesses  —                        no open state series yet: left empty, never filled with a stand-in
  Money       gdp_state_real_supply    real GDP, RM million at constant 2015 prices, yearly
Districts (shown on state pages, not ranked against states):
              population_district      population, thousand, yearly
              lfs_district             employed persons, thousand, yearly (single-district territories are not listed)
              hh_income_district       household income, RM a month, mean and median (HIES 2019, 2022, 2024; nominal)
              hh_poverty_district      absolute poverty, % of households (same surveys)
              hh_inequality_district   Gini coefficient (same surveys)
States also get hh_income_state (HIES, 1970 onward; we keep 2016 on).

Checks before anything is written:
  · every file has the columns we read (the header is the structure fingerprint)
  · the same 16 states in every state file
  · population: states add up to population_malaysia within 0.5% every year since 2020
  · jobs: states add up to the national quarterly labour force survey (lfs_qtr) within 0.5%
  · GDP: states plus "Supra" (GDP not attributable to a state, mostly oil and gas) add up to national GDP within 0.5%
  · districts: each state's districts add up to the state's population within 0.5%
"""

from __future__ import annotations

import csv
import io
import json
import re
import sys
import time
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))
from etl import OUT, HEADERS, ParserDriftError  # noqa: E402

BASE = "https://storage.dosm.gov.my/"
FILES = {  # key: (path, columns we rely on)
    "pop_state": ("population/population_state.csv", ["state", "date", "sex", "age", "ethnicity", "population"]),
    "pop_my": ("population/population_malaysia.csv", ["date", "sex", "age", "ethnicity", "population"]),
    "pop_district": ("population/population_district.csv", ["state", "district", "date", "sex", "age", "ethnicity", "population"]),
    "lfs_state": ("labour/lfs_qtr_state.csv", ["date", "state", "lf", "lf_employed", "lf_unemployed", "p_rate", "u_rate"]),
    "lfs_my": ("labour/lfs_qtr.csv", ["date", "lf_employed"]),
    "lfs_district": ("labour/lfs_district.csv", ["state", "district", "date", "lf_employed", "u_rate"]),
    "gdp_state": ("gdp/gdp_state_real_supply.csv", ["series", "date", "state", "sector", "value"]),
    "gdp_my": ("gdp/gdp_annual_real_supply.csv", ["series", "date", "sector", "value"]),
    "inc_district": ("hies/hh_income_district.csv", ["state", "district", "date", "income_mean", "income_median"]),
    "pov_district": ("hies/hh_poverty_district.csv", ["state", "district", "date", "poverty_absolute"]),
    "gini_district": ("hies/hh_inequality_district.csv", ["state", "district", "date", "gini"]),
    "inc_state": ("hies/hh_income_state.csv", ["state", "date", "income_mean", "income_median"]),
}
# DOSM label → (slug, English name, Malay name when it differs). The three federal territories drop "W.P."
STATES = {
    "Johor": ("johor", "Johor", ""), "Kedah": ("kedah", "Kedah", ""), "Kelantan": ("kelantan", "Kelantan", ""),
    "Melaka": ("melaka", "Melaka", ""), "Negeri Sembilan": ("negeri-sembilan", "Negeri Sembilan", ""),
    "Pahang": ("pahang", "Pahang", ""), "Perak": ("perak", "Perak", ""), "Perlis": ("perlis", "Perlis", ""),
    "Pulau Pinang": ("penang", "Penang", "Pulau Pinang"), "Sabah": ("sabah", "Sabah", ""), "Sarawak": ("sarawak", "Sarawak", ""),
    "Selangor": ("selangor", "Selangor", ""), "Terengganu": ("terengganu", "Terengganu", ""),
    "W.P. Kuala Lumpur": ("kuala-lumpur", "Kuala Lumpur", "Wilayah Persekutuan Kuala Lumpur"),
    "W.P. Labuan": ("labuan", "Labuan", "Wilayah Persekutuan Labuan"),
    "W.P. Putrajaya": ("putrajaya", "Putrajaya", "Wilayah Persekutuan Putrajaya"),
}
SUPRA = "Supra"
# the labour survey spells some districts differently from the population tables (some only in 2018–2020)
DISTRICT_ALIASES = {"Larut & Matang": "Larut Dan Matang", "Tanjong Manis": "Tanjung Manis", "Cameron Highland": "Cameron Highlands",
                    "Manjung (Dinding)": "Manjung", "Hulu Langat": "Ulu Langat", "Hulu Selangor": "Ulu Selangor"}
# the household surveys spell some districts their own way, and not always the same way each round
HIES_ALIASES = {("Terengganu", "hulu"): "Hulu Terengganu"}
SECTORS = {"p1": "Agriculture", "p2": "Mining and quarrying", "p3": "Manufacturing", "p4": "Construction", "p5": "Services"}
FIRST_YEAR = 2015
TOLERANCE = 0.005


def fetch(key: str) -> str:
    path, _ = FILES[key]
    for attempt in range(3):
        try:
            r = requests.get(BASE + path, headers=HEADERS, timeout=180)
            r.raise_for_status()
            return r.content.decode("utf-8-sig")
        except requests.RequestException:
            if attempt == 2:
                raise
            time.sleep(5 * (attempt + 1))
    raise AssertionError


def rows(key: str, text: str) -> list[dict]:
    """Parse one CSV, checking it still has the columns we read."""
    reader = csv.DictReader(io.StringIO(text))
    missing = [c for c in FILES[key][1] if c not in (reader.fieldnames or [])]
    if missing:
        raise ParserDriftError(f"{FILES[key][0]}: columns {missing} gone (has {reader.fieldnames})")
    return list(reader)


def overall(r: dict) -> bool:
    return r["sex"] == "both" and r["age"] == "overall" and r["ethnicity"] == "overall"


def year(d: str) -> int:
    return int(d[:4])


def quarter(d: str) -> str:
    """'2026-04-01' → '2026-Q2'"""
    m = re.fullmatch(r"(\d{4})-(\d{2})-01", d)
    if not m or m.group(2) not in ("01", "04", "07", "10"):
        raise ParserDriftError(f"unreadable quarter {d!r}")
    return f"{m.group(1)}-Q{(int(m.group(2)) - 1) // 3 + 1}"


def check_sum(what: str, parts: float, total: float):
    if total and abs(parts - total) / total > TOLERANCE:
        raise ParserDriftError(f"{what}: parts add up to {parts:,.1f}, total is {total:,.1f}")


def check_states(what: str, labels) -> None:
    got = set(labels) - {SUPRA}
    if got != set(STATES):
        raise ParserDriftError(f"{what}: states differ from the 16 expected: {sorted(got ^ set(STATES))}")


def dkey(name: str) -> str:
    """'S.P.Tengah' = 'Seberang Perai Tengah', 'Larut & Matang' = 'Larut dan Matang', 'Lubok antu' = 'Lubok Antu'"""
    n = name.lower().replace("&", "dan").replace("s.p.", "seberang perai ")
    return re.sub(r"[^a-z]", "", n)


def build(raw: dict[str, str]) -> dict:
    R = {k: rows(k, t) for k, t in raw.items()}

    # People
    pop = [r for r in R["pop_state"] if overall(r) and year(r["date"]) >= FIRST_YEAR]
    check_states("population_state", {r["state"] for r in pop})
    nat = {year(r["date"]): float(r["population"]) for r in R["pop_my"] if overall(r)}
    for y in sorted({year(r["date"]) for r in pop}):
        if y >= 2020 and y in nat:
            check_sum(f"population {y}", sum(float(r["population"]) for r in pop if year(r["date"]) == y), nat[y])

    # Jobs
    lfs = [r for r in R["lfs_state"] if year(r["date"]) >= FIRST_YEAR]
    check_states("lfs_qtr_state", {r["state"] for r in lfs})
    nat_e = {r["date"]: float(r["lf_employed"]) for r in R["lfs_my"]}
    for d in sorted({r["date"] for r in lfs}):
        if d in nat_e:
            check_sum(f"employed {quarter(d)}", sum(float(r["lf_employed"]) for r in lfs if r["date"] == d), nat_e[d])

    # Money
    gdp = [r for r in R["gdp_state"] if r["series"] == "abs" and year(r["date"]) >= FIRST_YEAR]
    check_states("gdp_state_real_supply", {r["state"] for r in gdp})
    nat_g = {year(r["date"]): float(r["value"]) for r in R["gdp_my"] if r["series"] == "abs" and r["sector"] == "p0"}
    for y in sorted({year(r["date"]) for r in gdp}):
        if y in nat_g:
            check_sum(f"GDP {y}", sum(float(r["value"]) for r in gdp if year(r["date"]) == y and r["sector"] == "p0"), nat_g[y])

    # Districts
    dpop = [r for r in R["pop_district"] if overall(r)]
    check_states("population_district", {r["state"] for r in dpop})
    dl = R["lfs_district"]
    known = {(r["state"], r["district"]) for r in dpop}
    for r in dl:
        r["district"] = DISTRICT_ALIASES.get(r["district"], r["district"])
        if (r["state"], r["district"]) not in known:
            raise ParserDriftError(f"lfs_district: {r['district']}, {r['state']} is not a district in population_district")
    for y in sorted({year(r["date"]) for r in dpop}):
        for st in STATES:
            state_pop = next((float(r["population"]) for r in pop if r["state"] == st and year(r["date"]) == y), None)
            if state_pop:
                check_sum(f"districts of {st} {y}", sum(float(r["population"]) for r in dpop if r["state"] == st and year(r["date"]) == y), state_pop)

    # Household surveys by district: matched to the population table's districts by folded name
    by_key = {(st, dkey(d)): d for st, d in known}
    hies: dict[tuple[str, str], dict[str, dict[str, float]]] = {}
    for key, col, field in (("inc_district", "income_median", "income_median"), ("inc_district", "income_mean", "income_mean"),
                            ("pov_district", "poverty_absolute", "poverty"), ("gini_district", "gini", "gini")):
        for r in R[key]:
            st = r["state"]
            name = HIES_ALIASES.get((st, dkey(r["district"])), r["district"])
            d = by_key.get((st, dkey(name)))
            if not d:
                raise ParserDriftError(f"{FILES[key][0]}: {r['district']}, {st} is not a district in population_district")
            if r[col].strip():
                hies.setdefault((st, d), {}).setdefault(field, {})[str(year(r["date"]))] = float(r[col])
    inc_state = {}
    check_states("hh_income_state", {x["state"] for x in R["inc_state"]} - {"Malaysia"})
    for r in R["inc_state"]:
        if r["state"] in STATES and year(r["date"]) >= 2016 and r["income_median"].strip():
            inc_state.setdefault(r["state"], {})[str(year(r["date"]))] = float(r["income_median"])

    out_states = {}
    for label, (slug, name, native) in STATES.items():
        s = {
            "pop": {year(r["date"]): float(r["population"]) for r in pop if r["state"] == label},
            "employed": {quarter(r["date"]): float(r["lf_employed"]) for r in lfs if r["state"] == label},
            "u_rate": {quarter(r["date"]): float(r["u_rate"]) for r in lfs if r["state"] == label},
            "p_rate": {quarter(r["date"]): float(r["p_rate"]) for r in lfs if r["state"] == label},
            "gdp": {year(r["date"]): float(r["value"]) for r in gdp if r["state"] == label and r["sector"] == "p0"},
        }
        gy = sorted(s["gdp"])[-2:]
        sectors = {code: {str(y): next((float(r["value"]) for r in gdp if r["state"] == label and r["sector"] == code and year(r["date"]) == y), None)
                          for y in gy} for code in SECTORS}
        districts = {}
        for r in dpop:
            if r["state"] == label:
                districts.setdefault(r["district"], {"pop": {}, "employed": {}, "u_rate": {}, **{f: {} for f in ("income_median", "income_mean", "poverty", "gini")}}
                                     )["pop"][str(year(r["date"]))] = float(r["population"])
        for r in dl:
            if r["state"] == label:
                d = districts[r["district"]]
                for k, col in (("employed", "lf_employed"), ("u_rate", "u_rate")):
                    if r[col].strip():                         # blank = not published for that district and year
                        d[k][str(year(r["date"]))] = float(r[col])
        for dn, d in districts.items():
            for f, ser in hies.get((label, dn), {}).items():
                d[f].update(ser)
        s["income_median"] = {int(y): v for y, v in inc_state.get(label, {}).items()}
        out_states[slug] = {"slug": slug, "name": name, "native": native, "dosm": label,
                            "series": {k: {str(x): v for x, v in sorted(ser.items())} for k, ser in s.items()},
                            "sectors": sectors,
                            "districts": [{"name": n, **{k: dict(sorted(v.items())) for k, v in d.items()}} for n, d in sorted(districts.items())]}
    return {
        "source": {"name": "Department of Statistics Malaysia (DOSM) — OpenDOSM", "url": "https://open.dosm.gov.my/",
                   "license": "CC BY 4.0"},
        "units": {"pop": "thousand persons", "employed": "thousand persons", "u_rate": "%", "p_rate": "%",
                  "gdp": "RM million, constant 2015 prices"},
        "sector_names": SECTORS,
        "supra_gdp": {str(year(r["date"])): float(r["value"]) for r in gdp if r["state"] == SUPRA and r["sector"] == "p0"},
        "files": {k: v[0] for k, v in FILES.items()},
        "states": dict(sorted(out_states.items())),
    }


def main() -> int:
    print("Malaysia OpenDOSM")
    raw = {}
    for k in FILES:
        raw[k] = fetch(k)
        print(f"  {FILES[k][0]:<38} {len(raw[k]) / 1e6:5.1f}MB")
    out = build(raw)
    OUT.mkdir(parents=True, exist_ok=True)
    json.dump(out, open(OUT / "my_dosm.json", "w"), ensure_ascii=False, indent=0)
    s = out["states"]["selangor"]["series"]
    print(f"  16 states  {sum(len(v['districts']) for v in out['states'].values())} districts  "
          f"Selangor pop {list(s['pop'].items())[-1]}  employed {list(s['employed'].items())[-1]}  GDP {list(s['gdp'].items())[-1]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
