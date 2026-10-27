"""
Where Money Moves — static site generator (English only).

  python build.py                     # data/processed/*.json → site/
  BASE_PATH=/repo SITE_URL=https://… python build.py   # for hosting under a sub-path

"See where people, jobs, businesses and money are moving across Southeast Asia."

Two layers, never mixed on one axis:
  · Region    — 11 countries, World Bank (comparable definitions)
  · Thailand  — 77 provinces × 4 lenses (DOPA, SSO, SSO-as-proxy, BOT) and 264 districts (BOT money)

Pages: /, /country/{c}/, /thailand/, /thailand/{p}/, /thailand/{p}/{d}/, /rankings/…, /compare/, /about/, 404.
Every page reads fully without JS. JS adds lens switching, tooltips, command palette, watchlist,
compare, toasts, theme, share and install. Standard library only, so Vercel / Actions can run it as-is.
"""

from __future__ import annotations

import html
import json
import math
import os
import re
import shutil
import urllib.parse
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data" / "processed"
REF = ROOT / "data" / "reference"
STATIC = ROOT / "static"
OUT = ROOT / "site"
SITE_URL = os.environ.get("SITE_URL", "https://wheremoneymoves.vercel.app").rstrip("/")   # origin only, no path
BASE = os.environ.get("BASE_PATH", "").rstrip("/")

LENSES = [  # key, label, what it measures (region), what it measures (Thailand)
    ("people", "People", "Urban population growth", "Registered population growth"),
    ("jobs", "Jobs", "Employment growth", "Formal-sector employees (SSO) growth"),
    ("biz", "Businesses", "New firm registrations growth", "SSO-registered employers growth (proxy)"),
    ("money", "Money", "Real GDP growth", "Bank deposits and credit growth"),
]
LENS = {k: (lab, r, t) for k, lab, r, t in LENSES}
ICON = {  # 24px stroke icons, drawn for this site
    "people": '<circle cx="9" cy="8" r="3.2"/><path d="M3 20c.6-3.4 3-5.4 6-5.4s5.4 2 6 5.4"/><circle cx="17" cy="9" r="2.4"/><path d="M16 14.2c2.6.2 4.4 2 5 4.8"/>',
    "jobs": '<rect x="3" y="7.5" width="18" height="12" rx="2"/><path d="M8.5 7.5V5.8c0-1 .8-1.8 1.8-1.8h3.4c1 0 1.8.8 1.8 1.8v1.7M3 12.5h18"/>',
    "biz": '<path d="M4 10v10h16V10M3 10l2-6h14l2 6M3 10c0 1.7 1.3 3 3 3s3-1.3 3-3c0 1.7 1.3 3 3 3s3-1.3 3-3c0 1.7 1.3 3 3 3s3-1.3 3-3"/><path d="M10 20v-4.5h4V20"/>',
    "money": '<ellipse cx="12" cy="6.5" rx="7" ry="2.8"/><path d="M5 6.5v5c0 1.5 3.1 2.8 7 2.8s7-1.3 7-2.8v-5M5 11.5v5c0 1.5 3.1 2.8 7 2.8s7-1.3 7-2.8v-5"/>',
    "score": '<path d="M4 17l5-5 4 3 7-8"/><path d="M15 7h5v5"/>',
}
SPIKE = 0.5


# ── formatting ───────────────────────────────────────────────────────────

def esc(s) -> str:
    return html.escape(str(s), quote=True)


def U(path: str) -> str:
    return BASE + path


def pct(x, digits=1) -> str:
    if x is None:
        return "–"
    v = x * 100
    s = f"{v:+,.0f}%" if abs(v) >= 1000 else f"{v:+.{digits}f}%"
    return s.replace("-", "−")


def big(x, unit="") -> str:
    if x is None:
        return "–"
    a = abs(x)
    for lim, suf in ((1e12, "T"), (1e9, "B"), (1e6, "M"), (1e3, "K")):
        if a >= lim:
            return f"{unit}{x/lim:,.1f}{suf}"
    return f"{unit}{x:,.0f}"


def baht(x) -> str:
    if x is None:
        return "–"
    if x >= 1e12:
        return f"฿{x/1e12:.2f}T"
    if x >= 1e9:
        return f"฿{x/1e9:.1f}B"
    return f"฿{x/1e6:,.0f}M"


def signed_int(x) -> str:
    if x is None:
        return "–"
    return "0" if x == 0 else f"{x:+,d}".replace("-", "−")


def month_label(p: str) -> str:
    y, m = (int(v) for v in p.split("-"))
    return ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"][m - 1] + f" {y}"


def slug(s: str) -> str:
    return re.sub(r"-+", "-", re.sub(r"[^a-z0-9]+", "-", s.lower())).strip("-")


def tone(g) -> str:
    if g is None:
        return ""
    return "up" if g > 0.0005 else ("down" if g < -0.0005 else "flat")


def pct_rank(values: dict) -> dict:
    xs = sorted((v, k) for k, v in values.items() if v is not None)
    n = len(xs)
    out = {k: None for k in values}
    i = 0
    while i < n:
        j = i
        while j + 1 < n and xs[j + 1][0] == xs[i][0]:
            j += 1
        for t in range(i, j + 1):
            out[xs[t][1]] = 100.0 * ((i + j) / 2) / (n - 1) if n > 1 else 50.0
        i = j + 1
    return out


def bin7(p) -> str:
    return "n" if p is None else str(min(7, int(p / (100 / 7)) + 1))


def growth(a, b):
    return None if a is None or b in (None, 0) else a / b - 1


# ── geometry ─────────────────────────────────────────────────────────────

def simplify(pts, tol):
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
    """A closed ring starts and ends on the same point, which collapses Douglas–Peucker. Split at the far point."""
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


class Proj:
    def __init__(self, lon0, lat1, scale, lat_ref):
        self.lon0, self.lat1, self.s, self.k = lon0, lat1, scale, math.cos(math.radians(lat_ref))

    def __call__(self, lon, lat):
        return ((lon - self.lon0) * self.k * self.s, (self.lat1 - lat) * self.s)


TH_PROJ = Proj(97.25, 20.55, 40.0, 13.0)
VN_PROJ = Proj(102.0, 23.5, 40.0, 16.0)
SEA_PROJ = Proj(90.0, 29.0, 15.0, 8.0)
SEA_BOX = (90.0, -12.0, 143.0, 29.0)
LABEL_AT = {  # lon, lat — placed by hand on open land (or open sea for the small three)
    "MMR": (96.0, 21.6), "THA": (100.9, 15.6), "LAO": (102.6, 19.4), "VNM": (108.6, 14.2), "KHM": (104.9, 12.8),
    "MYS": (102.2, 4.6), "IDN": (113.6, -1.2), "PHL": (125.8, 12.4), "SGP": (103.8, 0.2), "BRN": (114.6, 6.0),
    "TLS": (125.9, -10.1),
}


def thai_rings():
    topo = json.load(open(REF / "provinces.topo.json"))
    arcs = topo["arcs"]

    def arc(i):
        a = arcs[i] if i >= 0 else list(reversed(arcs[~i]))
        return [TH_PROJ(*pt[:2]) for pt in a]

    out = {}
    for g in topo["objects"]["data"]["geometries"]:
        polys = [g["arcs"]] if g["type"] == "Polygon" else g["arcs"]
        rings = []
        for poly in polys:
            for r in poly:
                pts = []
                for k, i in enumerate(r):
                    seg = arc(i)
                    pts.extend(seg if k == 0 else seg[1:])
                rings.append(pts)
        out[g["properties"]["tis1099_code"]] = rings
    return out


# ── charts ───────────────────────────────────────────────────────────────

def spark(vals, w=84, h=22) -> str:
    pts = [(i, v) for i, v in enumerate(vals) if v is not None]
    if len(pts) < 2:
        return ""
    lo, hi = min(v for _, v in pts), max(v for _, v in pts)
    span = (hi - lo) or 1
    n = len(vals)
    d, prev = "", False
    for i, v in enumerate(vals):
        if v is None:
            prev = False
            continue
        d += ("L" if prev else "M") + f"{i * w / (n - 1):.1f},{h - 2 - (v - lo) / span * (h - 4):.1f}"
        prev = True
    return f'<svg class="spark" viewBox="0 0 {w} {h}" width="{w}" height="{h}" aria-hidden="true"><path d="{d}"/></svg>'


def compact(x, unit="", d=1):
    a = abs(x)
    for lim, suf in ((1e12, "T"), (1e9, "B"), (1e6, "M"), (1e3, "K")):
        if a >= lim:
            return f"{unit}{x/lim:,.{d}f}{suf}"
    return f"{unit}{x:,.0f}"


def chart(points, title, unit="", x_label=lambda p: p, every=None, base=None, kind="line") -> str:
    """points: [(x_key, value|None)]. 'line' for monthly series, 'dots' for annual levels.
    Never bars: these are levels that move a few percent, and a bar has to start at zero to be honest."""
    W, H, L, R, T, B = 420, 168, 52, 10, 12, 24
    known = [v for _, v in points if v is not None]
    if len(known) < 2:
        return ""
    lo, hi = min(known), max(known)
    pad = (hi - lo) * 0.12 or abs(hi) * 0.05 or 1
    lo, hi = lo - pad, hi + pad
    n = len(points)
    xs = lambda i: L + 6 + i * (W - L - R - 12) / (n - 1)
    ys = lambda v: T + (hi - v) / (hi - lo) * (H - T - B)
    levels = [lo + (hi - lo) * (k + 0.5) / 3 for k in range(3)]
    for d in (1, 2, 3):          # add decimals until the three axis labels differ
        labels = [compact(v, unit, d) for v in levels]
        if len(set(labels)) == 3:
            break
    grid = "".join(f'<line x1="{L}" x2="{W-R}" y1="{ys(v):.1f}" y2="{ys(v):.1f}"/><text x="{L-6}" y="{ys(v)+4:.1f}" text-anchor="end">{esc(lab)}</text>'
                   for v, lab in zip(levels, labels))
    every = every or max(1, n // 5)
    ticks = "".join(f'<text x="{xs(i):.1f}" y="{H-6}" text-anchor="middle">{esc(x_label(p))}</text>'
                    for i, (p, _) in enumerate(points) if (i % every == 0 or i == n - 1))
    d, prev = "", False
    if True:
        for i, (_, v) in enumerate(points):
            if v is None:
                prev = False
                continue
            d += ("L" if prev else "M") + f"{xs(i):.1f},{ys(v):.1f}"
            prev = True
        last = next((i, v) for i, (_, v) in reversed(list(enumerate(points))) if v is not None)
        marks = f'<path class="ln" pathLength="1" d="{d}"/>'
        if kind == "dots":
            marks += "".join(f'<circle class="pt" cx="{xs(i):.1f}" cy="{ys(v):.1f}" r="3"/>' for i, (_, v) in enumerate(points) if v is not None)
        marks += f'<circle cx="{xs(last[0]):.1f}" cy="{ys(last[1]):.1f}" r="4"/>'
    b = ""
    if base is not None:
        bi = next((i for i, (p, _) in enumerate(points) if p == base), None)
        if bi is not None:
            b = f'<line class="base" x1="{xs(bi):.1f}" x2="{xs(bi):.1f}" y1="{T}" y2="{H-B}"/>'
    return (f'<figure class="chart {kind}"><figcaption>{esc(title)}</figcaption>'
            f'<svg viewBox="0 0 {W} {H}" role="img" aria-label="{esc(title)}"><g class="grid">{grid}</g>'
            f'<g class="ticks">{ticks}</g>{b}<g class="marks">{marks}</g></svg></figure>')


# ── data model ───────────────────────────────────────────────────────────

def load():
    meta = json.load(open(DATA / "meta.json"))
    D = json.load(open(DATA / "districts.json"))
    P = json.load(open(DATA / "provinces.json"))
    sso = json.load(open(DATA / "th_sso.json"))
    dopa = json.load(open(DATA / "th_dopa.json"))
    wb = json.load(open(DATA / "sea_wb.json"))
    ctx = json.load(open(REF / "nesdc_context.json")) if (REF / "nesdc_context.json").exists() else {"provinces": {}, "year": None}
    geo = json.load(open(REF / "sea.geo.json"))
    vn = json.load(open(DATA / "vn_gso.json"))
    vgeo = json.load(open(REF / "vn.geo.json"))
    return meta, D, P, sso, dopa, wb, ctx, geo, vn, vgeo


def region_model(wb):
    S, C = wb["series"], wb["countries"]

    def ser(ind, iso):
        return {int(y): v for y, v in S[ind][iso].items()}

    def yoy(ind, iso):
        s = ser(ind, iso)
        ys = sorted(y for y in s if y - 1 in s)
        if not ys:
            return None, None
        y = ys[-1]
        return growth(s[y], s[y - 1]), y

    def last(ind, iso):
        s = ser(ind, iso)
        return (s[max(s)], max(s)) if s else (None, None)

    R = {}
    for iso, c in C.items():
        r = {"iso": iso, "name": c["name"], "native": c["native"], "slug": c["slug"]}
        for lens, ind in (("people", "SP.URB.TOTL"), ("jobs", "EMPLOYED"), ("biz", "IC.BUS.NREG"), ("money", "NY.GDP.MKTP.KD")):
            r[lens], r[lens + "_year"] = yoy(ind, iso)
        r["pop"], r["pop_year"] = last("SP.POP.TOTL", iso)
        urb, _ = last("SP.URB.TOTL", iso)
        r["urban_share"] = urb / r["pop"] if urb and r["pop"] else None
        r["netmig"], r["netmig_year"] = last("SM.POP.NETM", iso)
        r["unemp"], r["unemp_year"] = last("SL.UEM.TOTL.ZS", iso)
        r["employed"], _ = last("EMPLOYED", iso)
        r["new_firms"], r["new_firms_year"] = last("IC.BUS.NREG", iso)
        r["firm_density"], _ = last("IC.BUS.NDNS.ZS", iso)
        r["gdp_usd"], r["gdp_year"] = last("NY.GDP.MKTP.CD", iso)
        r["fdi"], r["fdi_year"] = last("BX.KLT.DINV.CD.WD", iso)
        r["remit"], r["remit_year"] = last("BX.TRF.PWKR.CD.DT", iso)
        r["series"] = {k: sorted(ser(ind, iso).items()) for k, ind in
                       (("people", "SP.URB.TOTL"), ("jobs", "EMPLOYED"), ("biz", "IC.BUS.NREG"),
                        ("money", "NY.GDP.MKTP.KD"), ("fdi", "BX.KLT.DINV.CD.WD"))}
        R[iso] = r
    score_lenses(R, [k for k, *_ in LENSES])
    return R


def score_lenses(units: dict, keys, pre_pct=None):
    """Per-lens percentile within the layer, then the mean of available lenses = Momentum Score."""
    pre_pct = pre_pct or {}
    for k in keys:
        pr = pre_pct.get(k) or pct_rank({u: units[u][k] for u in units})
        for u in units:
            units[u][k + "_pct"] = pr[u]
    for u, r in units.items():
        parts = [r[k + "_pct"] for k in keys if r.get(k + "_pct") is not None]
        r["score"] = sum(parts) / len(parts) if parts else None
        r["n_lenses"] = len(parts)
    ranked = sorted((r for r in units.values() if r["score"] is not None), key=lambda r: -r["score"])
    for i, r in enumerate(ranked, 1):
        r["rank"] = i
    for k in keys:
        rk = sorted((r for r in units.values() if r.get(k) is not None), key=lambda r: -r[k])
        for i, r in enumerate(rk, 1):
            r[k + "_rank"] = i


def thailand_model(P, D, sso, dopa, ctx):
    sy, dy = sso["years"], dopa["years"]
    T = {}
    for p in P:
        tis = p["id"]
        s, d = sso["provinces"][tis], dopa["provinces"][tis]
        pop = {int(y): v["population"] for y, v in d.items()}
        ins = {int(y): v["insured"] for y, v in s.items()}
        ent = {int(y): v["enterprises"] for y, v in s.items()}
        r = {
            "id": tis, "name": p["name_en"], "native": p["name_th"], "slug": slug(p["name_en"]),
            "region": p["region"],
            "people": growth(pop[dy[-1]], pop[dy[-2]]), "people_5y": growth(pop[dy[-1]], pop[dy[0]]),
            "pop": pop[dy[-1]],
            "jobs": growth(ins[sy[-1]], ins[sy[-2]]), "jobs_3y": growth(ins[sy[-1]], ins[sy[0]]), "insured": ins[sy[-1]],
            "biz": growth(ent[sy[-1]], ent[sy[-2]]), "biz_3y": growth(ent[sy[-1]], ent[sy[0]]), "enterprises": ent[sy[-1]],
            "firm_size": ins[sy[-1]] / ent[sy[-1]] if ent[sy[-1]] else None,
            "money": p["dep_yoy"], "credit": p["cr_yoy"], "money_score": p["score"],
            "deposits": p["deposits"], "branches": p["branches"], "br_change": p["br_change"],
            "n_covered": p["n_covered"], "n_districts_total": p["n_districts_total"],
            "pop_series": sorted(pop.items()), "ins_series": sorted(ins.items()), "ent_series": sorted(ent.items()),
            "gpp_pc": (ctx["provinces"].get(tis) or {}).get("gpp_per_capita"),
        }
        T[tis] = r
    # money lens percentile = the BOT Money Momentum score (deposits + credit), already a percentile
    score_lenses(T, ["people", "jobs", "biz", "money"], pre_pct={"money": {k: v["money_score"] for k, v in T.items()}})
    for d in D:
        d["slug"] = None
    by_prov = {}
    for d in D:
        by_prov.setdefault(d["prov"], []).append(d)
    for ds in by_prov.values():
        seen = set()
        for d in sorted(ds, key=lambda x: x["id"]):
            s = slug(d["name_en"])
            if s in seen:
                s = f"{s}-{d['id']}"
            seen.add(s)
            d["slug"] = s
        for i, d in enumerate(sorted([x for x in ds if x.get("score") is not None], key=lambda x: -x["score"]), 1):
            d["prov_rank"] = i
    return T, by_prov


VN_DESC = {  # what each lens measures inside Vietnam (NSO tables, 34 provinces on 2025 boundaries)
    "people": "Average population growth",
    "jobs": "Employed workers growth",
    "biz": "Newly registered enterprises growth",
    "money": "Enterprise net revenue growth (nominal)",
}


def vietnam_model(vn):
    """34 provinces (2025 boundaries), each lens = latest year-on-year change of an additive series."""
    S = {"people": "pop", "jobs": "employed", "biz": "new_firms", "money": "revenue"}
    prelim = {k: set(map(int, v)) for k, v in vn["preliminary"].items()}
    V = {}
    years = {}
    for slug_, p in vn["provinces"].items():
        r = {"id": slug_, "slug": slug_, "name": p["name"], "native": p["native"], "former": p["former"],
             "former_detail": p["former_detail"], "series": {}}
        for lens, key in S.items():
            ser = {int(y): v for y, v in p["series"][key].items()}
            ys = sorted(y for y in ser if y - 1 in ser)
            y = ys[-1]
            r[lens] = growth(ser[y], ser[y - 1])
            years[lens] = (y - 1, y, y in prelim.get(key, set()))
            r["series"][lens] = sorted(ser.items())
        pop = {int(y): v for y, v in p["series"]["pop"].items()}
        y = max(pop)
        r["pop"] = pop[y] * 1000
        r["people_5y"] = growth(pop[y], pop.get(y - 5))
        mig = {int(k): v for k, v in p["series"]["netmig"].items()}
        r["netmig"], r["netmig_year"] = (mig[max(mig)], max(mig)) if mig else (None, None)
        r["employed"] = dict(r["series"]["jobs"])[years["jobs"][1]] * 1000
        r["new_firms"] = dict(r["series"]["biz"])[years["biz"][1]]
        firms = {int(k): v for k, v in p["series"]["firms"].items()}
        r["firms"], r["firms_year"] = (firms[max(firms)], max(firms)) if firms else (None, None)
        r["firms_growth"] = growth(firms.get(max(firms)), firms.get(max(firms) - 1)) if firms else None
        r["revenue"] = dict(r["series"]["money"])[years["money"][1]]
        V[slug_] = r
    score_lenses(V, ["people", "jobs", "biz", "money"])
    label = {k: (f"{a} to {b}" + (" (preliminary)" if pre else ""), b) for k, (a, b, pre) in years.items()}
    return V, label


# ── page shell ───────────────────────────────────────────────────────────

def icon(k, cls="ic"):
    return f'<svg class="{cls}" viewBox="0 0 24 24" aria-hidden="true">{ICON[k]}</svg>'


def native(s, lang="th"):
    return f'<span class="native" lang="{lang}">{esc(s)}</span>' if s else ""


# Khmer, Lao and Burmese appear only in three country names: load just those glyphs
NATIVE_GLYPHS = urllib.parse.quote("".join(sorted(set("កម្ពុជាລາວမြန်မာ"))))
NATIVE_LANG = {"THA": "th", "KHM": "km", "LAO": "lo", "MMR": "my", "VNM": "vi", "IDN": "id", "MYS": "ms",
               "PHL": "fil", "SGP": "ms", "BRN": "ms", "TLS": "pt"}


def page(path, title, desc, body, meta, crumbs=None, watch=None, extra_head="") -> str:
    canonical = SITE_URL + path
    ld = ""
    if crumbs:
        ld = ('<script type="application/ld+json">' + json.dumps({
            "@context": "https://schema.org", "@type": "BreadcrumbList",
            "itemListElement": [{"@type": "ListItem", "position": i + 1, "name": n, "item": SITE_URL + U(u)}
                                for i, (n, u) in enumerate(crumbs)]}, ensure_ascii=False) + "</script>")
    crumb_nav = ""
    if crumbs and len(crumbs) > 1:
        crumb_nav = ('<nav class="crumbs" aria-label="Breadcrumb"><ol>'
                     + "".join(f'<li><a href="{U(u)}">{esc(n)}</a></li>' for n, u in crumbs[:-1])
                     + f'<li aria-current="page">{esc(crumbs[-1][0])}</li></ol></nav>')
    actions = ""
    if watch:
        actions = (f'<div class="actions"><button class="btn ghost" data-watch=\'{esc(json.dumps(watch))}\' aria-pressed="false">'
                   f'<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 3.5l2.6 5.3 5.9.9-4.3 4.1 1 5.8L12 16.9l-5.2 2.7 1-5.8L3.5 9.7l5.9-.9z"/></svg>'
                   f'<span>Watch</span></button>'
                   f'<button class="btn ghost" data-share><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 15V3.5M7.5 8 12 3.5 16.5 8M5 12.5V19a1.5 1.5 0 0 0 1.5 1.5h11A1.5 1.5 0 0 0 19 19v-6.5"/></svg><span>Share</span></button></div>')
    v = meta["build_id"]
    return f"""<!doctype html>
<html lang="en" data-base="{BASE}" data-build="{v}">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>{esc(title)}</title>
<meta name="description" content="{esc(desc)}">
<link rel="canonical" href="{canonical}">
<meta property="og:type" content="website">
<meta property="og:site_name" content="Where Money Moves">
<meta property="og:title" content="{esc(title)}">
<meta property="og:description" content="{esc(desc)}">
<meta property="og:url" content="{canonical}">
<meta property="og:image" content="{SITE_URL}{U('/assets/og.png')}">
<meta name="twitter:card" content="summary_large_image">
<meta name="theme-color" content="#f6f7f4" media="(prefers-color-scheme: light)">
<meta name="theme-color" content="#0f1720" media="(prefers-color-scheme: dark)">
<script>try{{var t=localStorage.getItem("wmm-theme");if(t)document.documentElement.dataset.theme=t}}catch(e){{}}</script>
<link rel="manifest" href="{U('/manifest.webmanifest')}">
<link rel="icon" href="{U('/assets/icon.svg')}" type="image/svg+xml">
<link rel="apple-touch-icon" href="{U('/assets/icon-192.png')}">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Bricolage+Grotesque:opsz,wght@12..96,500..800&family=Inter:wght@400..700&family=Noto+Sans+Thai:wght@400;500&display=swap">
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Noto+Sans+Khmer&family=Noto+Sans+Lao&family=Noto+Sans+Myanmar&text={NATIVE_GLYPHS}&display=swap">
<link rel="stylesheet" href="{U('/assets/app.css')}?v={v}">
<script type="speculationrules">{{"prerender":[{{"where":{{"href_matches":"{BASE}/*"}},"eagerness":"moderate"}}]}}</script>
{extra_head}{ld}
</head>
<body>
<div class="progress" aria-hidden="true"></div>
<a class="skip" href="#main">Skip to content</a>
<header class="top">
  <a class="brand" href="{U('/')}"><img src="{U('/assets/icon.svg')}" alt="" width="26" height="26"><span>Where Money Moves</span></a>
  <nav class="nav" aria-label="Main">
    <a href="{U('/thailand/')}">Thailand</a>
    <a href="{U('/vietnam/')}">Vietnam</a>
    <a href="{U('/rankings/')}">Rankings</a>
    <a href="{U('/compare/')}" class="cmp">Compare<span class="count" hidden></span></a>
    <a href="{U('/about/')}">Method</a>
  </nav>
  <button class="search-btn" data-cmdk aria-label="Search countries, provinces and districts"><svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="11" cy="11" r="6.5"/><path d="m16 16 4.5 4.5"/></svg><span>Search</span><kbd>/</kbd></button>
  <button class="theme-btn" data-theme-toggle aria-label="Switch colour theme"><svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="4.5"/><path d="M12 2.5v2M12 19.5v2M2.5 12h2M19.5 12h2M5.3 5.3l1.4 1.4M17.3 17.3l1.4 1.4M5.3 18.7l1.4-1.4M17.3 6.7l1.4-1.4"/></svg></button>
</header>
<main id="main">
{f'<div class="pagebar">{crumb_nav}{actions}</div>' if crumb_nav or actions else ""}
{body}
</main>
<footer class="foot">
  <div>
    <p><b>Where Money Moves</b> tracks where people, jobs, businesses and money are moving across Southeast Asia, from public data only.</p>
    <p>Sources: World Bank WDI (CC BY 4.0). Thailand: Bank of Thailand district deposits and credit, Social Security Office, Department of Provincial Administration (Open Data Common). Vietnam: National Statistics Office (PX-Web). Boundaries: Natural Earth, geoBoundaries/OCHA and Government of Viet Nam via HDX (CC BY 3.0 IGO), thailand-canonical-admin-names (CC BY 4.0).</p>
  </div>
  <p class="small">Built {meta['built']}. <a href="{U('/about/')}">How the numbers work</a>. <a href="https://github.com/minsungkim-source/where-money-moves">Source code</a>.</p>
</footer>
<dialog id="cmdk" aria-label="Search">
  <div class="cmdk-box"><input type="search" placeholder="Country, province or district" autocomplete="off" aria-label="Search"><ul role="listbox"></ul>
  <p class="hint"><kbd>↑</kbd><kbd>↓</kbd> to move, <kbd>Enter</kbd> to open, <kbd>Esc</kbd> to close</p></div>
</dialog>
<div class="toasts" role="status" aria-live="polite"></div>
<div class="tip" role="tooltip" hidden></div>
<script src="{U('/assets/app.js')}?v={v}" defer></script>
</body>
</html>
"""


# ── components ───────────────────────────────────────────────────────────

def lens_tabs(include_score=True, default="score", label="Lens"):
    items = ([("score", "Momentum")] if include_score else []) + [(k, lab) for k, lab, *_ in LENSES]
    return (f'<div class="lenses" role="tablist" aria-label="{esc(label)}">'
            + "".join(f'<button role="tab" data-lens="{k}" aria-selected="{str(k == default).lower()}">{icon(k)}<span>{esc(lab)}</span></button>'
                      for k, lab in items)
            + '<span class="lens-ink" aria-hidden="true"></span></div>')


def legend(layer):
    sw = "".join(f'<i class="s{i}"></i>' for i in range(1, 8))
    return (f'<div class="legend"><span>Slower</span><span class="ramp">{sw}</span><span>Faster</span>'
            f'<span class="nd"><i></i>No data</span><span class="note">Colour is rank within {esc(layer)}</span></div>')


def lens_attrs(r, keys):
    a = [f'data-b-score="{bin7(r.get("score"))}"']
    for k in keys:
        a.append(f'data-b-{k}="{bin7(r.get(k + "_pct"))}"')
    return " ".join(a)


def value_cell(g, cls=""):
    return f'<td class="num {tone(g)} {cls}" data-v="{"" if g is None else round(g, 6)}">{pct(g)}</td>'


def score_pill(s):
    if s is None:
        return '<span class="pill none">No score</span>'
    return f'<span class="pill b{bin7(s)}"><b>{s:.0f}</b></span>'


def stat(label, value, sub="", cls="", count=True):
    data = f' data-count="{esc(value)}"' if count and value not in ("–",) else ""
    return (f'<div class="stat"><span class="k">{esc(label)}</span><span class="v {cls}"{data}>{esc(value)}</span>'
            + (f'<span class="s">{esc(sub)}</span>' if sub else "") + "</div>")


def lens_panel(k, headline, unit_label, rank_txt, rows, chart_html="", note=""):
    lab, *_ = LENS[k]
    return (f'<section class="lens-panel reveal" data-k="{k}"><header>{icon(k)}<h2>{esc(lab)}</h2>'
            f'<span class="rank">{esc(rank_txt)}</span></header>'
            f'<p class="headline"><span class="v {tone_from(headline)}" data-count="{esc(headline)}">{esc(headline)}</span>'
            f'<span class="u">{esc(unit_label)}</span></p>'
            + ("<dl>" + "".join(f"<div><dt>{esc(a)}</dt><dd>{esc(b)}</dd></div>" for a, b in rows) + "</dl>" if rows else "")
            + chart_html + (f'<p class="note">{esc(note)}</p>' if note else "") + "</section>")


def tone_from(s: str) -> str:
    return "up" if s.startswith("+") else ("down" if s.startswith("−") else "")


# ── build ────────────────────────────────────────────────────────────────

def main():
    meta, D, P, sso, dopa, wb, ctx, geo, vn, vgeo = load()
    meta["build_id"] = meta["generated_at"][:19].replace(":", "").replace("-", "")
    meta["built"] = meta["generated_at"][:10]
    latest, y1 = meta["latest"], meta["yoy_base"]
    R = region_model(wb)
    T, by_prov = thailand_model(P, D, sso, dopa, ctx)
    V, vlab = vietnam_model(vn)

    def v_url(v):
        return f"/vietnam/{v['slug']}/"
    Pm = {p["id"]: p for p in P}
    lens_keys = [k for k, *_ in LENSES]
    asof = {"people": f"Dec {dopa['years'][-1]}", "jobs": f"Dec {sso['years'][-1]}",
            "biz": f"Dec {sso['years'][-1]}", "money": month_label(latest)}
    base_of = {"people": f"Dec {dopa['years'][-2]}", "jobs": f"Dec {sso['years'][-2]}",
               "biz": f"Dec {sso['years'][-2]}", "money": month_label(y1)}

    def p_url(t):
        return f"/thailand/{t['slug']}/"

    def d_url(d):
        return f"/thailand/{T[d['prov']]['slug']}/{d['slug']}/"

    def c_url(r):
        return f"/country/{r['slug']}/"

    if OUT.exists():
        shutil.rmtree(OUT)
    (OUT / "assets").mkdir(parents=True)
    for f in STATIC.iterdir():
        if f.is_file() and f.name not in ("sw.js", "app.css"):
            shutil.copy(f, OUT / "assets" / f.name)

    # map colour rules are generated: one per lens × bin
    rules = []
    for lens in ["score"] + lens_keys:
        for b in range(1, 8):
            rules.append(f'.map[data-lens="{lens}"] [data-b-{lens}="{b}"]{{fill:var(--s{b})}}')
        rules.append(f'.map[data-lens="{lens}"] [data-b-{lens}="n"]{{fill:url(#hatch)}}')
    (OUT / "assets" / "app.css").write_text((STATIC / "app.css").read_text() + "\n/* generated */\n" + "\n".join(rules) + "\n")

    pages = []

    def write(path, content):
        fp = OUT / path.lstrip("/") / "index.html"
        fp.parent.mkdir(parents=True, exist_ok=True)
        fp.write_text(content, encoding="utf-8")
        pages.append(path)

    HATCH = ('<defs><pattern id="hatch" width="5" height="5" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">'
             '<rect width="5" height="5" class="hb"/><line x1="0" y1="0" x2="0" y2="5" class="hl"/></pattern></defs>')

    # ── region map
    def sea_map(highlight=None, interactive=True):
        feats = geo["features"]
        W, H = SEA_PROJ(SEA_BOX[2], SEA_BOX[1])
        grat = ""
        for lon in range(90, 145, 5):
            x, _ = SEA_PROJ(lon, 0)
            grat += f'<line x1="{x:.1f}" y1="0" x2="{x:.1f}" y2="{H:.1f}"/>'
        for lat in range(-10, 30, 5):
            _, y = SEA_PROJ(0, lat)
            grat += f'<line x1="0" y1="{y:.1f}" x2="{W:.1f}" y2="{y:.1f}"/>'
        ticks = "".join(f'<text x="{SEA_PROJ(lon, 0)[0]+3:.1f}" y="{H-6:.1f}">{lon}°E</text>' for lon in range(95, 145, 10))
        ticks += "".join(f'<text x="4" y="{SEA_PROJ(0, lat)[1]-4:.1f}">{abs(lat)}°{"N" if lat >= 0 else "S"}</text>'
                         for lat in range(-10, 30, 10))
        ctx_paths, shapes, labels = "", "", ""
        for f in feats:
            rings = [[SEA_PROJ(x, y) for x, y in r] for r in f["rings"]]
            d = path_d(rings)
            if not f["sea"]:
                ctx_paths += f'<path d="{d}"/>'
                continue
            r = R[f["iso3"]]
            # label at the bbox centre of the largest ring
            big_ring = max(rings, key=lambda rg: (max(p[0] for p in rg) - min(p[0] for p in rg)) * (max(p[1] for p in rg) - min(p[1] for p in rg)))
            cx = (max(p[0] for p in big_ring) + min(p[0] for p in big_ring)) / 2
            cy = (max(p[1] for p in big_ring) + min(p[1] for p in big_ring)) / 2
            tiny = f["iso3"] in ("SGP", "BRN", "TLS")
            attrs = lens_attrs(r, lens_keys)
            dot = f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="5" class="dot" {attrs}/>' if tiny else ""
            tip = {"n": r["name"], "a": r["native"], "s": None if r["score"] is None else round(r["score"]),
                   **{k: pct(r[k]) for k in lens_keys}, **{k + "y": r[k + "_year"] for k in lens_keys}}
            cls = ' class="on"' if highlight == f["iso3"] else ""
            body = f'<path d="{d}" {attrs}/>{dot}'
            if interactive:
                shapes += (f'<a href="{U(c_url(r))}" data-tip=\'{esc(json.dumps(tip, ensure_ascii=False))}\' aria-label="{esc(r["name"])}, momentum {tip["s"]}"{cls}>{body}</a>')
            else:
                shapes += f'<g{cls}>{body}</g>'
            lx, ly = SEA_PROJ(*LABEL_AT[f["iso3"]]) if f["iso3"] in LABEL_AT else (cx, cy)
            labels += f'<text x="{lx:.1f}" y="{ly + 4:.1f}" text-anchor="middle">{esc(r["name"])}</text>'
        return (f'<svg class="map sea" data-lens="score" viewBox="0 0 {W:.0f} {H:.0f}" role="group" aria-label="Map of Southeast Asia">{HATCH}'
                f'<rect class="sea-bg" width="{W:.0f}" height="{H:.0f}"/><g class="grat">{grat}</g><g class="ctx">{ctx_paths}</g>'
                f'<g class="units">{shapes}</g><g class="labels" aria-hidden="true">{labels}</g><g class="coords" aria-hidden="true">{ticks}</g></svg>')

    th_rings = thai_rings()
    th_full = {k: path_d(v) for k, v in th_rings.items()}
    th_mini = {k: path_d(v, tol=1.2, min_len=1.5) for k, v in th_rings.items()}
    TW = max(x for rs in th_rings.values() for r in rs for x, _ in r) + 4
    TH = max(y for rs in th_rings.values() for r in rs for _, y in r) + 4

    def th_map(highlight=None, mini=False):
        shapes = ""
        for tis, t in T.items():
            if tis not in th_full:
                continue
            if mini:
                shapes += f'<path d="{th_mini[tis]}"{" class=on" if highlight == tis else ""}/>'
                continue
            tip = {"n": t["name"], "a": t["native"], "s": None if t["score"] is None else round(t["score"]),
                   "people": pct(t["people"]), "jobs": pct(t["jobs"]), "biz": pct(t["biz"]), "money": pct(t["money"])}
            shapes += (f'<a href="{U(p_url(t))}" data-tip=\'{esc(json.dumps(tip, ensure_ascii=False))}\' aria-label="{esc(t["name"])}, momentum {tip["s"]}">'
                       f'<path d="{th_full[tis]}" {lens_attrs(t, lens_keys)}/></a>')
        dots = ""
        if mini and highlight:
            for d in by_prov.get(highlight, []):
                if d["in_latest"]:
                    x, y = TH_PROJ(d["lon"], d["lat"])
                    dots += f'<circle cx="{x:.1f}" cy="{y:.1f}" r="2.4"/>'
        if mini:
            return f'<svg class="map mini" viewBox="0 0 {TW:.0f} {TH:.0f}" aria-hidden="true"><g>{shapes}</g><g class="dots">{dots}</g></svg>'
        return (f'<svg class="map th" data-lens="score" viewBox="0 0 {TW:.0f} {TH:.0f}" role="group" aria-label="Map of Thailand by province">{HATCH}'
                f'<g class="units">{shapes}</g></svg>')

    # Vietnam: 34 provinces drawn from 63 old shapes. Fills carry no stroke; outlines and former borders are
    # separate layers built from shared TopoJSON arcs (etl/vn_geo.py), so merged provinces show no seam.
    vn_rings = {k: [[VN_PROJ(x, y) for x, y in r] for r in rs] for k, rs in vgeo["provinces"].items()}
    vn_full = {k: path_d(v, min_len=0.6) for k, v in vn_rings.items()}
    vn_mini = {k: path_d(v, tol=1.0, min_len=2.0) for k, v in vn_rings.items()}
    vn_line = lambda arcs, ml=0.0: "".join("M" + "L".join(f"{x:.1f},{y:.1f}" for x, y in (VN_PROJ(*pt) for pt in a)) for a in arcs
                                         if len(a) > 1 and (max(p[0] for p in a) - min(p[0] for p in a) + max(p[1] for p in a) - min(p[1] for p in a)) * 40 >= ml)
    vn_outline, vn_former = vn_line(vgeo["outline"], 0.8), vn_line(vgeo["former"])
    VW = max(x for rs in vn_rings.values() for r in rs for x, _ in r) + 4
    VH = max(y for rs in vn_rings.values() for r in rs for _, y in r) + 4

    def vn_map(highlight=None, mini=False):
        shapes = ""
        for k, v in V.items():
            if mini:
                shapes += f'<path d="{vn_mini[k]}"{" class=on" if highlight == k else ""}/>'
                continue
            tip = {"n": v["name"], "a": v["native"], "s": None if v["score"] is None else round(v["score"]),
                   "people": pct(v["people"]), "jobs": pct(v["jobs"]), "biz": pct(v["biz"]), "money": pct(v["money"])}
            shapes += (f'<a href="{U(v_url(v))}" data-tip=\'{esc(json.dumps(tip, ensure_ascii=False))}\' aria-label="{esc(v["name"])}, momentum {tip["s"]}">'
                       f'<path d="{vn_full[k]}" {lens_attrs(v, lens_keys)}/></a>')
        if mini:
            return f'<svg class="map mini vn" viewBox="0 0 {VW:.0f} {VH:.0f}" aria-hidden="true"><g>{shapes}</g></svg>'
        return (f'<svg class="map vn" data-lens="score" viewBox="0 0 {VW:.0f} {VH:.0f}" role="group" aria-label="Map of Vietnam by province (2025 boundaries)">{HATCH}'
                f'<g class="units">{shapes}</g><path class="former" d="{vn_former}"/><path class="outline" d="{vn_outline}"/></svg>')

    # ── ranked lists (reorder with FLIP on lens change)
    def rank_list(units, url_of, name_of, native_of, lang_of, cls="", limit=None, extra=""):
        keys = ["score"] + lens_keys
        ranked = sorted(units, key=lambda r: (r["score"] is None, -(r["score"] or 0)))
        items = ""
        for r in ranked:
            order = " ".join(f'data-r-{k}="{r.get(k + "_rank") if k != "score" else r.get("rank") or 999}"' for k in keys)
            shown = "–" if r["score"] is None else f'{r["score"]:.0f}'
            vals = " ".join(f'data-v-{k}="{esc(shown if k == "score" else pct(r.get(k)))}"' for k in keys)
            items += (f'<li {order} {vals}><a href="{U(url_of(r))}"><span class="pos">{r.get("rank") or "–"}</span>'
                      f'<span class="nm">{esc(name_of(r))}{native(native_of(r), lang_of(r))}</span>'
                      f'<span class="bar" style="--w:{(r["score"] or 0):.0f}%"></span><span class="val">{esc(shown)}</span></a></li>')
        return f'<ol class="rlist {cls}"{f" data-limit={limit}" if limit else ""}>{items}</ol>{extra}'

    # ── HOME
    Rv = list(R.values())
    lead = {k: max((r for r in Rv if r[k] is not None), key=lambda r: r[k]) for k in lens_keys}
    th_lead = {k: max((t for t in T.values() if t[k] is not None), key=lambda t: t[k]) for k in lens_keys}
    sea_pop = sum(r["pop"] for r in Rv if r["pop"])
    kpis = "".join(
        f'<a class="kpi reveal" href="{U(c_url(lead[k]))}">{icon(k)}<span class="k">{esc(LENS[k][1])}</span>'
        f'<span class="v up" data-count="{esc(pct(lead[k][k]))}">{esc(pct(lead[k][k]))}</span>'
        f'<span class="s">{esc(lead[k]["name"])}, {lead[k][k + "_year"]}</span></a>'
        for k in lens_keys)
    th_lists = ""
    for k in ["score"] + lens_keys:
        key = "score" if k == "score" else k
        top = sorted([t for t in T.values() if t.get(key) is not None], key=lambda t: -t[key])[:8]
        rows = "".join(
            f'<li><a href="{U(p_url(t))}"><span class="pos">{i}</span><span class="nm">{esc(t["name"])}{native(t["native"])}</span>'
            f'<span class="val {tone(t[key]) if k != "score" else ""}">{esc(f"{t[key]:.0f}" if k == "score" else pct(t[key]))}</span></a></li>'
            for i, t in enumerate(top, 1))
        sub = "Momentum across all four lenses" if k == "score" else f"{LENS[k][2]}, {base_of[k]} to {asof[k]}"
        th_lists += f'<div class="tlist" data-for="{k}"{"" if k == "score" else " hidden"}><p class="sub">{esc(sub)}</p><ol class="rlist plain">{rows}</ol></div>'
    vn_lists = ""
    for k in ["score"] + lens_keys:
        top = sorted([v for v in V.values() if v.get(k) is not None], key=lambda v: -v[k])[:8]
        rows = "".join(
            f'<li><a href="{U(v_url(v))}"><span class="pos">{i}</span><span class="nm">{esc(v["name"])}{native(v["native"], "vi")}</span>'
            f'<span class="val {tone(v[k]) if k != "score" else ""}">{esc(f"{v[k]:.0f}" if k == "score" else pct(v[k]))}</span></a></li>'
            for i, v in enumerate(top, 1))
        sub = "Momentum across all four lenses" if k == "score" else f"{VN_DESC[k]}, {vlab[k][0]}"
        vn_lists += f'<div class="tlist" data-for="{k}"{"" if k == "score" else " hidden"}><p class="sub">{esc(sub)}</p><ol class="rlist plain">{rows}</ol></div>'
    top_d = sorted([d for d in D if d.get("score") is not None], key=lambda d: d["rank"])[:10]
    leaving = sorted([d for d in D if d["dep_yoy"] is not None and d["in_latest"]], key=lambda d: d["dep_yoy"])[:5]

    def drow(d, val, key="dep_yoy"):
        return (f'<li><a href="{U(d_url(d))}"><span class="nm">{esc(d["name_en"])}{native(d["name_th"])}'
                f'<small>{esc(T[d["prov"]]["name"])}</small></span><span class="val {tone(val)}">{pct(val)}</span></a></li>')

    coverage_rows = ""
    for r in sorted(Rv, key=lambda r: r["name"]):
        sub = {"THA": '<td class="yes">77 provinces, 264 districts</td>', "VNM": '<td class="yes">34 provinces (2025)</td>'}.get(r["iso"], '<td class="soon">Planned</td>')
        coverage_rows += (f'<tr><th scope="row"><a href="{U(c_url(r))}">{esc(r["name"])}</a></th>'
                          + "".join(f'<td>{r[k + "_year"] or "–"}</td>' for k in lens_keys) + sub + "</tr>")
    home = f"""
<section class="hero">
  <h1>See where people, jobs, businesses and money are moving across Southeast&nbsp;Asia.</h1>
  <p class="lede">Eleven countries and {big(sea_pop)} people, ranked on four kinds of movement from public data. Thailand goes down to province and district, updated monthly from its central bank.</p>
</section>
<section class="atlas" id="atlas">
  <div class="atlas-map">
    {lens_tabs(label="Region lens")}
    <div class="mapframe">{sea_map()}</div>
    {legend("the 11 countries")}
  </div>
  <aside class="atlas-side">
    <h2 class="side-h">Ranking</h2>
    <p class="sub" data-sub-score>Momentum: average rank across all four lenses</p>
    {"".join(f'<p class="sub" data-sub-{k} hidden>{esc(LENS[k][1])}: latest year-on-year change</p>' for k in lens_keys)}
    {rank_list(Rv, c_url, lambda r: r["name"], lambda r: r["native"], lambda r: NATIVE_LANG.get(r["iso"], "und"), cls="sea-list")}
  </aside>
</section>
<section class="kpis">{kpis}</section>
<section class="split reveal" id="thailand">
  <div class="split-head">
    <h2>Inside Thailand</h2>
    <p>77 provinces on all four lenses. People from the civil registry, jobs and employers from social security, money from bank deposits and credit by district.</p>
    <a class="btn" href="{U('/thailand/')}">Open the Thailand explorer</a>
  </div>
  <div class="split-body">
    <div class="split-map">{lens_tabs(label="Thailand lens")}<div class="mapframe">{th_map()}</div>{legend("Thailand's 77 provinces")}</div>
    <div class="split-list">{th_lists}</div>
  </div>
</section>
<section class="split reveal" id="vietnam">
  <div class="split-head">
    <h2>Inside Vietnam</h2>
    <p>The 34 provinces formed in 2025, rebuilt from 63 old ones. Population and jobs to 2025, new businesses and enterprise revenue to 2024, from the National Statistics Office.</p>
    <a class="btn" href="{U('/vietnam/')}">Open the Vietnam explorer</a>
  </div>
  <div class="split-body">
    <div class="split-map">{lens_tabs(label="Vietnam lens")}<div class="mapframe">{vn_map()}</div>{legend("Vietnam's 34 provinces")}</div>
    <div class="split-list">{vn_lists}</div>
  </div>
</section>
<section class="movers reveal">
  <div><h2>Districts gaining money fastest</h2><p class="sub">Deposits, {month_label(y1)} to {month_label(latest)}</p>
    <ol class="dlist">{"".join(drow(d, d["dep_yoy"]) for d in top_d)}</ol>
    <a class="more" href="{U('/rankings/thailand-districts/')}">All {len([d for d in D if d.get('score') is not None])} districts</a></div>
  <div><h2>Where deposits fell most</h2><p class="sub">Same period, same districts</p>
    <ol class="dlist">{"".join(drow(d, d["dep_yoy"]) for d in leaving)}</ol>
    <a class="more" href="{U('/rankings/thailand-deposit-growth/')}">Full list</a></div>
</section>
<section class="coverage reveal">
  <h2>What we cover</h2>
  <p class="sub">Latest year available per lens at country level. National statistics are only compared inside a country, never across.</p>
  <div class="tablewrap"><table><thead><tr><th scope="col">Country</th>{"".join(f'<th scope="col">{esc(LENS[k][0])}</th>' for k in lens_keys)}<th scope="col">Subnational</th></tr></thead>
  <tbody>{coverage_rows}</tbody></table></div>
</section>
"""
    ld = ('<script type="application/ld+json">' + json.dumps({
        "@context": "https://schema.org", "@type": "Dataset", "name": "Where Money Moves — Southeast Asia",
        "description": "Where people, jobs, businesses and money are moving across Southeast Asia.",
        "url": SITE_URL + "/", "spatialCoverage": "Southeast Asia", "license": "https://creativecommons.org/licenses/by/4.0/",
        "creator": {"@type": "Organization", "name": "Where Money Moves"}}, ensure_ascii=False) + "</script>")
    write("/", page(U("/"), "Where Money Moves: where people, jobs, businesses and money are moving in Southeast Asia",
                    "Rank 11 Southeast Asian countries and every Thai province on population, jobs, businesses and money. Public data, updated monthly.",
                    home, meta, extra_head=ld))

    # ── COUNTRY pages
    for r in Rv:
        lang = NATIVE_LANG.get(r["iso"], "und")
        S = r["series"]

        def annual(series, fmt, title, since=2005):
            pts = [(y, v) for y, v in series if y >= since]
            return chart(pts, title, unit=fmt, x_label=lambda y: str(y), every=5, kind="line")

        panels = (
            lens_panel("people", pct(r["people"]), f"urban population, {r['people_year']}",
                       f"#{r.get('people_rank', '–')} of 11",
                       [("Population", big(r["pop"])), ("Urban share", f"{r['urban_share']*100:.0f}%" if r["urban_share"] else "–"),
                        ("Net migration", f"{signed_int(int(r['netmig'])) if r['netmig'] is not None else '–'} ({r['netmig_year']})")],
                       annual(S["people"], "", "Urban population")) +
            lens_panel("jobs", pct(r["jobs"]), f"employed people, {r['jobs_year']}", f"#{r.get('jobs_rank', '–')} of 11",
                       [("Employed", big(r["employed"])), ("Unemployment", f"{r['unemp']:.1f}% ({r['unemp_year']})" if r["unemp"] is not None else "–")],
                       annual(S["jobs"], "", "Employed people (ILO-modelled)")) +
            lens_panel("biz", pct(r["biz"]), f"new firms registered, {r['biz_year']}", f"#{r.get('biz_rank', '–')} of 11",
                       [("New firms", f"{big(r['new_firms'])} ({r['new_firms_year']})"),
                        ("Per 1,000 aged 15–64", f"{r['firm_density']:.2f}" if r["firm_density"] is not None else "–")],
                       annual(S["biz"], "", "New limited-liability firms per year")) +
            lens_panel("money", pct(r["money"]), f"real GDP, {r['money_year']}", f"#{r.get('money_rank', '–')} of 11",
                       [("GDP", f"{big(r['gdp_usd'], '$')} ({r['gdp_year']})"), ("FDI inflows", f"{big(r['fdi'], '$')} ({r['fdi_year']})"),
                        ("Remittances in", f"{big(r['remit'], '$')} ({r['remit_year']})" if r["remit"] else "–")],
                       annual(S["money"], "$", "Real GDP (constant 2015 US$)"))
        )
        deep = ""
        if r["iso"] == "THA":
            deep = (f'<section class="callout reveal"><h2>Go deeper: 77 provinces, 264 districts</h2>'
                    f'<p>Thailand has province-level data on all four lenses and monthly bank data by district.</p>'
                    f'<a class="btn" href="{U("/thailand/")}">Open the Thailand explorer</a></section>')
        elif r["iso"] == "VNM":
            deep = (f'<section class="callout reveal"><h2>Go deeper: 34 provinces</h2>'
                    f'<p>Population, jobs, new businesses and enterprise revenue for every province on the 2025 boundaries, with the 63 former provinces underneath.</p>'
                    f'<a class="btn" href="{U("/vietnam/")}">Open the Vietnam explorer</a></section>')
        else:
            deep = (f'<section class="callout quiet reveal"><h2>Subnational data for {esc(r["name"])}</h2>'
                    f'<p>Not yet. Country-level figures above are from the World Bank. Provinces arrive country by country: Thailand and Vietnam so far, Malaysia next.</p></section>')
        others = "".join(f'<li><a href="{U(c_url(o))}">{esc(o["name"])}</a></li>' for o in sorted(Rv, key=lambda o: o["name"]) if o is not r)
        body = f"""
<section class="hero detail">
  <div><h1>{esc(r['name'])} {native(r['native'], lang)}</h1>
  <p class="lede">Momentum {('%.0f' % r['score']) if r['score'] is not None else '–'} out of 100, #{r.get('rank', '–')} of 11 Southeast Asian countries.</p></div>
  <div class="mini-sea">{sea_map(highlight=r['iso'], interactive=False)}</div>
</section>
<div class="panels">{panels}</div>
{deep}
<nav class="others" aria-label="Other countries"><h2>Other countries</h2><ul class="chips">{others}</ul></nav>
"""
        path = c_url(r)
        write(path, page(U(path), f"{r['name']}: population, jobs, businesses and GDP growth | Where Money Moves",
                         f"{r['name']}: urban population {pct(r['people'])}, employment {pct(r['jobs'])}, new firms {pct(r['biz'])}, real GDP {pct(r['money'])}. Ranked #{r.get('rank', '–')} of 11 in Southeast Asia.",
                         body, meta, crumbs=[("Southeast Asia", "/"), (r["name"], path)],
                         watch={"id": f"c-{r['iso']}", "name": r["name"], "url": U(path)}))

    # ── THAILAND explorer
    trows = ""
    for t in sorted(T.values(), key=lambda t: (t["score"] is None, -(t["score"] or 0))):
        trows += (f'<tr><td class="num pos">{t.get("rank") or "–"}</td><th scope="row"><a href="{U(p_url(t))}">{esc(t["name"])}</a>{native(t["native"])}</th>'
                  f'<td data-v="{"" if t["score"] is None else round(t["score"], 2)}">{score_pill(t["score"])}</td>'
                  + value_cell(t["people"]) + value_cell(t["jobs"]) + value_cell(t["biz"]) + value_cell(t["money"]) + "</tr>")
    explorer = f"""
<section class="hero">
  <h1>Thailand, province by province</h1>
  <p class="lede">Where people are registering, where formal jobs and employers are being added, and where bank money is growing. Each lens has its own latest date, shown with the number.</p>
</section>
<section class="split flush">
  <div class="split-body">
    <div class="split-map">{lens_tabs(label="Thailand lens")}<div class="mapframe tall">{th_map()}</div>{legend("Thailand's 77 provinces")}</div>
    <div class="split-list">
      <dl class="asof">{"".join(f'<div>{icon(k)}<dt>{esc(LENS[k][0])}</dt><dd>{esc(LENS[k][2])}<br><small>{esc(base_of[k])} to {esc(asof[k])}</small></dd></div>' for k in lens_keys)}</dl>
    </div>
  </div>
</section>
<section class="reveal">
  <h2>All 77 provinces</h2>
  <p class="sub">Select a column heading to sort. Momentum is the average rank across the four lenses.</p>
  <div class="tablewrap"><table class="rank" data-sortable><thead><tr><th scope="col" class="num">#</th><th scope="col">Province</th>
  <th scope="col"><button data-k="2">Momentum</button></th><th scope="col" class="num"><button data-k="3">People</button></th>
  <th scope="col" class="num"><button data-k="4">Jobs</button></th><th scope="col" class="num"><button data-k="5">Businesses</button></th>
  <th scope="col" class="num"><button data-k="6">Money</button></th></tr></thead><tbody>{trows}</tbody></table></div>
</section>
"""
    write("/thailand/", page(U("/thailand/"), "Thailand provinces ranked by population, jobs, businesses and money | Where Money Moves",
                             "All 77 Thai provinces ranked on registered population, formal employment, registered employers and bank money growth.",
                             explorer, meta, crumbs=[("Southeast Asia", "/"), ("Thailand", "/thailand/")]))

    # ── PROVINCE pages
    for tis, t in T.items():
        ds = by_prov.get(tis, [])
        cur = sorted([d for d in ds if d["in_latest"]], key=lambda d: -(d.get("score") or -1))
        gone = [d for d in ds if not d["in_latest"]]
        yr = lambda pts: [(y, v) for y, v in pts]
        panels = (
            lens_panel("people", pct(t["people"]), f"registered population, {base_of['people']} to {asof['people']}",
                       f"#{t.get('people_rank', '–')} of 77",
                       [("Registered population", f"{t['pop']:,}"), ("Five-year change", pct(t["people_5y"]))],
                       chart(yr(t["pop_series"]), "Registered population, December", x_label=str, every=1, kind="dots"),
                       "Counts people at their registered address. It undercounts places people move to without re-registering.") +
            lens_panel("jobs", pct(t["jobs"]), f"formal-sector employees, {base_of['jobs']} to {asof['jobs']}",
                       f"#{t.get('jobs_rank', '–')} of 77",
                       [("Insured employees (Section 33)", f"{t['insured']:,}"), ("Three-year change", pct(t["jobs_3y"]))],
                       chart(yr(t["ins_series"]), "Section 33 insured employees, December", x_label=str, every=1, kind="dots")) +
            lens_panel("biz", pct(t["biz"]), f"employers registered with SSO, {base_of['biz']} to {asof['biz']}",
                       f"#{t.get('biz_rank', '–')} of 77",
                       [("Registered employers", f"{t['enterprises']:,}"), ("Three-year change", pct(t["biz_3y"])),
                        ("Employees per employer", f"{t['firm_size']:.1f}" if t["firm_size"] else "–")],
                       chart(yr(t["ent_series"]), "Employers registered with SSO, December", x_label=str, every=1, kind="dots"),
                       "Proxy for businesses. Every employer with staff must register with SSO.") +
            lens_panel("money", pct(t["money"]), f"bank deposits, {base_of['money']} to {asof['money']}",
                       f"#{t.get('money_rank', '–')} of 68" if t["money"] is not None else "No bank data",
                       [("Credit", pct(t["credit"])), ("Branches", f"{t['branches'] or '–'} ({signed_int(t['br_change'])} in a year)"),
                        ("Districts covered", f"{t['n_covered']} of {t['n_districts_total']}")],
                       "", "Sum of districts with four or more commercial banks, the only ones the Bank of Thailand publishes.")
        )
        drows = ""
        for d in cur:
            flag = ' <span class="flag" title="Unusual credit swing">!</span>' if d["cr_yoy"] is not None and abs(d["cr_yoy"]) > SPIKE else ""
            drows += (f'<tr><td class="num pos">{d.get("prov_rank") or "–"}</td><th scope="row"><a href="{U(d_url(d))}">{esc(d["name_en"])}</a>{native(d["name_th"])}</th>'
                      + value_cell(d["dep_yoy"]) + value_cell(d["cr_yoy"]).replace("</td>", flag + "</td>")
                      + f'<td class="num" data-v="{d["br_change"] if d["br_change"] is not None else ""}">{signed_int(d["br_change"])}</td>'
                      f'<td class="sp">{spark([r[1] for r in d["series"][-25:]])}</td></tr>')
        dtable = ""
        if drows:
            dtable = (f'<section class="reveal"><h2>Districts</h2><p class="sub">Bank money, {month_label(y1)} to {month_label(latest)}</p>'
                      f'<div class="tablewrap"><table class="rank" data-sortable><thead><tr><th scope="col" class="num">#</th><th scope="col">District</th>'
                      f'<th scope="col" class="num"><button data-k="2">Deposits</button></th><th scope="col" class="num"><button data-k="3">Credit</button></th>'
                      f'<th scope="col" class="num"><button data-k="4">Branches</button></th><th scope="col" class="sp"><span class="sr-only">Trend</span></th></tr></thead>'
                      f'<tbody>{drows}</tbody></table></div></section>')
        if gone:
            dtable += ('<section class="reveal"><h2>Dropped from the bank table</h2><p class="sub">Fell below four commercial banks during the year.</p><ul class="chips">'
                       + "".join(f'<li><a href="{U(d_url(d))}">{esc(d["name_en"])}</a></li>' for d in gone) + "</ul></section>")
        near = sorted([o for o in T.values() if o["region"] == t["region"] and o is not t], key=lambda o: -(o["score"] or 0))[:8]
        body = f"""
<section class="hero detail">
  <div><h1>{esc(t['name'])} {native(t['native'])}</h1>
  <p class="lede">Momentum {('%.0f' % t['score']) if t['score'] is not None else '–'} out of 100, #{t.get('rank', '–')} of 77 provinces.{f" GPP per head {t['gpp_pc']:,.0f} baht ({ctx['year']})." if t['gpp_pc'] else ""}</p></div>
  {th_map(highlight=tis, mini=True)}
</section>
<div class="panels">{panels}</div>
{dtable}
<nav class="others" aria-label="Nearby provinces"><h2>Elsewhere in the {esc(t['region'])} region</h2><ul class="chips">{"".join(f'<li><a href="{U(p_url(o))}">{esc(o["name"])}</a></li>' for o in near)}</ul></nav>
"""
        path = p_url(t)
        write(path, page(U(path), f"{t['name']} province: population, jobs, businesses and bank money | Where Money Moves",
                         f"{t['name']}, Thailand: registered population {pct(t['people'])}, formal jobs {pct(t['jobs'])}, employers {pct(t['biz'])}, deposits {pct(t['money'])}. #{t.get('rank', '–')} of 77 provinces.",
                         body, meta, crumbs=[("Southeast Asia", "/"), ("Thailand", "/thailand/"), (t["name"], path)],
                         watch={"id": f"p-{tis}", "name": t["name"], "url": U(path)}))

    # ── DISTRICT pages
    nD = len([d for d in D if d.get("score") is not None])
    for d in D:
        t = T[d["prov"]]
        unit = "Khet" if d["prov"] == "10" else "District"
        notes = ""
        if not d["in_latest"]:
            lp = next((r[0] for r in reversed(d["series"]) if r[1] is not None), None)
            notes += f'<p class="warn">Not in the latest Bank of Thailand table. Last figures: {month_label(lp)}.</p>'
        if d["cr_yoy"] is not None and abs(d["cr_yoy"]) > SPIKE:
            notes += '<p class="warn">Credit moved more than 50% in a year. This usually means one large borrower or loans moved between branches.</p>'
        ser = d["series"]
        mlabel = lambda p: p[:4] if p.endswith("-01") else ""
        charts = (chart([(r[0], r[1] and r[1] / 1e6) for r in ser], "Deposits, million baht", x_label=mlabel, every=1, base=y1)
                  + chart([(r[0], r[2] and r[2] / 1e6) for r in ser], "Credit, million baht", x_label=mlabel, every=1, base=y1)
                  + chart([(r[0], r[3]) for r in ser], "Bank branches", x_label=mlabel, every=1, base=y1))
        stats = ((stat("Money momentum", f'{d["score"]:.0f}', f'#{d["rank"]} of {nD} districts') if d.get("score") is not None else "")
                 + stat("Deposits", pct(d["dep_yoy"]), f"{month_label(y1)} to {month_label(latest)}", tone(d["dep_yoy"]))
                 + stat("Credit", pct(d["cr_yoy"]), "Same period", tone(d["cr_yoy"]))
                 + stat("Branches", str(d["branches"]) if d["branches"] is not None else "–", f'{signed_int(d["br_change"])} in a year')
                 + stat("Deposit balance", baht(d["deposits"]), month_label(latest) if d["in_latest"] else "")
                 + (stat("Deposits over three years", pct(d["dep_3y"]), f"Since {month_label(meta['base_3y'])}", tone(d["dep_3y"])) if d["dep_3y"] is not None else ""))
        months = "".join(f'<tr><th scope="row">{month_label(r[0])}</th><td class="num">{"–" if r[1] is None else f"{r[1]/1e6:,.0f}"}</td>'
                         f'<td class="num">{"–" if r[2] is None else f"{r[2]/1e6:,.0f}"}</td><td class="num">{"–" if r[3] is None else r[3]}</td></tr>'
                         for r in reversed(ser[-13:]))
        sibs = sorted([x for x in by_prov[d["prov"]] if x is not d and x["in_latest"]], key=lambda x: -(x.get("score") or -1))
        body = f"""
<section class="hero detail">
  <div><h1>{esc(d['name_en'])} {native(d['name_th'])}</h1>
  <p class="lede">{unit} in <a href="{U(p_url(t))}">{esc(t['name'])}</a>{f", #{d['prov_rank']} in the province on bank money" if d.get('prov_rank') else ""}.</p>
  {notes}</div>
</section>
<section class="stats reveal">{stats}</section>
<section class="charts reveal">{charts}</section>
<section class="reveal"><details><summary>Monthly figures</summary><div class="tablewrap"><table class="plain"><thead><tr><th scope="col">Month</th>
<th scope="col" class="num">Deposits (฿M)</th><th scope="col" class="num">Credit (฿M)</th><th scope="col" class="num">Branches</th></tr></thead><tbody>{months}</tbody></table></div></details></section>
{f'<nav class="others" aria-label="Other districts"><h2>Other districts in {esc(t["name"])}</h2><ul class="chips">' + "".join(f'<li><a href="{U(d_url(x))}">{esc(x["name_en"])} <span class="{tone(x["dep_yoy"])}">{pct(x["dep_yoy"])}</span></a></li>' for x in sibs) + "</ul></nav>" if sibs else ""}
"""
        path = d_url(d)
        write(path, page(U(path), f"{d['name_en']}, {t['name']}: bank deposits and credit ({month_label(latest)}) | Where Money Moves",
                         f"{d['name_en']} {unit.lower()}, {t['name']}, Thailand: deposits {pct(d['dep_yoy'])} and credit {pct(d['cr_yoy'])} year on year, {d['branches'] or '–'} bank branches.",
                         body, meta, crumbs=[("Southeast Asia", "/"), ("Thailand", "/thailand/"), (t["name"], p_url(t)), (d["name_en"], path)],
                         watch={"id": f"d-{d['id']}", "name": f"{d['name_en']}, {t['name']}", "url": U(path)}))

    # ── VIETNAM explorer
    vk = ["people", "jobs", "biz", "money"]
    vrows = ""
    for v in sorted(V.values(), key=lambda v: (v["score"] is None, -(v["score"] or 0))):
        vrows += (f'<tr><td class="num pos">{v.get("rank") or "–"}</td><th scope="row"><a href="{U(v_url(v))}">{esc(v["name"])}</a>{native(v["native"], "vi")}'
                  f'<small>{esc(", ".join(v["former"])) if len(v["former"]) > 1 else ""}</small></th>'
                  f'<td data-v="{"" if v["score"] is None else round(v["score"], 2)}">{score_pill(v["score"])}</td>'
                  + "".join(value_cell(v[k]) for k in vk) + "</tr>")
    vhead = ('<th scope="col" class="num">#</th><th scope="col">Province</th><th scope="col"><button data-k="2">Momentum</button></th>'
             + "".join(f'<th scope="col" class="num"><button data-k="{i}">{esc(LENS[k][0])}</button></th>' for i, k in enumerate(vk, 3)))
    explorer = f"""
<section class="hero">
  <h1>Vietnam, province by province</h1>
  <p class="lede">The 34 provinces created by the 2025 merger, each rebuilt from the old provinces it absorbed. Where people are settling, where jobs and new businesses are being added, and where enterprise revenue is growing.</p>
</section>
<section class="split flush">
  <div class="split-body">
    <div class="split-map">{lens_tabs(label="Vietnam lens")}<div class="mapframe tall">{vn_map()}</div>{legend("Vietnam's 34 provinces")}
      <p class="note">Dashed lines are the provincial borders before 1 July 2025.</p></div>
    <div class="split-list">
      <dl class="asof">{"".join(f'<div>{icon(k)}<dt>{esc(LENS[k][0])}</dt><dd>{esc(VN_DESC[k])}<br><small>{esc(vlab[k][0])}</small></dd></div>' for k in vk)}</dl>
    </div>
  </div>
</section>
<section class="reveal">
  <h2>All 34 provinces</h2>
  <p class="sub">Select a column heading to sort. Merged provinces list the provinces they were formed from.</p>
  <div class="tablewrap"><table class="rank" data-sortable><thead><tr>{vhead}</tr></thead><tbody>{vrows}</tbody></table></div>
</section>
"""
    write("/vietnam/", page(U("/vietnam/"), "Vietnam's 34 provinces ranked by population, jobs, new businesses and revenue | Where Money Moves",
                            "Every Vietnamese province on the 2025 boundaries, ranked on population, employment, new enterprises and enterprise revenue growth.",
                            explorer, meta, crumbs=[("Southeast Asia", "/"), ("Vietnam", "/vietnam/")]))

    # ── VIETNAM province pages
    units = vn["units"]
    for slug_, v in V.items():
        yl = lambda pts: [(y, val) for y, val in pts]
        merged = len(v["former"]) > 1
        formed = (f"Formed on 1 July 2025 from {', '.join(v['former'][:-1])} and {v['former'][-1]}." if merged
                  else "Unchanged by the 2025 merger.")
        panels = (
            lens_panel("people", pct(v["people"]), f"average population, {vlab['people'][0]}", f"#{v.get('people_rank', '–')} of 34",
                       [("Population", f"{v['pop']:,.0f}"), ("Five-year change", pct(v["people_5y"])),
                        ("Net migration", f"{v['netmig']:+.1f} per 1,000 ({v['netmig_year']})".replace("-", "−") if v["netmig"] is not None else "–")],
                       chart([(y, val * 1000) for y, val in v["series"]["people"]], "Average population", x_label=str, every=3, kind="dots"),
                       "Net migration is people moving in minus people moving out, per 1,000 residents. Positive means the province is gaining people from elsewhere.") +
            lens_panel("jobs", pct(v["jobs"]), f"employed workers, {vlab['jobs'][0]}", f"#{v.get('jobs_rank', '–')} of 34",
                       [("Employed workers", f"{v['employed']:,.0f}")],
                       chart([(y, val * 1000) for y, val in v["series"]["jobs"]], "Employed workers", x_label=str, every=1, kind="dots")) +
            lens_panel("biz", pct(v["biz"]), f"newly registered enterprises, {vlab['biz'][0]}", f"#{v.get('biz_rank', '–')} of 34",
                       [("New enterprises", f"{v['new_firms']:,.0f}"),
                        ("Active enterprises", f"{v['firms']:,.0f} ({pct(v['firms_growth'])}, {v['firms_year']})" if v["firms"] else "–")],
                       chart(yl(v["series"]["biz"]), "Newly registered enterprises per year", x_label=str, every=2, kind="dots")) +
            lens_panel("money", pct(v["money"]), f"enterprise net revenue, {vlab['money'][0]}", f"#{v.get('money_rank', '–')} of 34",
                       [("Net revenue", f"{v['revenue'] / 1000:,.0f} trillion dong")],
                       chart([(y, val * 1e9) for y, val in v["series"]["money"] if y >= 2015], "Enterprise net revenue, nominal", unit="₫", x_label=str, every=2, kind="dots"),
                       "Revenue of active enterprises with business results, by where the enterprise is registered. Nominal.")
        )
        fd = ""
        if merged:
            rows = ""
            for name, d in v["former_detail"].items():
                def yoy(key):
                    ser = sorted(d[key].items())
                    return growth(ser[-1][1], ser[-2][1]) if len(ser) == 2 else None
                popv = sorted(d["pop"].items())[-1][1] * 1000
                rows += (f'<tr><th scope="row">{esc(name)}</th><td class="num" data-v="{popv}">{popv:,.0f}</td>'
                         + value_cell(yoy("pop")) + value_cell(yoy("employed")) + value_cell(yoy("new_firms")) + value_cell(yoy("revenue")) + "</tr>")
            fd = (f'<section class="reveal"><h2>The provinces it was formed from</h2><p class="sub">Each former province on its own, latest year on year.</p>'
                  f'<div class="tablewrap"><table class="rank" data-sortable><thead><tr><th scope="col">Former province</th>'
                  f'<th scope="col" class="num"><button data-k="1">Population</button></th><th scope="col" class="num"><button data-k="2">People</button></th>'
                  f'<th scope="col" class="num"><button data-k="3">Jobs</button></th><th scope="col" class="num"><button data-k="4">New businesses</button></th>'
                  f'<th scope="col" class="num"><button data-k="5">Revenue</button></th></tr></thead><tbody>{rows}</tbody></table></div></section>')
        near = sorted([o for o in V.values() if o is not v], key=lambda o: -(o["score"] or 0))[:10]
        body = f"""
<section class="hero detail">
  <div><h1>{esc(v['name'])} {native(v['native'], 'vi')}</h1>
  <p class="lede">Momentum {('%.0f' % v['score']) if v['score'] is not None else '–'} out of 100, #{v.get('rank', '–')} of 34 provinces. {esc(formed)}</p></div>
  {vn_map(highlight=slug_, mini=True)}
</section>
<div class="panels">{panels}</div>
{fd}
<nav class="others" aria-label="Other provinces"><h2>Other provinces with high momentum</h2><ul class="chips">{"".join(f'<li><a href="{U(v_url(o))}">{esc(o["name"])}</a></li>' for o in near)}</ul></nav>
"""
        path = v_url(v)
        write(path, page(U(path), f"{v['name']}, Vietnam: population, jobs, new businesses and revenue | Where Money Moves",
                         f"{v['name']} province, Vietnam (2025 boundaries): population {pct(v['people'])}, employment {pct(v['jobs'])}, new enterprises {pct(v['biz'])}, enterprise revenue {pct(v['money'])}."
                         + (f" Formed from {', '.join(v['former'])}." if merged else ""),
                         body, meta, crumbs=[("Southeast Asia", "/"), ("Vietnam", "/vietnam/"), (v["name"], path)],
                         watch={"id": f"v-{slug_}", "name": f"{v['name']}, Vietnam", "url": U(path)}))

    # ── RANKINGS
    rk_index = []

    def ranking_page(key, title, desc, head, rows):
        body = (f'<section class="hero"><h1>{esc(title)}</h1><p class="lede">{esc(desc)}</p></section>'
                f'<section><div class="tablewrap"><table class="rank" data-sortable><thead><tr>{head}</tr></thead><tbody>{rows}</tbody></table></div></section>')
        path = f"/rankings/{key}/"
        write(path, page(U(path), f"{title} | Where Money Moves", desc, body, meta,
                         crumbs=[("Southeast Asia", "/"), ("Rankings", "/rankings/"), (title, path)]))
        rk_index.append((path, title, desc))

    head = ('<th scope="col" class="num">#</th><th scope="col">Country</th><th scope="col"><button data-k="2">Momentum</button></th>'
            + "".join(f'<th scope="col" class="num"><button data-k="{i}">{esc(LENS[k][0])}</button></th>' for i, k in enumerate(lens_keys, 3)))
    rows = "".join(f'<tr><td class="num pos">{r.get("rank")}</td><th scope="row"><a href="{U(c_url(r))}">{esc(r["name"])}</a></th>'
                   f'<td data-v="{round(r["score"], 2) if r["score"] is not None else ""}">{score_pill(r["score"])}</td>'
                   + "".join(value_cell(r[k]) for k in lens_keys) + "</tr>"
                   for r in sorted(Rv, key=lambda r: r.get("rank") or 99))
    ranking_page("southeast-asia", "Southeast Asian countries by momentum",
                 "Urban population, employment, new firm registrations and real GDP, latest year-on-year change for each.", head, rows)

    head_t = ('<th scope="col" class="num">#</th><th scope="col">Province</th><th scope="col"><button data-k="2">Momentum</button></th>'
              + "".join(f'<th scope="col" class="num"><button data-k="{i}">{esc(LENS[k][0])}</button></th>' for i, k in enumerate(lens_keys, 3)))

    def trow(t, pos):
        return (f'<tr><td class="num pos">{pos}</td><th scope="row"><a href="{U(p_url(t))}">{esc(t["name"])}</a>{native(t["native"])}</th>'
                f'<td data-v="{round(t["score"], 2) if t["score"] is not None else ""}">{score_pill(t["score"])}</td>'
                + "".join(value_cell(t[k]) for k in lens_keys) + "</tr>")

    ts = sorted(T.values(), key=lambda t: (t["score"] is None, -(t["score"] or 0)))
    ranking_page("thailand-provinces", "Thai provinces by momentum",
                 "All 77 provinces, average rank across registered population, formal jobs, employers and bank deposits.",
                 head_t, "".join(trow(t, t.get("rank") or "–") for t in ts))
    for k, key, title in (("people", "thailand-population-growth", "Thai provinces by population growth"),
                          ("jobs", "thailand-job-growth", "Thai provinces by formal job growth"),
                          ("biz", "thailand-business-growth", "Thai provinces by business growth")):
        srt = sorted([t for t in T.values() if t[k] is not None], key=lambda t: -t[k])
        ranking_page(key, title, f"{LENS[k][2]}, {base_of[k]} to {asof[k]}.", head_t, "".join(trow(t, i) for i, t in enumerate(srt, 1)))

    head_d = ('<th scope="col" class="num">#</th><th scope="col">District</th><th scope="col"><button data-k="2">Momentum</button></th>'
              '<th scope="col" class="num"><button data-k="3">Deposits</button></th><th scope="col" class="num"><button data-k="4">Credit</button></th>'
              '<th scope="col" class="num"><button data-k="5">Branches</button></th><th scope="col" class="sp"><span class="sr-only">Trend</span></th>')

    def drank(d, pos):
        flag = ' <span class="flag" title="Unusual credit swing">!</span>' if d["cr_yoy"] is not None and abs(d["cr_yoy"]) > SPIKE else ""
        return (f'<tr><td class="num pos">{pos}</td><th scope="row"><a href="{U(d_url(d))}">{esc(d["name_en"])}</a>{native(d["name_th"])}<small>{esc(T[d["prov"]]["name"])}</small></th>'
                f'<td data-v="{round(d["score"], 2) if d.get("score") is not None else ""}">{score_pill(d.get("score"))}</td>'
                + value_cell(d["dep_yoy"]) + value_cell(d["cr_yoy"]).replace("</td>", flag + "</td>")
                + f'<td class="num" data-v="{d["br_change"] if d["br_change"] is not None else ""}">{signed_int(d["br_change"])}</td>'
                f'<td class="sp">{spark([r[1] for r in d["series"][-25:]])}</td></tr>')

    live = [d for d in D if d["in_latest"]]
    per = f"{month_label(y1)} to {month_label(latest)}"
    ranking_page("thailand-districts", "Thai districts by money momentum", f"Bank deposits and credit, {per}. Districts with four or more commercial banks.",
                 head_d, "".join(drank(d, d["rank"]) for d in sorted([d for d in D if d.get("score") is not None], key=lambda d: d["rank"])))
    for key, title, f in (("thailand-deposit-growth", "Thai districts by deposit growth", "dep_yoy"),
                          ("thailand-credit-growth", "Thai districts by credit growth", "cr_yoy")):
        srt = sorted([d for d in live if d[f] is not None], key=lambda d: -d[f])
        ranking_page(key, title, f"{per}.", head_d, "".join(drank(d, i) for i, d in enumerate(srt, 1)))
    srt = sorted([d for d in live if d["br_change"] is not None], key=lambda d: (d["br_change"], d["dep_yoy"] or 0))
    ranking_page("thailand-branch-closures", "Thai districts losing bank branches", f"Change in commercial-bank branches, {per}.",
                 head_d, "".join(drank(d, i) for i, d in enumerate(srt, 1)))

    def vrow(v, pos):
        return (f'<tr><td class="num pos">{pos}</td><th scope="row"><a href="{U(v_url(v))}">{esc(v["name"])}</a>{native(v["native"], "vi")}</th>'
                f'<td data-v="{round(v["score"], 2) if v["score"] is not None else ""}">{score_pill(v["score"])}</td>'
                + "".join(value_cell(v[k]) for k in vk) + "</tr>")
    vs = sorted(V.values(), key=lambda v: (v["score"] is None, -(v["score"] or 0)))
    ranking_page("vietnam-provinces", "Vietnamese provinces by momentum",
                 "All 34 provinces (2025 boundaries), average rank across population, employment, new enterprises and enterprise revenue.",
                 vhead, "".join(vrow(v, v.get("rank") or "–") for v in vs))
    for k, key, title in (("people", "vietnam-population-growth", "Vietnamese provinces by population growth"),
                          ("jobs", "vietnam-job-growth", "Vietnamese provinces by job growth"),
                          ("biz", "vietnam-new-business-growth", "Vietnamese provinces by new business growth"),
                          ("money", "vietnam-revenue-growth", "Vietnamese provinces by enterprise revenue growth")):
        srt = sorted([v for v in V.values() if v[k] is not None], key=lambda v: -v[k])
        ranking_page(key, title, f"{VN_DESC[k]}, {vlab[k][0]}.", vhead, "".join(vrow(v, i) for i, v in enumerate(srt, 1)))

    body = ('<section class="hero"><h1>Rankings</h1><p class="lede">Every list on the site, as a sortable table.</p></section><ul class="rk-index">'
            + "".join(f'<li class="reveal"><a href="{U(p)}"><b>{esc(t)}</b><span>{esc(d)}</span></a></li>' for p, t, d in rk_index) + "</ul>")
    write("/rankings/", page(U("/rankings/"), "Rankings | Where Money Moves", "Sortable rankings of Southeast Asian countries, Thai provinces and districts.",
                             body, meta, crumbs=[("Southeast Asia", "/"), ("Rankings", "/rankings/")]))

    # ── COMPARE (client-rendered from compare.json)
    cmp = {}
    for r in Rv:
        cmp[f"c-{r['iso']}"] = {"n": r["name"], "u": U(c_url(r)), "k": "Country", "s": r["score"],
                                **{k: r[k] for k in lens_keys}, **{k + "y": str(r[k + "_year"]) for k in lens_keys}}
    for t in T.values():
        cmp[f"p-{t['id']}"] = {"n": t["name"], "a": t["native"], "u": U(p_url(t)), "k": "Thai province", "s": t["score"],
                               **{k: t[k] for k in lens_keys}, **{k + "y": asof[k] for k in lens_keys}}
    for d in D:
        cmp[f"d-{d['id']}"] = {"n": f"{d['name_en']}, {T[d['prov']]['name']}", "a": d["name_th"], "u": U(d_url(d)), "k": "Thai district",
                               "s": d.get("score"), "money": d["dep_yoy"], "moneyy": month_label(latest), "credit": d["cr_yoy"]}
    for v in V.values():
        cmp[f"v-{v['slug']}"] = {"n": f"{v['name']}, Vietnam", "a": v["native"], "u": U(v_url(v)), "k": "Vietnamese province", "s": v["score"],
                                 **{k: v[k] for k in vk}, **{k + "y": str(vlab[k][1]) for k in vk}}
    (OUT / "assets" / "compare.json").write_text(json.dumps(cmp, ensure_ascii=False, separators=(",", ":")))
    body = """
<section class="hero"><h1>Compare</h1><p class="lede">Places you watch appear here side by side. Select Watch on any country, province or district page.</p>
<p class="sub">Countries and Thai places use different measures (see <a href="__M__">Method</a>), and momentum is a rank within each place's own group, so compare like with like.</p></section>
<section id="compare" class="compare" data-lenses='""" + esc(json.dumps([[k, LENS[k][0]] for k in lens_keys])) + """'>
  <div class="empty"><p>Nothing to compare yet.</p><p class="sub">Try <a href="__T__">Thailand</a> or search with <kbd>/</kbd>, then select Watch.</p></div>
</section>
""".replace("__T__", U("/thailand/")).replace("__M__", U("/about/"))
    write("/compare/", page(U("/compare/"), "Compare places | Where Money Moves", "Compare countries, Thai provinces and districts on people, jobs, businesses and money.",
                            body, meta, crumbs=[("Southeast Asia", "/"), ("Compare", "/compare/")]))

    # ── ABOUT
    sections = [
        ("Two layers that are never mixed",
         "Countries are compared with World Bank indicators, which share definitions. Inside Thailand and Vietnam we use national sources, which are richer but not comparable across countries. A Thai province is only ever ranked against other Thai provinces, a Vietnamese one against Vietnamese provinces."),
        ("The four lenses for countries",
         "People is urban population growth: people moving into cities. Jobs is growth in employed people (labour force × (1 − unemployment), ILO-modelled). Businesses is growth in new limited-liability firms registered (World Bank Entrepreneurship data). Money is real GDP growth. Each uses its own latest year, shown next to the number."),
        ("The four lenses for Thailand",
         f"People: registered population, Department of Provincial Administration, {base_of['people']} to {asof['people']}. Jobs: employees insured under Section 33 of the Social Security Act, {base_of['jobs']} to {asof['jobs']}. Businesses: employers registered with the Social Security Office, the same period. Money: commercial-bank deposits, Bank of Thailand district table, {base_of['money']} to {asof['money']}."),
        ("The four lenses for Vietnam",
         f"From the National Statistics Office (formerly GSO). People: average population, {vlab['people'][0]}, with net migration per 1,000 residents alongside. Jobs: employed workers, {vlab['jobs'][0]}. Businesses: newly registered enterprises, {vlab['biz'][0]}. Money: net revenue of active enterprises, {vlab['money'][0]}, nominal. The latest year is often preliminary."),
        ("Vietnam's 2025 merger",
         "On 1 July 2025 Vietnam's 63 provinces became 34. Every merger joined whole provinces, so the statistics, still published for the 63, add up exactly into the new ones; we check that the 63 sum to the national total every year from 2010. Maps are rebuilt from the 63 former shapes, and the old borders are drawn dashed. Far-offshore archipelagos are not drawn at this scale."),
        ("Proxies, and why",
         "Thailand's company register has no clean province series in open data, so businesses are proxied by employers registered with social security: every business with staff must register. Registered population undercounts places people move to without changing their house registration, such as Bangkok and the Eastern Economic Corridor, and leaves out most migrant workers. Formal jobs leave out the informal sector, roughly half of Thai employment."),
        ("Momentum score",
         "Each lens is turned into a percentile rank within its layer (11 countries, 77 provinces or 234 districts), and the score is their average. We use ranks because Bangkok and Singapore are so much larger than their neighbours that raw values would hide everyone else. A missing lens is left out, never counted as zero."),
        ("Bank data by district",
         "The Bank of Thailand publishes deposits, credit and branches monthly, only for districts with four or more commercial banks (about 235). Province money figures add up those districts, so they are not full-province totals. Head-office balances are not assigned to any place. Credit can jump when a large borrower moves; we flag swings above ±50%. Values are nominal."),
        ("Updates",
         "Bank data monthly, social security yearly (December), registered population yearly, World Bank yearly. The pipeline stops rather than publish numbers it cannot verify: every source has a structure fingerprint and a total cross-check."),
    ]
    body = ('<section class="hero"><h1>How the numbers work</h1><p class="lede">Public data only. Every figure on the site comes from one of the sources below, unchanged except for the arithmetic described here.</p></section>'
            + "".join(f'<section class="prose reveal"><h2>{esc(h)}</h2><p>{esc(b)}</p></section>' for h, b in sections))
    write("/about/", page(U("/about/"), "Method and sources | Where Money Moves", "How Where Money Moves measures people, jobs, businesses and money across Southeast Asia.",
                          body, meta, crumbs=[("Southeast Asia", "/"), ("Method", "/about/")]))

    # ── search index, manifest, sw, sitemap, 404
    idx = ([{"n": r["name"], "a": r["native"], "u": U(c_url(r)), "k": "Country"} for r in Rv]
           + [{"n": t["name"], "a": t["native"], "u": U(p_url(t)), "k": "Province"} for t in T.values()]
           + [{"n": d["name_en"], "a": f'{d["name_th"]}  {T[d["prov"]]["name"]}', "u": U(d_url(d)), "k": "District"} for d in D]
           + [{"n": v["name"], "a": v["native"], "u": U(v_url(v)), "k": "Province"} for v in V.values()]
           + [{"n": f, "a": f"now part of {v['name']}", "u": U(v_url(v)), "k": "Former province"}
              for v in V.values() if len(v["former"]) > 1 for f in v["former"] if f != v["native"]]
           + [{"n": t, "a": "", "u": U(p), "k": "Ranking"} for p, t, _ in rk_index])
    (OUT / "assets" / "search.json").write_text(json.dumps(idx, ensure_ascii=False, separators=(",", ":")))
    (OUT / "manifest.webmanifest").write_text(json.dumps({
        "name": "Where Money Moves", "short_name": "Money Moves", "lang": "en", "start_url": U("/?source=pwa"),
        "scope": U("/"), "display": "standalone", "background_color": "#f6f7f4", "theme_color": "#0f1720",
        "description": "Where people, jobs, businesses and money are moving across Southeast Asia.",
        "icons": [{"src": U("/assets/icon-192.png"), "sizes": "192x192", "type": "image/png"},
                  {"src": U("/assets/icon-512.png"), "sizes": "512x512", "type": "image/png", "purpose": "any maskable"}],
    }, indent=1))
    (OUT / "sw.js").write_text((STATIC / "sw.js").read_text().replace("__BUILD__", meta["build_id"]).replace("__BASE__", BASE))
    (OUT / "404.html").write_text(page(U("/404/"), "Page not found | Where Money Moves", "Page not found.",
                                       f'<section class="hero"><h1>That page isn’t here</h1><p class="lede">It may have moved when the site went English-only. Search with <kbd>/</kbd>, or start from <a href="{U("/")}">Southeast Asia</a> or <a href="{U("/thailand/")}">Thailand</a>.</p></section>', meta))
    (OUT / "robots.txt").write_text(f"User-agent: *\nAllow: /\nSitemap: {SITE_URL}{U('/sitemap.xml')}\n")
    (OUT / "sitemap.xml").write_text('<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
                                     + "".join(f"<url><loc>{SITE_URL}{U(p)}</loc><lastmod>{meta['built']}</lastmod></url>\n" for p in pages) + "</urlset>\n")
    size = sum(f.stat().st_size for f in OUT.rglob("*") if f.is_file())
    print(f"site/  {len(pages)} pages  {size/1e6:.1f}MB  region 11 · provinces {len(T)} · districts {len(D)}")


if __name__ == "__main__":
    main()
