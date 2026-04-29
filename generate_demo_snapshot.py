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
    fetch_distress_elements,
    fetch_named_estates,
    fetch_tourism_nodes,
    filter_parcels,
    annotate_group2,
)
from rank import run_all_layers, score_parcel, ALL_SIGNAL_KEYS


# ── Demo config — mirror app.py's demo button ─────────────────────────────────
DEMO_BBOX   = (43.28, 11.27, 43.52, 11.68)
DEMO_REGION = "Chianti Classico, Siena (DEMO), Italy"

config.REGION      = DEMO_REGION
config.REGION_BBOX = DEMO_BBOX

config.FILTERS["proximity_to_airport"]    = True
config.FILTERS["agricultural_land"]       = True
config.FILTERS["min_square_footage"]      = True
config.FILTERS["historical_designation"]  = True

# All free GROUP 2 signals on — full free-tier comparison for the demo.
config.GROUP2["premium_wine_zone"] = True
config.GROUP2["distress_signal"]   = True
config.GROUP2["succession_signal"] = True
config.GROUP2["lodging_overlay"]   = True

# All free layers on; every paid layer off.
FREE_LAYERS = {
    "napa_neighbor", "digital_ghost", "succession_stress",
    "elevation_aspect", "road_access", "water_access", "listing_check",
}
for k in config.LAYERS:
    config.LAYERS[k] = (k in FREE_LAYERS)

# Demo cap — keep only the top N parcels by opportunity_score.
TOP_N = 3


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

    print("→ Fetching distress / estate / tourism overlays…")
    distress  = fetch_distress_elements()
    estates   = fetch_named_estates()
    tourism   = fetch_tourism_nodes()
    print(
        f"  ✓ {len(distress):,} distress  |  "
        f"{len(estates):,} estate(s)  |  {len(tourism):,} tourism node(s)"
    )

    print("→ Annotating Group 2 signals…")
    parcels = annotate_group2(parcels, distress, estates, tourism)

    print("→ Running acquisition layers (every free layer)…")
    parcels = run_all_layers(parcels)

    # run_all_layers sets per-signal flags but not opportunity_score.
    # Compute score + sort manually before slicing.
    for p in parcels:
        p["opportunity_score"] = score_parcel(p)
        p["signals_fired"]     = sum(1 for k in ALL_SIGNAL_KEYS if p.get(k))
    parcels.sort(key=lambda x: x["opportunity_score"], reverse=True)

    parcels = parcels[:TOP_N]
    print(f"→ Keeping top {len(parcels)} parcel(s) by opportunity_score:")
    for i, p in enumerate(parcels, 1):
        print(f"   {i}. score={p.get('opportunity_score', 0):.0f}  "
              f"{p.get('name') or p.get('gps_coordinates', '?')}")

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
