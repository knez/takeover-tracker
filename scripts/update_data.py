#!/usr/bin/env python3
"""Refresh the embedded unemployment data in index.html from public sources.

Sources (both CORS-open, no auth):
  * 2005-01 .. 2024-12  CSO (ČSÚ) JSON-stat dataset WADMUPCRMC, indicator 5973DI
  * 2025-01 onward      MPSV open-data portal table evid_pno_up_agr_frz_odata
                        (district x sex rows, aggregated here to regions and CZ)

Writes:
  index.html      the <script id="snapshot"> block is replaced in place
  data/pno.json   the same snapshot, pretty-printed
  data/pno.csv    month,pno for Czechia (convenience export)

Exit code is always 0. Prints `changed=true|false` and `asof=YYYY-MM` on the
last lines and, when running under GitHub Actions, appends them to $GITHUB_OUTPUT.
Only the Python standard library is used.
"""
import csv
import datetime as dt
import json
import os
import re
import sys
import urllib.request
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
INDEX = ROOT / "index.html"
DATA_DIR = ROOT / "data"

CSU_URL = "https://data.csu.gov.cz/api/dotaz/v1/data/sady/WADMUPCRMC"
MPSV_URL = ("https://data.mpsv.cz/portal/api/reports/by-table/"
            "evid_pno_up_agr_frz_odata/data/json?unbounded=true")

NAME2CODE = {
    "Hlavní město Praha": "CZ010", "Středočeský kraj": "CZ020", "Jihočeský kraj": "CZ031",
    "Plzeňský kraj": "CZ032", "Karlovarský kraj": "CZ041", "Ústecký kraj": "CZ042",
    "Liberecký kraj": "CZ051", "Královéhradecký kraj": "CZ052", "Pardubický kraj": "CZ053",
    "Kraj Vysočina": "CZ063", "Jihomoravský kraj": "CZ064", "Olomoucký kraj": "CZ071",
    "Zlínský kraj": "CZ072", "Moravskoslezský kraj": "CZ080",
}
ORDER = ["CZ", "CZ010", "CZ020", "CZ031", "CZ032", "CZ041", "CZ042", "CZ051",
         "CZ052", "CZ053", "CZ063", "CZ064", "CZ071", "CZ072", "CZ080"]


def fetch_json(url, timeout=60):
    req = urllib.request.Request(url, headers={"User-Agent": "takeover-tracker updater", "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


def parse_csu(js):
    """JSON-stat 2.0 -> {code: {label, map: {ym: value}}}"""
    ids, size, val = js["id"], js["size"], js["value"]
    dims = js["dimension"]
    i_ind, i_t, i_g = ids.index("IndicatorType"), ids.index("CasM"), ids.index("UZ02HU")
    ind = dims["IndicatorType"]["category"]["index"]["5973DI"]
    t_idx = dims["CasM"]["category"]["index"]
    g_idx = dims["UZ02HU"]["category"]["index"]
    g_lab = dims["UZ02HU"]["category"]["label"]
    strides = [1] * len(size)
    acc = 1
    for k in range(len(size) - 1, -1, -1):
        strides[k] = acc
        acc *= size[k]
    out = {}
    for code, gi in g_idx.items():
        m = {}
        for ym, ti in t_idx.items():
            if not re.fullmatch(r"\d{4}-\d{2}", ym):
                continue
            pos = [0] * len(size)
            pos[i_ind], pos[i_t], pos[i_g] = ind, ti, gi
            flat = sum(p * s for p, s in zip(pos, strides))
            v = val[flat] if isinstance(val, list) else val.get(str(flat))
            if v is not None:
                m[ym] = round(v, 3)
        out[code] = {"label": g_lab[code], "map": m}
    if "CZ" not in out:
        raise ValueError("CSU: CZ series missing")
    return out


def parse_mpsv(rows):
    """district x sex rows -> {code: {map: {ym: pno}}}, PNO = seekers / pop15-64 * 100"""
    agg = defaultdict(lambda: defaultdict(lambda: [0, 0]))
    for r in rows:
        ym = str(r.get("rozhodne_datum", ""))[:7]
        if not re.fullmatch(r"\d{4}-\d{2}", ym):
            continue
        a, b = r.get("pocet_uchazeci_dosazitelni"), r.get("pocet_obyvatel_vek_15_64")
        if not isinstance(a, (int, float)) or not isinstance(b, (int, float)):
            continue
        codes = ["CZ"]
        kc = NAME2CODE.get(r.get("kraj"))
        if kc:
            codes.append(kc)
        for c in codes:
            agg[c][ym][0] += a
            agg[c][ym][1] += b
    out = {}
    for c, months in agg.items():
        out[c] = {"map": {ym: round(100 * a / b, 3) for ym, (a, b) in months.items() if b > 0}}
    if "CZ" not in out:
        raise ValueError("MPSV: CZ series missing")
    return out


def add_months(ym, n):
    y, m = map(int, ym.split("-"))
    m0 = (m - 1) + n
    return f"{y + m0 // 12}-{m0 % 12 + 1:02d}"


def read_current_snapshot():
    html = INDEX.read_text(encoding="utf-8")
    m = re.search(r'<script type="application/json" id="snapshot">(.*?)</script>', html, re.S)
    if not m:
        raise ValueError("snapshot block not found in index.html")
    return html, m, json.loads(m.group(1))


def build_snapshot(base, csu, mpsv):
    regions = {}
    for code in ORDER:
        merged = {}
        # existing embedded data first, then live sources overlay (newer wins)
        if code in base.get("regions", {}):
            r = base["regions"][code]
            ym = r["start"]
            for v in r["values"]:
                if v is not None:
                    merged[ym] = v
                ym = add_months(ym, 1)
        if csu and code in csu:
            merged.update(csu[code]["map"])
        if mpsv and code in mpsv:
            merged.update(mpsv[code]["map"])
        if not merged:
            continue
        months = sorted(merged)
        start, end = months[0], months[-1]
        values, ym = [], start
        while ym <= end:
            values.append(merged.get(ym))
            ym = add_months(ym, 1)
        label = (base.get("regions", {}).get(code, {}).get("label")
                 or (csu and csu.get(code, {}).get("label")) or code)
        regions[code] = {"label": label, "start": start, "values": values}
    as_of = regions["CZ"]["start"]
    as_of = add_months(as_of, len(regions["CZ"]["values"]) - 1)
    return {"asOf": as_of, "fetched": dt.date.today().isoformat(), "regions": regions}


def main():
    html, m, base = read_current_snapshot()
    csu = mpsv = None
    try:
        csu = parse_csu(fetch_json(CSU_URL))
        print(f"CSU ok: CZ through {max(csu['CZ']['map'])}")
    except Exception as e:  # noqa: BLE001
        print(f"CSU failed: {e}", file=sys.stderr)
    try:
        mpsv = parse_mpsv(fetch_json(MPSV_URL, timeout=120))
        print(f"MPSV ok: CZ through {max(mpsv['CZ']['map'])}")
    except Exception as e:  # noqa: BLE001
        print(f"MPSV failed: {e}", file=sys.stderr)

    snap = build_snapshot(base, csu, mpsv)
    old_regions = base.get("regions")
    changed = snap["regions"] != old_regions

    if changed:
        new_html = html[:m.start(1)] + json.dumps(snap, ensure_ascii=False, separators=(",", ":")) + html[m.end(1):]
        INDEX.write_text(new_html, encoding="utf-8")
    DATA_DIR.mkdir(exist_ok=True)
    (DATA_DIR / "pno.json").write_text(json.dumps(snap, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    cz = snap["regions"]["CZ"]
    with (DATA_DIR / "pno.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["month", "pno_percent"])
        ym = cz["start"]
        for v in cz["values"]:
            w.writerow([ym, "" if v is None else v])
            ym = add_months(ym, 1)

    print(f"asof={snap['asOf']}")
    print(f"changed={'true' if changed else 'false'}")
    gh_out = os.environ.get("GITHUB_OUTPUT")
    if gh_out:
        with open(gh_out, "a", encoding="utf-8") as f:
            f.write(f"changed={'true' if changed else 'false'}\nasof={snap['asOf']}\n")


if __name__ == "__main__":
    main()
