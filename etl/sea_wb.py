"""
Southeast Asia — country-level lenses from the World Bank API (no key).

  python etl/sea_wb.py   → data/processed/sea_wb.json

Country level is the only layer that is comparable across all 11 ASEAN+TL countries.
National statistics differ in definitions, so subnational data is only ever compared
within a country, never across.

Lenses (first indicator in each is the headline):
  People      SP.URB.TOTL (urban population — people moving to cities), SP.POP.TOTL, SM.POP.NETM
  Jobs        employed = SL.TLF.TOTL.IN × (1 − SL.UEM.TOTL.ZS/100), SL.UEM.TOTL.ZS
  Businesses  IC.BUS.NREG (new limited-liability firms registered), IC.BUS.NDNS.ZS (per 1,000 aged 15–64)
  Money       NY.GDP.MKTP.KD (real GDP), BX.KLT.DINV.CD.WD (FDI net inflows), BX.TRF.PWKR.CD.DT (remittances received)
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))
from etl import OUT, HEADERS, ParserDriftError  # noqa: E402

API = "https://api.worldbank.org/v2/country/{c}/indicator/{i}?format=json&date=2000:2026&per_page=1000"
COUNTRIES = {
    "BRN": ("Brunei", "brunei"), "KHM": ("Cambodia", "cambodia"), "IDN": ("Indonesia", "indonesia"),
    "LAO": ("Laos", "laos"), "MYS": ("Malaysia", "malaysia"), "MMR": ("Myanmar", "myanmar"),
    "PHL": ("Philippines", "philippines"), "SGP": ("Singapore", "singapore"), "THA": ("Thailand", "thailand"),
    "TLS": ("Timor-Leste", "timor-leste"), "VNM": ("Vietnam", "vietnam"),
}
NATIVE = {"BRN": "Brunei Darussalam", "KHM": "កម្ពុជា", "IDN": "Indonesia", "LAO": "ລາວ", "MYS": "Malaysia",
          "MMR": "မြန်မာ", "PHL": "Pilipinas", "SGP": "Singapura", "THA": "ประเทศไทย", "TLS": "Timór-Leste",
          "VNM": "Việt Nam"}
INDICATORS = ["SP.URB.TOTL", "SP.POP.TOTL", "SM.POP.NETM", "SL.TLF.TOTL.IN", "SL.UEM.TOTL.ZS",
              "IC.BUS.NREG", "IC.BUS.NDNS.ZS", "NY.GDP.MKTP.KD", "NY.GDP.MKTP.CD",
              "BX.KLT.DINV.CD.WD", "BX.TRF.PWKR.CD.DT"]


def get(ind: str) -> dict[str, dict[int, float]]:
    url = API.format(c=";".join(COUNTRIES), i=ind)
    for attempt in range(3):
        try:
            r = requests.get(url, headers=HEADERS, timeout=60)
            r.raise_for_status()
            body = r.json()
            break
        except (requests.RequestException, ValueError):
            if attempt == 2:
                raise
            time.sleep(3 * (attempt + 1))
    if not isinstance(body, list) or len(body) < 2 or body[1] is None:
        raise ParserDriftError(f"World Bank {ind}: unexpected response {str(body)[:200]}")
    out: dict[str, dict[int, float]] = {c: {} for c in COUNTRIES}
    for row in body[1]:
        if row["value"] is not None:
            out[row["countryiso3code"]][int(row["date"])] = float(row["value"])
    return out


def main() -> int:
    print("World Bank — SEA")
    raw = {}
    for ind in INDICATORS:
        raw[ind] = get(ind)
        n = sum(1 for c in raw[ind].values() if c)
        print(f"  {ind:<20} {n}/11 countries  latest {max((max(v) for v in raw[ind].values() if v), default='–')}")
    # employed persons, derived
    emp = {}
    for c in COUNTRIES:
        lf, u = raw["SL.TLF.TOTL.IN"][c], raw["SL.UEM.TOTL.ZS"][c]
        emp[c] = {y: lf[y] * (1 - u[y] / 100) for y in lf if y in u}
    raw["EMPLOYED"] = emp
    out = {
        "source": {"name": "World Bank — World Development Indicators",
                   "url": "https://data.worldbank.org/", "license": "CC BY 4.0"},
        "countries": {c: {"name": n, "slug": s, "native": NATIVE[c]} for c, (n, s) in COUNTRIES.items()},
        "series": {ind: {c: {str(y): v for y, v in sorted(d.items())} for c, d in by_c.items()}
                   for ind, by_c in raw.items()},
    }
    OUT.mkdir(parents=True, exist_ok=True)
    json.dump(out, open(OUT / "sea_wb.json", "w"), ensure_ascii=False, separators=(",", ":"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
