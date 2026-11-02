"""
Which district each municipality's tambons lie in — the key to district population from stat.bora.

  python etl/th_dopa_xwalk.py   → data/reference/th_registry_tambon.csv   (run rarely; the catalog stopped at 2024)

stat.bora's province files (etl/th_dopa.py) list a district office's own registry, then every municipality (เทศบาล,
เมืองพัทยา) with the tambons it covers, by name only. Some tambon names repeat inside a province (ในเมือง, หนองปรือ…),
so a name cannot say which district a municipality's part belongs to. The DOPA open-data catalog's tambon file
(stat_t{yy}.xls inside stat_{yy}.zip, 2020–2024) gives the same registry rows with an 8-digit tambon code whose first
four digits are the district. We keep only municipality rows, from every year, so renamed municipalities (a เทศบาลตำบล
upgraded to เทศบาลเมือง) are found under either name.

Two municipalities can share a name inside a province (เทศบาลตำบลหนองไผ่ twice in Udon Thani). Both sources list
registries in registry-code order, so the key carries the occurrence: the 1st, 2nd … registry of that name.
"""

from __future__ import annotations

import csv
import html
import io
import re
import sys
import zipfile
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))
from etl import REF, HEADERS, ParserDriftError  # noqa: E402

PACKAGE = "https://catalog.dopa.go.th/api/3/action/package_show?id=221a73a3-2223-4fdc-a79e-6738ff40bb57"
YEARS_BE = range(2563, 2568)
OUT_CSV = REF / "th_registry_tambon.csv"
MUNI = re.compile(r"^(เทศบาล|เมืองพัทยา|ทต\.|ทม\.|ทน\.)")


def norm_registry(s: str) -> str:
    return re.sub(r"\s+", "", re.sub(r"^ท้องถิ่น", "", s.strip()))


def norm_tambon(s: str) -> str:
    return re.sub(r"\s+", "", re.sub(r"^(ตำบล|แขวง)", "", s.strip()))


def rows_of(table: str) -> list[list[str]]:
    return [[html.unescape(re.sub("<.*?>", "", c)).strip() for c in re.findall(r"<td>(.*?)</td>", r, re.S)]
            for r in re.findall(r"<tr>(.*?)</tr>", table, re.S)]


def main() -> int:
    res = {r["name"]: r["url"] for r in requests.get(PACKAGE, headers=HEADERS, timeout=60).json()["result"]["resources"]}
    pairs: dict[tuple[str, str, int, str], set[str]] = {}
    for be in YEARS_BE:
        url = next((u for n, u in res.items() if str(be) in n), None)
        if not url:
            raise ParserDriftError(f"catalog has no resource for {be}")
        z = zipfile.ZipFile(io.BytesIO(requests.get(url, headers=HEADERS, timeout=300).content))
        name = next(n for n in z.namelist() if re.search(rf"stat_t{be % 100}\.xls$", n))
        rows = rows_of(z.read(name).decode("utf-8-sig"))
        head = rows[0]
        if head[3:7] != ["รหัสสำนักทะเบียน", "ชื่อสำนักทะเบียน", "รหัสตำบล", "ชื่อตำบล"]:
            raise ParserDriftError(f"{name}: unexpected header {head}")
        n = 0
        seen: dict[tuple[str, str], list[str]] = {}            # (province, name) → registry codes in order
        for r in sorted(rows[1:], key=lambda r: (r[1], r[3].zfill(6))):
            prov, rcode, reg, code, tam = r[1], r[3], norm_registry(r[4]), r[5], norm_tambon(r[6])
            if not MUNI.match(reg) or not re.fullmatch(r"\d{8}", code):
                continue
            codes = seen.setdefault((prov, reg), [])
            if rcode not in codes:
                codes.append(rcode)
            pairs.setdefault((prov, reg, codes.index(rcode) + 1, tam), set()).add(code[:4])
            n += 1
        print(f"  {be}  {n} municipality × tambon rows")
    clash = {k: v for k, v in pairs.items() if len(v) > 1}
    if clash:
        raise ParserDriftError(f"a municipality's tambon sits in two districts: {list(clash.items())[:5]}")
    with open(OUT_CSV, "w", encoding="utf-8", newline="") as f:
        f.write("# municipality registry × tambon → district (TIS-1099), from DOPA catalog stat_t 2020–2024. etl/th_dopa_xwalk.py\n")
        w = csv.writer(f)
        w.writerow(["province", "registry", "nth", "tambon", "district"])
        for (p, reg, k, tam), ds in sorted(pairs.items()):
            w.writerow([p, reg, k, tam, next(iter(ds))])
    print(f"{OUT_CSV.name}  {len(pairs)} pairs")
    return 0


if __name__ == "__main__":
    sys.exit(main())
