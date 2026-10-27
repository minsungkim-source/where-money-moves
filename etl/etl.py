"""
Where Money Moves TH — ETL

BOT 군별 예수신 파일(cb_t3E-district.zip)을 받아 군·주 단위 시계열과 모멘텀을 굽는다.

  python etl/etl.py               # 다운로드 → data/processed/*.json
  python etl/etl.py --use-cache   # data/raw/의 zip 재사용 (개발용)

────────────────────────────────────────────────────────────────────────────
왜 이 파일인가
  BOT 주별 표(reportID=781)는 공개 페이지가 2025-06에서 멈춰 있다.
  군별 zip은 월간으로 계속 갱신된다 (2026-10 확인: 2026-07분까지).
  "돈이 어디로 움직이나"는 신선도가 생명이라 MVP는 이 파일을 척추로 쓴다.

이 파일의 성질 (2026-10-27 실측)
  · 연도별 xlsx, 시트 = 월. 같은 달이 두 파일에 있을 수 있다 —
    `(2025).xlsx`의 'Jan 25 P'(잠정)와 `(2025)_S2.xlsx`의 'Jan 25'(개정).
    → **_S2(개정)가 이긴다.** 같은 파일 안에서는 ' P'가 붙지 않은 쪽.
  · 기준월은 1행 'Outstanding As of July 2026'. 시트 이름은 'June 26'·'Jul23'처럼 제멋대로라
    1행을 우선하고, 1행이 비면(2025_S2의 'Jan 25') 시트 이름으로 폴백한다.
  · 3행 헤더, 4행 서브헤더, 5행 'Head Office', 6행부터 주 헤더(수치 칸이 '') + 군 행.
  · 금액 단위 **백만 바트**. 여기서 한 번만 바트로 바꾼다.
  · 수록 기준: "상업은행이 4곳 이상인 군"만. 주 헤더 포함 2023-01 338행 → 2026-07 309행
    (주 헤더를 빼면 군은 약 270 → 240개).
    **군이 표에서 빠지는 것 = 은행이 4곳 미만으로 줄었다는 신호**이고,
    증가율은 두 시점 모두에 있는 군끼리만 비교한다 (빠진 군을 0으로 두지 않는다).
  · 각주 **: 차주 5명 이하 구간의 여신은 비공개 → 여신 칸이 비거나 '-'일 수 있다.
  · Head Office 행은 본점 장부라 지리가 아니다. 군·주 합계에서 뺀다.
────────────────────────────────────────────────────────────────────────────
"""

from __future__ import annotations

import argparse
import csv
import difflib
import io
import json
import re
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import openpyxl
import requests

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"
REF = ROOT / "data" / "reference"
OUT = ROOT / "data" / "processed"

URL = ("https://www.bot.or.th/content/dam/bot/documents/en/statistics/"
       "financial-institutions-statistics/cb_t3E-district.zip")
HEADERS = {"User-Agent": "wheremoneymoves-th/0.1 (public-data research)"}

START_YEAR = 2023          # 3년 비교 + 스파크라인에 충분하다
MB = 1_000_000.0

MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}

# 4행 서브헤더 지문. 공백·대소문자는 무시한다. 양식이 둘이다 —
#   2024-07~ : 여신 세부 3칸 (Overdraft · Loan · Bills and Others)
#   ~2024-06 : 여신 세부 4칸 (Overdraft · Loan · Bills · Others)
# 지문이 둘 중 어느 것과도 다르면 멈춘다.
DEPOSIT_SUB = ["current", "saving", "time", "promissorynote", "ncd", "total"]
LAYOUTS = {
    3: DEPOSIT_SUB + ["overdraft", "loan", "billsandothers", "total"],
    4: DEPOSIT_SUB + ["overdraft", "loan", "bills", "others", "total"],
}


class ParserDriftError(RuntimeError):
    """표 구조가 기대와 다르다. 틀린 숫자를 만드느니 멈춘다."""


# ── 다운로드 ─────────────────────────────────────────────────────────────

def fetch_zip(use_cache: bool) -> bytes:
    RAW.mkdir(parents=True, exist_ok=True)
    path = RAW / "cb_t3E-district.zip"
    if use_cache and path.exists():
        print(f"  cache  {path.name}")
        return path.read_bytes()
    r = requests.get(URL, headers=HEADERS, timeout=180)
    r.raise_for_status()
    if not r.content.startswith(b"PK"):
        raise ParserDriftError("응답이 zip이 아니다 — URL이 바뀌었거나 오류 페이지다.")
    path.write_bytes(r.content)
    print(f"  fetch  {len(r.content)/1e6:.1f}MB")
    return r.content


# ── 시트 파싱 ────────────────────────────────────────────────────────────

def _norm(s: str) -> str:
    return re.sub(r"[^a-z]", "", (s or "").lower())


def _num(v) -> float | None:
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip().replace(",", "")
    if s in ("", "-", "n.a.", "na"):
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _period_of(label, sheet_name: str) -> str:
    """'Outstanding As of July 2026' 또는 시트 이름 'Jun23' → '2026-07'."""
    if label:
        m = re.search(r"([A-Za-z]{3})[a-z]*\s+(\d{4})", str(label).split("of", 1)[-1])
        if m and m.group(1).lower() in MONTHS:
            return f"{m.group(2)}-{MONTHS[m.group(1).lower()]:02d}"
    m = re.match(r"\s*([A-Za-z]{3})[a-z]*\s*(\d{2})", sheet_name)
    if m and m.group(1).lower() in MONTHS:
        return f"20{m.group(2)}-{MONTHS[m.group(1).lower()]:02d}"
    raise ParserDriftError(f"시트 '{sheet_name}'의 기준월을 읽지 못했다 (1행: {label!r}).")


def parse_sheet(rows: list[tuple], where: str) -> tuple[dict, list[dict]]:
    """→ (head_office, [ {province_raw, district_raw, branches, deposits, credits} ])"""
    if _norm(rows[3][0]) != "provincesdistricts":
        raise ParserDriftError(f"{where}: 3행 헤더가 'Provinces/Districts'가 아니다: {rows[3][0]!r}")
    sub = [_norm(c) for c in rows[4][2:] if c]
    n_cr = next((k for k, v in LAYOUTS.items() if sub == v), None)
    if n_cr is None:
        raise ParserDriftError(f"{where}: 4행 서브헤더 지문 불일치: {sub}")
    width = 2 + len(LAYOUTS[n_cr])          # 0열 이름 + 1열 지점 + 세부·합계
    if not any("millionbaht" in _norm(c) for c in rows[2] if c):
        raise ParserDriftError(f"{where}: 단위가 'Million Baht'가 아니다.")

    head, out, province = None, [], None
    for i, r in enumerate(rows[5:], start=5):
        name = (str(r[0]).strip() if r[0] is not None else "")
        if not name:
            continue
        if name.lower().startswith(("remark", "*", "note", "source")):
            break
        if _norm(name) in ("total", "grandtotal"):      # 2023-01~04 시트에만 있는 전국 합계 행
            break
        vals = [_num(c) for c in r[1:width]]
        if all(v is None for v in vals):           # 주 헤더
            province = name
            continue
        br, dep, cr = vals[0], vals[6], vals[-1]
        if dep is None or br is None:
            raise ParserDriftError(f"{where} {i}행 '{name}': 지점 수나 예금 합계가 비었다.")
        # 열 정렬 교차 검증 — 합계 = 세부의 합. 한 칸 밀리면 여기서 깨진다.
        parts = [v or 0.0 for v in vals[1:6]]
        if abs(sum(parts) - dep) > max(2.0, dep * 0.001):
            raise ParserDriftError(f"{where} {i}행 '{name}': 예금 세부 합 {sum(parts)} ≠ 합계 {dep}")
        if cr is not None:
            # 각주 **: 차주 5명 이하 세부 칸은 'n.a.'로 가려진다. 합계는 그대로 공표된다.
            # 가려진 칸이 있으면 '세부 합 ≤ 합계'만, 없으면 같음을 요구한다.
            cparts = vals[7:-1]
            known = sum(v for v in cparts if v is not None)
            tol = max(2.0, cr * 0.001)
            if (None in cparts and known > cr + tol) or (None not in cparts and abs(known - cr) > tol):
                raise ParserDriftError(f"{where} {i}행 '{name}': 여신 세부 합 {known} ≠ 합계 {cr}")
        rec = {"branches": int(br), "deposits": dep * MB,
               "credits": cr * MB if cr is not None else None}
        if _norm(name) == "headoffice":
            head = rec
            continue
        if province is None:
            raise ParserDriftError(f"{where} {i}행 '{name}': 주 헤더보다 군이 먼저 나왔다.")
        out.append({"province_raw": province, "district_raw": name, **rec})
    if len(out) < 200:
        raise ParserDriftError(f"{where}: 군 행이 {len(out)}개뿐이다 (주 헤더를 뺀 군은 240~270개다).")
    return head, out


def read_all(zbytes: bytes) -> dict[str, dict]:
    """→ {period: {'head': ..., 'rows': [...], 'src': 'file/sheet'}} — 개정판 우선."""
    zf = zipfile.ZipFile(io.BytesIO(zbytes))
    chosen: dict[str, tuple[int, dict]] = {}
    for name in sorted(zf.namelist()):
        m = re.search(r"\((\d{4})\)(_S\d)?\.xlsx$", name)
        if not m or int(m.group(1)) < START_YEAR:
            continue
        revised = bool(m.group(2))
        wb = openpyxl.load_workbook(io.BytesIO(zf.read(name)), read_only=True, data_only=True)
        for sheet in wb.sheetnames:
            rows = list(wb[sheet].iter_rows(max_row=420, max_col=16, values_only=True))
            period = _period_of(rows[1][0] if len(rows) > 1 else None, sheet)
            prelim = bool(re.search(r"\sP\s*$", sheet))
            rank = (2 if revised else 0) + (0 if prelim else 1)
            if period in chosen and chosen[period][0] >= rank:
                continue
            where = f"{Path(name).name}/{sheet}"
            head, recs = parse_sheet(rows, where)
            chosen[period] = (rank, {"head": head, "rows": recs, "src": where, "prelim": prelim})
    return {p: v for p, (_, v) in sorted(chosen.items())}


# ── 조인 ─────────────────────────────────────────────────────────────────

def _skel(s: str) -> str:
    """로마자 표기 흔들림을 접는다: Chiengmai ≈ Chiang Mai, Muang ≈ Mueang, Pahtthalung ≈ Phatthalung."""
    s = _norm(s)
    for a, b in (("mueang", "muang"), ("ue", "u"), ("ph", "p"), ("th", "t"), ("kh", "k"),
                 ("ch", "c"), ("j", "c"), ("ie", "ia"), ("oe", "o"), ("aeo", "aew"),
                 ("w", "o"), ("y", "i"), ("ee", "i"), ("oo", "u"), ("h", "")):
        s = s.replace(a, b)
    return re.sub(r"(.)\1+", r"\1", s)     # 겹자음 접기


def load_reference():
    provs = list(csv.DictReader(open(REF / "thailand-adm1-provinces-v1.0.0.csv", encoding="utf-8")))
    dists = list(csv.DictReader(open(REF / "thailand-adm2-districts-v1.0.0.csv", encoding="utf-8")))
    aliases = {}
    alias_path = REF / "district_aliases.csv"
    if alias_path.exists():
        for r in csv.DictReader(l for l in open(alias_path, encoding="utf-8") if not l.startswith("#")):
            aliases[(r["province_tis"], _norm(r["district_raw"]))] = r["district_tis"]
    return provs, dists, aliases


def build_province_index(provs) -> dict[str, str]:
    """정식명 + name_alternates_en + blindspot-th의 BOT 별칭표(province_name_aliases.csv)."""
    idx: dict[str, str] = {}
    for p in provs:
        names = [p["name_en_canonical"], *(p["name_alternates_en"] or "").split("|")]
        for n in names:
            if n:
                idx.setdefault(_skel(n), p["tis1099_code"])
    lines = (l for l in open(REF / "province_name_aliases.csv", encoding="utf-8") if not l.startswith("#"))
    for r in csv.DictReader(lines):
        idx.setdefault(_skel(r["source_spelling"]), r["tis1099_code"].zfill(2))
    return idx


def match_province(raw: str, idx: dict[str, str]) -> str:
    k = _skel(raw)
    if k in idx:
        return idx[k]
    best = difflib.get_close_matches(k, idx.keys(), n=2, cutoff=0.8)
    if len(best) == 1 or (len(best) == 2 and idx[best[0]] == idx[best[1]]):
        return idx[best[0]]
    raise ParserDriftError(f"주 이름 '{raw}'를 붙이지 못했다 (후보 {best}).")


def match_district(prov: str, raw: str, by_prov: dict, aliases: dict) -> tuple[str, float]:
    if (prov, _norm(raw)) in aliases:
        return aliases[(prov, _norm(raw))], 1.0
    cands = by_prov.get(prov, [])
    k = _skel(raw)
    scored = []
    for d in cands:
        name = d["name_en"]
        keys = {_skel(name)}
        if name.lower().startswith("mueang "):          # 'Muang Chiangmai' ↔ 'Mueang Chiang Mai'
            keys.add(_skel("muang"))
            keys.add(_skel(name.split(" ", 1)[1]))
        scored.append((max(difflib.SequenceMatcher(None, k, x).ratio() for x in keys), d["tis1099_district_code"]))
    scored.sort(reverse=True)
    if not scored:
        raise ParserDriftError(f"주 {prov}에 군 후보가 없다.")
    top = scored[0]
    second = scored[1][0] if len(scored) > 1 else 0.0
    if top[0] >= 0.86 and top[0] - second >= 0.08:
        return top[1], top[0]
    raise LookupError(f"{prov}/{raw}: 최고 {top} 차점 {second:.2f}")


# ── 지표 ─────────────────────────────────────────────────────────────────

def shift(period: str, months: int) -> str:
    y, m = (int(x) for x in period.split("-"))
    t = y * 12 + (m - 1) - months
    return f"{t // 12}-{t % 12 + 1:02d}"


def growth(series: dict, a: str, b: str, key: str) -> float | None:
    va, vb = (series.get(a) or {}).get(key), (series.get(b) or {}).get(key)
    if va is None or vb is None or vb <= 0:
        return None
    return va / vb - 1


def pct_rank(values: dict[str, float | None]) -> dict[str, float | None]:
    """77개·309개 안의 백분위 (0~100, 동점 평균순위). 결측은 결측으로 둔다."""
    xs = sorted((v, k) for k, v in values.items() if v is not None)
    n = len(xs)
    out: dict[str, float | None] = {k: None for k in values}
    i = 0
    while i < n:
        j = i
        while j + 1 < n and xs[j + 1][0] == xs[i][0]:
            j += 1
        r = (i + j) / 2
        for t in range(i, j + 1):
            out[xs[t][1]] = 100.0 * r / (n - 1) if n > 1 else 50.0
        i = j + 1
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--use-cache", action="store_true")
    args = ap.parse_args()

    print("BOT district zip")
    months = read_all(fetch_zip(args.use_cache))
    periods = list(months)
    latest = periods[-1]
    print(f"  {len(periods)}개월  {periods[0]} … {latest}  (최신 {months[latest]['src']})")

    provs, dists, aliases = load_reference()
    pidx = build_province_index(provs)
    by_prov: dict[str, list] = {}
    for d in dists:
        by_prov.setdefault(d["parent_province_tis1099_code"], []).append(d)
    dmeta = {d["tis1099_district_code"]: d for d in dists}
    pmeta = {p["tis1099_code"]: p for p in provs}

    # 군 시계열 쌓기
    series: dict[str, dict] = {}
    raw_names: dict[str, set] = {}
    unmatched: dict[tuple, str] = {}
    for period, blob in months.items():
        seen = set()
        for r in blob["rows"]:
            ptis = match_province(r["province_raw"], pidx)
            try:
                dtis, _ = match_district(ptis, r["district_raw"], by_prov, aliases)
            except LookupError as e:
                unmatched[(ptis, r["district_raw"].strip())] = str(e)
                continue
            if dtis in seen:
                raise ParserDriftError(f"{period}: 군 {dtis}에 두 행이 붙었다 ('{r['district_raw']}').")
            seen.add(dtis)
            series.setdefault(dtis, {})[period] = {k: r[k] for k in ("branches", "deposits", "credits")}
            raw_names.setdefault(dtis, set()).add(r["district_raw"].strip())

    if unmatched:
        print(f"\n  ✗ 군 이름 {len(unmatched)}개를 붙이지 못했다 → data/reference/district_aliases.csv에 추가:")
        for (p, raw), why in sorted(unmatched.items()):
            print(f"     {p},{raw}    ({why})")
        return 1

    y1, y3 = shift(latest, 12), shift(latest, 36)
    if y1 not in months:
        raise ParserDriftError(f"전년 동월 {y1}이 파일에 없다.")

    # 군 지표
    D = {}
    for dtis, s in series.items():
        d = dmeta[dtis]
        D[dtis] = {
            "id": dtis, "prov": d["parent_province_tis1099_code"],
            "name_en": d["name_en"], "name_th": d["name_th"],
            "lat": float(d["centroid_lat"]), "lon": float(d["centroid_lon"]),
            "bot_names": sorted(raw_names[dtis]),
            "in_latest": latest in s,
            "branches": (s.get(latest) or {}).get("branches"),
            "deposits": (s.get(latest) or {}).get("deposits"),
            "credits": (s.get(latest) or {}).get("credits"),
            "dep_yoy": growth(s, latest, y1, "deposits"),
            "cr_yoy": growth(s, latest, y1, "credits"),
            "dep_3y": growth(s, latest, y3, "deposits"),
            "br_change": (s[latest]["branches"] - s[y1]["branches"]) if latest in s and y1 in s else None,
            "series": [[p, s[p]["deposits"], s[p]["credits"], s[p]["branches"]] if p in s else [p, None, None, None]
                       for p in periods],
        }
    score_inputs = {k: v for k, v in D.items() if v["in_latest"]}
    pd_ = pct_rank({k: v["dep_yoy"] for k, v in score_inputs.items()})
    pc_ = pct_rank({k: v["cr_yoy"] for k, v in score_inputs.items()})
    for k, v in D.items():
        a, b = pd_.get(k), pc_.get(k)
        parts = [x for x in (a, b) if x is not None]
        v["score"] = sum(parts) / len(parts) if parts else None
        v["score_parts"] = len(parts)
    ranked = sorted((v for v in D.values() if v["score"] is not None), key=lambda v: -v["score"])
    for i, v in enumerate(ranked, 1):
        v["rank"] = i

    # 주 지표 — 두 시점 모두에 있는 군끼리 합산 (같은 군 집합 비교)
    P = {}
    for ptis, p in pmeta.items():
        members = [v for v in D.values() if v["prov"] == ptis]
        both = [series[v["id"]] for v in members if latest in series[v["id"]] and y1 in series[v["id"]]]

        def tot(per, key, sset=both):
            xs = [s[per][key] for s in sset]
            return None if not xs or any(x is None for x in xs) else sum(xs)

        dep_now, dep_then = tot(latest, "deposits"), tot(y1, "deposits")
        cr_now, cr_then = tot(latest, "credits"), tot(y1, "credits")
        P[ptis] = {
            "id": ptis, "name_en": p["name_en_canonical"], "name_th": p["name_th"],
            "region": p["region"],
            "n_districts_total": int(p["num_amphoe"]),
            "n_covered": sum(1 for v in members if v["in_latest"]),
            "n_dropped": sum(1 for v in members if not v["in_latest"] and y1 in series[v["id"]]),
            "deposits": sum(v["deposits"] for v in members if v["in_latest"]) or None,
            "branches": sum(v["branches"] for v in members if v["in_latest"]) or None,
            "dep_yoy": (dep_now / dep_then - 1) if dep_now and dep_then else None,
            "cr_yoy": (cr_now / cr_then - 1) if cr_now and cr_then else None,
            "br_change": (sum(s[latest]["branches"] for s in both) - sum(s[y1]["branches"] for s in both)) if both else None,
        }
    qd = pct_rank({k: v["dep_yoy"] for k, v in P.items()})
    qc = pct_rank({k: v["cr_yoy"] for k, v in P.items()})
    for k, v in P.items():
        parts = [x for x in (qd[k], qc[k]) if x is not None]
        v["score"] = sum(parts) / len(parts) if parts else None
    pr = sorted((v for v in P.values() if v["score"] is not None), key=lambda v: -v["score"])
    for i, v in enumerate(pr, 1):
        v["rank"] = i

    # 전국 (커버된 군 합계, 같은 집합)
    both_all = [s for s in series.values() if latest in s and y1 in s]
    nat = {
        "dep_yoy": sum(s[latest]["deposits"] for s in both_all) / sum(s[y1]["deposits"] for s in both_all) - 1,
        "n_covered": sum(1 for v in D.values() if v["in_latest"]),
        "n_dropped": sum(1 for v in D.values() if not v["in_latest"] and y1 in series[v["id"]]),
        "head_office_deposits": (months[latest]["head"] or {}).get("deposits"),
    }

    OUT.mkdir(parents=True, exist_ok=True)
    meta = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "latest": latest, "yoy_base": y1, "base_3y": y3 if y3 in months else None,
        "latest_prelim": months[latest]["prelim"], "latest_src": months[latest]["src"],
        "periods": periods, "national": nat,
        "source": {"name": "Bank of Thailand — Deposits and Credits Classified by Districts",
                   "url": URL, "unit": "baht (nominal)",
                   "coverage": "Districts with four or more commercial banks only",
                   "license": "Bank of Thailand — attribution required, aggregate publication only"},
        "admin_ref": {"name": "thailand-canonical-admin-names v1.0.2", "license": "CC BY 4.0"},
    }
    json.dump(meta, open(OUT / "meta.json", "w"), ensure_ascii=False, indent=1)
    json.dump(sorted(D.values(), key=lambda v: v["id"]), open(OUT / "districts.json", "w"), ensure_ascii=False)
    json.dump(sorted(P.values(), key=lambda v: v["id"]), open(OUT / "provinces.json", "w"), ensure_ascii=False)
    print(f"\n  군 {len(D)} (최신 {nat['n_covered']}, 1년 새 빠짐 {nat['n_dropped']})  주 {len(pr)}/77 점수")
    print(f"  전국(커버 군 합) 예금 YoY {nat['dep_yoy']*100:+.2f}%")
    for v in ranked[:5]:
        print(f"   #{v['rank']:<3} {v['name_en']:<22} {pmeta[v['prov']]['name_en_canonical']:<16} "
              f"dep {v['dep_yoy']*100:+6.1f}%  cr {(v['cr_yoy'] or 0)*100:+6.1f}%  score {v['score']:.0f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
