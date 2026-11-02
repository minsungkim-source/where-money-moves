# Where Money Moves

**See where people, jobs, businesses and money are moving across Southeast Asia.**

A static, English-only data site. Native place names (ชลบุรี, Việt Nam, កម្ពុជា …) sit beside the English ones.

- **Region**: 11 countries (ASEAN + Timor-Leste), ranked on four lenses with World Bank indicators
- **Thailand**: 77 provinces on all four lenses, 264 districts on monthly bank money, all 928 districts on registered population
- **Vietnam**: 34 provinces (2025 boundaries) on all four lenses, rebuilt from the 63 former provinces
- **Malaysia**: 16 states and federal territories on three lenses (no open business series by state), 166 districts on
  population and employment
- **Philippines**: 83 provinces (each highly urbanized city counted with the province around it, Metro Manila as one)
  on two lenses, census population and real GDP
- 516 pages, each complete without JavaScript (search engines, slow phones). JS adds the interactive layer.

## The four lenses

| Lens | Countries (World Bank) | Thai provinces | Thai districts | Vietnamese provinces (NSO) | Malaysian states (DOSM) | Philippine provinces (PSA) |
|---|---|---|---|---|---|---|
| People | urban population growth `SP.URB.TOTL` | registered population, DOPA stat.bora (Dec, yearly) | registered population, the same files split by registry office | average population `V02.03-07` + net migration `V02.21-23` | population estimates `population_state` | census 2020 → 2024, a year |
| Jobs | employed = labour force × (1 − unemployment) | Section 33 insured employees, SSO (Dec, yearly) | – | employed workers `V02.45` | employed persons `lfs_qtr_state`, same quarter a year earlier | – (national survey only) |
| Businesses | new LLC registrations `IC.BUS.NREG` | employers registered with SSO (**proxy**) | – | newly registered enterprises `V05.02` | – (no open state series; left blank, never zero) | – |
| Money | real GDP `NY.GDP.MKTP.KD` | bank deposits + credit, BOT (monthly) | bank deposits + credit, BOT | enterprise net revenue `V05.23` (nominal) | real GDP `gdp_state_real_supply` (2015 prices) | real GDP, Provincial Product Accounts (2018 prices) |

**Momentum score** is the mean of per-lens percentile ranks *within a layer*: 11 countries, 77 Thai provinces,
234 Thai districts, 34 Vietnamese provinces, 16 Malaysian states or 83 Philippine provinces. A missing lens is left out of the mean.
Layers are never mixed on one axis, because national definitions differ.

### Proxies (where open data has a gap)

- **Businesses in Thailand**: the company register (DBD) has no clean province series in open data. Every employer
  with staff must register with the Social Security Office, so SSO enterprises are the business proxy.
- **People in Thailand**: *registered* population undercounts where people move without re-registering
  (Bangkok, EEC) and omits most migrant workers. Read it as a conservative signal.
- **Jobs in Thailand**: formal sector only. Informal work, roughly half of Thai employment, is not counted.

## Data pipeline

```
etl/etl.py      BOT district deposits/credit/branches (zip, 2023-01 → latest)  → data/processed/{meta,districts,provinces}.json
etl/th_sso.py   SSO enterprises + insured by province (xlsx per year)           → data/processed/th_sso.json
etl/th_dopa.py  DOPA registered population by province and district (stat.bora)  → data/processed/th_dopa.json
etl/th_dopa_xwalk.py  municipality × tambon → district, from DOPA's coded catalog  → data/reference/th_registry_tambon.csv
etl/vn_gso.py   Vietnam NSO PX-Web, 63 old provinces → 34 new                  → data/processed/vn_gso.json
etl/vn_geo.py   geoBoundaries VNM ADM1 TopoJSON, merged by shared arcs          → data/reference/vn.geo.json
etl/my_dosm.py  OpenDOSM CSVs: state population, quarterly LFS, real GDP, districts → data/processed/my_dosm.json
etl/my_geo.py   geoBoundaries MYS ADM1 TopoJSON (UNHCR via HDX)                 → data/reference/my.geo.json
etl/ph_psa.py   PSA OpenSTAT: provincial GDP + 2020/2024 censuses, HUCs → host  → data/processed/ph_psa.json
etl/ph_geo.py   geoBoundaries PHL ADM2 (NAMRIA/PSA via HDX), merged by arcs     → data/reference/ph.geo.json
etl/sea_wb.py   World Bank WDI, 11 countries                                    → data/processed/sea_wb.json
etl/sea_geo.py  Natural Earth 1:50m outlines                                    → data/reference/sea.geo.json
```

Each source has a structure fingerprint and a total cross-check, and stops rather than publish a number it cannot verify:

- **BOT**: two sheet layouts, revised beats preliminary, deposit and credit parts sum to totals, masked `n.a.` cells
- **SSO**: the December title matches the year, exactly 77 provinces, and they sum to "Whole Kingdom"
- **Vietnam**: the 63 provinces must be found by exact (diacritic-folded) name in every table, and must add up to the
  national total every year from 2010 (Hà Tây was separate before 2008). Crosswalk: `data/reference/vn_provinces_2025.csv`,
  verified against the 2025 merger list
- **Malaysia**: every file must keep the columns we read; the same 16 states in each; states add up to the national
  population, employed persons (every quarter) and GDP (with "Supra", output no state can claim); districts add up to
  their state. Labour-survey district spellings that differ are aliased by hand, anything else stops the run
- **Philippines**: every place a table lists must map to a unit (provinces by name, HUCs through a fixed host table);
  places add up to their region and regions to the Philippines, for both price bases and both censuses. The boundary
  units must equal the PSA units (the TopoJSON lost Sultan Kudarat, patched from the same release's GeoJSON)
- **DOPA**: the year page must list 77 provinces, male + female = total in every file; 2020–2024 match the old catalog exactly.
  Districts must add up to their province exactly; people that cannot be placed blank only the districts they could be in;
  December 2024 matches the catalog's coded tambon file in 926 of 928 districts (two differ by 1,301 people, see the script)

```bash
PY=../blindspot-th/etl/.venv/bin/python     # needs requests + openpyxl
$PY etl/etl.py && $PY etl/th_sso.py && $PY etl/th_dopa.py && $PY etl/vn_gso.py && $PY etl/my_dosm.py && $PY etl/ph_psa.py && $PY etl/sea_wb.py
$PY etl/sea_geo.py && $PY etl/vn_geo.py && $PY etl/my_geo.py && $PY etl/ph_geo.py   # rarely; outlines don't change
```

Add `--use-cache` to the first three to reuse `data/raw/` (gitignored, never committed).

### Monthly refresh

`.github/workflows/refresh-data.yml` runs on the 15th of each month (and on demand):
parser tests → every ETL → build → if the data really changed (timestamps ignored), a pull request
`data/monthly-refresh` with a summary written by `etl/summary.py`. **Nothing merges by itself**; merging
publishes through `pages.yml`. A failed source opens or updates a `source-failed` issue and keeps its last
data; an overdue source opens a `source-stale` issue.

DOPA's servers don't answer GitHub's runners (outside Thailand), so CI keeps the committed population data
and DOPA is refreshed from a machine in Thailand once a year: `python etl/th_dopa.py`, commit, push.

If the repository doesn't let Actions open pull requests, the run pushes the branch and opens a `data`
issue with a one-click link to create the PR. To let it open PRs directly: Settings → Actions → General →
"Allow GitHub Actions to create and approve pull requests".

Tests: `python -m unittest discover -s tests` (parser guards, name matching, real SSO/DOPA fixtures),
run by `test.yml` on every push and pull request.

## Site

```bash
python3 build.py                                                     # → site/  (stdlib only)
BASE_PATH=/where-money-moves SITE_URL=https://minsungkim-source.github.io python3 build.py   # sub-path hosting
python3 -m http.server 5180 -d site
$PY tools/make_assets.py                                             # icons + OG image (macOS: CoreText text)
```

Interactive layer (`static/app.js`, progressive enhancement):

- **Lenses** switch the map colour and reorder the ranking with a FLIP animation; the lens is kept in the URL hash
- **Map tooltip** on hover; on touch, a tap sheet (first tap shows numbers, second opens the page)
- **Search palette**: `/` or `⌘K`, English or native names
- **Watch → Compare**: up to six places, a toast with Undo, and a shareable `?ids=` link
- **Toasts** for watch, share, theme, install, offline/online and new data
- **Reveal and count-up** on scroll (Web Animations API with no fill, so the resting state is always visible)
- Theme toggle (system / dark / light), reading progress, view transitions, speculation-rules prerender
- PWA manifest and service worker (https only)

- **3D view** on the Thailand, Vietnam, Malaysia and Philippines explorers (`static/map3d.js`, three.js 0.169.0 self-hosted in
  `static/vendor/`, MIT): provinces extruded to their rank on the selected lens; loads only when "3D" is pressed
- **Film** `/film/` (`static/film.js`): a 43-second data film drawn in code, directed with the
  [Lemo-Opuscar](https://github.com/lemomo-ai/lemo-opuscar) method (Data Storytelling grammar). Captions and subjects are
  chosen from the data at build time; Web Audio sonification; `window.wmmFilmRender(t)` renders any frame for export.
  Treatment and credits: `docs/film/`. To export a 1080p mp4 (needs Chrome and ffmpeg 7+, no packages):
  `python build.py && node tools/film_mp4.mjs` → `dist/where-the-money-moved.mp4` (frames and sound come from the page itself)

Design notes live at the top of `static/app.css`. Project skills used while building are in `.claude/skills/`
(frontend-design, accessibility, seo, performance, programmatic-seo), each with its licence and `SOURCE.md`.

## Hosting

Live on **GitHub Pages**: <https://minsungkim-source.github.io/where-money-moves/>.
`.github/workflows/pages.yml` builds and deploys on every push to `main` (`BASE_PATH=/where-money-moves`).
`vercel.json` and `./deploy.sh` remain as an alternative host.

## Licences

Code: MIT. Data: World Bank WDI (CC BY 4.0); Bank of Thailand (attribution, aggregate publication);
SSO and DOPA (Open Data Common); National Statistics Office of Viet Nam (attribution); Natural Earth (public domain); geoBoundaries/OCHA and Government of Viet Nam via HDX (CC BY 3.0 IGO);
thailand-canonical-admin-names (CC BY 4.0).
