# Where Money Moves

**See where people, jobs, businesses and money are moving across Southeast Asia.**

A static, English-only data site. Native place names (ชลบุรี, Việt Nam, កម្ពុជា …) sit beside the English ones.

- **Region**: 11 countries (ASEAN + Timor-Leste), ranked on four lenses with World Bank indicators
- **Thailand**: 77 provinces on all four lenses, 264 districts on monthly bank money
- 366 pages, each complete without JavaScript (search engines, slow phones). JS adds the interactive layer.

## The four lenses

| Lens | Countries (World Bank) | Thai provinces | Thai districts |
|---|---|---|---|
| People | urban population growth `SP.URB.TOTL` | registered population, DOPA (Dec, yearly) | – |
| Jobs | employed = labour force × (1 − unemployment) | Section 33 insured employees, SSO (Dec, yearly) | – |
| Businesses | new LLC registrations `IC.BUS.NREG` | employers registered with SSO (**proxy**) | – |
| Money | real GDP `NY.GDP.MKTP.KD` | bank deposits + credit, BOT (monthly) | bank deposits + credit, BOT |

**Momentum score** is the mean of per-lens percentile ranks *within a layer*: 11 countries, 77 provinces or 234 districts.
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
etl/th_dopa.py  DOPA registered population by province (zip → HTML table)       → data/processed/th_dopa.json
etl/sea_wb.py   World Bank WDI, 11 countries                                    → data/processed/sea_wb.json
etl/sea_geo.py  Natural Earth 1:50m outlines                                    → data/reference/sea.geo.json
```

Each source has a structure fingerprint and a total cross-check, and stops rather than publish a number it cannot verify:

- **BOT**: two sheet layouts, revised beats preliminary, deposit and credit parts sum to totals, masked `n.a.` cells
- **SSO**: the December title matches the year, exactly 77 provinces, and they sum to "Whole Kingdom"
- **DOPA**: Buddhist-year December period, provinces sum to the kingdom total, a duplicated table accepted only if identical

```bash
PY=../blindspot-th/etl/.venv/bin/python     # needs requests + openpyxl
$PY etl/etl.py && $PY etl/th_sso.py && $PY etl/th_dopa.py && $PY etl/sea_wb.py
$PY etl/sea_geo.py                           # rarely; outlines don't change
```

Add `--use-cache` to the first three to reuse `data/raw/` (gitignored, never committed).

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

Design notes live at the top of `static/app.css`. Project skills used while building are in `.claude/skills/`
(frontend-design, accessibility, seo, performance, programmatic-seo), each with its licence and `SOURCE.md`.

## Hosting

- **Vercel**: `vercel.json` runs `python3 build.py` and serves `site/`. Manual: `./deploy.sh`
- **GitHub Pages**: `.github/workflows/pages.yml`, run manually (Actions → Deploy to GitHub Pages) after Pages is
  enabled in the repository settings with source "GitHub Actions"

## Licences

Code: MIT. Data: World Bank WDI (CC BY 4.0); Bank of Thailand (attribution, aggregate publication);
SSO and DOPA (Open Data Common); Natural Earth (public domain); geoBoundaries/OCHA (CC BY 3.0 IGO);
thailand-canonical-admin-names (CC BY 4.0).
