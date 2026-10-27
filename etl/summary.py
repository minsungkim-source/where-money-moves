"""
Markdown summary of what a data refresh changed — the body of the monthly data PR.

  python etl/summary.py [--base HEAD]   → stdout
  python etl/summary.py --changed       → exit 0 if the data really changed, 1 if not (timestamps ignored)
  python etl/summary.py --stale         → print overdue sources; exit 1 if any

Compares data/processed/* in the working tree with the same files at --base (default HEAD).
The reviewer should be able to merge or reject from this text alone: what moved, by how much,
and anything that looks wrong (a source stuck on an old month, coverage dropping, big swings).
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data" / "processed"
STALE_MONTHS = 6          # a monthly source this far behind today gets a warning


def old(name: str, base: str):
    try:
        out = subprocess.run(["git", "show", f"{base}:data/processed/{name}"], cwd=ROOT,
                             capture_output=True, check=True, text=True).stdout
        return json.loads(out)
    except (subprocess.CalledProcessError, json.JSONDecodeError):
        return None


def new(name: str):
    p = DATA / name
    return json.loads(p.read_text()) if p.exists() else None


FILES = ["meta.json", "districts.json", "provinces.json", "th_sso.json", "th_dopa.json", "sea_wb.json", "vn_gso.json"]


def strip_stamps(x):
    if isinstance(x, dict):
        return {k: strip_stamps(v) for k, v in x.items() if k != "generated_at"}
    if isinstance(x, list):
        return [strip_stamps(v) for v in x]
    return x


def changed(base: str) -> bool:
    return any(strip_stamps(old(f, base)) != strip_stamps(new(f)) for f in FILES)


def stale(today: date | None = None) -> list[str]:
    """Sources whose next release is overdue. Monthly: > STALE_MONTHS behind. Yearly (December figures):
    from July of year Y, December of Y-1 should be out."""
    today = today or date.today()
    out = []
    m = new("meta.json")
    if m and months_behind(m["latest"], today) > STALE_MONTHS:
        out.append(f"Bank of Thailand district data ends {m['latest']}, {months_behind(m['latest'], today)} months ago.")
    expect = today.year - 1 if today.month >= 7 else today.year - 2
    for name, label, hint in (("th_dopa.json", "DOPA registered population", " catalog.dopa.go.th blocks overseas runners: run `python etl/th_dopa.py` from a machine in Thailand and commit."),
                              ("th_sso.json", "SSO insured and employers", "")):
        d = new(name)
        if d and d["years"][-1] < expect:
            out.append(f"{label} ends December {d['years'][-1]}; December {expect} should be published by now.{hint}")
    return out


def months_behind(period: str, today: date | None = None) -> int:
    y, m = (int(x) for x in period.split("-"))
    t = today or date.today()
    return (t.year - y) * 12 + (t.month - m)


def pct(x) -> str:
    return "–" if x is None else f"{x * 100:+.2f}%"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="HEAD")
    ap.add_argument("--changed", action="store_true")
    ap.add_argument("--stale", action="store_true")
    args = ap.parse_args()
    if args.changed:
        return 0 if changed(args.base) else 1
    if args.stale:
        for line in stale():
            print(f"- {line}")
        return 1 if stale() else 0
    lines, warn = [], []

    # ── BOT districts (money)
    m0, m1 = old("meta.json", args.base), new("meta.json")
    if m1:
        was = m0["latest"] if m0 else "–"
        lines.append(f"### Money — Bank of Thailand, districts\n")
        lines.append(f"- Latest month: **{was} → {m1['latest']}**" + (" (revised file)" if not m1.get("latest_prelim") else " (preliminary)"))
        n0 = m0["national"]["n_covered"] if m0 else None
        n1 = m1["national"]["n_covered"]
        lines.append(f"- Districts in the latest table: {n0 if n0 is not None else '–'} → {n1}")
        lines.append(f"- Deposits, covered districts, year on year: {pct(m0['national']['dep_yoy']) if m0 else '–'} → {pct(m1['national']['dep_yoy'])}")
        if m0 and m0["latest"] == m1["latest"]:
            warn.append(f"BOT district file still ends at {m1['latest']} — no new month this run.")
        if months_behind(m1["latest"]) > STALE_MONTHS:
            warn.append(f"BOT district data is {months_behind(m1['latest'])} months behind today.")
        if n0 and n1 < n0 * 0.9:
            warn.append(f"Covered districts fell from {n0} to {n1} (more than 10%). Check the parser before merging.")
        d1 = new("districts.json") or []
        movers = sorted([d for d in d1 if d.get("score") is not None], key=lambda d: d["rank"])[:5]
        if movers:
            lines.append("- Top districts now: " + ", ".join(f"{d['name_en']} ({pct(d['dep_yoy'])})" for d in movers))
        spikes = [d["name_en"] for d in d1 if d.get("cr_yoy") is not None and abs(d["cr_yoy"]) > 0.5 and d["in_latest"]]
        if spikes:
            lines.append(f"- Credit swings over ±50% (flagged on site): {', '.join(spikes)}")
        lines.append("")

    # ── SSO (jobs, businesses)
    s0, s1 = old("th_sso.json", args.base), new("th_sso.json")
    if s1:
        ys = s1["years"]
        a, b = ys[-1], ys[-2]
        tot = lambda key, y: sum(p[str(y)][key] for p in s1["provinces"].values())
        lines.append("### Jobs and businesses — Social Security Office, provinces\n")
        lines.append(f"- Years: {s0['years'][0] if s0 else '–'}–{s0['years'][-1] if s0 else '–'} → **{ys[0]}–{ys[-1]}** (December)")
        lines.append(f"- Insured employees: {tot('insured', a):,} ({pct(tot('insured', a) / tot('insured', b) - 1)})")
        lines.append(f"- Registered employers: {tot('enterprises', a):,} ({pct(tot('enterprises', a) / tot('enterprises', b) - 1)})")
        lines.append("")

    # ── DOPA (people)
    p0, p1 = old("th_dopa.json", args.base), new("th_dopa.json")
    if p1:
        ys = p1["years"]
        tot = lambda y: sum(p[str(y)]["population"] for p in p1["provinces"].values())
        lines.append("### People — DOPA registered population, provinces\n")
        lines.append(f"- Years: {p0['years'][-1] if p0 else '–'} → **{ys[-1]}** (December)")
        lines.append(f"- Registered population: {tot(ys[-1]):,} ({pct(tot(ys[-1]) / tot(ys[-2]) - 1)})")
        lines.append("")

    # ── Vietnam NSO
    v0, v1 = old("vn_gso.json", args.base), new("vn_gso.json")
    if v1:
        lines.append("### Vietnam — National Statistics Office, 34 provinces\n")
        for key, label in (("pop", "Population"), ("employed", "Employed"), ("new_firms", "New enterprises"), ("revenue", "Enterprise revenue")):
            last = lambda d: max((int(y) for p in d["provinces"].values() for y in p["series"][key]), default=None) if d else None
            tot = lambda d, y: sum(p["series"][key].get(str(y), 0) for p in d["provinces"].values())
            y1 = last(v1)
            pre = " (preliminary)" if y1 in v1["preliminary"].get(key, []) else ""
            lines.append(f"- {label}: latest year {last(v0) or '–'} → **{y1}**{pre}, national {pct(tot(v1, y1) / tot(v1, y1 - 1) - 1)}")
        lines.append("")

    # ── World Bank (region)
    w0, w1 = old("sea_wb.json", args.base), new("sea_wb.json")
    if w1:
        lines.append("### Region — World Bank, 11 countries\n")
        for ind, label in (("SP.URB.TOTL", "People"), ("EMPLOYED", "Jobs"), ("IC.BUS.NREG", "Businesses"), ("NY.GDP.MKTP.KD", "Money")):
            latest = lambda w: max((int(y) for c in w["series"][ind].values() for y in c), default=None) if w else None
            lines.append(f"- {label} (`{ind}`): latest year {latest(w0) or '–'} → {latest(w1)}")
        lines.append("")

    warn += stale()
    head = ["## Monthly data refresh", ""]
    if warn:
        head += ["> [!WARNING]"] + [f"> {w}" for w in warn] + [""]
    head += ["Review the numbers below, then merge to publish. Merging deploys the site to GitHub Pages.", ""]
    print("\n".join(head + lines))
    return 0


if __name__ == "__main__":
    sys.exit(main())
