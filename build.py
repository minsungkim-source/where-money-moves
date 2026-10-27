"""
Where Money Moves TH — 정적 사이트 생성기

  python build.py        # data/processed/*.json → site/

페이지 (언어마다, th · en):
  /{lang}/                              홈: 지도 + 순위
  /{lang}/province/{p}/                 주 77개 (점수 없는 9개 주도 '데이터 없음' 페이지를 만든다)
  /{lang}/district/{p}/{d}/             군 (BOT 표에 한 번이라도 나온 군 전부)
  /{lang}/rankings/{key}/               순위 5종
  /{lang}/about/                        방법론·출처
+ /index.html(언어 선택), sitemap.xml, robots.txt, manifest, sw.js, search-{lang}.json

런타임 백엔드 없음. 페이지는 JS 없이도 전부 읽힌다 — JS는 지도 탭·검색·정렬·설치만 맡는다.
화면 문구는 이 파일의 STR 한 곳에만 둔다. th가 기준 형태이고 en은 같은 키를 가져야 한다.
"""

from __future__ import annotations

import html
import json
import math
import re
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data" / "processed"
REF = ROOT / "data" / "reference"
STATIC = ROOT / "static"
OUT = ROOT / "site"
SITE_URL = "https://wheremoneymoves-th.vercel.app"     # 배포 주소가 정해지면 바꾼다
# 주 맥락값(인구·1인당 GPP, NESDC). blindspot-th ETL이 굽는 값을 슬림하게 옮겨 둔 것 —
# Vercel 빌드에는 옆 폴더가 없으므로 이 저장소 안의 사본을 읽는다.
CONTEXT = REF / "nesdc_context.json"

LANGS = ("th", "en")

# ── 문구 ─────────────────────────────────────────────────────────────────

STR = {
    "th": {
        "brand": "เงินไหลไปไหน",
        "brand_sub": "Where Money Moves",
        "tagline": "เงินฝากและสินเชื่อธนาคารพาณิชย์รายอำเภอ เทียบกับปีก่อน",
        "hero": "เงินกำลังไหลไปที่ไหน",
        "hero_sub": "ดูว่าอำเภอไหนเงินฝากและสินเชื่อโตเร็วที่สุด และที่ไหนเงินกำลังไหลออก จากข้อมูลธนาคารแห่งประเทศไทยรายเดือน",
        "data_as_of": "ข้อมูลเดือน {p}",
        "prelim": "ตัวเลขเบื้องต้น",
        "national_dep": "เงินฝากรวม (อำเภอที่เข้าเกณฑ์)",
        "vs_last_year": "เทียบ {p}",
        "score": "คะแนนโมเมนตัมเงิน",
        "score_short": "คะแนน",
        "deposits": "เงินฝาก",
        "credits": "สินเชื่อ",
        "branches": "สาขา",
        "branch_change": "สาขาเปลี่ยนแปลง",
        "yoy": "เทียบปีก่อน",
        "three_year": "เงินฝาก 3 ปี",
        "dep_balance": "ยอดเงินฝาก",
        "rank_of": "อันดับ {r} จาก {n}",
        "n_districts": "อำเภอ",
        "n_provinces": "จังหวัด",
        "province": "จังหวัด",
        "district": "อำเภอ",
        "khet": "เขต",
        "map_title": "แผนที่โมเมนตัมเงินรายจังหวัด",
        "map_hint": "แตะจังหวัดเพื่อดูตัวเลข",
        "metric_score": "คะแนน",
        "metric_dep": "เงินฝาก",
        "metric_cr": "สินเชื่อ",
        "legend_low": "ต่ำ",
        "legend_high": "สูง",
        "no_data": "ไม่มีข้อมูล",
        "open_page": "ดูรายละเอียด",
        "top_districts": "อำเภอที่เงินโตเร็วที่สุด",
        "top_provinces": "จังหวัดที่เงินโตเร็วที่สุด",
        "money_leaving": "อำเภอที่เงินฝากลดลงมากที่สุด",
        "branch_losers": "อำเภอที่สาขาธนาคารลดลงมากที่สุด",
        "dropped_title": "หลุดจากตาราง ธปท. ในปีที่ผ่านมา",
        "dropped_note": "ธปท. เผยแพร่เฉพาะอำเภอที่มีธนาคารพาณิชย์ตั้งแต่ 4 แห่งขึ้นไป อำเภอเหล่านี้เคยอยู่ในตารางเมื่อ {p} แต่ไม่อยู่ในเดือนล่าสุด",
        "view_all": "ดูทั้งหมด",
        "search": "ค้นหาจังหวัดหรืออำเภอ",
        "search_none": "ไม่พบ",
        "rankings": "อันดับ",
        "about": "วิธีคิดและที่มา",
        "home": "หน้าแรก",
        "coverage": "นับเฉพาะอำเภอที่มีธนาคารพาณิชย์ตั้งแต่ 4 แห่งขึ้นไป: {n} จาก {total} อำเภอของจังหวัดนี้",
        "coverage_none": "จังหวัดนี้ไม่มีอำเภอที่อยู่ในตาราง ธปท. ในเดือนล่าสุด จึงยังไม่มีคะแนน",
        "district_table": "อำเภอในจังหวัดนี้",
        "national_rank": "อันดับประเทศ",
        "in_province": "ในจังหวัด",
        "trend": "แนวโน้มเงินฝาก",
        "chart_dep": "เงินฝาก (ล้านบาท)",
        "chart_cr": "สินเชื่อ (ล้านบาท)",
        "chart_br": "จำนวนสาขา",
        "monthly_table": "ตัวเลขรายเดือน",
        "month": "เดือน",
        "spike": "สินเชื่อเปลี่ยนแปลงผิดปกติ อาจมาจากสินเชื่อรายใหญ่ไม่กี่ราย หรือการย้ายบัญชีระหว่างสาขา",
        "not_in_latest": "อำเภอนี้ไม่อยู่ในตาราง ธปท. เดือนล่าสุด (ข้อมูลล่าสุดที่มี: {p})",
        "other_districts": "อำเภออื่นในจังหวัดเดียวกัน",
        "context": "ข้อมูลประกอบ",
        "population": "ประชากร",
        "gpp_pc": "GPP ต่อหัว",
        "context_src": "สศช. ปี {y}",
        "rk_districts": "อำเภอ: คะแนนโมเมนตัมเงิน",
        "rk_provinces": "จังหวัด: คะแนนโมเมนตัมเงิน",
        "rk_deposit": "อำเภอ: เงินฝากโตเร็วที่สุด",
        "rk_credit": "อำเภอ: สินเชื่อโตเร็วที่สุด",
        "rk_branches": "อำเภอ: สาขาธนาคารเปลี่ยนแปลง",
        "rk_desc": "{what} เทียบ {p1} กับ {p0} จากข้อมูลธนาคารแห่งประเทศไทย",
        "sort": "เรียงตาม",
        "install": "ติดตั้งบนหน้าจอหลัก",
        "nominal": "มูลค่าตามราคาปัจจุบัน ไม่ปรับเงินเฟ้อ",
        "src_line": "ที่มา: ธนาคารแห่งประเทศไทย (รายงานเงินฝากและสินเชื่อจำแนกตามอำเภอ) · ขอบเขตการปกครอง: thailand-canonical-admin-names (CC BY 4.0), geoBoundaries/OCHA (CC BY 3.0 IGO)",
        "built": "สร้างเมื่อ {d}",
        "score_explain": "คะแนน 0–100 = ค่าเฉลี่ยของเปอร์เซ็นไทล์อัตราการเติบโตของเงินฝากและสินเชื่อเทียบปีก่อน ในบรรดา {n} อำเภอ (จังหวัด: เทียบกันเอง {m} จังหวัด)",
        "lang_other": "English",
        "million": "ล้านบาท",
        "title_home": "เงินไหลไปไหน — อำเภอไหนเงินฝากและสินเชื่อโตเร็วที่สุด ({p})",
        "desc_home": "อันดับอำเภอและจังหวัดที่เงินฝากและสินเชื่อธนาคารโตเร็วที่สุดในประเทศไทย เทียบปีก่อน ข้อมูล ธปท. เดือน {p}",
        "title_prov": "{name}: เงินฝาก สินเชื่อ และสาขาธนาคาร ({p}) — เงินไหลไปไหน",
        "desc_prov": "{name} เงินฝากเทียบปีก่อน {dep} สินเชื่อ {cr} อันดับ {rank} ของประเทศ ข้อมูล ธปท. เดือน {p}",
        "title_dist": "{name} {prov}: เงินฝากและสินเชื่อ ({p}) — เงินไหลไปไหน",
        "desc_dist": "{unit}{name} จังหวัด{prov} เงินฝากเทียบปีก่อน {dep} สินเชื่อ {cr} จำนวนสาขา {br} ข้อมูล ธปท. เดือน {p}",
        "about_body": [
            ("ข้อมูลมาจากไหน", "ธนาคารแห่งประเทศไทยเผยแพร่ยอดเงินฝาก สินเชื่อ และจำนวนสาขาของธนาคารพาณิชย์รายอำเภอทุกเดือน เว็บนี้ดาวน์โหลดไฟล์นั้นโดยตรงและไม่ได้แก้ตัวเลข"),
            ("ขอบเขต", "ธปท. เผยแพร่เฉพาะอำเภอที่มีธนาคารพาณิชย์ตั้งแต่ 4 แห่งขึ้นไป เดือนล่าสุดมี {n} อำเภอ อำเภอที่ไม่อยู่ในตารางไม่ได้แปลว่าไม่มีเงิน แต่เราไม่มีตัวเลขของอำเภอนั้น ยอดของสำนักงานใหญ่ (Head Office) ไม่นับเป็นพื้นที่ใด"),
            ("คะแนนคิดอย่างไร", "เทียบเดือนล่าสุดกับเดือนเดียวกันของปีก่อน เฉพาะอำเภอที่มีตัวเลขทั้งสองเดือน แล้วแปลงอัตราการเติบโตของเงินฝากและสินเชื่อเป็นเปอร์เซ็นไทล์ (0–100) และเฉลี่ยกัน ใช้เปอร์เซ็นไทล์เพราะกรุงเทพฯ ใหญ่กว่าที่อื่นมาก ตัวเลขจริงจะทำให้ที่อื่นแยกกันไม่ออก"),
            ("ระดับจังหวัด", "รวมเฉพาะอำเภอที่อยู่ในตารางทั้งสองเดือน จึงไม่ใช่ยอดทั้งจังหวัด จังหวัดที่ไม่มีอำเภอเข้าเกณฑ์จะไม่มีคะแนน"),
            ("ข้อควรระวัง", "ตัวเลขเป็นมูลค่าตามราคาปัจจุบัน ไม่ปรับเงินเฟ้อ สินเชื่อรายอำเภออาจกระโดดได้เมื่อมีสินเชื่อรายใหญ่หรือการย้ายบัญชีระหว่างสาขา เราจะติดป้ายเตือนเมื่อสินเชื่อเปลี่ยนเกิน ±50% ในหนึ่งปี ตัวเลขบางช่องของ ธปท. ถูกปิดไว้เมื่อลูกหนี้น้อยกว่า 5 ราย แต่ยอดรวมยังเผยแพร่ครบ"),
            ("ต่อไป", "เราจะเพิ่มประชากร (กรมการปกครอง) การจ้างงาน (ประกันสังคม) และนิติบุคคลใหม่ (กรมพัฒนาธุรกิจการค้า) เมื่อยืนยันแหล่งข้อมูลได้แล้ว"),
        ],
    },
    "en": {
        "brand": "Where Money Moves",
        "brand_sub": "Thailand",
        "tagline": "Commercial-bank deposits and credit by district, year over year",
        "hero": "Where is the money moving?",
        "hero_sub": "See which Thai districts are growing deposits and credit fastest, and where money is leaving. Built from monthly Bank of Thailand data.",
        "data_as_of": "Data for {p}",
        "prelim": "preliminary",
        "national_dep": "Deposits, covered districts",
        "vs_last_year": "vs {p}",
        "score": "Money Momentum Score",
        "score_short": "Score",
        "deposits": "Deposits",
        "credits": "Credit",
        "branches": "Branches",
        "branch_change": "Branch change",
        "yoy": "year over year",
        "three_year": "Deposits, 3 years",
        "dep_balance": "Deposit balance",
        "rank_of": "#{r} of {n}",
        "n_districts": "districts",
        "n_provinces": "provinces",
        "province": "Province",
        "district": "District",
        "khet": "Khet",
        "map_title": "Money momentum by province",
        "map_hint": "Tap a province to see its numbers",
        "metric_score": "Score",
        "metric_dep": "Deposits",
        "metric_cr": "Credit",
        "legend_low": "Low",
        "legend_high": "High",
        "no_data": "No data",
        "open_page": "Open page",
        "top_districts": "Fastest-growing districts",
        "top_provinces": "Fastest-growing provinces",
        "money_leaving": "Where deposits fell most",
        "branch_losers": "Where bank branches shrank most",
        "dropped_title": "Dropped from the BOT table this year",
        "dropped_note": "The Bank of Thailand only publishes districts with four or more commercial banks. These districts were in the table in {p} but not in the latest month.",
        "view_all": "See all",
        "search": "Search a province or district",
        "search_none": "No match",
        "rankings": "Rankings",
        "about": "Method & sources",
        "home": "Home",
        "coverage": "Counts only districts with four or more commercial banks: {n} of this province's {total} districts",
        "coverage_none": "No district of this province is in the latest BOT table, so it has no score yet.",
        "district_table": "Districts in this province",
        "national_rank": "National rank",
        "in_province": "in province",
        "trend": "Deposit trend",
        "chart_dep": "Deposits (million baht)",
        "chart_cr": "Credit (million baht)",
        "chart_br": "Branches",
        "monthly_table": "Monthly figures",
        "month": "Month",
        "spike": "Unusual credit swing. Often one or a few large borrowers, or loans moved between branches.",
        "not_in_latest": "This district is not in the latest BOT table (last available: {p}).",
        "other_districts": "Other districts in this province",
        "context": "Context",
        "population": "Population",
        "gpp_pc": "GPP per capita",
        "context_src": "NESDC {y}",
        "rk_districts": "Districts by Money Momentum Score",
        "rk_provinces": "Provinces by Money Momentum Score",
        "rk_deposit": "Districts by deposit growth",
        "rk_credit": "Districts by credit growth",
        "rk_branches": "Districts by bank-branch change",
        "rk_desc": "{what}, {p1} vs {p0}, from Bank of Thailand data.",
        "sort": "Sort by",
        "install": "Install app",
        "nominal": "Nominal values, not inflation-adjusted",
        "src_line": "Source: Bank of Thailand (Deposits and Credits Classified by Districts) · Boundaries: thailand-canonical-admin-names (CC BY 4.0), geoBoundaries/OCHA (CC BY 3.0 IGO)",
        "built": "Built {d}",
        "score_explain": "Score 0–100 = average percentile of year-over-year deposit and credit growth across {n} districts (provinces are ranked among {m} provinces).",
        "lang_other": "ไทย",
        "million": "million baht",
        "title_home": "Where Money Moves Thailand: fastest-growing districts by deposits and credit ({p})",
        "desc_home": "Which Thai districts and provinces are growing bank deposits and credit fastest, year over year. Bank of Thailand data for {p}.",
        "title_prov": "{name} province: deposits, credit and bank branches ({p}) | Where Money Moves",
        "desc_prov": "{name}: deposits {dep} and credit {cr} year over year, ranked {rank} nationally. Bank of Thailand data for {p}.",
        "title_dist": "{name}, {prov}: deposits and credit ({p}) | Where Money Moves",
        "desc_dist": "{name} district, {prov}: deposits {dep} and credit {cr} year over year, {br} bank branches. Bank of Thailand data for {p}.",
        "about_body": [
            ("Where the data comes from", "Every month the Bank of Thailand publishes commercial-bank deposits, credit and branch counts by district. This site downloads that file directly and does not alter the numbers."),
            ("Coverage", "The BOT only publishes districts with four or more commercial banks. The latest month covers {n} districts. A missing district does not mean there is no money there, only that we have no figure for it. Head-office balances are not assigned to any place."),
            ("How the score works", "We compare the latest month with the same month a year earlier, using only districts present in both. Deposit and credit growth are converted to percentiles (0–100) and averaged. We use percentiles because Bangkok is so much larger than everywhere else that raw values would leave the rest of the country indistinguishable."),
            ("Province level", "Province figures add up only the districts present in both months, so they are not full-province totals. Provinces with no covered district have no score."),
            ("Caveats", "Values are nominal, not inflation-adjusted. District credit can jump when a large borrower or a book of loans moves between branches. We flag credit swings above ±50% in a year. Some BOT sub-cells are masked when a segment has five or fewer debtors, but totals are always published."),
            ("Next", "Population (Department of Provincial Administration), employment (Social Security Office) and new companies (Department of Business Development) will be added once their sources are verified."),
        ],
    },
}
assert STR["th"].keys() == STR["en"].keys(), set(STR["th"]) ^ set(STR["en"])

TH_MONTHS = ["ม.ค.", "ก.พ.", "มี.ค.", "เม.ย.", "พ.ค.", "มิ.ย.", "ก.ค.", "ส.ค.", "ก.ย.", "ต.ค.", "พ.ย.", "ธ.ค."]
EN_MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]

# '값을 모른다'는 낮은 값과 다른 말이다 — 램프의 가장 옅은 칸과 헷갈리지 않게 빗금으로 칠한다
HATCH = ('<defs><pattern id="hatch" width="4" height="4" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">'
         '<rect width="4" height="4" class="hb"/><line x1="0" y1="0" x2="0" y2="4" class="hl"/></pattern></defs>')
SPIKE = 0.5            # 여신 ±50%/년 이상이면 경고 배지
DIV_BINS = [-0.10, -0.05, -0.02, 0.02, 0.05, 0.10]    # 증가율 발산 램프 경계 (7칸)


def esc(s) -> str:
    return html.escape(str(s), quote=True)


def period_label(p: str, lang: str) -> str:
    y, m = (int(x) for x in p.split("-"))
    return f"{TH_MONTHS[m-1]} {y+543}" if lang == "th" else f"{EN_MONTHS[m-1]} {y}"


def pct(x, digits=1) -> str:
    if x is None:
        return "–"
    v = x * 100
    if abs(v) >= 1000:
        return f"{v:+,.0f}%"
    return f"{v:+.{digits}f}%".replace("-", "−")


def money(x, lang: str) -> str:
    if x is None:
        return "–"
    if lang == "th":
        return f"{x/1e6:,.0f} ล้านบาท"
    if x >= 1e12:
        return f"฿{x/1e12:.2f}tn"
    if x >= 1e9:
        return f"฿{x/1e9:.1f}bn"
    return f"฿{x/1e6:,.0f}m"


def signed_int(x) -> str:
    if x is None:
        return "–"
    return "0" if x == 0 else f"{x:+d}".replace("-", "−")


def slug(s: str) -> str:
    return re.sub(r"-+", "-", re.sub(r"[^a-z0-9]+", "-", s.lower())).strip("-")


def seq_bin(score) -> str:
    """점수 0–100 → 1..7 (순차 램프)."""
    if score is None:
        return "n"
    return str(min(7, int(score / (100 / 7)) + 1))


def div_bin(g) -> str:
    if g is None:
        return "n"
    return str(sum(1 for b in DIV_BINS if g >= b) + 1)


# ── 지도 ─────────────────────────────────────────────────────────────────

LON0, LAT1, KX = 97.25, 20.55, math.cos(math.radians(13.0))
S = 40.0


def proj(lon, lat):
    return ((lon - LON0) * KX * S, (LAT1 - lat) * S)


def topo_rings():
    """provinces.topo.json → {tis: [ring(투영 좌표 리스트), ...]}. transform이 없어 arcs는 절대좌표다."""
    topo = json.load(open(REF / "provinces.topo.json"))
    arcs = topo["arcs"]

    def arc(i):
        a = arcs[i] if i >= 0 else list(reversed(arcs[~i]))
        return [proj(*pt[:2]) for pt in a]

    def ring(idx):
        pts = []
        for k, i in enumerate(idx):
            seg = arc(i)
            pts.extend(seg if k == 0 else seg[1:])
        return pts

    out = {}
    for g in topo["objects"]["data"]["geometries"]:
        polys = [g["arcs"]] if g["type"] == "Polygon" else g["arcs"]
        out[g["properties"]["tis1099_code"]] = [ring(r) for poly in polys for r in poly]
    return out


def simplify(pts, tol):
    """Douglas–Peucker. 미니맵용."""
    if len(pts) < 3:
        return pts
    (x1, y1), (x2, y2) = pts[0], pts[-1]
    dx, dy = x2 - x1, y2 - y1
    norm = math.hypot(dx, dy) or 1e-9
    dmax, idx = 0.0, 0
    for i in range(1, len(pts) - 1):
        x0, y0 = pts[i]
        d = abs(dy * x0 - dx * y0 + x2 * y1 - y2 * x1) / norm
        if d > dmax:
            dmax, idx = d, i
    if dmax > tol:
        return simplify(pts[:idx + 1], tol)[:-1] + simplify(pts[idx:], tol)
    return [pts[0], pts[-1]]


def simplify_ring(ring, tol):
    """닫힌 고리는 첫 점 = 끝 점이라 기준선 길이가 0이 되어 통째로 접힌다. 가장 먼 점에서 둘로 나눠 단순화한다."""
    x0, y0 = ring[0]
    far = max(range(len(ring)), key=lambda i: (ring[i][0] - x0) ** 2 + (ring[i][1] - y0) ** 2)
    return simplify(ring[:far + 1], tol)[:-1] + simplify(ring[far:], tol)


def path_d(rings, tol=None, min_len=0.0):
    parts = []
    for r in rings:
        if tol:
            r = simplify_ring(r, tol)
            if len(r) < 4:
                continue
        xs = [p[0] for p in r]
        if max(xs) - min(xs) < min_len:
            continue
        parts.append("M" + "L".join(f"{x:.1f},{y:.1f}" for x, y in r) + "Z")
    return "".join(parts)


# ── 차트 ─────────────────────────────────────────────────────────────────

def sparkline(series, idx=1, n=25, w=88, h=24) -> str:
    vals = [r[idx] for r in series[-n:]]
    pts = [(i, v) for i, v in enumerate(vals) if v is not None]
    if len(pts) < 2:
        return ""
    lo, hi = min(v for _, v in pts), max(v for _, v in pts)
    span = (hi - lo) or 1
    sx = w / (n - 1)
    d, prev = "", None
    for i, v in enumerate(vals):
        if v is None:
            prev = None
            continue
        x, y = i * sx, h - 2 - (v - lo) / span * (h - 4)
        d += ("L" if prev is not None else "M") + f"{x:.1f},{y:.1f}"
        prev = i
    return (f'<svg class="spark" viewBox="0 0 {w} {h}" width="{w}" height="{h}" aria-hidden="true">'
            f'<path d="{d}"/></svg>')


def line_chart(series, idx, title, lang, base_period=None) -> str:
    W, H, L, R, T, B = 380, 150, 48, 8, 10, 22      # 휴대폰 폭에서 글자가 9px 아래로 줄지 않는 크기
    vals = [(r[0], r[idx]) for r in series]
    known = [v for _, v in vals if v is not None]
    if len(known) < 2:
        return ""
    lo, hi = min(known), max(known)
    pad = (hi - lo) * 0.08 or hi * 0.05 or 1
    lo, hi = lo - pad, hi + pad
    n = len(vals)
    xs = lambda i: L + i * (W - L - R) / (n - 1)
    ys = lambda v: T + (hi - v) / (hi - lo) * (H - T - B)
    d, prev = "", False
    for i, (_, v) in enumerate(vals):
        if v is None:
            prev = False
            continue
        d += ("L" if prev else "M") + f"{xs(i):.1f},{ys(v):.1f}"
        prev = True
    scale = 1e6 if idx in (1, 2) else 1
    if idx == 3:            # 지점 수는 정수 눈금만 — 반올림한 같은 숫자가 여러 번 찍히지 않게
        lv = list(range(math.ceil(lo), math.floor(hi) + 1))
        levels = lv[:: max(1, math.ceil(len(lv) / 3))] or [round((lo + hi) / 2)]
    else:
        levels = [lo + (hi - lo) * (k + 0.5) / 3 for k in range(3)]
    grid = ""
    for v in levels:
        grid += (f'<line x1="{L}" x2="{W-R}" y1="{ys(v):.1f}" y2="{ys(v):.1f}"/>'
                 f'<text x="{L-5}" y="{ys(v)+4:.1f}" text-anchor="end">{v/scale:,.0f}</text>')
    ticks = ""
    for i, (p, _) in enumerate(vals):
        if p.endswith("-01"):
            y = int(p[:4]) + (543 if lang == "th" else 0)
            ticks += f'<text x="{xs(i):.1f}" y="{H-6}" text-anchor="middle">{y}</text>'
    base = ""
    if base_period:
        bi = next((i for i, (p, _) in enumerate(vals) if p == base_period), None)
        if bi is not None:
            base = f'<line class="base" x1="{xs(bi):.1f}" x2="{xs(bi):.1f}" y1="{T}" y2="{H-B}"/>'
    last = next(((i, v) for i, (_, v) in reversed(list(enumerate(vals))) if v is not None))
    dot = f'<circle cx="{xs(last[0]):.1f}" cy="{ys(last[1]):.1f}" r="3.5"/>'
    return (f'<figure class="chart"><figcaption>{esc(title)}</figcaption>'
            f'<svg viewBox="0 0 {W} {H}" role="img" aria-label="{esc(title)}">'
            f'<g class="grid">{grid}</g><g class="ticks">{ticks}</g>{base}'
            f'<path class="line l{idx}" d="{d}"/>{dot}</svg></figure>')


# ── 페이지 껍데기 ────────────────────────────────────────────────────────

def page(lang, path, title, desc, body, meta, extra_head="", crumbs=None) -> str:
    t = STR[lang]
    other = "en" if lang == "th" else "th"
    alt_path = "/" + other + path[3:]
    canonical = SITE_URL + path
    crumb_ld = ""
    if crumbs:
        items = [{"@type": "ListItem", "position": i + 1, "name": n, "item": SITE_URL + u}
                 for i, (n, u) in enumerate(crumbs)]
        crumb_ld = ('<script type="application/ld+json">'
                    + json.dumps({"@context": "https://schema.org", "@type": "BreadcrumbList",
                                  "itemListElement": items}, ensure_ascii=False) + "</script>")
    nav_crumbs = ""
    if crumbs:
        nav_crumbs = ('<nav class="crumbs" aria-label="breadcrumb">'
                      + " › ".join(f'<a href="{u}">{esc(n)}</a>' for n, u in crumbs[:-1])
                      + f' › <span aria-current="page">{esc(crumbs[-1][0])}</span></nav>')
    return f"""<!doctype html>
<html lang="{lang}">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>{esc(title)}</title>
<meta name="description" content="{esc(desc)}">
<link rel="canonical" href="{canonical}">
<link rel="alternate" hreflang="{lang}" href="{canonical}">
<link rel="alternate" hreflang="{other}" href="{SITE_URL}{alt_path}">
<link rel="alternate" hreflang="x-default" href="{SITE_URL}/th{path[3:]}">
<meta property="og:type" content="website">
<meta property="og:title" content="{esc(title)}">
<meta property="og:description" content="{esc(desc)}">
<meta property="og:url" content="{canonical}">
<meta property="og:image" content="{SITE_URL}/assets/og-{lang}.png">
<meta property="og:locale" content="{'th_TH' if lang == 'th' else 'en_US'}">
<meta name="twitter:card" content="summary_large_image">
<meta name="theme-color" content="#0b1f1a" media="(prefers-color-scheme: dark)">
<meta name="theme-color" content="#f6f8f6" media="(prefers-color-scheme: light)">
<link rel="manifest" href="/manifest-{lang}.webmanifest">
<link rel="icon" href="/assets/icon.svg" type="image/svg+xml">
<link rel="apple-touch-icon" href="/assets/icon-192.png">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=IBM+Plex+Sans+Thai:wght@400;500;600;700&family=IBM+Plex+Mono:wght@500&display=swap">
<link rel="stylesheet" href="/assets/app.css?v={meta['build_id']}">
{extra_head}{crumb_ld}
</head>
<body>
<header class="top">
  <a class="brand" href="/{lang}/"><img class="mark" src="/assets/icon.svg" alt="" width="28" height="28"><span><b>{esc(t['brand'])}</b><small>{esc(t['brand_sub'])}</small></span></a>
  <div class="search" role="search">
    <input id="q" type="search" placeholder="{esc(t['search'])}" aria-label="{esc(t['search'])}" autocomplete="off" data-none="{esc(t['search_none'])}">
    <ul id="qr" role="listbox" hidden></ul>
  </div>
  <nav class="links">
    <a href="/{lang}/rankings/districts/">{esc(t['rankings'])}</a>
    <a href="{alt_path}" hreflang="{other}" lang="{other}">{esc(t['lang_other'])}</a>
  </nav>
</header>
<main>
{nav_crumbs}
{body}
</main>
<footer>
  <p>{esc(t['src_line'])}</p>
  <p>{esc(t['nominal'])} · <a href="/{lang}/about/">{esc(t['about'])}</a> · {esc(t['built'].format(d=meta['built']))}</p>
  <button id="install" class="chip" hidden>{esc(t['install'])}</button>
</footer>
<script src="/assets/app.js?v={meta['build_id']}" defer></script>
</body>
</html>
"""


def stat(label, value, cls="", sub=""):
    return (f'<div class="stat"><span class="k">{esc(label)}</span>'
            f'<span class="v num {cls}">{esc(value)}</span>{f"<span class=s>{esc(sub)}</span>" if sub else ""}</div>')


def growth_cls(g):
    if g is None:
        return ""
    return "up" if g > 0.005 else ("down" if g < -0.005 else "flat")


def score_badge(score, lang, size=""):
    t = STR[lang]
    if score is None:
        return f'<span class="score {size} none">{esc(t["no_data"])}</span>'
    return f'<span class="score {size} b{seq_bin(score)}" title="{esc(t["score"])}"><b class="num">{score:.0f}</b><small>/100</small></span>'


# ── 빌드 ─────────────────────────────────────────────────────────────────

def main():
    meta = json.load(open(DATA / "meta.json"))
    D = json.load(open(DATA / "districts.json"))
    P = json.load(open(DATA / "provinces.json"))
    meta["build_id"] = meta["generated_at"][:19].replace(":", "").replace("-", "")
    meta["built"] = meta["generated_at"][:10]
    latest, y1 = meta["latest"], meta["yoy_base"]

    ctx_src = json.load(open(CONTEXT)) if CONTEXT.exists() else {"provinces": {}, "year": None}
    figi = ctx_src["provinces"]

    Pm = {p["id"]: p for p in P}
    for p in P:
        p["slug"] = slug(p["name_en"])
    # 군 slug: 주 안에서 유일하게
    by_prov: dict[str, list] = {}
    for d in D:
        by_prov.setdefault(d["prov"], []).append(d)
    for ds in by_prov.values():
        seen = {}
        for d in sorted(ds, key=lambda x: x["id"]):
            s = slug(d["name_en"])
            if s in seen:
                s = f"{s}-{d['id']}"
            seen[s] = 1
            d["slug"] = s

    def d_url(lang, d):
        return f"/{lang}/district/{Pm[d['prov']]['slug']}/{d['slug']}/"

    def p_url(lang, p):
        return f"/{lang}/province/{p['slug']}/"

    def dname(d, lang):
        return d["name_th"] if lang == "th" else d["name_en"]

    def pname(p, lang):
        return p["name_th"] if lang == "th" else p["name_en"]

    def unit(d, lang):
        return STR[lang]["khet" if d["prov"] == "10" else "district"]

    scored_d = sorted([d for d in D if d.get("score") is not None], key=lambda d: d["rank"])
    scored_p = sorted([p for p in P if p.get("score") is not None], key=lambda p: p["rank"])
    nD, nP = len(scored_d), len(scored_p)
    # 주 안 순위
    for ds in by_prov.values():
        for i, d in enumerate(sorted([x for x in ds if x.get("score") is not None], key=lambda x: -x["score"]), 1):
            d["prov_rank"] = i

    rings = topo_rings()
    W = max(x for rs in rings.values() for r in rs for x, _ in r) + 4
    H = max(y for rs in rings.values() for r in rs for _, y in r) + 4
    mini_d = {k: path_d(v, tol=1.2, min_len=1.5) for k, v in rings.items()}
    full_d = {k: path_d(v) for k, v in rings.items()}

    if OUT.exists():
        shutil.rmtree(OUT)
    (OUT / "assets").mkdir(parents=True)
    for f in STATIC.iterdir():
        if f.is_file():
            shutil.copy(f, OUT / "assets" / f.name)

    pages: list[str] = []

    def write(path, content):
        fp = OUT / path.lstrip("/") / "index.html"
        fp.parent.mkdir(parents=True, exist_ok=True)
        fp.write_text(content, encoding="utf-8")
        pages.append(path)

    def district_row(d, lang, show_prov=True, rank_key="rank"):
        t = STR[lang]
        p = Pm[d["prov"]]
        flag = ' <span class="flag" title="{}">⚠</span>'.format(esc(t["spike"])) if d["cr_yoy"] is not None and abs(d["cr_yoy"]) > SPIKE else ""
        return (f'<tr><td class="num rk">{d.get(rank_key) or "–"}</td>'
                f'<th scope="row"><a href="{d_url(lang, d)}">{esc(dname(d, lang))}</a>'
                + (f'<small>{esc(pname(p, lang))}</small>' if show_prov else "")
                + f'</th><td>{score_badge(d.get("score"), lang, "sm")}</td>'
                f'<td class="num {growth_cls(d["dep_yoy"])}" data-v="{d["dep_yoy"] if d["dep_yoy"] is not None else ""}">{pct(d["dep_yoy"])}</td>'
                f'<td class="num {growth_cls(d["cr_yoy"])}" data-v="{d["cr_yoy"] if d["cr_yoy"] is not None else ""}">{pct(d["cr_yoy"])}{flag}</td>'
                f'<td class="num" data-v="{d["br_change"] if d["br_change"] is not None else ""}">{signed_int(d["br_change"])}</td>'
                f'<td class="sp">{sparkline(d["series"])}</td></tr>')

    def district_table(rows, lang, show_prov=True, rank_key="rank", sortable=False, caption=""):
        t = STR[lang]
        sort_attr = ' data-sortable' if sortable else ""
        head = (f'<thead><tr><th scope="col" class="num">#</th><th scope="col">{esc(t["district"])}</th>'
                f'<th scope="col">{esc(t["score_short"])}</th>'
                f'<th scope="col" class="num"><button data-k="3">{esc(t["deposits"])}</button></th>'
                f'<th scope="col" class="num"><button data-k="4">{esc(t["credits"])}</button></th>'
                f'<th scope="col" class="num"><button data-k="5">{esc(t["branches"])}</button></th>'
                f'<th scope="col" class="sp"><span class="sr-only">{esc(t["trend"])}</span></th></tr></thead>')
        cap = f"<caption>{esc(caption)}</caption>" if caption else ""
        return (f'<div class="tablewrap"><table class="rank"{sort_attr}>{cap}{head}<tbody>'
                + "".join(district_row(d, lang, show_prov, rank_key) for d in rows)
                + "</tbody></table></div>")

    def map_svg(lang, highlight=None, mini=False):
        t = STR[lang]
        shapes = []
        for p in P:
            k = p["id"]
            if k not in rings:
                continue
            d_attr = (mini_d if mini else full_d)[k]
            cls = "on" if highlight == k else ""
            if mini:
                shapes.append(f'<path d="{d_attr}" class="{cls}"/>')
                continue
            label = (f'{pname(p, lang)} · {t["score_short"]} {p["score"]:.0f}' if p["score"] is not None
                     else f'{pname(p, lang)} · {t["no_data"]}')
            shapes.append(
                f'<a href="{p_url(lang, p)}" aria-label="{esc(label)}" data-id="{k}" '
                f'data-name="{esc(pname(p, lang))}" data-score="{"" if p["score"] is None else round(p["score"])}" '
                f'data-dep="{esc(pct(p["dep_yoy"]))}" data-cr="{esc(pct(p["cr_yoy"]))}" '
                f'data-rank="{p.get("rank") or ""}">'
                f'<path d="{d_attr}" data-s="{seq_bin(p["score"])}" data-d="{div_bin(p["dep_yoy"])}" '
                f'data-c="{div_bin(p["cr_yoy"])}"/></a>')
        dots = ""
        if mini and highlight:
            for d in by_prov.get(highlight, []):
                if d["in_latest"]:
                    x, y = proj(d["lon"], d["lat"])
                    dots += f'<circle cx="{x:.1f}" cy="{y:.1f}" r="2.2"/>'
        cls = "map mini" if mini else "map"
        return (f'<svg class="{cls}" viewBox="0 0 {W:.0f} {H:.0f}" '
                + ('aria-hidden="true"' if mini else f'role="group" aria-label="{esc(t["map_title"])}"')
                + f'>{"" if mini else HATCH}<g class="provs">{"".join(shapes)}</g><g class="dots">{dots}</g></svg>')

    def legend(lang):
        t = STR[lang]
        sw = "".join(f'<i class="s{i}"></i>' for i in range(1, 8))
        dv = "".join(f'<i class="d{i}"></i>' for i in range(1, 8))
        return (f'<div class="legend" data-for="score"><span>{esc(t["legend_low"])}</span>{sw}<span>{esc(t["legend_high"])}</span>'
                f'<i class="nn"></i><span>{esc(t["no_data"])}</span></div>'
                f'<div class="legend" data-for="dep cr" hidden><span class="num">−10%</span>{dv}<span class="num">+10%</span>'
                f'<i class="nn"></i><span>{esc(t["no_data"])}</span></div>')

    for lang in LANGS:
        t = STR[lang]
        pl, pl0 = period_label(latest, lang), period_label(y1, lang)
        chip = (f'<span class="chip">{esc(t["data_as_of"].format(p=pl))}'
                + (f' · {esc(t["prelim"])}' if meta["latest_prelim"] else "") + "</span>")

        # ── 홈
        nat = meta["national"]
        top_d = scored_d[:10]
        top_p = scored_p[:10]
        leaving = sorted([d for d in D if d["dep_yoy"] is not None and d["in_latest"]], key=lambda d: d["dep_yoy"])[:10]
        br_los = sorted([d for d in D if d["br_change"] is not None and d["br_change"] < 0],
                        key=lambda d: (d["br_change"], d["dep_yoy"] or 0))[:10]
        dropped = [d for d in D if not d["in_latest"] and any(r[0] == y1 and r[1] is not None for r in d["series"])]

        prov_list = "".join(
            f'<li><a href="{p_url(lang, p)}"><span class="num rk">{p["rank"]}</span>'
            f'<span class="nm">{esc(pname(p, lang))}<small>{esc(p["name_en"] if lang == "th" else p["name_th"])}</small></span>'
            f'{score_badge(p["score"], lang, "sm")}<span class="num {growth_cls(p["dep_yoy"])}">{pct(p["dep_yoy"])}</span></a></li>'
            for p in top_p)
        dropped_html = ""
        if dropped:
            dropped_html = (f'<section class="card"><h2>{esc(t["dropped_title"])}</h2>'
                            f'<p class="note">{esc(t["dropped_note"].format(p=pl0))}</p><ul class="pills">'
                            + "".join(f'<li><a href="{d_url(lang, d)}">{esc(dname(d, lang))}'
                                      f'<small>{esc(pname(Pm[d["prov"]], lang))}</small></a></li>'
                                      for d in sorted(dropped, key=lambda d: d["prov"]))
                            + "</ul></section>")
        body = f"""
<section class="hero">
  {chip}
  <h1>{esc(t['hero'])}</h1>
  <p class="lede">{esc(t['hero_sub'])}</p>
  <div class="stats">
    {stat(t['national_dep'], pct(nat['dep_yoy']), growth_cls(nat['dep_yoy']), t['vs_last_year'].format(p=pl0))}
    {stat(t['n_districts'], f"{nat['n_covered']}", "", t['data_as_of'].format(p=pl))}
  </div>
</section>
<div class="grid2">
<section class="card mapcard" id="mapcard">
  <div class="cardhead"><h2>{esc(t['map_title'])}</h2>
    <div class="seg" role="radiogroup" aria-label="{esc(t['map_title'])}">
      <button role="radio" aria-checked="true" data-m="score">{esc(t['metric_score'])}</button>
      <button role="radio" aria-checked="false" data-m="dep">{esc(t['metric_dep'])}</button>
      <button role="radio" aria-checked="false" data-m="cr">{esc(t['metric_cr'])}</button>
    </div></div>
  <div class="mapwrap" data-metric="score">{map_svg(lang)}</div>
  {legend(lang)}
  <div class="pick" id="pick" aria-live="polite"><span class="hint">{esc(t['map_hint'])}</span></div>
  <template id="pick-tpl"><a class="pickcard" href=""><b class="nm"></b><span class="sc"></span>
    <span class="row"><span>{esc(t['deposits'])}</span><b class="num dep"></b></span>
    <span class="row"><span>{esc(t['credits'])}</span><b class="num cr"></b></span>
    <span class="go">{esc(t['open_page'])} →</span></a></template>
</section>
<section class="card">
  <div class="cardhead"><h2>{esc(t['top_provinces'])}</h2><a href="/{lang}/rankings/provinces/">{esc(t['view_all'])} →</a></div>
  <ol class="plist">{prov_list}</ol>
</section>
</div>
<section class="card">
  <div class="cardhead"><h2>{esc(t['top_districts'])}</h2><a href="/{lang}/rankings/districts/">{esc(t['view_all'])} →</a></div>
  {district_table(top_d, lang)}
  <p class="note">{esc(t['score_explain'].format(n=nD, m=nP))}</p>
</section>
<div class="grid2">
<section class="card">
  <div class="cardhead"><h2>{esc(t['money_leaving'])}</h2><a href="/{lang}/rankings/deposit-growth/">{esc(t['view_all'])} →</a></div>
  {district_table(leaving, lang)}
</section>
<section class="card">
  <div class="cardhead"><h2>{esc(t['branch_losers'])}</h2><a href="/{lang}/rankings/branches/">{esc(t['view_all'])} →</a></div>
  {district_table(br_los, lang)}
</section>
</div>
{dropped_html}
"""
        ld = ('<script type="application/ld+json">' + json.dumps({
            "@context": "https://schema.org", "@type": "Dataset",
            "name": t["title_home"].format(p=pl), "description": t["desc_home"].format(p=pl),
            "url": f"{SITE_URL}/{lang}/", "temporalCoverage": f"{meta['periods'][0]}/{latest}",
            "spatialCoverage": "Thailand", "isBasedOn": meta["source"]["url"],
            "creator": {"@type": "Organization", "name": "Where Money Moves"},
        }, ensure_ascii=False) + "</script>")
        write(f"/{lang}/", page(lang, f"/{lang}/", t["title_home"].format(p=pl), t["desc_home"].format(p=pl),
                                body, meta, extra_head=ld))

        # ── 주
        for p in P:
            ds = by_prov.get(p["id"], [])
            cur = sorted([d for d in ds if d["in_latest"]], key=lambda d: -(d.get("score") or -1))
            gone = [d for d in ds if not d["in_latest"]]
            ctx = ""
            f = figi.get(p["id"])
            if f and f.get("population"):
                y = ctx_src["year"] + (543 if lang == "th" else 0)
                ctx = (f'<section class="card"><h2>{esc(t["context"])}</h2><div class="stats">'
                       + stat(t["population"], f'{f["population"]:,.0f}', "", t["context_src"].format(y=y))
                       + stat(t["gpp_pc"], (f'{f["gpp_per_capita"]:,.0f} ' + ("บาท" if lang == "th" else "baht")), "", t["context_src"].format(y=y))
                       + "</div></section>")
            if p["score"] is not None:
                cov = t["coverage"].format(n=p["n_covered"], total=p["n_districts_total"])
                stats = (stat(t["score"], f'{p["score"]:.0f}', "", t["rank_of"].format(r=p["rank"], n=nP))
                         + stat(t["deposits"], pct(p["dep_yoy"]), growth_cls(p["dep_yoy"]), t["yoy"])
                         + stat(t["credits"], pct(p["cr_yoy"]), growth_cls(p["cr_yoy"]), t["yoy"])
                         + stat(t["branch_change"], signed_int(p["br_change"]), "", t["vs_last_year"].format(p=pl0)))
            else:
                cov = t["coverage_none"]
                stats = ""
            table = district_table(cur, lang, show_prov=False, rank_key="prov_rank", caption=t["district_table"]) if cur else ""
            gone_html = ""
            if gone:
                gone_html = ('<ul class="pills">' + "".join(
                    f'<li><a href="{d_url(lang, d)}">{esc(dname(d, lang))}</a></li>' for d in gone) + "</ul>")
            name = pname(p, lang)
            sub = p["name_en"] if lang == "th" else p["name_th"]
            body = f"""
<section class="hero prov">
  <div class="herorow"><div>{chip}
    <h1>{esc(name)} <small lang="{'en' if lang == 'th' else 'th'}">{esc(sub)}</small></h1>
    <p class="note">{esc(cov)}</p></div>
    {map_svg(lang, highlight=p['id'], mini=True)}</div>
  <div class="stats">{stats}</div>
</section>
{f'<section class="card">{table}</section>' if table else ''}
{f'<section class="card"><h2>{esc(t["dropped_title"])}</h2>{gone_html}</section>' if gone_html else ''}
{ctx}
"""
            dep_s, cr_s = pct(p["dep_yoy"]), pct(p["cr_yoy"])
            path = p_url(lang, p)
            write(path, page(lang, path, t["title_prov"].format(name=name, p=pl),
                             t["desc_prov"].format(name=name, dep=dep_s, cr=cr_s, rank=(p.get("rank") or "–"), p=pl),
                             body, meta, crumbs=[(t["home"], f"/{lang}/"), (name, path)]))

        # ── 군
        for d in D:
            p = Pm[d["prov"]]
            name, prov = dname(d, lang), pname(p, lang)
            last_p = next((r[0] for r in reversed(d["series"]) if r[1] is not None), None)
            notice = ""
            if not d["in_latest"]:
                notice = f'<p class="warn">{esc(t["not_in_latest"].format(p=period_label(last_p, lang)))}</p>'
            if d["cr_yoy"] is not None and abs(d["cr_yoy"]) > SPIKE:
                notice += f'<p class="warn">⚠ {esc(t["spike"])}</p>'
            stats = ""
            if d.get("score") is not None:
                stats += stat(t["score"], f'{d["score"]:.0f}', "", t["rank_of"].format(r=d["rank"], n=nD))
            stats += (stat(t["deposits"], pct(d["dep_yoy"]), growth_cls(d["dep_yoy"]), t["yoy"])
                      + stat(t["credits"], pct(d["cr_yoy"]), growth_cls(d["cr_yoy"]), t["yoy"])
                      + stat(t["branches"], f'{d["branches"]}' if d["branches"] is not None else "–", "",
                             f'{signed_int(d["br_change"])} {t["vs_last_year"].format(p=pl0)}' if d["br_change"] is not None else "")
                      + stat(t["dep_balance"], money(d["deposits"], lang), "", pl if d["in_latest"] else "")
                      + (stat(t["three_year"], pct(d["dep_3y"]), growth_cls(d["dep_3y"]),
                              t["vs_last_year"].format(p=period_label(meta["base_3y"], lang))) if d["dep_3y"] is not None else ""))
            charts = (line_chart(d["series"], 1, t["chart_dep"], lang, y1)
                      + line_chart(d["series"], 2, t["chart_cr"], lang, y1)
                      + line_chart(d["series"], 3, t["chart_br"], lang, y1))
            months_rows = "".join(
                f'<tr><th scope="row">{esc(period_label(r[0], lang))}</th>'
                f'<td class="num">{"–" if r[1] is None else f"{r[1]/1e6:,.0f}"}</td>'
                f'<td class="num">{"–" if r[2] is None else f"{r[2]/1e6:,.0f}"}</td>'
                f'<td class="num">{"–" if r[3] is None else r[3]}</td></tr>'
                for r in reversed(d["series"][-13:]))
            sibs = sorted([x for x in by_prov[d["prov"]] if x["id"] != d["id"] and x["in_latest"]],
                          key=lambda x: -(x.get("score") or -1))
            sib_html = "".join(f'<li><a href="{d_url(lang, x)}">{esc(dname(x, lang))}'
                               f'<span class="num {growth_cls(x["dep_yoy"])}">{pct(x["dep_yoy"])}</span></a></li>' for x in sibs)
            u = unit(d, lang)
            sub = d["name_en"] if lang == "th" else d["name_th"]
            body = f"""
<section class="hero">
  {chip}
  <h1>{esc(name)} <small lang="{'en' if lang == 'th' else 'th'}">{esc(sub)}</small></h1>
  <p class="lede">{esc(u)} · <a href="{p_url(lang, p)}">{esc(t['province'])} {esc(prov)}</a>
  {f" · {esc(t['in_province'])} #{d['prov_rank']}" if d.get('prov_rank') else ""}</p>
  {notice}
  <div class="stats">{stats}</div>
</section>
<section class="card charts">{charts}</section>
<section class="card"><details><summary>{esc(t['monthly_table'])}</summary>
<div class="tablewrap"><table class="plain"><thead><tr><th scope="col">{esc(t['month'])}</th>
<th scope="col" class="num">{esc(t['chart_dep'])}</th><th scope="col" class="num">{esc(t['chart_cr'])}</th>
<th scope="col" class="num">{esc(t['chart_br'])}</th></tr></thead><tbody>{months_rows}</tbody></table></div></details></section>
{f'<section class="card"><h2>{esc(t["other_districts"])}</h2><ul class="pills">{sib_html}</ul></section>' if sib_html else ''}
"""
            path = d_url(lang, d)
            write(path, page(lang, path, t["title_dist"].format(name=name, prov=prov, p=pl),
                             t["desc_dist"].format(unit=(u if lang == "th" else ""), name=name, prov=prov,
                                                   dep=pct(d["dep_yoy"]), cr=pct(d["cr_yoy"]),
                                                   br=d["branches"] if d["branches"] is not None else "–", p=pl),
                             body, meta,
                             crumbs=[(t["home"], f"/{lang}/"), (prov, p_url(lang, p)), (name, path)]))

        # ── 순위
        live = [d for d in D if d["in_latest"]]

        def ranked(key):
            xs = sorted([d for d in live if d[key] is not None], key=lambda d: -d[key])
            for i, d in enumerate(xs, 1):
                d["_r"] = i
            return xs

        rk_pages = {
            "districts": (t["rk_districts"], scored_d, "rank"),
            "deposit-growth": (t["rk_deposit"], ranked("dep_yoy"), "_r"),
        }
        for key, (title, rows, rkey) in rk_pages.items():
            body = (f'<section class="hero">{chip}<h1>{esc(title)}</h1>'
                    f'<p class="lede">{esc(t["rk_desc"].format(what=title, p1=pl, p0=pl0))}</p></section>'
                    f'<section class="card">{district_table([dict(d) for d in rows], lang, rank_key=rkey, sortable=True)}</section>')
            write(f"/{lang}/rankings/{key}/", page(lang, f"/{lang}/rankings/{key}/", f"{title} ({pl}) | {t['brand']}",
                                                   t["rk_desc"].format(what=title, p1=pl, p0=pl0), body, meta,
                                                   crumbs=[(t["home"], f"/{lang}/"), (title, f"/{lang}/rankings/{key}/")]))
        for key, title, field in (("credit-growth", t["rk_credit"], "cr_yoy"), ("branches", t["rk_branches"], "br_change")):
            rows = [dict(d) for d in ranked(field)]
            if field == "br_change":
                rows = sorted(rows, key=lambda d: (d["br_change"], d["dep_yoy"] or 0))
                for i, d in enumerate(rows, 1):
                    d["_r"] = i
            body = (f'<section class="hero">{chip}<h1>{esc(title)}</h1>'
                    f'<p class="lede">{esc(t["rk_desc"].format(what=title, p1=pl, p0=pl0))}</p></section>'
                    f'<section class="card">{district_table(rows, lang, rank_key="_r", sortable=True)}</section>')
            write(f"/{lang}/rankings/{key}/", page(lang, f"/{lang}/rankings/{key}/", f"{title} ({pl}) | {t['brand']}",
                                                   t["rk_desc"].format(what=title, p1=pl, p0=pl0), body, meta,
                                                   crumbs=[(t["home"], f"/{lang}/"), (title, f"/{lang}/rankings/{key}/")]))
        # 주 순위
        rows = "".join(
            f'<tr><td class="num rk">{p.get("rank") or "–"}</td><th scope="row"><a href="{p_url(lang, p)}">{esc(pname(p, lang))}</a>'
            f'<small>{esc(p["name_en"] if lang == "th" else p["name_th"])}</small></th>'
            f'<td>{score_badge(p["score"], lang, "sm")}</td>'
            f'<td class="num {growth_cls(p["dep_yoy"])}" data-v="{p["dep_yoy"] if p["dep_yoy"] is not None else ""}">{pct(p["dep_yoy"])}</td>'
            f'<td class="num {growth_cls(p["cr_yoy"])}" data-v="{p["cr_yoy"] if p["cr_yoy"] is not None else ""}">{pct(p["cr_yoy"])}</td>'
            f'<td class="num" data-v="{p["br_change"] if p["br_change"] is not None else ""}">{signed_int(p["br_change"])}</td>'
            f'<td class="num">{p["n_covered"]}/{p["n_districts_total"]}</td></tr>'
            for p in scored_p + [p for p in P if p["score"] is None])
        title = t["rk_provinces"]
        body = (f'<section class="hero">{chip}<h1>{esc(title)}</h1>'
                f'<p class="lede">{esc(t["rk_desc"].format(what=title, p1=pl, p0=pl0))}</p></section>'
                f'<section class="card"><div class="tablewrap"><table class="rank" data-sortable><thead><tr>'
                f'<th scope="col" class="num">#</th><th scope="col">{esc(t["province"])}</th><th scope="col">{esc(t["score_short"])}</th>'
                f'<th scope="col" class="num"><button data-k="3">{esc(t["deposits"])}</button></th>'
                f'<th scope="col" class="num"><button data-k="4">{esc(t["credits"])}</button></th>'
                f'<th scope="col" class="num"><button data-k="5">{esc(t["branches"])}</button></th>'
                f'<th scope="col" class="num">{esc(t["n_districts"])}</th></tr></thead><tbody>{rows}</tbody></table></div>'
                f'<p class="note">{esc(t["score_explain"].format(n=nD, m=nP))}</p></section>')
        write(f"/{lang}/rankings/provinces/", page(lang, f"/{lang}/rankings/provinces/", f"{title} ({pl}) | {t['brand']}",
                                                   t["rk_desc"].format(what=title, p1=pl, p0=pl0), body, meta,
                                                   crumbs=[(t["home"], f"/{lang}/"), (title, f"/{lang}/rankings/provinces/")]))

        # ── 소개
        secs = "".join(f'<section class="card prose"><h2>{esc(h)}</h2><p>{esc(b.format(n=nD))}</p></section>'
                       for h, b in t["about_body"])
        links = "".join(f'<li><a href="/{lang}/rankings/{k}/">{esc(v)}</a></li>' for k, v in (
            ("districts", t["rk_districts"]), ("provinces", t["rk_provinces"]), ("deposit-growth", t["rk_deposit"]),
            ("credit-growth", t["rk_credit"]), ("branches", t["rk_branches"])))
        body = (f'<section class="hero"><h1>{esc(t["about"])}</h1></section>{secs}'
                f'<section class="card prose"><h2>{esc(t["rankings"])}</h2><ul>{links}</ul>'
                f'<p><a href="{esc(meta["source"]["url"])}">{esc(meta["source"]["name"])}</a> · {esc(meta["latest_src"])}</p></section>')
        write(f"/{lang}/about/", page(lang, f"/{lang}/about/", f"{t['about']} | {t['brand']}", t["tagline"], body, meta,
                                      crumbs=[(t["home"], f"/{lang}/"), (t["about"], f"/{lang}/about/")]))

        # ── 검색 색인 · 매니페스트
        idx = ([{"n": pname(p, lang), "a": p["name_en"] if lang == "th" else p["name_th"], "u": p_url(lang, p), "k": "p"} for p in P]
               + [{"n": dname(d, lang), "a": f'{d["name_en"] if lang == "th" else d["name_th"]} · {pname(Pm[d["prov"]], lang)}',
                   "u": d_url(lang, d), "k": "d"} for d in D])
        (OUT / "assets" / f"search-{lang}.json").write_text(json.dumps(idx, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        (OUT / f"manifest-{lang}.webmanifest").write_text(json.dumps({
            "name": f'{t["brand"]} · {t["brand_sub"]}', "short_name": t["brand"], "lang": lang,
            "start_url": f"/{lang}/?source=pwa", "scope": "/", "display": "standalone",
            "background_color": "#0b1f1a", "theme_color": "#0b1f1a", "description": t["tagline"],
            "icons": [{"src": "/assets/icon-192.png", "sizes": "192x192", "type": "image/png"},
                      {"src": "/assets/icon-512.png", "sizes": "512x512", "type": "image/png"},
                      {"src": "/assets/icon-512.png", "sizes": "512x512", "type": "image/png", "purpose": "maskable"}],
        }, ensure_ascii=False, indent=1), encoding="utf-8")

    # ── 루트 · 크롤러 · 서비스워커
    (OUT / "index.html").write_text(f"""<!doctype html>
<html lang="th"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>เงินไหลไปไหน · Where Money Moves Thailand</title>
<link rel="alternate" hreflang="th" href="{SITE_URL}/th/"><link rel="alternate" hreflang="en" href="{SITE_URL}/en/">
<link rel="alternate" hreflang="x-default" href="{SITE_URL}/th/"><link rel="canonical" href="{SITE_URL}/th/">
<script>location.replace((navigator.languages||[navigator.language||'']).some(function(l){{return /^th/i.test(l)}})?'/th/':'/en/')</script>
<style>body{{font:16px system-ui;background:#0b1f1a;color:#e8f2ee;display:grid;place-items:center;min-height:100vh;margin:0}}a{{color:#7ee0b8;margin:0 12px}}</style>
</head><body><p><a href="/th/">ภาษาไทย</a><a href="/en/">English</a></p></body></html>
""", encoding="utf-8")
    (OUT / "robots.txt").write_text(f"User-agent: *\nAllow: /\nSitemap: {SITE_URL}/sitemap.xml\n")
    (OUT / "sitemap.xml").write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        + "".join(f"<url><loc>{SITE_URL}{u}</loc><lastmod>{meta['built']}</lastmod></url>\n" for u in pages)
        + "</urlset>\n")
    sw = (STATIC / "sw.js").read_text().replace("__BUILD__", meta["build_id"])
    (OUT / "sw.js").write_text(sw)
    (OUT / "assets" / "sw.js").unlink(missing_ok=True)

    size = sum(f.stat().st_size for f in OUT.rglob("*") if f.is_file())
    print(f"site/  {len(pages)} pages  {size/1e6:.1f}MB  (latest {latest}, {nD} districts, {nP} provinces scored)")


if __name__ == "__main__":
    main()
