"""
Headless generator for the "Demo for Michael Kennedy" snapshot.

Runs the same scan the demo button would run, but with no Streamlit UI,
and writes the resulting parcels list to demo_snapshot.json at the
project root. The app's _load_demo_snapshot() helper falls back to that
location, so committing the JSON makes the demo instant on every deploy.

Usage:  python generate_demo_snapshot.py
"""

from __future__ import annotations

import json
import sys
import time
from datetime import datetime

import config
import storage

# filter_parcels and the layers call storage.log_audit, which has a SQLite FK
# constraint on parcel_id → parcels(id). In a fresh / partial run those rows
# may not exist yet, so audit inserts fail. We don't need audit rows for the
# snapshot, so neuter the call.
storage.log_audit = lambda *a, **kw: None

from scout import (
    fetch_airports,
    fetch_historic_sites,
    fetch_agricultural_parcels,
    filter_parcels,
    annotate_group2,
)
from rank import run_all_layers


# ── Demo config — mirror app.py's demo button ─────────────────────────────────
DEMO_BBOX   = (43.28, 11.27, 43.52, 11.68)
DEMO_REGION = "Chianti Classico, Siena (DEMO), Italy"

config.REGION      = DEMO_REGION
config.REGION_BBOX = DEMO_BBOX

config.FILTERS["proximity_to_airport"]    = True
config.FILTERS["agricultural_land"]       = True
config.FILTERS["min_square_footage"]      = True
config.FILTERS["historical_designation"]  = True

config.GROUP2["premium_wine_zone"] = True
config.GROUP2["distress_signal"]   = False
config.GROUP2["succession_signal"] = False
config.GROUP2["lodging_overlay"]   = False

# Layers — only Napa Neighbor on, like the demo
for k in config.LAYERS:
    config.LAYERS[k] = False
config.LAYERS["napa_neighbor"] = True


def main() -> int:
    t0 = time.time()
    print(f"Generating demo snapshot for {DEMO_REGION}")
    print(f"BBox: {DEMO_BBOX}")
    print()

    # filter_parcels and the layers call storage.log_audit, which requires an
    # active scan row to satisfy a foreign-key constraint. Open one for this run.
    storage.start_scan("SEED", DEMO_REGION + " — demo snapshot generator")

    print("→ Fetching airports…")
    airports = fetch_airports()
    print(f"  ✓ {len(airports)} airport(s)")

    print("→ Fetching historic sites…")
    historic_sites = fetch_historic_sites()
    print(f"  ✓ {len(historic_sites):,} historic site(s)")
    if not historic_sites:
        print("  ⚠ Got 0 historic sites — Overpass likely rate-limited.")
        print("    Re-run in a minute; do NOT save a 0-result snapshot.")
        return 1

    print("→ Fetching agricultural parcels…")
    raw = fetch_agricultural_parcels()
    print(f"  ✓ {len(raw):,} raw OSM element(s)")
    if not raw:
        print("  ⚠ Got 0 agricultural parcels — Overpass likely rate-limited.")
        return 1

    print("→ Applying hard filters…")
    parcels, skipped = filter_parcels(raw, airports, historic_sites)
    print(
        f"  ✓ {len(parcels)} parcel(s) passed  |  "
        f"no_geom: {skipped['no_geometry']}  area: {skipped['area']}  "
        f"airport: {skipped['airport']}  historic: {skipped['historic']}  "
        f"dups: {skipped.get('duplicates', 0)}"
    )

    if not parcels:
        print("  ⚠ Zero parcels after filtering — refusing to save snapshot.")
        return 1

    print("→ Annotating Group 2 signals…")
    parcels = annotate_group2(parcels, [], [], [])

    print("→ Running acquisition layers…")
    parcels = run_all_layers(parcels)

    out = {
        "parcels":   parcels,
        "total_raw": len(raw),
        "saved_at":  datetime.now().isoformat(timespec="seconds"),
        "region":    DEMO_REGION,
    }
    out_path = "demo_snapshot.json"
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(out, fh, default=str)

    elapsed = time.time() - t0
    size_kb = round(__import__("os").path.getsize(out_path) / 1024, 1)
    print()
    print(f"✓ Wrote {out_path}  ({len(parcels)} parcels, {size_kb} KB, {elapsed:.0f}s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
