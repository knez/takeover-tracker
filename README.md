# pno-cz

Monthly **podíl nezaměstnaných osob** (share of unemployed persons, PNO) for Czechia since January 2005, as a single-page app, with an illustrative projection of the [AI 2027](https://ai-2027.com/) scenario laid over it.

The page is one self-contained `index.html`. The data is embedded in it, so it works from GitHub Pages, from a local file, or anywhere else with no backend.

## Data

| Period | Source | Endpoint |
|---|---|---|
| 2005-01 – 2024-12 | Czech Statistical Office, dataset WADMUPCRMC (republishes MPSV figures) | `https://data.csu.gov.cz/api/dotaz/v1/data/sady/WADMUPCRMC` |
| 2025-01 onward | MPSV open-data portal, table `evid_pno_up_agr_frz_odata` | `https://data.mpsv.cz/portal/api/reports/by-table/evid_pno_up_agr_frz_odata/data/json?unbounded=true` |

The MPSV table is published per district and sex; the updater aggregates it to regions and the whole country as `available job seekers / population aged 15–64 × 100`. The two sources agree to three decimals at their December 2024 overlap.

`data/pno.json` holds the full snapshot (Czechia plus the 14 regions), `data/pno.csv` the national series.

## Updating

MPSV releases each month's figures around the 8th or 9th of the following month. The workflow in `.github/workflows/update.yml` runs every day from the 5th to the 16th, executes `scripts/update_data.py`, commits `index.html` and `data/` only when a new month has appeared, and redeploys GitHub Pages. It can also be run by hand from the Actions tab.

To refresh locally:

```
python3 scripts/update_data.py
```

Only the Python standard library is needed.

## AI 2027 projection

The scenario gives no unemployment numbers, only dated narrative milestones. The orange line is an estimate of what those milestones would mean for the Czech PNO indicator; the assumptions (displacement anchors, employment ratio, registration share, seasonality) are documented in the collapsible section at the bottom of the page and in the `SCEN` object in `index.html`. The projection is pinned to August 2026 so that actual months published afterwards run alongside it.
