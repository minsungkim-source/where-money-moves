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

- [x] Hosting: GitHub Pages, deployed by `pages.yml` on push to `main`
- [ ] Search Console + sitemap (note: robots.txt only counts at a domain root, so a sub-path site relies on the sitemap being submitted)
- [x] Monthly refresh workflow: tests → four ETLs → build → data PR with a summary (never auto-merge);
      failed sources → `source-failed` issue, overdue → `source-stale` issue
- [x] Parser regression tests + CI (`test.yml`)
- [x] DOPA switched to stat.bora (December 2025, one year fresher; 2020–2024 identical to the catalog)
- [ ] DOPA is unreachable from GitHub's runners: refresh it yearly from Thailand, or run a self-hosted runner there
- [ ] Owner setting: allow Actions to open PRs (otherwise the run leaves an issue with a one-click PR link)
- [ ] District-level population: map municipality (เทศบาล) registries to their districts, then add People to district pages

## v1.2 — Vietnam subnational ✓ (2026-10-27)

- [x] NSO PX-Web: population + net migration, employed, new enterprises, active enterprises, enterprise revenue
- [x] 63 → 34 crosswalk (2025 merger), checked against the national total every year; old provinces kept as a breakdown
- [x] Map merged from geoBoundaries TopoJSON by shared arcs; former borders drawn dashed
- [x] /vietnam/ explorer, 34 province pages, 5 rankings, home section, search finds former provinces, monthly refresh
- [ ] Vietnam has only province level (no district stats in PX-Web); a Money lens closer to Thailand's
      (bank credit by province) would need State Bank of Vietnam regional data

## v1.3 — Malaysia subnational (third country) ✓ (2026-11-02)

- [x] OpenDOSM CSVs on storage.dosm.gov.my (the data.gov.my API copy lagged: population stopped at 2023 there):
      state population to 2026, quarterly employed persons to Q2 2026, real GDP by state to 2025
- [x] Checks: column fingerprint, 16 states everywhere, states = nation (GDP with "Supra"), districts = state
- [x] `/malaysia/` explorer (full-width map, East Malaysia drawn closer and labelled), 16 state pages with every
      district's population and employment, 4 rankings, home section, search finds districts, monthly refresh
- [ ] Businesses lens is blank for Malaysia: no open state series. Candidates: SSM company registrations by state
      (published only as PDFs), or the OSM proxy below
- [ ] District GDP exists (`gdp_district_real_supply`, to 2020 only) and district household income (HIES 2022):
      district pages with a map would need geoBoundaries MYS ADM2 and a name match for 166 districts

## v1.5 — Philippines (fourth country) ✓ (2026-11-02)

- [x] PSA OpenSTAT (PX-Web, no key; needs a User-Agent): Provincial Product Accounts 2018–2025 by province and HUC,
      2020 and 2024 censuses
- [x] HUCs added to their host province, Metro Manila's 17 LGUs as one, Maguindanao whole (split 2022): 83 units that
      are all places on the map; the cities kept as a breakdown; EMBO barangays (Makati → Taguig, 2023) explained on the page
- [x] Map from geoBoundaries gbOpen PHL ADM2 merged by arcs; Sultan Kudarat patched from the simplified GeoJSON
- [ ] Jobs and Businesses blank at province level. Regional LFS exists only 2018–2021 on OpenSTAT; approved
      investments are by region only. A region layer (18) could carry them
- [ ] Indonesia (BPS) needs a registered API key: the owner would have to create one

## v1.4 — proxies where open data is thin

- [ ] Night-time lights (VIIRS monthly) as a common subnational Money proxy for countries without bank data
- [ ] OSM points of interest, year on year (Overpass attic), as a Businesses proxy outside Thailand
- [ ] Label every proxy on the page, next to the number

## Later

- [ ] Indonesia (BPS, 38 provinces / 514 kab/kota; API key needed)
- [ ] Screener with presets (franchise site, branch/agent expansion, factory land)
- [ ] LINE OA / email alerts for watched places
