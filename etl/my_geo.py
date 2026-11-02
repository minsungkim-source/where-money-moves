"""
Malaysia state outlines (13 states, 3 federal territories).

  python etl/my_geo.py   → data/reference/my.geo.json

Source: geoBoundaries gbHumanitarian MYS ADM1 (UNHCR via HDX, 2019, CC BY 3.0 IGO), TopoJSON. Arcs are simplified once
and shared by both neighbours, so borders stay identical. Coordinates stay in lon/lat; build.py draws East Malaysia
closer to the peninsula than it really is (an inset, labelled on the map).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))
from etl import REF, HEADERS, ParserDriftError  # noqa: E402
from vn_geo import simplify  # noqa: E402

URL = ("https://github.com/wmgeolab/geoBoundaries/raw/9469f09/releaseData/gbHumanitarian/"
       "MYS/ADM1/geoBoundaries-MYS-ADM1.topojson")
TOL = 0.006          # degrees, Douglas–Peucker per arc
MIN_AREA = 0.0004    # square degrees (~5 km²): smaller islands are not drawn at this scale
NAMES = {  # geoBoundaries shapeName → our slug (my_dosm.py)
    "Johor": "johor", "Kedeh": "kedah", "Kelantan": "kelantan", "Melaka": "melaka", "Negeri": "negeri-sembilan",
    "Pahang": "pahang", "Perak": "perak", "Perlis": "perlis", "Pulau Pinang": "penang", "Sabah": "sabah",
    "Sarawak": "sarawak", "Selangor": "selangor", "Terengganu": "terengganu", "W.P. Kuala Lumpur": "kuala-lumpur",
    "W.P. Labuan": "labuan", "W.P. Putrajaya": "putrajaya",
}


def area(r):
    return abs(sum(x1 * y2 - x2 * y1 for (x1, y1), (x2, y2) in zip(r, r[1:] + r[:1]))) / 2


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
        arcs.append([(round(px, 4), round(py, 4)) for px, py in simplify(pts, TOL)])

    geoms = list(topo["objects"].values())[0]["geometries"]
    names = {g["properties"]["shapeName"] for g in geoms}
    if names != set(NAMES):
        raise ParserDriftError(f"boundary names ≠ expected: {sorted(names ^ set(NAMES))}")
    rings: dict[str, list] = {}
    for g in geoms:
        slug = NAMES[g["properties"]["shapeName"]]
        polys = [g["arcs"]] if g["type"] == "Polygon" else g["arcs"]
        for poly in polys:
            for ring in poly[:1]:                 # outer rings only: no state has a hole worth drawing
                pts = []
                for k, i in enumerate(ring):
                    seg = arcs[i] if i >= 0 else arcs[~i][::-1]
                    pts.extend(seg if k == 0 else seg[1:])
                if len(pts) >= 4 and area(pts) >= MIN_AREA:
                    rings.setdefault(slug, []).append(pts)
    if len(rings) != 16:
        raise ParserDriftError(f"{len(rings)} states with shapes, expected 16")
    out = {"source": "geoBoundaries gbHumanitarian MYS ADM1 (UNHCR via HDX, 2019), CC BY 3.0 IGO",
           "states": {s: r for s, r in sorted(rings.items())}}
    (REF / "my.geo.json").write_text(json.dumps(out, separators=(",", ":")))
    print(f"my.geo.json  16 states  {sum(len(r) for r in rings.values())} rings  {(REF / 'my.geo.json').stat().st_size / 1e3:.0f}KB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
