"""
Vietnam province outlines for the 2025 boundaries (34), built from the 63 pre-merger provinces.

  python etl/vn_geo.py   → data/reference/vn.geo.json

Source: geoBoundaries gbHumanitarian VNM ADM1 (Government of Viet Nam via HDX, 2020, CC BY 3.0 IGO), TopoJSON.
Because TopoJSON shares each border arc between the two shapes it separates, merging needs no polygon union:
  · an arc whose sides belong to two different new provinces (or to one province and the sea) is an outline
  · an arc between two old provinces that merged into the same new one is a former border — drawn faint, dashed
Arcs are simplified once and reused by both neighbours, so shared borders stay identical.

Display choice: far-offshore archipelagos are not drawn at this map scale (rings entirely east of 109.6°E).
"""

from __future__ import annotations

import csv
import json
import math
import sys
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))
from etl import REF, HEADERS, ParserDriftError  # noqa: E402

URL = ("https://github.com/wmgeolab/geoBoundaries/raw/9469f09/releaseData/gbHumanitarian/"
       "VNM/ADM1/geoBoundaries-VNM-ADM1.topojson")
TOL = 0.008          # degrees, Douglas–Peucker per arc
EAST_LIMIT = 109.6


def simplify(pts, tol):
    if len(pts) < 3:
        return pts
    (x1, y1), (x2, y2) = pts[0], pts[-1]
    dx, dy = x2 - x1, y2 - y1
    norm = math.hypot(dx, dy)
    best, idx = 0.0, 0
    for i in range(1, len(pts) - 1):
        x0, y0 = pts[i]
        d = abs(dy * x0 - dx * y0 + x2 * y1 - y2 * x1) / norm if norm else math.hypot(x0 - x1, y0 - y1)
        if d > best:
            best, idx = d, i
    if best > tol:
        return simplify(pts[:idx + 1], tol)[:-1] + simplify(pts[idx:], tol)
    return [pts[0], pts[-1]]


def main() -> int:
    topo = requests.get(URL, headers=HEADERS, timeout=180).json()
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
        arcs.append([(round(px, 3), round(py, 3)) for px, py in simplify(pts, TOL)])

    cw = {r["gb_name"]: r["new_slug"] for r in csv.DictReader(
        l for l in open(REF / "vn_provinces_2025.csv", encoding="utf-8") if not l.startswith("#"))}
    geoms = list(topo["objects"].values())[0]["geometries"]
    names = {g["properties"]["shapeName"] for g in geoms}
    if names != set(cw):
        raise ParserDriftError(f"boundary names ≠ crosswalk: {sorted(names ^ set(cw))}")

    users: dict[int, list[str]] = {}          # arc → new provinces on each side
    rings: dict[str, list] = {}
    for g in geoms:
        slug = cw[g["properties"]["shapeName"]]
        polys = [g["arcs"]] if g["type"] == "Polygon" else g["arcs"]
        for poly in polys:
            for ring in poly:
                pts = []
                for k, i in enumerate(ring):
                    seg = arcs[i] if i >= 0 else arcs[~i][::-1]
                    pts.extend(seg if k == 0 else seg[1:])
                    users.setdefault(i if i >= 0 else ~i, []).append(slug)
                if all(x > EAST_LIMIT for x, _ in pts) or len(pts) < 4:
                    continue
                rings.setdefault(slug, []).append(pts)
    outline, former = [], []
    for i, who in users.items():
        line = arcs[i]
        if all(x > EAST_LIMIT for x, _ in line):
            continue
        (former if len(who) == 2 and who[0] == who[1] else outline).append(line)
    if len(rings) != 34:
        raise ParserDriftError(f"{len(rings)} provinces with shapes, expected 34")
    out = {"source": "geoBoundaries gbHumanitarian VNM ADM1 (Government of Viet Nam via HDX, 2020), CC BY 3.0 IGO",
           "provinces": {s: r for s, r in sorted(rings.items())}, "outline": outline, "former": former}
    (REF / "vn.geo.json").write_text(json.dumps(out, separators=(",", ":")))
    print(f"vn.geo.json  34 provinces  {len(outline)} outline arcs  {len(former)} former-border arcs  "
          f"{(REF / 'vn.geo.json').stat().st_size / 1e3:.0f}KB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
