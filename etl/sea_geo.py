"""
Southeast Asia country outlines for the regional map.

  python etl/sea_geo.py   → data/reference/sea.geo.json

Natural Earth 1:50m via world-atlas@2.0.2 (Natural Earth: public domain; world-atlas: ISC).
Keeps the 11 ASEAN+TL countries plus neighbours as grey context, simplified (Douglas–Peucker,
0.02°) and rounded to 0.01° — enough for a ~1000px-wide map and a ~90KB file.
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))
from etl import REF, HEADERS  # noqa: E402

URL = "https://cdn.jsdelivr.net/npm/world-atlas@2.0.2/countries-50m.json"
SEA = {"096": "BRN", "116": "KHM", "360": "IDN", "418": "LAO", "458": "MYS", "104": "MMR",
       "608": "PHL", "702": "SGP", "764": "THA", "626": "TLS", "704": "VNM"}
CONTEXT = {"156": "CHN", "356": "IND", "050": "BGD", "036": "AUS", "598": "PNG", "158": "TWN", "064": "BTN"}
BBOX = (88.0, -13.0, 146.0, 30.0)      # lon0, lat0, lon1, lat1
TOL = 0.02


def decode(topo):
    sx, sy = topo["transform"]["scale"]
    tx, ty = topo["transform"]["translate"]
    arcs = []
    for a in topo["arcs"]:
        x = y = 0
        pts = []
        for dx, dy in a:
            x += dx
            y += dy
            pts.append((x * sx + tx, y * sy + ty))
        arcs.append(pts)
    return arcs


def simplify(pts, tol):
    if len(pts) < 3:
        return pts
    (x1, y1), (x2, y2) = pts[0], pts[-1]
    dx, dy = x2 - x1, y2 - y1
    norm = math.hypot(dx, dy)
    best, idx = 0.0, 0
    for i in range(1, len(pts) - 1):
        x0, y0 = pts[i]
        d = (abs(dy * x0 - dx * y0 + x2 * y1 - y2 * x1) / norm) if norm else math.hypot(x0 - x1, y0 - y1)
        if d > best:
            best, idx = d, i
    if best > tol:
        return simplify(pts[:idx + 1], tol)[:-1] + simplify(pts[idx:], tol)
    return [pts[0], pts[-1]]


def main() -> int:
    topo = requests.get(URL, headers=HEADERS, timeout=60).json()
    arcs = decode(topo)

    def arc(i):
        return arcs[i] if i >= 0 else arcs[~i][::-1]

    out = {"source": "Natural Earth 1:50m via world-atlas@2.0.2 (public domain / ISC)", "features": []}
    for g in topo["objects"]["countries"]["geometries"]:
        gid = g.get("id")
        iso = SEA.get(gid) or CONTEXT.get(gid)
        if not iso:
            continue
        polys = [g["arcs"]] if g["type"] == "Polygon" else g["arcs"]
        rings = []
        for poly in polys:
            for ring_idx in poly:
                pts = []
                for k, i in enumerate(ring_idx):
                    seg = arc(i)
                    pts.extend(seg if k == 0 else seg[1:])
                if not any(BBOX[0] <= x <= BBOX[2] and BBOX[1] <= y <= BBOX[3] for x, y in pts):
                    continue
                far = max(range(len(pts)), key=lambda j: (pts[j][0] - pts[0][0]) ** 2 + (pts[j][1] - pts[0][1]) ** 2)
                s = simplify(pts[:far + 1], TOL)[:-1] + simplify(pts[far:], TOL)
                if len(s) >= 4:
                    rings.append([[round(x, 2), round(y, 2)] for x, y in s])
        if rings:
            out["features"].append({"iso3": iso, "sea": iso in SEA.values(), "rings": rings})
    missing = set(SEA.values()) - {f["iso3"] for f in out["features"]}
    if missing:
        raise RuntimeError(f"SEA countries missing from Natural Earth: {missing}")
    json.dump(out, open(REF / "sea.geo.json", "w"), separators=(",", ":"))
    print(f"sea.geo.json  {len(out['features'])} countries  {(REF / 'sea.geo.json').stat().st_size/1e3:.0f}KB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
