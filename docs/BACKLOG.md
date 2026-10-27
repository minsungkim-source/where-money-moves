# BACKLOG

Ship small, then widen. Top to bottom.

## v0 — Thailand MVP (2026-10-27) ✓

- [x] BOT district zip ETL, 43 months, two layouts, revised > preliminary, sum cross-checks
- [x] District name matching inside each province + 11-line alias table; unmatched → stop

## v1 — Southeast Asia, four lenses (2026-10-27) ✓

- [x] English only; native names alongside (Thai, Khmer, Lao, Burmese glyph subsets)
- [x] Region layer: 11 countries × People / Jobs / Businesses / Money from World Bank WDI
- [x] Thailand: DOPA registered population (People), SSO insured (Jobs), SSO employers (Businesses, proxy)
- [x] Momentum score per layer; layers never mixed on one axis
- [x] Interactive layer: lens tabs + FLIP ranking, tooltip / tap sheet, ⌘K palette, Watch → Compare,
      toasts, reveal + count-up, theme, share, PWA, view transitions, speculation rules
- [x] Public repository

## v1.1 — go live (needs the owner)

- [ ] Pick hosting: Vercel (`vercel.json`) or GitHub Pages (enable Pages, source "GitHub Actions", run `pages.yml`)
- [ ] Set `SITE_URL` / `BASE_PATH` for that host; Search Console + sitemap
- [ ] Monthly refresh workflow: run the four ETLs → open a data PR (never auto-merge)
- [ ] ETL regression tests with trimmed real fixtures (BOT layouts, SSO regions, DOPA duplicate table)

## v1.2 — Malaysia subnational (second country)

- [ ] OpenDOSM (data.gov.my, open API): population by state/district, labour force by state, GDP by state
- [ ] Proves the "one country at a time" structure: `/malaysia/{state}/`, its own layer and ranks

## v1.3 — proxies where open data is thin

- [ ] Night-time lights (VIIRS monthly) as a common subnational Money proxy for countries without bank data
- [ ] OSM points of interest, year on year (Overpass attic), as a Businesses proxy outside Thailand
- [ ] Label every proxy on the page, next to the number

## Later

- [ ] Vietnam (34 provinces after the 2025 merger: crosswalk needed), Indonesia (BPS, 514 kab/kota), Philippines (PSA)
- [ ] Screener with presets (franchise site, branch/agent expansion, factory land)
- [ ] LINE OA / email alerts for watched places
