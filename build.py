"""
Where Money Moves — static site generator (English only).

  python build.py                     # data/processed/*.json → site/
  BASE_PATH=/repo SITE_URL=https://… python build.py   # for hosting under a sub-path

"See where people, jobs, businesses and money are moving across Southeast Asia."

Layers, never mixed on one axis:
  · Region    — 11 countries, World Bank (comparable definitions)
  · Thailand  — 77 provinces × 4 lenses (DOPA, SSO, SSO-as-proxy, BOT) and 264 districts (BOT money)
  · Vietnam   — 34 provinces (2025 boundaries) × 4 lenses (NSO)
  · Malaysia  — 16 states and federal territories × 3 lenses (DOSM; no open state series for businesses), 166 districts
  · Philippines — 83 provinces (HUCs added to the province around them, Metro Manila as one) × 2 lenses (PSA)

Pages: /, /country/{c}/, /thailand/…, /vietnam/…, /malaysia/…, /philippines/…, /rankings/…, /film/, /compare/, /about/, 404.
Every page reads fully without JS. JS adds lens switching, tooltips, command palette, watchlist,
compare, toasts, theme, share and install. Standard library only, so Vercel / Actions can run it as-is.
"""

from __future__ import annotations

import csv
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
ON = ' class="on"'      # the highlighted place on a locator map (quoted: an unquoted on/> reads as 'on/')
# "no data" fill. Defined once per page in the shell (not per map), so pages with several maps have one #hatch.
# "Shrinking" is a texture on top of the colour, because colour is rank and a place can rank high while it shrinks
# (most Thai provinces lose people). One pattern per ramp step: the step's own fill, cut by thin paper-coloured lines
# at the other diagonal from #hatch, so stripes never read as "no data".
HATCH = ('<defs><pattern id="hatch" width="5" height="5" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">'
         '<rect width="5" height="5" class="hb"/><line x1="0" y1="0" x2="0" y2="5" class="hl"/></pattern>'
         + "".join(f'<pattern id="ebb{b}" width="4" height="4" patternUnits="userSpaceOnUse" patternTransform="rotate(-45)">'
                   f'<rect width="4" height="4" style="fill:var(--s{b})"/><line x1="0" y1="0" x2="0" y2="4" class="el"/></pattern>'
                   for b in range(1, 8))
         + '</defs>')



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


def strip(points, mine, caption) -> str:
    """Where one place sits among its whole layer, on the lens's own scale: every other place a grey dot, this one in
    ink. Dots that would overlap stack outwards from the centre line (a beeswarm), so close values never hide each
    other. Only the extremes and zero are labelled; app.js gives the nearest dot a tooltip."""
    pts = [(n, v) for n, v in points if v is not None]
    me = next((v for n, v in pts if n == mine), None)
    if len(pts) < 3 or me is None:
        return ""
    W, L, R, r, d = 420, 10, 10, 4, 9.5                 # r ≥ 4: an 8px marker; d: centre spacing with a 1.5px gap
    lo, hi = min(v for _, v in pts), max(v for _, v in pts)
    X = lambda v: L + (v - lo) / ((hi - lo) or 1) * (W - L - R)
    placed = [(X(me), 0.0)]                              # this place sits on the centre line; the rest dodge around it
    dots = []
    for n, v in sorted(((n, v) for n, v in pts if n != mine), key=lambda p: abs(p[1] - me)):
        x = X(v)
        for k in range(60):
            y = ((k + 1) // 2) * d * (1 if k % 2 else -1)
            if all((x - px) ** 2 + (y - py) ** 2 >= d * d for px, py in placed):
                break
        placed.append((x, y))
        dots.append((n, v, x, y))
    # a tight cluster would stack into a tower: past five rows each side, squeeze the stack (the rings keep dots apart)
    tallest = max(abs(y) for _, y in placed)
    if tallest > 5 * d:
        dots = [(n, v, x, y * 5 * d / tallest) for n, v, x, y in dots]
        tallest = 5 * d
    reach = tallest + r + 3
    mid, H = reach, 2 * reach + 18
    zero = (f'<line class="zero" x1="{X(0):.1f}" x2="{X(0):.1f}" y1="2" y2="{H - 16:.1f}"/>'
            f'<text x="{X(0):.1f}" y="{H - 3:.1f}" text-anchor="middle">0</text>') if lo < 0 < hi and 56 < X(0) < W - 56 else ""
    marks = "".join(f'<circle class="o" cx="{x:.1f}" cy="{mid + y:.1f}" r="{r}" data-n="{esc(n)}" data-v="{esc(pct(v))}"/>'
                    for n, v, x, y in dots)
    return (f'<figure class="strip"><figcaption>{esc(caption)}</figcaption>'
            f'<svg viewBox="0 0 {W} {H:.0f}" role="img" aria-label="{esc(f"{mine} {pct(me)}. {caption}: lowest {pct(lo)}, highest {pct(hi)}")}">'
            f'<line class="axis" x1="{L}" x2="{W - R}" y1="{mid:.1f}" y2="{mid:.1f}"/>{zero}{marks}'
            f'<circle class="me" cx="{X(me):.1f}" cy="{mid:.1f}" r="6" data-n="{esc(mine)}" data-v="{esc(pct(me))}"/>'
            f'<text x="{L}" y="{H - 3:.1f}">{esc(pct(lo))}</text><text x="{W - R}" y="{H - 3:.1f}" text-anchor="end">{esc(pct(hi))}</text>'
            f'</svg></figure>')


def growth_series(levels, lag=1, keep=None):
    """[(period, level)] → {period: growth on the period `lag` steps earlier}; `keep` thins a long series to every
    nth period counted back from the latest, so monthly data reads as quarters."""
    pts = [(p_, v) for p_, v in levels if v is not None]
    out = {pts[i][0]: growth(pts[i][1], pts[i - lag][1]) for i in range(lag, len(pts))}
    out = {k: v for k, v in out.items() if v is not None}
    if keep:
        ks = sorted(out)
        out = {k: out[k] for k in ks[::-1][::keep]}
    return out


def rank_chart(by_unit, mine, caption, label=str, recent=10) -> str:
    """How one place's rank on a lens has moved, among its whole layer: every place a faint line (rank 1 at the top),
    this one in current-teal with its latest rank at the end. Ranks are recomputed each period among the places with a
    figure that period. app.js reads data-pts for the tooltip."""
    periods = sorted({p_ for ser in by_unit.values() for p_ in ser})[-recent:]
    if mine not in by_unit or len(periods) < 3:
        return ""
    ranks = {u: {} for u in by_unit}
    count = {}
    for p_ in periods:
        have = sorted((u for u in by_unit if p_ in by_unit[u]), key=lambda u: -by_unit[u][p_])
        count[p_] = len(have)
        for i, u in enumerate(have, 1):
            ranks[u][p_] = i
    mp = [p_ for p_ in periods if p_ in ranks[mine]]
    if len(mp) < 3:
        return ""
    W, H, L, R, T, B = 420, 190, 40, 44, 14, 26
    n = max(count.values())
    xs = lambda i: L + i * (W - L - R) / (len(periods) - 1)
    ys = lambda rk: T + (rk - 1) / max(1, n - 1) * (H - T - B)
    def line(u, cls):
        d, prev = "", False
        for i, p_ in enumerate(periods):
            rk = ranks[u].get(p_)
            if rk is None:
                prev = False
                continue
            d += ("L" if prev else "M") + f"{xs(i):.1f},{ys(rk):.1f}"
            prev = True
        return f'<path class="{cls}" d="{d}"/>' if d.count("L") else ""
    rest = "".join(line(u, "o") for u in by_unit if u != mine)
    last_i = max(i for i, p_ in enumerate(periods) if p_ in ranks[mine])
    last_rk = ranks[mine][periods[last_i]]
    every = max(1, len(periods) // 4)
    last = len(periods) - 1
    ticks = "".join(f'<text x="{xs(i):.1f}" y="{H - 6}" text-anchor="middle">{esc(label(p_))}</text>'
                    for i, p_ in enumerate(periods) if i == last or (i % every == 0 and last - i >= max(2, every * 0.75)))
    pts = [[label(p_), ranks[mine][p_], count[p_]] for p_ in periods if p_ in ranks[mine]]
    first_rk = ranks[mine][mp[0]]
    return (f'<figure class="rankh"><figcaption>{esc(caption)}</figcaption>'
            f'<svg viewBox="0 0 {W} {H}" role="img" data-pts=\'{esc(json.dumps(pts))}\' data-x="{",".join(f"{xs(i):.1f}" for i, p_ in enumerate(periods) if p_ in ranks[mine])}" '
            f'aria-label="{esc(f"{mine}: ranked {ordinal(first_rk)} in {label(mp[0])}, {ordinal(last_rk)} in {label(mp[-1])}, of {count[mp[-1]]}")}">'
            f'<g class="grid"><line x1="{L}" x2="{W - R}" y1="{ys(1):.1f}" y2="{ys(1):.1f}"/><line x1="{L}" x2="{W - R}" y1="{ys(n):.1f}" y2="{ys(n):.1f}"/>'
            f'<text x="{L - 8}" y="{ys(1) + 4:.1f}" text-anchor="end">1st</text><text x="{L - 8}" y="{ys(n) + 4:.1f}" text-anchor="end">{n}th</text></g>'
            f'<g class="ticks">{ticks}</g><g class="rest">{rest}</g>{line(mine, "me")}'
            f'<circle class="end" cx="{xs(last_i):.1f}" cy="{ys(last_rk):.1f}" r="4.5"/>'
            f'<text class="endl" x="{xs(last_i) + 9:.1f}" y="{ys(last_rk) + 4:.1f}">#{last_rk}</text></svg></figure>')


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
_MY = Proj(99.4, 7.6, 60.0, 4.0)
MY_EAST, MY_SHIFT = 108.0, 3.6     # East Malaysia (Sarawak, Sabah, Labuan) is drawn 3.6° closer to the peninsula: an inset


PH_PROJ = Proj(116.6, 21.4, 40.0, 12.0)


def MY_PROJ(lon, lat):
    return _MY(lon - MY_SHIFT if lon > MY_EAST else lon, lat)
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
    my = json.load(open(DATA / "my_dosm.json"))
    mgeo = json.load(open(REF / "my.geo.json"))
    ph = json.load(open(DATA / "ph_psa.json"))
    pgeo = json.load(open(REF / "ph.geo.json"))
    return meta, D, P, sso, dopa, wb, ctx, geo, vn, vgeo, my, mgeo, ph, pgeo


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


MY_DESC = {  # what each lens measures inside Malaysia (OpenDOSM, 16 states and federal territories)
    "people": "Population growth",
    "jobs": "Employed persons growth, same quarter a year earlier",
    "biz": "No open state series yet",
    "money": "Real GDP growth (constant 2015 prices)",
}


def qlabel(q: str) -> str:
    """'2026-Q2' → 'Q2 2026'"""
    return f"{q[5:]} {q[:4]}"


def malaysia_model(my):
    """16 states and federal territories. Businesses has no open state series, so that lens stays empty (never zero)
    and Momentum averages the other three."""
    M = {}
    for slug_, s in my["states"].items():
        S = s["series"]
        pop = {int(y): v for y, v in S["pop"].items()}
        gdp = {int(y): v for y, v in S["gdp"].items()}
        emp = S["employed"]
        y, g, q = max(pop), max(gdp), max(emp)
        q0 = f"{int(q[:4]) - 1}{q[4:]}"
        r = {"id": slug_, "slug": slug_, "name": s["name"], "native": s["native"],
             "people": growth(pop[y], pop.get(y - 1)), "people_5y": growth(pop[y], pop.get(y - 5)), "pop": pop[y] * 1000,
             "jobs": growth(emp[q], emp.get(q0)), "employed": emp[q] * 1000,
             "u_rate": S["u_rate"][q], "u_rate_prev": S["u_rate"].get(q0), "p_rate": S["p_rate"][q],
             "biz": None,
             "money": growth(gdp[g], gdp.get(g - 1)), "gdp": gdp[g], "gdp_5y": growth(gdp[g], gdp.get(g - 5)),
             "gdp_pc": gdp[g] * 1e6 / (pop[g] * 1000) if g in pop else None,
             "pop_series": sorted(pop.items()), "emp_series": sorted(emp.items()), "gdp_series": sorted(gdp.items()),
             "sectors": {c: growth(v.get(str(g)), v.get(str(g - 1))) for c, v in s["sectors"].items()},
             "sector_share": {c: (v.get(str(g)) or 0) / gdp[g] for c, v in s["sectors"].items()},
             "districts": []}
        inc = {int(y): v for y, v in S.get("income_median", {}).items()}
        hy = max(inc) if inc else None
        r["income"], r["income_year"] = (inc[hy], hy) if hy else (None, None)
        r["income_growth"] = growth(inc.get(hy), inc.get(hy - 2)) if hy else None
        for d in s["districts"]:
            dp = {int(k): v for k, v in d["pop"].items()}
            de = {int(k): v for k, v in d["employed"].items()}
            dy, ey = max(dp), max(de) if de else None
            hi = {int(k): v for k, v in d.get("income_median", {}).items()}
            hp = {int(k): v for k, v in d.get("poverty", {}).items()}
            iy = max(hi) if hi else None
            hies = {"income": hi.get(iy), "income_growth": growth(hi.get(iy), hi.get(iy - 2)) if iy else None,
                    "poverty": hp.get(iy), "poverty_change": (hp[iy] - hp[iy - 2]) if iy and iy in hp and iy - 2 in hp else None,
                    "gini": d.get("gini", {}).get(str(iy)) if iy else None, "income_year": iy}
            r["districts"].append({**hies, "name": d["name"], "pop": dp[dy] * 1000, "people": growth(dp[dy], dp.get(dy - 1)),
                                   "people_5y": growth(dp[dy], dp.get(dy - 5)),
                                   "employed": de[ey] * 1000 if ey else None, "jobs": growth(de[ey], de.get(ey - 1)) if ey else None,
                                   "u_rate": d["u_rate"].get(str(ey)) if ey else None, "pop_year": dy, "emp_year": ey})
        M[slug_] = r
    score_lenses(M, ["people", "jobs", "biz", "money"])
    label = {"people": (f"{y - 1} to {y} (estimates)", y), "jobs": (f"{qlabel(q0)} to {qlabel(q)}", qlabel(q)),
             "biz": ("no open state series", None), "money": (f"{g - 1} to {g}", g)}
    years = {"district_pop": max(d["pop_year"] for m in M.values() for d in m["districts"]),
             "district_emp": max((d["emp_year"] for m in M.values() for d in m["districts"] if d["emp_year"]), default=None),
             "district_income": max((d["income_year"] for m in M.values() for d in m["districts"] if d["income_year"]), default=None)}
    return M, label, years


PH_DESC = {  # what each lens measures inside the Philippines (PSA, provinces with their HUCs)
    "people": "Population growth a year, between the 2020 and 2024 censuses",
    "jobs": "No province series (the labour survey is national)",
    "biz": "No province series",
    "money": "Real GDP growth (constant 2018 prices)",
}


def philippines_model(ph):
    """83 units: provinces with the highly urbanized cities inside them, Metro Manila, Isabela City. Two lenses."""
    yrs = ph["census_years"]
    out = {}
    for slug_, p in ph["provinces"].items():
        S = p["series"]
        g = {int(y): v * 1000 for y, v in S["gdp_real"].items()}
        gn = {int(y): v * 1000 for y, v in S["gdp_nominal"].items()}
        Y = max(g)
        p20, p24 = S["pop2020"], S["pop2024"]
        r = {"id": slug_, "slug": slug_, "name": p["name"], "native": "", "region": p["region"],
             "people": (p24 / p20) ** (1 / yrs) - 1, "people_total": growth(p24, p20), "pop": p24, "pop2020": p20,
             "jobs": None, "biz": None,
             "money": growth(g[Y], g.get(Y - 1)), "gdp_real": g[Y], "gdp_nominal": gn[Y], "gdp_5y": growth(g[Y], g.get(Y - 5)),
             "gdp_pc": gn[Y] / p24, "gdp_series": sorted(g.items()), "parts": []}
        for name, d in p["parts"].items():
            dg = {int(y): v for y, v in d.get("gdp_real", {}).items()}
            dn = {int(y): v for y, v in d.get("gdp_nominal", {}).items()}
            r["parts"].append({"name": name, "pop": d.get("pop2024"),
                               "people": (d["pop2024"] / d["pop2020"]) ** (1 / yrs) - 1 if d.get("pop2020") and d.get("pop2024") else None,
                               "money": growth(dg.get(Y), dg.get(Y - 1)), "share": (dn.get(Y) or 0) * 1000 / gn[Y]})
        out[slug_] = r
    score_lenses(out, ["people", "jobs", "biz", "money"])
    label = {"people": ("2020 to 2024 censuses, a year", 2024), "jobs": ("no province series", None),
             "biz": ("no province series", None), "money": (f"{Y - 1} to {Y}", Y)}
    return out, label


# ── plain-English summaries ──────────────────────────────────────────────
# Every detail page opens with two or three sentences computed from its own numbers: where it is strongest,
# where it is weakest, and one fact particular to it. Same data as the panels, said once in words.

PHRASE = {
    "region": {"people": "urban population growth", "jobs": "employment growth", "biz": "new firm registrations", "money": "real GDP growth"},
    "th": {"people": "registered population growth", "jobs": "formal job growth", "biz": "growth in registered employers", "money": "bank deposit growth"},
    "vn": {"people": "population growth", "jobs": "job growth", "biz": "new business registrations", "money": "enterprise revenue growth"},
    "my": {"people": "population growth", "jobs": "job growth", "biz": "business growth", "money": "real GDP growth"},
    "ph": {"people": "population growth", "jobs": "job growth", "biz": "business growth", "money": "real GDP growth"},
}


def ordinal(n: int) -> str:
    return f"{n}{'th' if 10 <= n % 100 <= 20 else {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th')}"


def brief(r, layer: str, n: int, group: str, extra: str = "") -> str:
    """'Chon Buri ranks 2nd of 77 Thai provinces on momentum. It is strongest on …, and weakest on ….' + extra"""
    ranks = [(k, r[k + "_rank"]) for k in ("people", "jobs", "biz", "money") if r.get(k) is not None and r.get(k + "_rank")]
    out = []
    if r.get("rank"):
        out.append(f"{r['name']} ranks {ordinal(r['rank'])} of {n} {group} on momentum.")
    if ranks:
        best = min(ranks, key=lambda x: x[1])
        worst = max(ranks, key=lambda x: x[1])
        ph = PHRASE[layer]
        lo, hi = n * 0.25, n * 0.75
        if len(ranks) > 1 and worst[1] <= lo:
            out.append(f"It is in the top quarter on every lens; even its weakest, {ph[worst[0]]} ({pct(r[worst[0]])}), ranks {ordinal(worst[1])}.")
        elif len(ranks) > 1 and best[1] > hi:
            out.append(f"It is in the bottom quarter on every lens; its strongest, {ph[best[0]]} ({pct(r[best[0]])}), ranks {ordinal(best[1])}.")
        elif worst[0] != best[0]:
            out.append(f"Its strongest lens is {ph[best[0]]} ({pct(r[best[0]])}, {ordinal(best[1])}); "
                       f"its weakest is {ph[worst[0]]} ({pct(r[worst[0]])}, {ordinal(worst[1])}).")
        else:
            out.append(f"Its one ranked lens is {ph[best[0]]} ({pct(r[best[0]])}, {ordinal(best[1])}).")
    if extra:
        out.append(extra)
    return " ".join(out)


def first_sentences(text: str, limit: int = 190) -> str:
    """Meta description: whole sentences up to ~190 characters (search engines cut at ~160; two sentences read better)."""
    out = ""
    for sent in re.split(r"(?<=\.)\s+", text):
        if len(out) + len(sent) + 1 > limit and out:
            break
        out = f"{out} {sent}".strip()
    return out


# ── page shell ───────────────────────────────────────────────────────────

def icon(k, cls="ic"):
    return f'<svg class="{cls}" viewBox="0 0 24 24" aria-hidden="true">{ICON[k]}</svg>'


def native(s, lang="th"):
    return f'<span class="native" lang="{lang}">{esc(s)}</span>' if s else ""


# Khmer, Lao and Burmese appear only in three country names: load just those glyphs
NATIVE_GLYPHS = urllib.parse.quote("".join(sorted(set("កម្ពុជាລາວမြန်မာ"))))
NATIVE_LANG = {"THA": "th", "KHM": "km", "LAO": "lo", "MMR": "my", "VNM": "vi", "IDN": "id", "MYS": "ms",
               "PHL": "fil", "SGP": "ms", "BRN": "ms", "TLS": "pt"}


CARDS: dict[str, dict] = {}   # page path → what its share image shows (registered before page(); page() fills the rest)


def og_key(path: str) -> str:
    p = path[len(BASE):] if BASE and path.startswith(BASE) else path
    return p.strip("/").replace("/", "--") or "home"


def page(path, title, desc, body, meta, crumbs=None, watch=None, extra_head="") -> str:
    canonical = SITE_URL + path
    card = CARDS.setdefault(path, {})
    card.setdefault("title", title.split(" | ")[0])
    card.setdefault("line", desc)
    card.setdefault("map", "sea")
    card["key"] = og_key(path)
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
<meta property="og:image" content="{SITE_URL}{U('/og/' + card['key'] + '.png')}">
<meta property="og:image:width" content="1200">
<meta property="og:image:height" content="630">
<meta name="twitter:card" content="summary_large_image">
<meta name="theme-color" content="#f6f7f4" media="(prefers-color-scheme: light)">
<meta name="theme-color" content="#0f1720" media="(prefers-color-scheme: dark)">
<script>try{{var t=localStorage.getItem("wmm-theme");if(t)document.documentElement.dataset.theme=t}}catch(e){{}}</script>
<link rel="manifest" href="{U('/manifest.webmanifest')}">
<link rel="icon" href="{U('/assets/icon.svg')}" type="image/svg+xml">
<link rel="apple-touch-icon" href="{U('/assets/icon-192.png')}">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Bricolage+Grotesque:opsz,wght@12..96,700..750&family=Inter:wght@400..700&family=Noto+Sans+Thai:wght@400;500&display=swap">
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Noto+Sans+Khmer&family=Noto+Sans+Lao&family=Noto+Sans+Myanmar&text={NATIVE_GLYPHS}&display=swap">
<link rel="stylesheet" href="{U('/assets/app.css')}?v={v}">
<script type="speculationrules">{{"prerender":[{{"where":{{"href_matches":"{BASE}/*"}},"eagerness":"moderate"}}]}}</script>
{extra_head}{ld}
</head>
<body>
<svg width="0" height="0" style="position:absolute" aria-hidden="true" focusable="false">{HATCH}</svg>
<div class="progress" aria-hidden="true"></div>
<a class="skip" href="#main">Skip to content</a>
<header class="top">
  <a class="brand" href="{U('/')}"><img src="{U('/assets/icon.svg')}" alt="" width="26" height="26"><span>Where Money Moves</span></a>
  <nav class="nav" aria-label="Main">
    <a href="{U('/thailand/')}">Thailand</a>
    <a href="{U('/vietnam/')}">Vietnam</a>
    <a href="{U('/malaysia/')}">Malaysia</a>
    <a href="{U('/philippines/')}">Philippines</a>
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
    <p>Sources: World Bank WDI (CC BY 4.0). Thailand: Bank of Thailand district deposits and credit, Social Security Office, Department of Provincial Administration (Open Data Common). Vietnam: National Statistics Office (PX-Web). Malaysia: Department of Statistics, OpenDOSM (CC BY 4.0). Philippines: Philippine Statistics Authority (OpenSTAT). Boundaries: Natural Earth, geoBoundaries/OCHA, Government of Viet Nam, UNHCR and NAMRIA/PSA via HDX (CC BY 3.0 IGO), thailand-canonical-admin-names (CC BY 4.0).</p>
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
    # a group of toggle buttons: they recolour the map and reorder the list beside it, they don't swap panels
    return (f'<div class="lenses" role="group" aria-label="{esc(label)}">'
            + "".join(f'<button type="button" data-lens="{k}" aria-pressed="{str(k == default).lower()}">{icon(k)}<span>{esc(lab)}</span></button>'
                      for k, lab in items)
            + '<span class="lens-ink" aria-hidden="true"></span></div>')


def legend(layer):
    sw = "".join(f'<i class="s{i}"></i>' for i in range(1, 8))
    return (f'<div class="legend" data-lens="score"><span>Slower</span><span class="ramp">{sw}</span><span>Faster</span>'
            f'<span class="dn"><i></i>Striped: shrinking</span>'
            f'<span class="nd"><i></i>No data</span><span class="note">Colour is rank within {esc(layer)}</span></div>')


def lens_attrs(r, keys):
    """Colour bin per lens (data-b-*, used by CSS) and percentile rank per lens (data-p-*, used as height in 3D)."""
    a = [f'data-b-score="{bin7(r.get("score"))}"']
    if r.get("score") is not None:
        a.append(f'data-p-score="{r["score"]:.1f}"')
    for k in keys:
        a.append(f'data-b-{k}="{bin7(r.get(k + "_pct"))}"')
        if r.get(k) is not None and r[k] < 0:
            a.append(f"data-d-{k}")
        if r.get(k + "_pct") is not None:
            a.append(f'data-p-{k}="{r[k + "_pct"]:.1f}"')
    return " ".join(a)


def view_toggle():
    """2D/3D switch. The 3D view (assets/map3d.js + three.js) loads only when pressed."""
    return ('<div class="views" role="group" aria-label="Map view">'
            '<button type="button" data-view="2d" aria-pressed="true">2D</button>'
            '<button type="button" data-view="3d" aria-pressed="false">3D</button></div>')


def import_map():
    v = "/assets/vendor/three@0.169.0/"
    return ('<script type="importmap">' + json.dumps({"imports": {"three": U(v + "three.module.min.js"),
                                                                   "three/addons/": U(v + "addons/")}}) + "</script>")


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


def with_strips(panels: str, strips: dict) -> str:
    """Put each lens's where-it-sits strip under its headline number."""
    for k, html_ in strips.items():
        at = panels.find(f'data-k="{k}"')
        end = panels.find("</p>", at) + 4 if at >= 0 else -1
        if html_ and end > 3:
            panels = panels[:end] + html_ + panels[end:]
    return panels


def tone_from(s: str) -> str:
    return "up" if s.startswith("+") else ("down" if s.startswith("−") else "")


# ── build ────────────────────────────────────────────────────────────────

def main():
    meta, D, P, sso, dopa, wb, ctx, geo, vn, vgeo, my, mgeo, ph, pgeo = load()
    meta["build_id"] = meta["generated_at"][:19].replace(":", "").replace("-", "")
    meta["built"] = meta["generated_at"][:10]
    latest, y1 = meta["latest"], meta["yoy_base"]
    R = region_model(wb)
    T, by_prov = thailand_model(P, D, sso, dopa, ctx)
    # registered population for every district (928), from DOPA's province files split by registry (etl/th_dopa.py)
    dy = dopa["years"]
    DP = {}
    for row in csv.DictReader(open(REF / "thailand-adm2-districts-v1.0.0.csv", encoding="utf-8")):
        ser = {int(y): v for y, v in dopa.get("districts", {}).get(row["tis1099_district_code"], {}).items() if v is not None}
        last = dy[-1] if dy[-1] in ser else None
        DP[row["tis1099_district_code"]] = {
            "id": row["tis1099_district_code"], "prov": row["parent_province_tis1099_code"], "name_en": row["name_en"], "name_th": row["name_th"],
            "pop": ser.get(last), "people": growth(ser.get(last), ser.get(dy[-2])) if last else None,
            "people_5y": growth(ser.get(last), ser.get(dy[0])) if last else None, "series": sorted(ser.items())}
    for i, x in enumerate(sorted([x for x in DP.values() if x["people"] is not None], key=lambda x: -x["people"]), 1):
        x["people_rank"] = i
    nDP = sum(1 for x in DP.values() if x["people"] is not None)
    page_of = {d["id"]: d for d in D}
    V, vlab = vietnam_model(vn)
    M, mlab, myears = malaysia_model(my)
    H, hlab = philippines_model(ph)

    # ── growth per period, per place, per lens: rank histories on detail pages, "the period before" on Compare
    def prov_money(ds):
        """Province deposits, year on year each month, over the districts reported in both months; every 3rd month
        counted back from the latest bank month, the same calendar for every province."""
        by_m = {}
        for d in ds:
            for row in d["series"]:
                if row[1] is not None:
                    by_m.setdefault(row[0], {})[d["id"]] = row[1]
        ms = sorted(by_m)
        out = {}
        for i in range(12, len(ms)):
            a, b = by_m[ms[i]], by_m[ms[i - 12]]
            both = [k for k in a if k in b]
            if both:
                out[ms[i]] = sum(a[k] for k in both) / sum(b[k] for k in both) - 1
        ly, lm = (int(x) for x in latest.split("-"))
        return {k: g for k, g in out.items() if ((ly - int(k[:4])) * 12 + lm - int(k[5:])) % 3 == 0}
    lens_keys = [k for k, *_ in LENSES]
    GR = {
        "region": {k: {r["name"]: growth_series(r["series"][k]) for r in R.values()} for k in lens_keys},
        "th": {"people": {t["name"]: growth_series(t["pop_series"]) for t in T.values()},
               "jobs": {t["name"]: growth_series(t["ins_series"]) for t in T.values()},
               "biz": {t["name"]: growth_series(t["ent_series"]) for t in T.values()},
               "money": {t["name"]: prov_money(by_prov.get(tis, [])) for tis, t in T.items()}},
        "vn": {k: {v["name"]: growth_series(v["series"][k]) for v in V.values()} for k in lens_keys},
        "my": {"people": {m["name"]: {y: g for y, g in growth_series(m["pop_series"]).items() if y >= 2021} for m in M.values()},
               "jobs": {m["name"]: growth_series(m["emp_series"], lag=4) for m in M.values()},
               "money": {m["name"]: growth_series(m["gdp_series"]) for m in M.values()}},
        "ph": {"money": {h["name"]: growth_series(h["gdp_series"]) for h in H.values()}},
    }
    PERIOD_LABEL = {"th": {"money": month_label}, "my": {"jobs": qlabel}}

    def rank_section(layer, name, group, keys):
        figs = "".join(rank_chart({u: ser for u, ser in GR[layer][k].items() if ser}, name,
                                  f"{LENS[k][0]}: rank among {group}", PERIOD_LABEL.get(layer, {}).get(k, str))
                       for k in keys if k in GR[layer])
        return (f'<section class="rank-history reveal"><h2>How its rank has moved</h2>'
                f'<p class="sub">Each lens re-ranked every period among the places with a figure. Faint lines are the rest.</p>'
                f'<div class="rankh-grid">{figs}</div></section>') if figs else ""

    def before(layer, k, name):
        """The growth a year before the latest (same month or quarter for sub-yearly series) and its label, for Compare."""
        ser = GR.get(layer, {}).get(k, {}).get(name) or {}
        if not ser:
            return None, ""
        last = max(ser)
        prev = last - 1 if isinstance(last, int) else f"{int(last[:4]) - 1}{last[4:]}"
        if prev not in ser:
            return None, ""
        return ser[prev], PERIOD_LABEL.get(layer, {}).get(k, str)(prev)

    def h_url(h):
        return f"/philippines/{h['slug']}/"

    def v_url(v):
        return f"/vietnam/{v['slug']}/"

    def m_url(m):
        return f"/malaysia/{m['slug']}/"

    def card(path, kicker, name, native_, rank, stats, map_, hl=None):
        """What the share image for `path` shows (tools/og_images.mjs draws it from og/og-data.json)."""
        CARDS[U(path)] = {"kicker": kicker, "title": name, "native": native_ or "", "rank": rank,
                          "stats": [s_ for s_ in stats if s_[1] not in (None, "–")][:4], "map": map_, "hl": hl}

    def lens_stats(r, keys=None):
        return [[LENS[k][0], pct(r.get(k)), tone(r.get(k))] for k in (keys or [k for k, *_ in LENSES])]
    Pm = {p["id"]: p for p in P}
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
    shutil.copytree(STATIC / "vendor", OUT / "assets" / "vendor")       # three.js (MIT), for the 3D view only

    # map colour rules are generated: one per lens × bin
    rules = []
    for lens in ["score"] + lens_keys:
        for b in range(1, 8):
            rules.append(f'.map[data-lens="{lens}"] [data-b-{lens}="{b}"]{{fill:var(--s{b})}}')
        rules.append(f'.map[data-lens="{lens}"] [data-b-{lens}="n"]{{fill:url(#hatch)}}')
        if lens != "score":                     # Momentum is a rank, it has no sign
            rules += [f'.map[data-lens="{lens}"] [data-b-{lens}="{b}"][data-d-{lens}]{{fill:url(#ebb{b})}}' for b in range(1, 8)]
    (OUT / "assets" / "app.css").write_text((STATIC / "app.css").read_text() + "\n/* generated */\n" + "\n".join(rules) + "\n")

    pages = []

    def write(path, content):
        fp = OUT / path.lstrip("/") / "index.html"
        fp.parent.mkdir(parents=True, exist_ok=True)
        fp.write_text(content, encoding="utf-8")
        pages.append(path)


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
            # the interactive map keeps ~0.4px detail; the thumbnail on country pages needs far less
            if not f["sea"]:                    # neighbours are backdrop only: coarse is fine
                ctx_paths += f'<path d="{path_d(rings, tol=1.6, min_len=4.0)}"/>'
                continue
            d = path_d(rings, tol=0.5, min_len=1.0) if interactive else path_d(rings, tol=1.4, min_len=3.0)
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
                shapes += f'<g data-k="{f["iso3"]}"{cls}>{body}</g>'
            lx, ly = SEA_PROJ(*LABEL_AT[f["iso3"]]) if f["iso3"] in LABEL_AT else (cx, cy)
            labels += f'<text x="{lx:.1f}" y="{ly + 4:.1f}" text-anchor="middle">{esc(r["name"])}</text>'
        return (f'<svg class="map sea" data-lens="score" viewBox="0 0 {W:.0f} {H:.0f}" role="group" aria-label="Map of Southeast Asia">'
                f'<rect class="sea-bg" width="{W:.0f}" height="{H:.0f}"/><g class="grat">{grat}</g><g class="ctx">{ctx_paths}</g>'
                f'<g class="units">{shapes}</g><g class="labels" aria-hidden="true">{labels}</g><g class="coords" aria-hidden="true">{ticks}</g></svg>')

    def pin(rings, limit=26):
        """A ring around a highlighted place too small to see on a locator map (Bangkok, Metro Manila, Putrajaya)."""
        pts = [pt for r in rings for pt in r]
        x0, x1 = min(x for x, _ in pts), max(x for x, _ in pts)
        y0, y1 = min(y for _, y in pts), max(y for _, y in pts)
        if max(x1 - x0, y1 - y0) > limit:
            return ""
        return f'<circle class="pin" cx="{(x0 + x1) / 2:.1f}" cy="{(y0 + y1) / 2:.1f}" r="{max(x1 - x0, y1 - y0) / 2 + 9:.1f}"/>'

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
                shapes += f'<path data-k="{tis}" d="{th_mini[tis]}"{ON if highlight == tis else ""}/>'
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
            ring = pin(th_rings[highlight]) if highlight in th_rings else ""
            return f'<svg class="map mini" viewBox="0 0 {TW:.0f} {TH:.0f}" aria-hidden="true"><g>{shapes}</g><g class="dots">{dots}</g>{ring}</svg>'
        return (f'<svg class="map th" data-lens="score" viewBox="0 0 {TW:.0f} {TH:.0f}" role="group" aria-label="Map of Thailand by province">'
                f'<g class="units">{shapes}</g></svg>')

    # Vietnam: 34 provinces drawn from 63 old shapes. Fills carry no stroke; outlines and former borders are
    # separate layers built from shared TopoJSON arcs (etl/vn_geo.py), so merged provinces show no seam.
    vn_rings = {k: [[VN_PROJ(x, y) for x, y in r] for r in rs] for k, rs in vgeo["provinces"].items()}
    vn_full = {k: path_d(v, tol=0.6, min_len=2.0) for k, v in vn_rings.items()}
    vn_mini = {k: path_d(v, tol=1.0, min_len=2.0) for k, v in vn_rings.items()}

    def vn_line(arcs, min_extent=0.0, tol=0.6):
        """Open polylines (outline / former borders), simplified per arc so neighbours still meet."""
        out = []
        for a in arcs:
            pts = simplify([VN_PROJ(*pt) for pt in a], tol)
            xs, ys = [p[0] for p in pts], [p[1] for p in pts]
            if len(pts) > 1 and (max(xs) - min(xs)) + (max(ys) - min(ys)) >= min_extent:
                out.append("M" + "L".join(f"{x:.1f},{y:.1f}" for x, y in pts))
        return "".join(out)

    vn_outline, vn_former = vn_line(vgeo["outline"], 2.0), vn_line(vgeo["former"])
    VW = max(x for rs in vn_rings.values() for r in rs for x, _ in r) + 4
    VH = max(y for rs in vn_rings.values() for r in rs for _, y in r) + 4

    def vn_map(highlight=None, mini=False):
        shapes = ""
        for k, v in V.items():
            if mini:
                shapes += f'<path data-k="{k}" d="{vn_mini[k]}"{ON if highlight == k else ""}/>'
                continue
            tip = {"n": v["name"], "a": v["native"], "s": None if v["score"] is None else round(v["score"]),
                   "people": pct(v["people"]), "jobs": pct(v["jobs"]), "biz": pct(v["biz"]), "money": pct(v["money"])}
            shapes += (f'<a href="{U(v_url(v))}" data-tip=\'{esc(json.dumps(tip, ensure_ascii=False))}\' aria-label="{esc(v["name"])}, momentum {tip["s"]}">'
                       f'<path d="{vn_full[k]}" {lens_attrs(v, lens_keys)}/></a>')
        if mini:
            return f'<svg class="map mini vn" viewBox="0 0 {VW:.0f} {VH:.0f}" aria-hidden="true"><g>{shapes}</g>{pin(vn_rings[highlight]) if highlight in vn_rings else ""}</svg>'
        return (f'<svg class="map vn" data-lens="score" viewBox="0 0 {VW:.0f} {VH:.0f}" role="group" aria-label="Map of Vietnam by province (2025 boundaries)">'
                f'<g class="units">{shapes}</g><path class="former" d="{vn_former}"/><path class="outline" d="{vn_outline}"/></svg>')

    # Malaysia: the peninsula and Borneo, with East Malaysia moved closer (MY_PROJ). The three federal territories are
    # a few pixels across, so they also get a marker dot; their shapes are drawn unsimplified so they never vanish.
    MY_TINY = ("kuala-lumpur", "putrajaya", "labuan")
    my_rings = {k: [[MY_PROJ(x, y) for x, y in r] for r in rs] for k, rs in mgeo["states"].items()}
    my_full = {k: path_d(v, tol=None if k in MY_TINY else 0.5, min_len=0.0 if k in MY_TINY else 2.0) for k, v in my_rings.items()}
    my_mini = {k: path_d(v, tol=None if k in MY_TINY else 1.2, min_len=0.0 if k in MY_TINY else 4.0) for k, v in my_rings.items()}
    MW = max(x for rs in my_rings.values() for r in rs for x, _ in r) + 4
    MH = max(y for rs in my_rings.values() for r in rs for _, y in r) + 4
    my_gap = _MY(105.3, 0)[0]                 # the cut between the peninsula and the moved-in east

    def my_dot(k):
        pts = [pt for r in my_rings[k] for pt in r]
        return (min(x for x, _ in pts) + max(x for x, _ in pts)) / 2, (min(y for _, y in pts) + max(y for _, y in pts)) / 2

    def my_map(highlight=None, mini=False):
        shapes = ""
        for k, m in M.items():
            if mini:
                shapes += f'<path data-k="{k}" d="{my_mini[k]}"{ON if highlight == k else ""}/>'
                continue
            tip = {"n": m["name"], "a": m["native"], "s": None if m["score"] is None else round(m["score"]),
                   "people": pct(m["people"]), "jobs": pct(m["jobs"]), "biz": "–", "money": pct(m["money"])}
            attrs = lens_attrs(m, lens_keys)
            dot = ""
            if k in MY_TINY:
                cx, cy = my_dot(k)
                dot = f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="4.5" class="dot" {attrs}/>'
            shapes += (f'<a href="{U(m_url(m))}" data-tip=\'{esc(json.dumps(tip, ensure_ascii=False))}\' aria-label="{esc(m["name"])}, momentum {tip["s"]}">'
                       f'<path d="{my_full[k]}" {attrs}/>{dot}</a>')
        if mini:
            return f'<svg class="map mini my" viewBox="0 0 {MW:.0f} {MH:.0f}" aria-hidden="true"><g>{shapes}</g>{pin(my_rings[highlight], 40) if highlight in my_rings else ""}</svg>'
        return (f'<svg class="map my" data-lens="score" viewBox="0 0 {MW:.0f} {MH:.0f}" role="group" aria-label="Map of Malaysia by state">'
                f'<line class="inset" x1="{my_gap:.1f}" y1="8" x2="{my_gap:.1f}" y2="{MH - 8:.1f}"/>'
                f'<text class="inset-note" x="{my_gap + 8:.1f}" y="20" aria-hidden="true">East Malaysia, drawn closer than it is</text>'
                f'<g class="units">{shapes}</g></svg>')

    # Philippines: 83 units, many of them islands. Same drawing as Vietnam: no stroke on fills, one outline layer
    # from the shared arcs (etl/ph_geo.py), so Metro Manila's districts and Maguindanao's parts read as one.
    ph_rings = {k: [[PH_PROJ(x, y) for x, y in r] for r in rs] for k, rs in pgeo["provinces"].items()}
    ph_full = {k: path_d(v, tol=0.5, min_len=0.0) for k, v in ph_rings.items()}
    ph_mini = {k: path_d(v, tol=1.0, min_len=0.0) for k, v in ph_rings.items()}
    ph_outline = ""
    for a in pgeo["outline"]:
        pts = simplify([PH_PROJ(*pt) for pt in a], 0.5)
        if len(pts) > 1:
            ph_outline += "M" + "L".join(f"{x:.1f},{y:.1f}" for x, y in pts)
    HW = max(x for rs in ph_rings.values() for r in rs for x, _ in r) + 4
    HH = max(y for rs in ph_rings.values() for r in rs for _, y in r) + 4

    def ph_map(highlight=None, mini=False):
        shapes = ""
        for k, h in H.items():
            if mini:
                shapes += f'<path data-k="{k}" d="{ph_mini[k]}"{ON if highlight == k else ""}/>'
                continue
            tip = {"n": h["name"], "a": h["region"], "s": None if h["score"] is None else round(h["score"]),
                   "people": pct(h["people"]), "jobs": "–", "biz": "–", "money": pct(h["money"])}
            shapes += (f'<a href="{U(h_url(h))}" data-tip=\'{esc(json.dumps(tip, ensure_ascii=False))}\' aria-label="{esc(h["name"])}, momentum {tip["s"]}">'
                       f'<path d="{ph_full[k]}" {lens_attrs(h, lens_keys)}/></a>')
        if mini:
            return f'<svg class="map mini ph" viewBox="0 0 {HW:.0f} {HH:.0f}" aria-hidden="true"><g>{shapes}</g>{pin(ph_rings[highlight]) if highlight in ph_rings else ""}</svg>'
        return (f'<svg class="map ph" data-lens="score" viewBox="0 0 {HW:.0f} {HH:.0f}" role="group" aria-label="Map of the Philippines by province">'
                f'<g class="units">{shapes}</g><path class="outline" d="{ph_outline}"/></svg>')

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
    my_lists = ""
    for k in ["score"] + lens_keys:
        top = sorted([m for m in M.values() if m.get(k) is not None], key=lambda m: -m[k])[:8]
        rows = "".join(
            f'<li><a href="{U(m_url(m))}"><span class="pos">{i}</span><span class="nm">{esc(m["name"])}{native(m["native"], "ms")}</span>'
            f'<span class="val {tone(m[k]) if k != "score" else ""}">{esc(f"{m[k]:.0f}" if k == "score" else pct(m[k]))}</span></a></li>'
            for i, m in enumerate(top, 1))
        sub = ("Momentum across people, jobs and money" if k == "score" else
               "Malaysia publishes no open business series by state yet." if k == "biz" else f"{MY_DESC[k]}, {mlab[k][0]}")
        my_lists += (f'<div class="tlist" data-for="{k}"{"" if k == "score" else " hidden"}><p class="sub">{esc(sub)}</p>'
                     + (f'<ol class="rlist plain">{rows}</ol>' if rows else "") + "</div>")
    ph_lists = ""
    for k in ["score"] + lens_keys:
        top = sorted([h for h in H.values() if h.get(k) is not None], key=lambda h: -h[k])[:8]
        rows = "".join(
            f'<li><a href="{U(h_url(h))}"><span class="pos">{i}</span><span class="nm">{esc(h["name"])}<span class="native">{esc(h["region"])}</span></span>'
            f'<span class="val {tone(h[k]) if k != "score" else ""}">{esc(f"{h[k]:.0f}" if k == "score" else pct(h[k]))}</span></a></li>'
            for i, h in enumerate(top, 1))
        sub = ("Momentum across people and money" if k == "score" else
               f"The Philippines publishes no {LENS[k][0].lower()} series by province." if k in ("jobs", "biz") else f"{PH_DESC[k]}, {hlab[k][0]}")
        ph_lists += (f'<div class="tlist" data-for="{k}"{"" if k == "score" else " hidden"}><p class="sub">{esc(sub)}</p>'
                     + (f'<ol class="rlist plain">{rows}</ol>' if rows else "") + "</div>")
    top_d = sorted([d for d in D if d.get("score") is not None], key=lambda d: d["rank"])[:10]
    leaving = sorted([d for d in D if d["dep_yoy"] is not None and d["in_latest"]], key=lambda d: d["dep_yoy"])[:5]

    def drow(d, val, key="dep_yoy"):
        return (f'<li><a href="{U(d_url(d))}"><span class="nm">{esc(d["name_en"])}{native(d["name_th"])}'
                f'<small>{esc(T[d["prov"]]["name"])}</small></span><span class="val {tone(val)}">{pct(val)}</span></a></li>')

    coverage_rows = ""
    for r in sorted(Rv, key=lambda r: r["name"]):
        sub = {"THA": '<td class="yes">77 provinces, 264 districts</td>', "VNM": '<td class="yes">34 provinces (2025)</td>',
               "MYS": f'<td class="yes">16 states, {sum(len(m["districts"]) for m in M.values())} districts</td>',
               "PHL": f'<td class="yes">{len(H)} provinces and cities</td>'}.get(r["iso"], '<td class="soon">Planned</td>')
        coverage_rows += (f'<tr><th scope="row"><a href="{U(c_url(r))}">{esc(r["name"])}</a></th>'
                          + "".join(f'<td>{r[k + "_year"] or "–"}</td>' for k in lens_keys) + sub + "</tr>")
    home = f"""
<section class="hero home">
  <h1>See where people, jobs, businesses and money are moving across Southeast&nbsp;Asia.</h1>
  <div class="hero-side">
    <p class="lede">Eleven countries and {big(sea_pop)} people, ranked on four kinds of movement from public data. Thailand, Vietnam, Malaysia and the Philippines go further, province by province; Thailand down to district, every month.</p>
    <a class="btn ghost film-link" href="{U('/film/')}"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M8 5.5v13l10.5-6.5z"/></svg><span>Watch the 40-second film</span></a>
  </div>
</section>
<section class="atlas band" id="atlas">
  <div class="atlas-map">
    {lens_tabs(label="Region lens")}
    <a class="skip-map" href="#after-map-1">Skip the map</a><div class="mapframe">{sea_map()}</div><span id="after-map-1" tabindex="-1"></span>
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
<section class="countries" aria-labelledby="countries-h">
<div class="countries-head"><h2 id="countries-h">Inside the countries</h2>
  <div class="ctabs" role="tablist" aria-label="Country" hidden>
    <button type="button" role="tab" data-for="thailand">Thailand<small>77 provinces</small></button>
    <button type="button" role="tab" data-for="vietnam">Vietnam<small>34 provinces</small></button>
    <button type="button" role="tab" data-for="malaysia">Malaysia<small>16 states</small></button>
    <button type="button" role="tab" data-for="philippines">Philippines<small>{len(H)} provinces</small></button>
  </div></div>
<section class="split country" id="thailand">
  <div class="split-head">
    <h2>Inside Thailand</h2>
    <p>77 provinces on all four lenses. People from the civil registry, jobs and employers from social security, money from bank deposits and credit by district.</p>
    <a class="btn" href="{U('/thailand/')}">Open the Thailand explorer</a>
  </div>
  <div class="split-body">
    <div class="split-map">{lens_tabs(label="Thailand lens")}<a class="skip-map" href="#after-map-2">Skip the map</a><div class="mapframe">{th_map()}</div><span id="after-map-2" tabindex="-1"></span>{legend("Thailand's 77 provinces")}</div>
    <div class="split-list">{th_lists}</div>
  </div>
</section>
<section class="split country" id="vietnam">
  <div class="split-head">
    <h2>Inside Vietnam</h2>
    <p>The 34 provinces formed in 2025, rebuilt from 63 old ones. Population and jobs to 2025, new businesses and enterprise revenue to 2024, from the National Statistics Office.</p>
    <a class="btn" href="{U('/vietnam/')}">Open the Vietnam explorer</a>
  </div>
  <div class="split-body">
    <div class="split-map">{lens_tabs(label="Vietnam lens")}<a class="skip-map" href="#after-map-3">Skip the map</a><div class="mapframe">{vn_map()}</div><span id="after-map-3" tabindex="-1"></span>{legend("Vietnam's 34 provinces")}</div>
    <div class="split-list">{vn_lists}</div>
  </div>
</section>
<section class="split country" id="malaysia">
  <div class="split-head">
    <h2>Inside Malaysia</h2>
    <p>The 13 states and 3 federal territories. Population to {mlab['people'][1]}, jobs to {mlab['jobs'][1]} and real GDP to {mlab['money'][1]}, from the Department of Statistics. There is no open business series by state yet, so that lens is left blank.</p>
    <a class="btn" href="{U('/malaysia/')}">Open the Malaysia explorer</a>
  </div>
  <div class="split-body wide">
    <div class="split-map">{lens_tabs(label="Malaysia lens")}<a class="skip-map" href="#after-map-6">Skip the map</a><div class="mapframe">{my_map()}</div><span id="after-map-6" tabindex="-1"></span>{legend("Malaysia's 16 states")}</div>
    <div class="split-list">{my_lists}</div>
  </div>
</section>
<section class="split country" id="philippines">
  <div class="split-head">
    <h2>Inside the Philippines</h2>
    <p>{len(H)} provinces, each with the cities inside it, and Metro Manila as one. Population from the 2020 and 2024 censuses, real GDP to {hlab['money'][1]} from the provincial accounts of the Philippine Statistics Authority.</p>
    <a class="btn" href="{U('/philippines/')}">Open the Philippines explorer</a>
  </div>
  <div class="split-body">
    <div class="split-map">{lens_tabs(label="Philippines lens")}<a class="skip-map" href="#after-map-8">Skip the map</a><div class="mapframe tall">{ph_map()}</div><span id="after-map-8" tabindex="-1"></span>{legend("the Philippines' provinces")}</div>
    <div class="split-list">{ph_lists}</div>
  </div>
</section>
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
    CARDS[U("/")] = {"kicker": "Eleven countries, four kinds of movement", "title": "Where is the money moving in Southeast Asia?",
                     "line": "People, jobs, businesses and money, ranked from public data, down to province and district.", "map": "sea"}
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
        extra = ""
        if r["fdi"] and r["gdp_usd"]:
            extra = f"Foreign direct investment brought in {big(r['fdi'], '$')} in {r['fdi_year']}, {r['fdi'] / r['gdp_usd'] * 100:.1f}% of GDP."
        if r["pop"] and r["pop"] < 3e6:
            extra += " With so small an economy, single-year changes swing widely; read them with care."
        summary = brief(r, "region", 11, "Southeast Asian countries", extra.strip())
        deep = ""
        if r["iso"] == "THA":
            deep = (f'<section class="callout reveal"><h2>Go deeper: 77 provinces, 264 districts</h2>'
                    f'<p>Thailand has province-level data on all four lenses and monthly bank data by district.</p>'
                    f'<a class="btn" href="{U("/thailand/")}">Open the Thailand explorer</a></section>')
        elif r["iso"] == "VNM":
            deep = (f'<section class="callout reveal"><h2>Go deeper: 34 provinces</h2>'
                    f'<p>Population, jobs, new businesses and enterprise revenue for every province on the 2025 boundaries, with the 63 former provinces underneath.</p>'
                    f'<a class="btn" href="{U("/vietnam/")}">Open the Vietnam explorer</a></section>')
        elif r["iso"] == "MYS":
            deep = (f'<section class="callout reveal"><h2>Go deeper: 16 states</h2>'
                    f'<p>Population, quarterly employment and real GDP for every state and federal territory, with population and jobs for each of their districts.</p>'
                    f'<a class="btn" href="{U("/malaysia/")}">Open the Malaysia explorer</a></section>')
        elif r["iso"] == "PHL":
            deep = (f'<section class="callout reveal"><h2>Go deeper: {len(H)} provinces</h2>'
                    f'<p>Census population growth and real GDP for every province, with Metro Manila\'s cities and the highly urbanized cities underneath.</p>'
                    f'<a class="btn" href="{U("/philippines/")}">Open the Philippines explorer</a></section>')
        else:
            deep = (f'<section class="callout quiet reveal"><h2>Subnational data for {esc(r["name"])}</h2>'
                    f'<p>Not yet. Country-level figures above are from the World Bank. Provinces arrive country by country: Thailand, Vietnam, Malaysia and the Philippines so far.</p></section>')
        others = "".join(f'<li><a href="{U(c_url(o))}">{esc(o["name"])}</a></li>' for o in sorted(Rv, key=lambda o: o["name"]) if o is not r)
        panels = with_strips(panels, {k: strip([(o["name"], o[k]) for o in Rv], r["name"], "Among the 11 countries") for k in lens_keys})
        rankh = rank_section("region", r["name"], "the 11 countries", lens_keys)
        body = f"""
<section class="hero detail">
  <div><h1>{esc(r['name'])} {native(r['native'], lang)}</h1>
  <p class="lede">{esc(summary)}</p></div>
  <div class="mini-sea">{sea_map(highlight=r['iso'], interactive=False)}</div>
</section>
<div class="panels">{panels}</div>
{rankh}
{deep}
<nav class="others" aria-label="Other countries"><h2>Other countries</h2><ul class="chips">{others}</ul></nav>
"""
        path = c_url(r)
        card(path, "Southeast Asian country", r["name"], r["native"], f"{ordinal(r['rank'])} of 11 on momentum" if r.get("rank") else "",
             lens_stats(r), "sea", r["iso"])
        write(path, page(U(path), f"{r['name']}: population, jobs, businesses and GDP growth | Where Money Moves",
                         first_sentences(summary),
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
    <div class="split-map"><div class="maptools">{lens_tabs(label="Thailand lens")}{view_toggle()}</div><a class="skip-map" href="#after-map-4">Skip the map</a><div class="mapframe tall">{th_map()}</div><span id="after-map-4" tabindex="-1"></span>{legend("Thailand's 77 provinces")}</div>
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
    CARDS[U("/thailand/")] = {"map": "th"}
    write("/thailand/", page(U("/thailand/"), "Thailand provinces ranked by population, jobs, businesses and money | Where Money Moves",
                             "All 77 Thai provinces ranked on registered population, formal employment, registered employers and bank money growth.",
                             explorer, meta, crumbs=[("Southeast Asia", "/"), ("Thailand", "/thailand/")], extra_head=import_map()))

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
        prows = ""
        for x in sorted([x for x in DP.values() if x["prov"] == tis], key=lambda x: -(x["pop"] or 0)):
            nm = (f'<a href="{U(d_url(page_of[x["id"]]))}">{esc(x["name_en"])}</a>' if x["id"] in page_of else esc(x["name_en"]))
            popv = f'{x["pop"]:,}' if x["pop"] else "–"
            prows += (f'<tr><th scope="row">{nm}{native(x["name_th"])}</th>'
                      f'<td class="num" data-v="{x["pop"] or ""}">{popv}</td>'
                      + value_cell(x["people"]) + value_cell(x["people_5y"]) + "</tr>")
        if prows:
            dtable += (f'<section class="reveal" id="population"><h2>Population by district</h2>'
                       f'<p class="sub">Registered population, December {dy[-2]} to December {dy[-1]}, every district in the province. '
                       f'A district is its own registry office plus the municipal parts of its tambons.</p>'
                       f'<div class="tablewrap"><table class="rank" data-sortable><thead><tr><th scope="col">District</th>'
                       f'<th scope="col" class="num"><button data-k="1">Population</button></th><th scope="col" class="num"><button data-k="2">One year</button></th>'
                       f'<th scope="col" class="num"><button data-k="3">Five years</button></th></tr></thead><tbody>{prows}</tbody></table></div></section>')
        if gone:
            dtable += ('<section class="reveal"><h2>Dropped from the bank table</h2><p class="sub">Fell below four commercial banks during the year.</p><ul class="chips">'
                       + "".join(f'<li><a href="{U(d_url(d))}">{esc(d["name_en"])}</a></li>' for d in gone) + "</ul></section>")
        near = sorted([o for o in T.values() if o["region"] == t["region"] and o is not t], key=lambda o: -(o["score"] or 0))[:8]
        added = t["insured"] - dict(t["ins_series"])[sso["years"][-2]]
        extra = f"Formal employment {'grew by' if added >= 0 else 'fell by'} {abs(added):,} people in {sso['years'][-1]}."
        if t["br_change"]:
            extra += f" Banks {'closed' if t['br_change'] < 0 else 'opened'} {abs(t['br_change'])} branch{'es' if abs(t['br_change']) != 1 else ''} in the year to {month_label(latest)}."
        elif t["money"] is None:
            extra += " No district here has four commercial banks, so there are no bank figures."
        summary = brief(t, "th", 77, "Thai provinces", extra)
        panels = with_strips(panels, {k: strip([(o["name"], o[k]) for o in T.values()], t["name"], f"Among Thailand's {sum(1 for o in T.values() if o[k] is not None)} provinces with a figure" if k == "money" else "Among Thailand's 77 provinces") for k in lens_keys})
        rankh = rank_section("th", t["name"], "Thailand's provinces", lens_keys)
        body = f"""
<section class="hero detail">
  <div><h1>{esc(t['name'])} {native(t['native'])}</h1>
  <p class="lede">{esc(summary)}</p></div>
  {th_map(highlight=tis, mini=True)}
</section>
<div class="panels">{panels}</div>
{rankh}
{dtable}
<nav class="others" aria-label="Nearby provinces"><h2>Elsewhere in the {esc(t['region'])} region</h2><ul class="chips">{"".join(f'<li><a href="{U(p_url(o))}">{esc(o["name"])}</a></li>' for o in near)}</ul></nav>
"""
        path = p_url(t)
        card(path, f"Province of Thailand, {t['region']} region", t["name"], t["native"], f"{ordinal(t['rank'])} of 77 on momentum" if t.get("rank") else "",
             lens_stats(t), "th", tis)
        write(path, page(U(path), f"{t['name']} province: population, jobs, businesses and bank money | Where Money Moves",
                         first_sentences(summary),
                         body, meta, crumbs=[("Southeast Asia", "/"), ("Thailand", "/thailand/"), (t["name"], path)],
                         watch={"id": f"p-{tis}", "name": t["name"], "url": U(path)}))

    # ── DISTRICT pages
    nD = len([d for d in D if d.get("score") is not None])
    dep_rank = {d["id"]: i for i, d in enumerate(sorted([d for d in D if d["in_latest"] and d["dep_yoy"] is not None], key=lambda d: -d["dep_yoy"]), 1)}
    for d in D:
        t = T[d["prov"]]
        unit = "Khet" if d["prov"] == "10" else "District"
        notes = ""
        if not d["in_latest"]:
            lp = next((r[0] for r in reversed(d["series"]) if r[1] is not None), None)
            notes += f'<p class="warn">Not in the latest Bank of Thailand table. Last figures: {month_label(lp)}.</p>'
        if d["cr_yoy"] is not None and abs(d["cr_yoy"]) > SPIKE:
            notes += '<p class="warn">Credit moved more than 50% in a year. This usually means one large borrower or loans moved between branches.</p>'
        if d["dep_yoy"] is not None and d["in_latest"]:
            summary = (f"Bank deposits {'grew' if d['dep_yoy'] >= 0 else 'fell'} {pct(abs(d['dep_yoy']))[1:]} in the year to {month_label(latest)}, "
                       f"{ordinal(dep_rank[d['id']])} of {len(dep_rank)} districts")
            if d["cr_yoy"] is not None:
                summary += f", while credit {'rose' if d['cr_yoy'] >= 0 else 'fell'} {pct(abs(d['cr_yoy']))[1:]}"
            summary += "."
            if d["br_change"]:
                summary += f" It {'lost' if d['br_change'] < 0 else 'gained'} {abs(d['br_change'])} bank branch{'es' if abs(d['br_change']) != 1 else ''}, to {d['branches']}."
            if d.get("prov_rank"):
                summary += f" {ordinal(d['prov_rank']).capitalize()} in {t['name']} on bank money."
        else:
            summary = "Not in the latest Bank of Thailand table, which lists only districts with four or more commercial banks."
        dp = DP.get(d["id"], {})
        if dp.get("people") is not None:
            summary += (f" Its registered population {'grew' if dp['people'] >= 0 else 'fell'} {pct(abs(dp['people']))[1:]} in {dy[-1]}, "
                        f"to {dp['pop']:,} ({ordinal(dp['people_rank'])} of {nDP} districts).")
        ser = d["series"]
        mlabel = lambda p: p[:4] if p.endswith("-01") else ""
        charts = (chart([(r[0], r[1] and r[1] / 1e6) for r in ser], "Deposits, million baht", x_label=mlabel, every=1, base=y1)
                  + chart([(r[0], r[2] and r[2] / 1e6) for r in ser], "Credit, million baht", x_label=mlabel, every=1, base=y1)
                  + chart([(r[0], r[3]) for r in ser], "Bank branches", x_label=mlabel, every=1, base=y1)
                  + (chart(dp["series"], "Registered population, December", x_label=str, every=1, kind="dots") if len(dp.get("series") or []) > 1 else ""))
        stats = ((stat("Money momentum", f'{d["score"]:.0f}', f'#{d["rank"]} of {nD} districts') if d.get("score") is not None else "")
                 + stat("Deposits", pct(d["dep_yoy"]), f"{month_label(y1)} to {month_label(latest)}", tone(d["dep_yoy"]))
                 + stat("Credit", pct(d["cr_yoy"]), "Same period", tone(d["cr_yoy"]))
                 + stat("Branches", str(d["branches"]) if d["branches"] is not None else "–", f'{signed_int(d["br_change"])} in a year')
                 + stat("Deposit balance", baht(d["deposits"]), month_label(latest) if d["in_latest"] else "")
                 + (stat("Deposits over three years", pct(d["dep_3y"]), f"Since {month_label(meta['base_3y'])}", tone(d["dep_3y"])) if d["dep_3y"] is not None else "")
                 + (stat("Registered population", f"{dp['pop']:,}", f"December {dy[-1]}") if dp.get("pop") else "")
                 + (stat("People", pct(dp["people"]), f"Dec {dy[-2]} to Dec {dy[-1]}", tone(dp["people"])) if dp.get("people") is not None else "")
                 + (stat("People over five years", pct(dp["people_5y"]), f"Since Dec {dy[0]}", tone(dp["people_5y"])) if dp.get("people_5y") is not None else ""))
        months = "".join(f'<tr><th scope="row">{month_label(r[0])}</th><td class="num">{"–" if r[1] is None else f"{r[1]/1e6:,.0f}"}</td>'
                         f'<td class="num">{"–" if r[2] is None else f"{r[2]/1e6:,.0f}"}</td><td class="num">{"–" if r[3] is None else r[3]}</td></tr>'
                         for r in reversed(ser[-13:]))
        sibs = sorted([x for x in by_prov[d["prov"]] if x is not d and x["in_latest"]], key=lambda x: -(x.get("score") or -1))
        body = f"""
<section class="hero detail">
  <div><h1>{esc(d['name_en'])} {native(d['name_th'])}</h1>
  <p class="lede">{unit} in <a href="{U(p_url(t))}">{esc(t['name'])}</a>. {esc(summary)}</p>
  {notes}</div>
</section>
<section class="stats reveal">{stats}</section>
<section class="charts reveal">{charts}</section>
<section class="reveal"><details><summary>Monthly figures</summary><div class="tablewrap"><table class="plain"><thead><tr><th scope="col">Month</th>
<th scope="col" class="num">Deposits (฿M)</th><th scope="col" class="num">Credit (฿M)</th><th scope="col" class="num">Branches</th></tr></thead><tbody>{months}</tbody></table></div></details></section>
{f'<nav class="others" aria-label="Other districts"><h2>Other districts in {esc(t["name"])}</h2><ul class="chips">' + "".join(f'<li><a href="{U(d_url(x))}">{esc(x["name_en"])} <span class="{tone(x["dep_yoy"])}">{pct(x["dep_yoy"])}</span></a></li>' for x in sibs) + "</ul></nav>" if sibs else ""}
"""
        path = d_url(d)
        card(path, f"District of {t['name']}, Thailand", d["name_en"], d["name_th"],
             f"{ordinal(d['rank'])} of {nD} districts on bank money" if d.get("score") is not None else "",
             [["Deposits", pct(d["dep_yoy"]), tone(d["dep_yoy"])], ["Credit", pct(d["cr_yoy"]), tone(d["cr_yoy"])],
              ["People", pct(dp.get("people")), tone(dp.get("people"))],
              ["Branches", signed_int(d["br_change"]) if d["br_change"] is not None else None, tone(d["br_change"])]], "th", d["prov"])
        write(path, page(U(path), f"{d['name_en']}, {t['name']}: bank deposits, credit and population | Where Money Moves",
                         first_sentences(f"{d['name_en']}, {t['name']}, Thailand. {summary}"),
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
    <div class="split-map"><div class="maptools">{lens_tabs(label="Vietnam lens")}{view_toggle()}</div><a class="skip-map" href="#after-map-5">Skip the map</a><div class="mapframe tall">{vn_map()}</div><span id="after-map-5" tabindex="-1"></span>{legend("Vietnam's 34 provinces")}
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
    CARDS[U("/vietnam/")] = {"map": "vn"}
    write("/vietnam/", page(U("/vietnam/"), "Vietnam's 34 provinces ranked by population, jobs, new businesses and revenue | Where Money Moves",
                            "Every Vietnamese province on the 2025 boundaries, ranked on population, employment, new enterprises and enterprise revenue growth.",
                            explorer, meta, crumbs=[("Southeast Asia", "/"), ("Vietnam", "/vietnam/")], extra_head=import_map()))

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
        extra = ""
        if v["netmig"] is not None:
            extra = (f"More people moved in than out in {v['netmig_year']}, a net gain of {v['netmig']:.1f} per 1,000 residents." if v["netmig"] > 0.05
                     else f"More people moved out than in during {v['netmig_year']}, a net loss of {abs(v['netmig']):.1f} per 1,000 residents." if v["netmig"] < -0.05
                     else f"Migration in and out roughly balanced in {v['netmig_year']}.")
        if merged:
            def nb(dd):
                ser = sorted(dd["new_firms"].items())
                return growth(ser[-1][1], ser[-2][1]) if len(ser) == 2 else None
            fb = [(name, nb(dd)) for name, dd in v["former_detail"].items() if nb(dd) is not None]
            if fb:
                top = max(fb, key=lambda x: x[1])
                extra += f" Of its former provinces, {top[0]} grew new business registrations fastest ({pct(top[1])})."
        summary = brief(v, "vn", 34, "Vietnamese provinces", extra.strip())
        panels = with_strips(panels, {k: strip([(o["name"], o[k]) for o in V.values()], v["name"], "Among Vietnam's 34 provinces") for k in lens_keys})
        rankh = rank_section("vn", v["name"], "Vietnam's 34 provinces", lens_keys)
        body = f"""
<section class="hero detail">
  <div><h1>{esc(v['name'])} {native(v['native'], 'vi')}</h1>
  <p class="lede">{esc(summary)}</p><p class="sub formed">{esc(formed)}</p></div>
  {vn_map(highlight=slug_, mini=True)}
</section>
<div class="panels">{panels}</div>
{rankh}
{fd}
<nav class="others" aria-label="Other provinces"><h2>Other provinces with high momentum</h2><ul class="chips">{"".join(f'<li><a href="{U(v_url(o))}">{esc(o["name"])}</a></li>' for o in near)}</ul></nav>
"""
        path = v_url(v)
        card(path, "Province of Vietnam" + (", formed in 2025" if merged else ""), v["name"], v["native"],
             f"{ordinal(v['rank'])} of 34 on momentum" if v.get("rank") else "", lens_stats(v), "vn", slug_)
        write(path, page(U(path), f"{v['name']}, Vietnam: population, jobs, new businesses and revenue | Where Money Moves",
                         first_sentences(summary + (f" Formed in 2025 from {', '.join(v['former'])}." if merged else "")),
                         body, meta, crumbs=[("Southeast Asia", "/"), ("Vietnam", "/vietnam/"), (v["name"], path)],
                         watch={"id": f"v-{slug_}", "name": f"{v['name']}, Vietnam", "url": U(path)}))

    # ── MALAYSIA explorer
    mk = lens_keys
    mrows = ""
    for m in sorted(M.values(), key=lambda m: (m["score"] is None, -(m["score"] or 0))):
        mrows += (f'<tr><td class="num pos">{m.get("rank") or "–"}</td><th scope="row"><a href="{U(m_url(m))}">{esc(m["name"])}</a>{native(m["native"], "ms")}</th>'
                  f'<td data-v="{"" if m["score"] is None else round(m["score"], 2)}">{score_pill(m["score"])}</td>'
                  + value_cell(m["people"]) + value_cell(m["jobs"]) + value_cell(m["money"]) + "</tr>")
    mhead = ('<th scope="col" class="num">#</th><th scope="col">State</th><th scope="col"><button data-k="2">Momentum</button></th>'
             '<th scope="col" class="num"><button data-k="3">People</button></th><th scope="col" class="num"><button data-k="4">Jobs</button></th>'
             '<th scope="col" class="num"><button data-k="5">Money</button></th>')
    all_md = [(m, d) for m in M.values() for d in m["districts"] if len(m["districts"]) > 1 and d["people"] is not None]

    def mdrow(m, d, val):
        return (f'<li><a href="{U(m_url(m))}#districts"><span class="nm">{esc(d["name"])}<small>{esc(m["name"])}</small></span>'
                f'<span class="val {tone(val)}">{pct(val)}</span></a></li>')
    grow = sorted(all_md, key=lambda x: -x[1]["people"])[:10]
    iyr = myears["district_income"]
    inc_md = [(m, d) for m in M.values() for d in m["districts"] if len(m["districts"]) > 1 and d["income_growth"] is not None]
    inc_up = sorted(inc_md, key=lambda x: -x[1]["income_growth"])[:10]
    inc_down = sorted(inc_md, key=lambda x: x[1]["income_growth"])[:5]
    shrink = sorted(all_md, key=lambda x: x[1]["people"])[:5]
    explorer = f"""
<section class="hero">
  <h1>Malaysia, state by state</h1>
  <p class="lede">The 13 states and 3 federal territories: where people are settling, where jobs are being added and where the economy is growing. Each lens has its own latest date, shown with the number.</p>
</section>
<section class="split flush">
  <div class="split-body wide">
    <div class="split-map"><div class="maptools">{lens_tabs(label="Malaysia lens")}{view_toggle()}</div><a class="skip-map" href="#after-map-7">Skip the map</a><div class="mapframe">{my_map()}</div><span id="after-map-7" tabindex="-1"></span>{legend("Malaysia's 16 states")}
      <p class="note">Sabah, Sarawak and Labuan are drawn closer to the peninsula than they are. Kuala Lumpur, Putrajaya and Labuan carry a dot so they can be found.</p></div>
    <div class="split-list">
      <dl class="asof">{"".join(f'<div>{icon(k)}<dt>{esc(LENS[k][0])}</dt><dd>{esc(MY_DESC[k])}<br><small>{esc(mlab[k][0])}</small></dd></div>' for k in mk)}</dl>
    </div>
  </div>
</section>
<section class="reveal">
  <h2>All 16 states and federal territories</h2>
  <p class="sub">Select a column heading to sort. Momentum is the average rank across people, jobs and money.</p>
  <div class="tablewrap"><table class="rank" data-sortable><thead><tr>{mhead}</tr></thead><tbody>{mrows}</tbody></table></div>
</section>
<section class="movers reveal">
  <div><h2>Districts growing fastest</h2><p class="sub">Population, {myears['district_pop'] - 1} to {myears['district_pop']} (estimates)</p>
    <ol class="dlist">{"".join(mdrow(m, d, d["people"]) for m, d in grow)}</ol></div>
  <div><h2>Districts losing people</h2><p class="sub">Same period, all {len(all_md)} districts</p>
    <ol class="dlist">{"".join(mdrow(m, d, d["people"]) for m, d in shrink)}</ol></div>
</section>
<section class="movers reveal">
  <div><h2>Household income rising fastest</h2><p class="sub">Median household income, {iyr - 2} to {iyr} (Household Income Survey, nominal)</p>
    <ol class="dlist">{"".join(mdrow(m, d, d["income_growth"]) for m, d in inc_up)}</ol>
    <a class="more" href="{U('/rankings/malaysia-district-income-growth/')}">All {len(inc_md)} districts</a></div>
  <div><h2>Household income falling</h2><p class="sub">Same surveys</p>
    <ol class="dlist">{"".join(mdrow(m, d, d["income_growth"]) for m, d in inc_down)}</ol></div>
</section>
"""
    CARDS[U("/malaysia/")] = {"map": "my"}
    write("/malaysia/", page(U("/malaysia/"), "Malaysia's states ranked by population, jobs and GDP growth | Where Money Moves",
                             "All 13 Malaysian states and 3 federal territories ranked on population, employment and real GDP growth, with every district's population.",
                             explorer, meta, crumbs=[("Southeast Asia", "/"), ("Malaysia", "/malaysia/")], extra_head=import_map()))

    # ── MALAYSIA state pages
    sec_names = my["sector_names"]
    for slug_, m in M.items():
        ft = slug_ in ("kuala-lumpur", "putrajaya", "labuan")
        kind = "federal territory" if ft else "state"
        g = mlab["money"][1]
        biggest = max(m["sector_share"], key=lambda c: m["sector_share"][c])
        sec_rows = [(f"{sec_names[c]} ({m['sector_share'][c] * 100:.0f}% of output)", pct(m["sectors"][c]))
                    for c in sorted(m["sector_share"], key=lambda c: -m["sector_share"][c]) if m["sector_share"][c] >= 0.005]
        panels = (
            lens_panel("people", pct(m["people"]), f"population, {mlab['people'][0]}", f"#{m.get('people_rank', '–')} of 16",
                       [("Population", f"{m['pop']:,.0f}"), ("Five-year change", pct(m["people_5y"]))],
                       chart([(y, v * 1000) for y, v in m["pop_series"] if y >= 2020], "Population", x_label=str, every=1, kind="dots"),
                       "DOSM's yearly estimates, which count everyone living in the state, including non-citizens. "
                       "Shown from 2020: the 2020 Census reset the base, so earlier years do not line up.") +
            lens_panel("jobs", pct(m["jobs"]), f"employed persons, {mlab['jobs'][0]}", f"#{m.get('jobs_rank', '–')} of 16",
                       [("Employed persons", f"{m['employed']:,.0f}"),
                        ("Unemployment rate", f"{m['u_rate']:.1f}%" + (f" (was {m['u_rate_prev']:.1f}%)" if m["u_rate_prev"] is not None else "")),
                        ("Labour force participation", f"{m['p_rate']:.1f}%")],
                       chart([(q, v * 1000) for q, v in m["emp_series"] if q >= "2019"], "Employed persons, quarterly",
                             x_label=lambda q: q[:4], every=4, kind="line"),
                       "Labour Force Survey, quarterly. Compared with the same quarter a year earlier, so seasons cancel out.") +
            lens_panel("biz", "–", "no open state series yet", "Not ranked", [], "",
                       "DOSM publishes no open count of businesses or new registrations by state. Momentum for Malaysia averages the other three lenses; a proxy will be labelled as one when it arrives.") +
            lens_panel("money", pct(m["money"]), f"real GDP, {mlab['money'][0]}", f"#{m.get('money_rank', '–')} of 16",
                       [("GDP", f"RM {m['gdp'] / 1000:,.1f} billion ({g}, 2015 prices)"),
                        ("Per person", f"RM {m['gdp_pc']:,.0f}" if m["gdp_pc"] else "–"), ("Five-year change", pct(m["gdp_5y"]))]
                       + ([(f"Median household income ({m['income_year']})", f"RM {m['income']:,.0f} a month, {pct(m['income_growth'])} since {m['income_year'] - 2}")] if m["income"] else [])
                       + sec_rows,
                       chart([(y, v * 1e6) for y, v in m["gdp_series"]], "Real GDP (RM, constant 2015 prices)", unit="RM", x_label=str, every=2, kind="dots"),
                       f"Oil and gas output not tied to any state (RM {float(my['supra_gdp'][str(g)]) / 1000:,.0f} billion in {g}) is left out of every state.")
        )
        multi = len(m["districts"]) > 1
        dtable = ""
        if multi:
            ey = myears["district_emp"]
            rows = ""
            for d in sorted(m["districts"], key=lambda d: -d["pop"]):
                rows += (f'<tr><th scope="row">{esc(d["name"])}</th><td class="num" data-v="{d["pop"]:.0f}">{d["pop"]:,.0f}</td>'
                         + value_cell(d["people"]) + value_cell(d["people_5y"])
                         + (f'<td class="num" data-v="{d["employed"]:.0f}">{d["employed"]:,.0f}</td>' if d["employed"] else '<td class="num" data-v="">–</td>')
                         + value_cell(d["jobs"])
                         + (f'<td class="num" data-v="{d["u_rate"]}">{d["u_rate"]:.1f}%</td>' if d["u_rate"] is not None else '<td class="num" data-v="">–</td>')
                         + (f'<td class="num" data-v="{d["income"]:.0f}">RM {d["income"]:,.0f}</td>' if d["income"] else '<td class="num" data-v="">–</td>')
                         + value_cell(d["income_growth"])
                         + (f'<td class="num" data-v="{d["poverty"]}">{d["poverty"]:.1f}%</td>' if d["poverty"] is not None else '<td class="num" data-v="">–</td>')
                         + "</tr>")
            dtable = (f'<section class="reveal" id="districts"><h2>Districts</h2>'
                      f'<p class="sub">Population {myears["district_pop"] - 1} to {myears["district_pop"]} (estimates); employment and unemployment {ey - 1} to {ey}, from the yearly Labour Force Survey; '
                      f'median household income and absolute poverty from the Household Income Survey, {iyr - 2} to {iyr} (income is nominal, a month).</p>'
                      f'<div class="tablewrap"><table class="rank" data-sortable><thead><tr><th scope="col">District</th>'
                      f'<th scope="col" class="num"><button data-k="1">Population</button></th><th scope="col" class="num"><button data-k="2">People</button></th>'
                      f'<th scope="col" class="num"><button data-k="3">Five years</button></th><th scope="col" class="num"><button data-k="4">Employed</button></th>'
                      f'<th scope="col" class="num"><button data-k="5">Jobs</button></th><th scope="col" class="num"><button data-k="6">Unemployment</button></th>'
                      f'<th scope="col" class="num"><button data-k="7">Household income</button></th><th scope="col" class="num"><button data-k="8">Income change</button></th>'
                      f'<th scope="col" class="num"><button data-k="9">Poverty</button></th>'
                      f'</tr></thead><tbody>{rows}</tbody></table></div></section>')
        extra = (f"Its economy grew {pct(m['money'])} in real terms in {g}; {sec_names[biggest].lower()}, the largest sector at "
                 f"{m['sector_share'][biggest] * 100:.0f}% of output, grew {pct(m['sectors'][biggest])}.") if m["money"] is not None else ""
        if multi:
            fast = max((d for d in m["districts"] if d["people"] is not None), key=lambda d: d["people"])
            extra += f" Its fastest-growing district is {fast['name']} ({pct(fast['people'])} population in a year)."
        if m["income"]:
            extra += (f" Median household income {'rose' if (m['income_growth'] or 0) >= 0 else 'fell'} {pct(abs(m['income_growth'] or 0))[1:]} "
                      f"between {m['income_year'] - 2} and {m['income_year']}, to RM {m['income']:,.0f} a month.")
        if m["pop"] < 200000:
            extra += " With so few people, single-year changes swing widely; read them with care."
        summary = brief(m, "my", 16, "Malaysian states and federal territories", extra.strip())
        near = sorted([o for o in M.values() if o is not m], key=lambda o: -(o["score"] or 0))[:8]
        panels = with_strips(panels, {k: strip([(o["name"], o[k]) for o in M.values()], m["name"], "Among Malaysia's 16 states and federal territories") for k in ("people", "jobs", "money")})
        rankh = rank_section("my", m["name"], "Malaysia's 16 states", ["people", "jobs", "money"])
        body = f"""
<section class="hero detail">
  <div><h1>{esc(m['name'])} {native(m['native'], 'ms')}</h1>
  <p class="lede">{esc(summary)}</p><p class="sub formed">A {kind} of Malaysia.</p></div>
  {my_map(highlight=slug_, mini=True)}
</section>
<div class="panels">{panels}</div>
{rankh}
{dtable}
<nav class="others" aria-label="Other states"><h2>Other states with high momentum</h2><ul class="chips">{"".join(f'<li><a href="{U(m_url(o))}">{esc(o["name"])}</a></li>' for o in near)}</ul></nav>
"""
        path = m_url(m)
        card(path, f"{kind[0].upper() + kind[1:]} of Malaysia", m["name"], m["native"],
             f"{ordinal(m['rank'])} of 16 on momentum" if m.get("rank") else "", lens_stats(m, ["people", "jobs", "money"]), "my", slug_)
        write(path, page(U(path), f"{m['name']}, Malaysia: population, jobs and GDP growth | Where Money Moves",
                         first_sentences(summary), body, meta,
                         crumbs=[("Southeast Asia", "/"), ("Malaysia", "/malaysia/"), (m["name"], path)],
                         watch={"id": f"m-{slug_}", "name": f"{m['name']}, Malaysia", "url": U(path)}))

    # ── PHILIPPINES explorer
    hrows = ""
    for h in sorted(H.values(), key=lambda h: (h["score"] is None, -(h["score"] or 0))):
        hrows += (f'<tr><td class="num pos">{h.get("rank") or "–"}</td><th scope="row"><a href="{U(h_url(h))}">{esc(h["name"])}</a><small>{esc(h["region"])}</small></th>'
                  f'<td data-v="{"" if h["score"] is None else round(h["score"], 2)}">{score_pill(h["score"])}</td>'
                  + value_cell(h["people"]) + value_cell(h["money"])
                  + f'<td class="num" data-v="{h["gdp_pc"]:.0f}">₱{h["gdp_pc"]:,.0f}</td></tr>')
    hhead = ('<th scope="col" class="num">#</th><th scope="col">Province</th><th scope="col"><button data-k="2">Momentum</button></th>'
             '<th scope="col" class="num"><button data-k="3">People</button></th><th scope="col" class="num"><button data-k="4">Money</button></th>'
             '<th scope="col" class="num"><button data-k="5">GDP per person</button></th>')
    explorer = f"""
<section class="hero">
  <h1>The Philippines, province by province</h1>
  <p class="lede">Where people are settling and where the economy is growing, across {len(H)} provinces. Each highly urbanized city is counted with the province around it, and Metro Manila's seventeen cities as one place, so every number is a place you can find on the map.</p>
</section>
<section class="split flush">
  <div class="split-body">
    <div class="split-map"><div class="maptools">{lens_tabs(label="Philippines lens")}{view_toggle()}</div><a class="skip-map" href="#after-map-9">Skip the map</a><div class="mapframe tall">{ph_map()}</div><span id="after-map-9" tabindex="-1"></span>{legend("the Philippines' provinces")}
      <p class="note">Islets smaller than about 15 km² are not drawn.</p></div>
    <div class="split-list">
      <dl class="asof">{"".join(f'<div>{icon(k)}<dt>{esc(LENS[k][0])}</dt><dd>{esc(PH_DESC[k])}<br><small>{esc(hlab[k][0])}</small></dd></div>' for k in lens_keys)}</dl>
    </div>
  </div>
</section>
<section class="reveal">
  <h2>All {len(H)} provinces</h2>
  <p class="sub">Select a column heading to sort. Momentum is the average rank on people and money. GDP per person is at current prices, over the 2024 census population.</p>
  <div class="tablewrap"><table class="rank" data-sortable><thead><tr>{hhead}</tr></thead><tbody>{hrows}</tbody></table></div>
</section>
"""
    CARDS[U("/philippines/")] = {"map": "ph"}
    write("/philippines/", page(U("/philippines/"), "Philippine provinces ranked by population and GDP growth | Where Money Moves",
                                f"All {len(H)} Philippine provinces, with their cities, ranked on census population growth and real GDP growth.",
                                explorer, meta, crumbs=[("Southeast Asia", "/"), ("Philippines", "/philippines/")], extra_head=import_map()))

    # ── PHILIPPINES province pages
    for slug_, h in H.items():
        Y = hlab["money"][1]
        n = len(H)
        kind = ("the capital region" if slug_ == "metro-manila" else "a city outside any province" if slug_ == "city-of-isabela"
                else f"a province in {h['region']}")
        panels = (
            lens_panel("people", pct(h["people"]), "a year, 2020 to 2024 censuses", f"#{h.get('people_rank', '–')} of {n}",
                       [("Population (2024)", f"{h['pop']:,.0f}"), ("Population (2020)", f"{h['pop2020']:,.0f}"), ("Change since 2020", pct(h["people_total"]))],
                       "", "Census counts on 1 May 2020 and 1 July 2024; the yearly rate spreads the change over the 4.2 years between them.") +
            lens_panel("jobs", "–", "no province series", "Not ranked", [], "",
                       "The Labor Force Survey is published for the country and its regions, not for provinces.") +
            lens_panel("biz", "–", "no province series", "Not ranked", [], "",
                       "No open count of businesses by province. Momentum here averages people and money.") +
            lens_panel("money", pct(h["money"]), f"real GDP, {hlab['money'][0]}", f"#{h.get('money_rank', '–')} of {n}",
                       [("GDP", f"₱{h['gdp_nominal'] / 1e9:,.1f} billion ({Y}, current prices)"), ("Per person", f"₱{h['gdp_pc']:,.0f}"),
                        ("Five-year change", pct(h["gdp_5y"]))],
                       chart([(y, v) for y, v in h["gdp_series"]], "Real GDP (₱, constant 2018 prices)", unit="₱", x_label=str, every=1, kind="dots"),
                       "Provincial Product Accounts of the Philippine Statistics Authority.")
        )
        ptable = ""
        if h["parts"]:
            rows = ""
            for d in sorted(h["parts"], key=lambda d: -(d["share"] or 0)):
                popv = f'{d["pop"]:,.0f}' if d["pop"] else "–"
                rows += (f'<tr><th scope="row">{esc(d["name"])}</th><td class="num" data-v="{d["pop"] or ""}">{popv}</td>'
                         + value_cell(d["people"]) + value_cell(d["money"])
                         + f'<td class="num" data-v="{d["share"]:.4f}">{d["share"] * 100:.0f}%</td></tr>')
            what = "Its cities" if slug_ == "metro-manila" else "The province and the cities counted with it"
            # a boundary change, not a migration: ten barangays went from Makati to Taguig after a 2023 Supreme Court ruling
            embo = (" Makati's fall and Taguig's jump in population are ten barangays (the “EMBO” area) passing from Makati to Taguig "
                    "after a 2023 Supreme Court ruling, not people moving. Metro Manila as a whole is unaffected." if slug_ == "metro-manila" else "")
            ptable = (f'<section class="reveal" id="places"><h2>{what}</h2><p class="sub">Each on its own: population growth a year since 2020, real GDP growth {hlab["money"][0]}, and its share of the output.{esc(embo)}</p>'
                      f'<div class="tablewrap"><table class="rank" data-sortable><thead><tr><th scope="col">Place</th>'
                      f'<th scope="col" class="num"><button data-k="1">Population</button></th><th scope="col" class="num"><button data-k="2">People</button></th>'
                      f'<th scope="col" class="num"><button data-k="3">Money</button></th><th scope="col" class="num"><button data-k="4">Share of GDP</button></th>'
                      f'</tr></thead><tbody>{rows}</tbody></table></div></section>')
        extra = f"Its economy grew {pct(h['money'])} in real terms in {Y}, to ₱{h['gdp_nominal'] / 1e9:,.0f} billion."
        movers = [d for d in h["parts"] if d["money"] is not None]
        if len(movers) > 1:
            top = max(movers, key=lambda d: d["money"])
            extra += f" Of the places it is made of, {top['name']} grew fastest ({pct(top['money'])})."
        if h["pop"] < 200000:
            extra += " With so few people, single-year changes swing widely; read them with care."
        summary = brief(h, "ph", n, "Philippine provinces", extra)
        near = sorted([o for o in H.values() if o["region"] == h["region"] and o is not h], key=lambda o: -(o["score"] or 0))[:8]
        panels = with_strips(panels, {k: strip([(o["name"], o[k]) for o in H.values()], h["name"], f"Among the Philippines' {len(H)} provinces") for k in ("people", "money")})
        rankh = rank_section("ph", h["name"], f"the Philippines' {len(H)} provinces", ["money"])
        body = f"""
<section class="hero detail">
  <div><h1>{esc(h['name'])}</h1>
  <p class="lede">{esc(summary)}</p><p class="sub formed">{esc(kind[0].upper() + kind[1:])} of the Philippines.</p></div>
  {ph_map(highlight=slug_, mini=True)}
</section>
<div class="panels">{panels}</div>
{rankh}
{ptable}
<nav class="others" aria-label="Nearby provinces"><h2>{"Elsewhere in " + esc(h["region"]) if near else "Other provinces"}</h2><ul class="chips">{"".join(f'<li><a href="{U(h_url(o))}">{esc(o["name"])}</a></li>' for o in (near or sorted(H.values(), key=lambda o: -(o["score"] or 0))[:8]))}</ul></nav>
"""
        path = h_url(h)
        card(path, f"Province of the Philippines, {h['region']}", h["name"], "",
             f"{ordinal(h['rank'])} of {n} on momentum" if h.get("rank") else "", lens_stats(h, ["people", "money"]), "ph", slug_)
        write(path, page(U(path), f"{h['name']}, Philippines: population and GDP growth | Where Money Moves",
                         first_sentences(summary), body, meta,
                         crumbs=[("Southeast Asia", "/"), ("Philippines", "/philippines/"), (h["name"], path)],
                         watch={"id": f"h-{slug_}", "name": f"{h['name']}, Philippines", "url": U(path)}))

    # ── FILM: "Where the money moved", drawn in code (static/film.js). Every caption is computed here from the data,
    # so the film stays true when a new month arrives; the beats pick their subjects (the province that added the
    # most jobs, the district first on money momentum) rather than naming them by hand.
    home = R["THA"]
    bkk = T["10"]
    gain = {k: t["insured"] - dict(t["ins_series"])[sso["years"][-2]] for k, t in T.items()}
    east_id = max(gain, key=gain.get)
    east = T[east_id]
    top_d = min((d for d in D if d.get("score") is not None), key=lambda d: d["rank"])
    weak = max(((k, home[k + "_rank"]) for k in lens_keys if home.get(k + "_rank")), key=lambda x: x[1])

    def centroid(rings):
        big_ring = max(rings, key=len)
        xs, ys = [p[0] for p in big_ring], [p[1] for p in big_ring]
        return (min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2

    film = {
        "duration": 43.0,
        "question": "Where is the money moving in Southeast Asia?",
        "countries": [{"n": r["name"], "s": round(r["score"], 1), "home": r["iso"] == "THA"}
                      for r in sorted(Rv, key=lambda r: -(r["score"] or 0))],
        "thai": {"viewBox": [round(TW), round(TH)], "provinces": [
            {"n": t["name"], "d": th_mini[k], "cx": round(centroid(th_rings[k])[0], 1), "cy": round(centroid(th_rings[k])[1], 1),
             "s": round(t["score"] or 0, 1), "rank": t.get("rank") or 77,
             "role": "bkk" if k == "10" else "east" if k == east_id else ""}
            for k, t in T.items() if k in th_mini]},
        "district": {"n": top_d["name_en"], "prov": T[top_d["prov"]]["name"], "dep": pct(top_d["dep_yoy"])},
        "notes": {"bkk": ["Bangkok", (f"{bkk['br_change']:+d} bank branches".replace("-", "−") if bkk["br_change"]
                                      else f"employers {pct(bkk['biz'])}")],
                  "east": [east["name"], f"+{gain[east_id]:,} formal jobs"]},
        "endline": "See every country, province and district",
    }
    caps = [
        (3.4, 8.4, "11 countries. Four kinds of movement."),
        (8.9, 12.2, f"{home['name']}: {ordinal(home['rank'])} of 11."),
        (12.4, 16.6, "But averages hide where money goes."),
        (16.8, 21.4, (f"Bangkok closed {abs(bkk['br_change'])} bank branches in a year." if (bkk["br_change"] or 0) < 0
                      else f"Bangkok: registered employers {pct(bkk['biz'])} in a year.")),
        (21.6, 26.6, f"{east['name']} added {gain[east_id]:,} formal jobs."),
        (26.8, 33.2, "Now rank all 77 provinces by momentum."),
        (33.4, 38.4, f"{top_d['name_en']}, {T[top_d['prov']]['name']}: deposits {pct(top_d['dep_yoy'])} in a year."),
        (38.6, 43.0, "Every country, province and district, on the site."),
    ]
    film["captions"] = [list(c) for c in caps]
    sources = [f"World Bank WDI, {home['money_year']}", f"Social Security Office, Dec {sso['years'][-1]}",
               f"Bank of Thailand district table, {month_label(latest)}"]
    transcript = "".join(f"<li><span class=\"num\">{int(a) // 60}:{int(a) % 60:02d}</span> {esc(txt)}</li>" for a, b, txt in caps)
    body = f"""
<section class="hero"><h1>Where the money moved</h1>
<p class="lede">A 43-second film drawn in code from this site's data. Every bar, province and number on screen is real; the captions are written from the latest figures each time the site is built.</p></section>
<section id="film" class="film">
  <div class="film-stage"><canvas width="1920" height="1080" role="img" aria-label="Animated chart film. The transcript below has every line."></canvas>
    <p class="film-cap" aria-hidden="true"></p></div>
  <div class="film-controls">
    <button type="button" class="btn film-play">Play</button>
    <label class="film-mute"><input type="checkbox" data-mute> Mute</label>
    <span class="film-bar" aria-hidden="true"><i></i></span>
  </div>
</section>
<section class="prose reveal"><h2>Transcript</h2><ol class="transcript">{transcript}</ol></section>
<section class="prose reveal"><h2>How it was made</h2>
<p>Directed with the method of <a href="https://github.com/lemomo-ai/lemo-opuscar">Lemo-Opuscar</a> (MIT) in its Data Storytelling grammar: the chart is the film, every mark is a real number, transitions are chart operations, and the sound is the data, each mark a pitch from its value, with two silences before the turns. Drawn on a canvas by a single function of time, so it can also be rendered frame by frame to video.</p>
<p>Data: {esc("; ".join(sources))}. Thailand's provinces: geoBoundaries / OCHA (CC BY 3.0 IGO).</p></section>
<script type="application/json" id="film-data">{json.dumps(film, ensure_ascii=False)}</script>
<script src="{U('/assets/film.js')}?v={meta['build_id']}" defer></script>
"""
    write("/film/", page(U("/film/"), "Where the money moved: a 43-second film | Where Money Moves",
                         first_sentences(f"{home['name']} ranks {ordinal(home['rank'])} of 11 Southeast Asian countries on momentum, but inside it money is moving. A 43-second data film drawn in code."),
                         body, meta, crumbs=[("Southeast Asia", "/"), ("Film", "/film/")]))

    # ── RANKINGS
    rk_index = []

    def ranking_page(key, title, desc, head, rows):
        body = (f'<section class="hero"><h1>{esc(title)}</h1><p class="lede">{esc(desc)}</p></section>'
                f'<section><div class="tablewrap"><table class="rank" data-sortable><thead><tr>{head}</tr></thead><tbody>{rows}</tbody></table></div></section>')
        path = f"/rankings/{key}/"
        CARDS[U(path)] = {"kicker": "Ranking", "map": next((m for pre, m in (("thailand", "th"), ("vietnam", "vn"), ("malaysia", "my"),
                                                                            ("philippines", "ph")) if key.startswith(pre)), "sea")}
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

    drows = ""
    for i, x in enumerate(sorted([x for x in DP.values() if x["people"] is not None], key=lambda x: -x["people"]), 1):
        nm = (f'<a href="{U(d_url(page_of[x["id"]]))}">{esc(x["name_en"])}</a>' if x["id"] in page_of else esc(x["name_en"]))
        drows += (f'<tr><td class="num pos">{i}</td><th scope="row">{nm}{native(x["name_th"])}<small>{esc(T[x["prov"]]["name"])}</small></th>'
                  f'<td class="num" data-v="{x["pop"]}">{x["pop"]:,}</td>' + value_cell(x["people"]) + value_cell(x["people_5y"]) + "</tr>")
    ranking_page("thailand-district-population-growth", "Thai districts by population growth",
                 f"All {nDP} districts with a figure, registered population December {dy[-2]} to December {dy[-1]}, with five years beside it.",
                 '<th scope="col" class="num">#</th><th scope="col">District</th><th scope="col" class="num"><button data-k="2">Population</button></th>'
                 '<th scope="col" class="num"><button data-k="3">One year</button></th><th scope="col" class="num"><button data-k="4">Five years</button></th>', drows)

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

    def mrow(m, pos):
        return (f'<tr><td class="num pos">{pos}</td><th scope="row"><a href="{U(m_url(m))}">{esc(m["name"])}</a>{native(m["native"], "ms")}</th>'
                f'<td data-v="{round(m["score"], 2) if m["score"] is not None else ""}">{score_pill(m["score"])}</td>'
                + value_cell(m["people"]) + value_cell(m["jobs"]) + value_cell(m["money"]) + "</tr>")
    ms = sorted(M.values(), key=lambda m: (m["score"] is None, -(m["score"] or 0)))
    ranking_page("malaysia-states", "Malaysian states by momentum",
                 "All 13 states and 3 federal territories, average rank across population, employment and real GDP growth.",
                 mhead, "".join(mrow(m, m.get("rank") or "–") for m in ms))
    for k, key, title in (("people", "malaysia-population-growth", "Malaysian states by population growth"),
                          ("jobs", "malaysia-job-growth", "Malaysian states by job growth"),
                          ("money", "malaysia-gdp-growth", "Malaysian states by real GDP growth")):
        srt = sorted([m for m in M.values() if m[k] is not None], key=lambda m: -m[k])
        ranking_page(key, title, f"{MY_DESC[k]}, {mlab[k][0]}.", mhead, "".join(mrow(m, i) for i, m in enumerate(srt, 1)))

    irows = ""
    for i, (m, d) in enumerate(sorted(inc_md, key=lambda x: -x[1]["income_growth"]), 1):
        irows += (f'<tr><td class="num pos">{i}</td><th scope="row"><a href="{U(m_url(m))}#districts">{esc(d["name"])}</a><small>{esc(m["name"])}</small></th>'
                  f'<td class="num" data-v="{d["income"]:.0f}">RM {d["income"]:,.0f}</td>' + value_cell(d["income_growth"])
                  + (f'<td class="num" data-v="{d["poverty"]}">{d["poverty"]:.1f}%</td>' if d["poverty"] is not None else '<td class="num" data-v="">–</td>')
                  + (f'<td class="num" data-v="{d["gini"]}">{d["gini"]:.3f}</td>' if d["gini"] is not None else '<td class="num" data-v="">–</td>') + "</tr>")
    ranking_page("malaysia-district-income-growth", "Malaysian districts by household income growth",
                 f"All {len(inc_md)} districts, median household income {iyr - 2} to {iyr} (nominal, a month), with absolute poverty and the Gini coefficient.",
                 '<th scope="col" class="num">#</th><th scope="col">District</th><th scope="col" class="num"><button data-k="2">Median income</button></th>'
                 '<th scope="col" class="num"><button data-k="3">Change</button></th><th scope="col" class="num"><button data-k="4">Poverty</button></th>'
                 '<th scope="col" class="num"><button data-k="5">Gini</button></th>', irows)

    def hrow(h, pos):
        return (f'<tr><td class="num pos">{pos}</td><th scope="row"><a href="{U(h_url(h))}">{esc(h["name"])}</a><small>{esc(h["region"])}</small></th>'
                f'<td data-v="{round(h["score"], 2) if h["score"] is not None else ""}">{score_pill(h["score"])}</td>'
                + value_cell(h["people"]) + value_cell(h["money"]) + f'<td class="num" data-v="{h["gdp_pc"]:.0f}">₱{h["gdp_pc"]:,.0f}</td></tr>')
    hs = sorted(H.values(), key=lambda h: (h["score"] is None, -(h["score"] or 0)))
    ranking_page("philippines-provinces", "Philippine provinces by momentum",
                 f"All {len(H)} provinces with their cities, average rank on census population growth and real GDP growth.",
                 hhead, "".join(hrow(h, h.get("rank") or "–") for h in hs))
    for k, key, title in (("people", "philippines-population-growth", "Philippine provinces by population growth"),
                          ("money", "philippines-gdp-growth", "Philippine provinces by real GDP growth")):
        srt = sorted([h for h in H.values() if h[k] is not None], key=lambda h: -h[k])
        ranking_page(key, title, f"{PH_DESC[k]}, {hlab[k][0]}.", hhead, "".join(hrow(h, i) for i, h in enumerate(srt, 1)))

    groups = [("Southeast Asia", "southeast-asia"), ("Thailand", "thailand-"), ("Vietnam", "vietnam-"),
              ("Malaysia", "malaysia-"), ("Philippines", "philippines-")]
    body = '<section class="hero"><h1>Rankings</h1><p class="lede">Every list on the site, as a sortable table.</p></section>'
    for gname, prefix in groups:
        items = [(p, t, d) for p, t, d in rk_index if p.split("/")[2].startswith(prefix)]
        body += (f'<section class="rk-group"><h2>{esc(gname)}</h2><ul class="rk-index">'
                 + "".join(f'<li><a href="{U(p)}"><b>{esc(t)}</b><span>{esc(d)}</span></a></li>' for p, t, d in items) + "</ul></section>")
    write("/rankings/", page(U("/rankings/"), "Rankings | Where Money Moves", "Sortable rankings of Southeast Asian countries, Thai provinces and districts, Vietnamese provinces, Malaysian states and Philippine provinces.",
                             body, meta, crumbs=[("Southeast Asia", "/"), ("Rankings", "/rankings/")]))

    # ── COMPARE (client-rendered from compare.json)
    cmp = {}
    for r in Rv:
        cmp[f"c-{r['iso']}"] = {"n": r["name"], "u": U(c_url(r)), "k": "Country", "s": r["score"],
                                **{k: r[k] for k in lens_keys}, **{k + "y": str(r[k + "_year"]) for k in lens_keys}}
        for k in lens_keys:
            cmp[f"c-{r['iso']}"][k + "p"], cmp[f"c-{r['iso']}"][k + "py"] = before("region", k, r["name"])
    for t in T.values():
        cmp[f"p-{t['id']}"] = {"n": t["name"], "a": t["native"], "u": U(p_url(t)), "k": "Thai province", "s": t["score"],
                               **{k: t[k] for k in lens_keys}, **{k + "y": asof[k] for k in lens_keys}}
        for k in lens_keys:
            cmp[f"p-{t['id']}"][k + "p"], cmp[f"p-{t['id']}"][k + "py"] = before("th", k, t["name"])
    for d in D:
        dser = [r_[1] for r_ in d["series"]]
        dprev = growth(dser[-13], dser[-25]) if len(dser) >= 25 else None
        cmp[f"d-{d['id']}"] = {"n": f"{d['name_en']}, {T[d['prov']]['name']}", "a": d["name_th"], "u": U(d_url(d)), "k": "Thai district",
                               "s": d.get("score"), "money": d["dep_yoy"], "moneyy": month_label(latest), "credit": d["cr_yoy"],
                               "moneyp": dprev, "moneypy": month_label(d["series"][-13][0]) if len(dser) >= 25 else ""}
    for v in V.values():
        cmp[f"v-{v['slug']}"] = {"n": f"{v['name']}, Vietnam", "a": v["native"], "u": U(v_url(v)), "k": "Vietnamese province", "s": v["score"],
                                 **{k: v[k] for k in vk}, **{k + "y": str(vlab[k][1]) for k in vk}}
        for k in vk:
            cmp[f"v-{v['slug']}"][k + "p"], cmp[f"v-{v['slug']}"][k + "py"] = before("vn", k, v["name"])
    for m in M.values():
        cmp[f"m-{m['slug']}"] = {"n": f"{m['name']}, Malaysia", "a": m["native"], "u": U(m_url(m)), "k": "Malaysian state", "s": m["score"],
                                 **{k: m[k] for k in lens_keys}, **{k + "y": str(mlab[k][1] or "") for k in lens_keys}}
        for k in ("people", "jobs", "money"):
            cmp[f"m-{m['slug']}"][k + "p"], cmp[f"m-{m['slug']}"][k + "py"] = before("my", k, m["name"])
    for h in H.values():
        cmp[f"h-{h['slug']}"] = {"n": f"{h['name']}, Philippines", "a": h["region"], "u": U(h_url(h)), "k": "Philippine province", "s": h["score"],
                                 **{k: h[k] for k in lens_keys}, **{k + "y": str(hlab[k][1] or "") for k in lens_keys}}
        cmp[f"h-{h['slug']}"]["moneyp"], cmp[f"h-{h['slug']}"]["moneypy"] = before("ph", "money", h["name"])
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
         f"People: registered population, Department of Provincial Administration, {base_of['people']} to {asof['people']}. Jobs: employees insured under Section 33 of the Social Security Act, {base_of['jobs']} to {asof['jobs']}. Businesses: employers registered with the Social Security Office, the same period. Money: commercial-bank deposits, Bank of Thailand district table, {base_of['money']} to {asof['money']}. Districts also carry registered population: DOPA publishes it by registry office, so a district is its own office plus the municipal parts of its tambons, placed with the registry's coded tambon file; districts add up exactly to their province."),
        ("The four lenses for Vietnam",
         f"From the National Statistics Office (formerly GSO). People: average population, {vlab['people'][0]}, with net migration per 1,000 residents alongside. Jobs: employed workers, {vlab['jobs'][0]}. Businesses: newly registered enterprises, {vlab['biz'][0]}. Money: net revenue of active enterprises, {vlab['money'][0]}, nominal. The latest year is often preliminary."),
        ("The lenses for Malaysia",
         f"From the Department of Statistics Malaysia (OpenDOSM). People: population estimates, {mlab['people'][0]}. Jobs: employed persons from the quarterly Labour Force Survey, {mlab['jobs'][0]}, so seasons cancel out. Money: real GDP at constant 2015 prices, {mlab['money'][0]}; output that cannot be placed in a state, mostly oil and gas, is left out of every state. Businesses: DOSM publishes no open business count by state, so the lens is blank and Momentum averages the other three. State pages list every district's population and, where the survey covers it, employment, with median household income, absolute poverty and the Gini coefficient from the Household Income Survey (2019, 2022, 2024; income is nominal). East Malaysia is drawn closer to the peninsula than it is."),
        ("The lenses for the Philippines",
         f"From the Philippine Statistics Authority (OpenSTAT). People: census population on 1 May 2020 and 1 July 2024, as a yearly rate. Money: real GDP from the Provincial Product Accounts, {hlab['money'][0]}, at constant 2018 prices. Jobs and businesses have no province series, so Momentum averages the two. PSA counts highly urbanized cities apart from their provinces; we add each to the province around it, and Metro Manila's seventeen cities into one, so every unit is a place on the map. Maguindanao is shown whole (it was split in 2022), with its two halves on its page. Islets smaller than about 15 km² are not drawn."),
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
    # the pipeline in one figure: where each number comes from, the gate it must pass, and what happens when it fails
    def node(x, y, w, title, sub, cls=""):
        return (f'<rect class="n{cls}" x="{x}" y="{y}" width="{w}" height="52" rx="10"/>'
                f'<text class="t" x="{x + w / 2}" y="{y + 22}" text-anchor="middle">{esc(title)}</text>'
                f'<text class="s" x="{x + w / 2}" y="{y + 40}" text-anchor="middle">{esc(sub)}</text>')

    def arrow(x1, y1, x2, y2, label, lx=None, ly=None, cls=""):
        lx = (x1 + x2) / 2 if lx is None else lx
        ly = min(y1, y2) - 8 if ly is None else ly
        return (f'<line class="a{cls}" x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" marker-end="url(#wmm-arrow)"/>'
                f'<text class="l" x="{lx}" y="{ly}" text-anchor="middle">{esc(label)}</text>')
    srcs = ["World Bank, 11 countries", "BOT, SSO, DOPA: Thailand", "NSO: Vietnam", "DOSM: Malaysia", "PSA: Philippines"]
    flow = "".join(f'<rect class="src" x="0" y="{40 + i * 46}" width="196" height="36" rx="8"/>'
                   f'<text class="s ink" x="14" y="{63 + i * 46}">{esc(t)}</text>'
                   f'<line class="a" x1="196" y1="{58 + i * 46}" x2="236" y2="176"/>' for i, t in enumerate(srcs))
    flow += (node(240, 150, 150, "Monthly refresh", "on the 15th")
             + node(440, 150, 150, "Checks", "columns and totals", " gate")
             + node(415, 26, 200, "Stop and report", "last good data stays live", " stop")
             + node(640, 150, 150, "Data pull request", "reviewed, then merged")
             + node(840, 150, 150, "Rank in country", "each lens a percentile")
             + node(840, 274, 150, "Momentum", "mean of lenses present")
             + arrow(390, 176, 436, 176, "parse")
             + arrow(515, 150, 515, 82, "fails", 540, 120, " fail")
             + arrow(590, 176, 636, 176, "passes")
             + arrow(790, 176, 836, 176, "build")
             + arrow(915, 202, 915, 270, "average", 950, 242))
    pipeline = (f'<figure class="pipeline"><div class="scroll"><svg viewBox="0 0 1000 340" role="img" '
                f'aria-label="Each source is fetched monthly and must pass column and total checks; if it fails the run stops and '
                f'the last good data stays live, if it passes a reviewed pull request publishes it; then every lens is ranked as a '
                f'percentile within its own country and Momentum is the mean of the lenses present.">'
                f'<defs><marker id="wmm-arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">'
                f'<path d="M0 0 10 5 0 10z" fill="currentColor"/></marker></defs>{flow}</svg></div>'
                f'<figcaption>A number reaches the site only through the checks: when a source changes shape or its parts stop adding '
                f'up to its total, the run stops and the last verified data stays published. Ranks never cross a border.</figcaption></figure>')
    body = ('<section class="hero"><h1>How the numbers work</h1><p class="lede">Public data only. Every figure on the site comes from one of the sources below, unchanged except for the arithmetic described here.</p></section>'
            + pipeline + "".join(f'<section class="prose reveal"><h2>{esc(h)}</h2><p>{esc(b)}</p></section>' for h, b in sections))
    write("/about/", page(U("/about/"), "Method and sources | Where Money Moves", "How Where Money Moves measures people, jobs, businesses and money across Southeast Asia.",
                          body, meta, crumbs=[("Southeast Asia", "/"), ("Method", "/about/")]))

    # ── share images: one card per page. The template holds every locator map once; tools/og_images.mjs photographs
    # it 1200×630 for each entry of og-data.json. Not linked, not in the sitemap, not indexed.
    og_maps = {"sea": sea_map(interactive=False), "th": th_map(mini=True), "vn": vn_map(mini=True),
               "my": my_map(mini=True), "ph": ph_map(mini=True)}
    (OUT / "og").mkdir(exist_ok=True)
    (OUT / "og" / "og-data.json").write_text(json.dumps(list(CARDS.values()), ensure_ascii=False, separators=(",", ":")))
    (OUT / "og" / "index.html").write_text(f"""<!doctype html>
<html lang="en" data-theme="light"><head><meta charset="utf-8"><meta name="robots" content="noindex">
<title>Share cards</title>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Bricolage+Grotesque:opsz,wght@12..96,700..750&family=Inter:wght@400..700&family=Noto+Sans+Thai:wght@400;500&display=swap">
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Noto+Sans+Khmer&family=Noto+Sans+Lao&family=Noto+Sans+Myanmar&text={NATIVE_GLYPHS}&display=swap">
<link rel="stylesheet" href="{U('/assets/app.css')}?v={meta['build_id']}">
<style>
  html, body {{ margin: 0; width: 1200px; height: 630px; overflow: hidden; background: var(--paper); }}
  *, *::before, *::after {{ transition: none !important; animation: none !important; }}   /* a photo, not a page: no fills mid-fade */
  .card {{ position: relative; width: 1200px; height: 630px; display: grid; grid-template-columns: 1fr 440px; }}
  .words {{ display: grid; grid-template-rows: auto 1fr auto; padding: 56px 0 52px 64px; min-width: 0; }}
  .brand {{ display: flex; align-items: center; gap: 12px; font: 700 24px var(--display); letter-spacing: -0.02em; color: var(--ink); }}
  .brand img {{ width: 34px; height: 34px; }}
  .mid {{ align-self: center; display: grid; gap: 14px; padding-right: 40px; min-width: 0; }}
  .kicker {{ font: 500 24px var(--body); color: var(--muted); }}
  h1 {{ margin: 0; font: 750 92px/0.98 var(--display); letter-spacing: -0.04em; color: var(--ink); white-space: nowrap; min-width: 0; overflow: hidden; }}
  h1.long {{ white-space: normal; text-wrap: balance; }}
  .native {{ font: 400 34px var(--native); color: var(--muted); margin: 0; display: block; }}
  .rank {{ font: 600 28px var(--body); color: var(--current); }}
  .line {{ font: 400 28px/1.35 var(--body); color: var(--muted); max-width: 640px; display: -webkit-box; -webkit-line-clamp: 3; -webkit-box-orient: vertical; overflow: hidden; }}
  .nums {{ display: flex; gap: 36px; }}
  .nums div {{ display: grid; gap: 2px; }}
  .nums span {{ font: 500 20px var(--body); color: var(--muted); }}
  .nums b {{ font: 700 40px var(--display); letter-spacing: -0.03em; color: var(--ink); }}
  .nums b.up {{ color: var(--current); }} .nums b.down {{ color: var(--ebb); }}
  .sea {{ background: var(--sea); display: grid; place-items: center; padding: 36px; }}
  .sea svg {{ width: 100% !important; height: 100% !important; max-width: 368px; max-height: 558px !important; display: none; }}
  .sea .map.sea {{ max-width: none; }}
  .sea circle.ring {{ display: block !important; fill: none; stroke: var(--current); stroke-width: 2.5; vector-effect: non-scaling-stroke; }}
  .sea svg.show {{ display: block; }}
  .sea .map.mini path, .sea .map.sea .units path, .sea .map.sea .units .dot {{ fill: color-mix(in srgb, var(--ink) 16%, var(--sea)); stroke: var(--sea); }}
  .sea .map.mini path.on, .sea .map.sea .on path, .sea .map.sea .on .dot {{ fill: var(--current); }}
  .sea .map.sea .sea-bg, .sea .map.sea .grat, .sea .map.sea .labels, .sea .map.sea .coords {{ display: none; }}
  .sea .map.sea .ctx path {{ fill: color-mix(in srgb, var(--ink) 7%, var(--sea)); stroke: none; }}
  .sea .map.mini circle {{ display: none; }}
</style></head>
<body><div class="card">
  <div class="words">
    <div class="brand"><img src="{U('/assets/icon.svg')}" alt="">Where Money Moves</div>
    <div class="mid"><div class="kicker"></div><h1></h1><span class="native"></span><div class="rank"></div><p class="line"></p></div>
    <div class="nums"></div>
  </div>
  <div class="sea">{"".join(svg.replace("<svg ", f'<svg data-map="{k}" ', 1) for k, svg in og_maps.items())}</div>
</div>
<script>
window.ogReady = (async () => {{
  window.CARDS = await (await fetch("og-data.json")).json();
  await document.fonts.ready;
  return CARDS.length;
}})();
window.card = async (i) => {{
  const c = CARDS[i], $ = (s) => document.querySelector(s);
  $(".kicker").textContent = c.kicker || "";
  const h = $("h1"); h.textContent = c.title; h.className = ""; h.style.fontSize = "";      // each card starts at full size
  for (let px = 92; px > 52 && h.scrollWidth > h.clientWidth; px -= 4) h.style.fontSize = px + "px";
  if (h.scrollWidth > h.clientWidth) {{ h.className = "long"; }}
  const nat = $(".native");
  nat.textContent = c.native && c.native !== c.title ? c.native : "";
  // Burmese, Khmer and Lao faces load only when their text appears: fetch them before the photograph
  if (nat.textContent) await document.fonts.load(`400 34px ${{getComputedStyle(nat).fontFamily}}`, nat.textContent);
  $(".rank").textContent = c.rank || "";
  $(".line").textContent = c.stats && c.stats.length ? "" : (c.line || "");
  $(".nums").replaceChildren(...(c.stats || []).map(([k, v, t]) => {{
    const d = document.createElement("div"); d.innerHTML = "<span></span><b></b>";
    d.firstChild.textContent = k; d.lastChild.textContent = v; d.lastChild.className = t || ""; return d; }}));
  document.querySelectorAll("[data-map]").forEach((m) => m.classList.toggle("show", m.dataset.map === c.map));
  document.querySelectorAll(".on").forEach((e) => e.classList.remove("on"));
  document.querySelectorAll("circle.ring").forEach((e) => e.remove());
  const svg = document.querySelector(`[data-map="${{c.map}}"]`);
  const hit = c.hl ? svg.querySelector(`[data-k="${{c.hl}}"]`) : null;
  if (hit) {{
    hit.classList.add("on");
    // a place too small to see at this size gets a ring (Bangkok, Metro Manila, Putrajaya, Singapore…)
    const b = hit.getBBox(), vb = svg.viewBox.baseVal, scale = svg.getBoundingClientRect().width / vb.width;
    if (Math.max(b.width, b.height) * scale < 26) {{
      const r = document.createElementNS("http://www.w3.org/2000/svg", "circle");
      r.setAttribute("class", "ring"); r.setAttribute("cx", b.x + b.width / 2); r.setAttribute("cy", b.y + b.height / 2);
      r.setAttribute("r", 18 / scale); svg.append(r);
    }}
  }}
  await document.fonts.ready;
  return c.key;
}};
</script></body></html>
""")

    # ── search index, manifest, sw, sitemap, 404
    idx = ([{"n": r["name"], "a": r["native"], "u": U(c_url(r)), "k": "Country"} for r in Rv]
           + [{"n": t["name"], "a": t["native"], "u": U(p_url(t)), "k": "Province"} for t in T.values()]
           + [{"n": d["name_en"], "a": f'{d["name_th"]}  {T[d["prov"]]["name"]}', "u": U(d_url(d)), "k": "District"} for d in D]
           + [{"n": v["name"], "a": v["native"], "u": U(v_url(v)), "k": "Province"} for v in V.values()]
           + [{"n": f, "a": f"now part of {v['name']}", "u": U(v_url(v)), "k": "Former province"}
              for v in V.values() if len(v["former"]) > 1 for f in v["former"] if f != v["native"]]
           + [{"n": m["name"], "a": m["native"] or "Malaysia", "u": U(m_url(m)), "k": "State"} for m in M.values()]
           + [{"n": d["name"], "a": f"{m['name']}, Malaysia", "u": U(m_url(m)) + "#districts", "k": "District"}
              for m in M.values() if len(m["districts"]) > 1 for d in m["districts"]]
           + [{"n": h["name"], "a": f"{h['region']}, Philippines", "u": U(h_url(h)), "k": "Province"} for h in H.values()]
           + [{"n": d["name"], "a": f"{h['name']}, Philippines", "u": U(h_url(h)) + "#places", "k": "City"}
              for h in H.values() for d in h["parts"] if d["name"] != h["name"]]
           + [{"n": t, "a": "", "u": U(p), "k": "Ranking"} for p, t, _ in rk_index]
           + [{"n": "Where the money moved", "a": "a 43-second film", "u": U("/film/"), "k": "Film"}])
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
    print(f"site/  {len(pages)} pages  {size/1e6:.1f}MB  region 11 · provinces {len(T)} · districts {len(D)} · vietnam {len(V)} · malaysia {len(M)} · philippines {len(H)}")


if __name__ == "__main__":
    main()
