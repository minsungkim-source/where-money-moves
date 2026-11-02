"""
Philippine province outlines for the units in ph_psa.py (provinces with their HUCs, Metro Manila as one, Isabela City).

  python etl/ph_geo.py   → data/reference/ph.geo.json

Source: geoBoundaries gbOpen PHL ADM2 (NAMRIA, PSA and OCHA Philippines via HDX, 2020, CC BY 3.0 IGO), TopoJSON, ~100MB:
run it rarely, it only changes when a province does. Merging works on the shared arcs, as in vn_geo.py:
  · Metro Manila's four districts become one unit; Cotabato City joins Maguindanao (PSA counts it there)
  · an arc with two different units (or the sea) on its sides is an outline; one inside a merged unit is dropped
  · the TopoJSON lost Sultan Kudarat (86 shapes, the metadata says 87); its outline comes from the same release's
    simplified GeoJSON, simplified with the same tolerance, so its borders meet the neighbours' within a third of a pixel
Display choice: islets under MIN_AREA are not drawn at this scale, but every unit keeps at least its largest island.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))
from etl import REF, OUT, HEADERS, ParserDriftError  # noqa: E402
from vn_geo import simplify  # noqa: E402

URL = ("https://github.com/wmgeolab/geoBoundaries/raw/9469f09/releaseData/gbOpen/"
       "PHL/ADM2/geoBoundaries-PHL-ADM2.topojson")
TOL = 0.008           # degrees, Douglas–Peucker per arc
MIN_AREA = 0.0012     # square degrees (~15 km²)
PATCH_URL = ("https://github.com/wmgeolab/geoBoundaries/raw/9469f09/releaseData/gbOpen/"
             "PHL/ADM2/geoBoundaries-PHL-ADM2_simplified.geojson")
PATCH = ("Sultan Kudarat",)
GB_UNIT = {"Compostela Valley": "davao-de-oro", "Cotabato City": "maguindanao", "City of Isabela": "city-of-isabela"}


def unit(name: str) -> str:
    if name.startswith("NCR"):
        return "metro-manila"
    return GB_UNIT.get(name) or re.sub(r"-+", "-", re.sub(r"[^a-z0-9]+", "-", name.lower())).strip("-")


def area(r):
    return abs(sum(x1 * y2 - x2 * y1 for (x1, y1), (x2, y2) in zip(r, r[1:] + r[:1]))) / 2


def main() -> int:
    print("downloading geoBoundaries PHL ADM2 (~100MB)…")
    topo = requests.get(URL, headers=HEADERS, timeout=600).json()
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

    want = set(json.load(open(OUT / "ph_psa.json"))["provinces"])
    geoms = list(topo["objects"].values())[0]["geometries"]
    patch = [f for f in requests.get(PATCH_URL, headers=HEADERS, timeout=300).json()["features"]
             if f["properties"]["shapeName"] in PATCH and f["properties"]["shapeName"] not in {g["properties"]["shapeName"] for g in geoms}]
    have = {unit(g["properties"]["shapeName"]) for g in geoms} | {unit(f["properties"]["shapeName"]) for f in patch}
    if have != want:
        raise ParserDriftError(f"boundary units ≠ PSA units: only in boundaries {sorted(have - want)}, only in PSA {sorted(want - have)}")

    users: dict[int, list[str]] = {}
    rings: dict[str, list] = {}
    for g in geoms:
        u = unit(g["properties"]["shapeName"])
        polys = [g["arcs"]] if g["type"] == "Polygon" else g["arcs"]
        for poly in polys:
            for ring in poly[:1]:
                pts = []
                for k, i in enumerate(ring):
                    seg = arcs[i] if i >= 0 else arcs[~i][::-1]
                    pts.extend(seg if k == 0 else seg[1:])
                    users.setdefault(i if i >= 0 else ~i, []).append(u)
                if len(pts) >= 4:
                    rings.setdefault(u, []).append(pts)
    for f in patch:
        u = unit(f["properties"]["shapeName"])
        polys = [f["geometry"]["coordinates"]] if f["geometry"]["type"] == "Polygon" else f["geometry"]["coordinates"]
        for poly in polys:
            pts = [(round(x, 3), round(y, 3)) for x, y in simplify([tuple(c[:2]) for c in poly[0]], TOL)]
            if len(pts) >= 4:
                rings.setdefault(u, []).append(pts)
    keep = {}
    for u, rs in rings.items():
        big = max(rs, key=area)
        keep[u] = [r for r in rs if area(r) >= MIN_AREA or r is big]
    # outline arcs: between two units, or on the coast of a ring we draw (not of a dropped islet)
    drawn = {pt for rs in keep.values() for r in rs for pt in r}
    outline = []
    for i, who in users.items():
        if len(who) == 2 and who[0] == who[1]:
            continue                                  # inside Metro Manila or Maguindanao
        line = arcs[i]
        if len(line) > 1 and (len(who) == 2 or line[0] in drawn):
            outline.append(line)
    outline += [r for f in patch for r in keep[unit(f["properties"]["shapeName"])]]
    out = {"source": "geoBoundaries gbOpen PHL ADM2 (NAMRIA, PSA, OCHA Philippines via HDX, 2020), CC BY 3.0 IGO",
           "provinces": {u: r for u, r in sorted(keep.items())}, "outline": outline}
    (REF / "ph.geo.json").write_text(json.dumps(out, separators=(",", ":")))
    print(f"ph.geo.json  {len(keep)} units  {sum(len(r) for r in keep.values())} rings  {len(outline)} outline arcs  "
          f"{(REF / 'ph.geo.json').stat().st_size / 1e3:.0f}KB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
