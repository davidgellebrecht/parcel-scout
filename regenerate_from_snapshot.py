"""
Re-score the existing demo snapshot with every free layer enabled and
keep only the top N parcels by opportunity_score.

Why this exists separately from generate_demo_snapshot.py:
  - The full generator re-queries Overpass for airports, historic sites,
    and agricultural parcels — each of those can rate-limit for hours.
  - This script skips all that. It loads the parcels we already have,
    re-runs the (cheaper) Group-2 overlays + every free layer, and
    writes back the top N.

Run inside the Fly container:
  python regenerate_from_snapshot.py
"""

from __future__ import annotations

import json
import sys
import time
from datetime import datetime

import config
import storage

# Audit logging hits a SQLite FK that requires parcels to already exist
# in the parcels table — they don't here, so neuter the call.
storage.log_audit = lambda *a, **kw: None

from scout import (
    annotate_group2,
    fetch_distress_elements,
    fetch_named_estates,
    fetch_tourism_nodes,
)
from rank import run_all_layers, score_parcel, ALL_SIGNAL_KEYS


SNAPSHOT_PATH = "/app/data/demo_snapshot.json"
DEMO_BBOX     = (43.28, 11.27, 43.52, 11.68)
DEMO_REGION   = "Chianti Classico, Siena (DEMO), Italy"
TOP_N         = 3


def _safe_overpass(label: str, fn) -> list:
    """Run an Overpass-backed fetch; return [] on any failure."""
    try:
        result = fn()
        print(f"  ✓ {label}: {len(result):,}")
        return result
    except Exception as exc:
        print(f"  ⚠ {label} failed ({exc}) — continuing with empty list")
        return []


def main() -> int:
    t0 = time.time()

    config.REGION      = DEMO_REGION
    config.REGION_BBOX = DEMO_BBOX

    config.GROUP2["premium_wine_zone"] = True
    config.GROUP2["distress_signal"]   = True
    config.GROUP2["succession_signal"] = True
    config.GROUP2["lodging_overlay"]   = True

    FREE_LAYERS = {
        "napa_neighbor", "digital_ghost", "succession_stress",
        "elevation_aspect", "road_access", "water_access", "listing_check",
    }
    for k in config.LAYERS:
        config.LAYERS[k] = (k in FREE_LAYERS)

    print(f"Loading existing snapshot from {SNAPSHOT_PATH}…")
    with open(SNAPSHOT_PATH, encoding="utf-8") as fh:
        snap = json.load(fh)
    parcels   = snap["parcels"]
    total_raw = snap.get("total_raw", len(parcels))
    print(f"  ✓ {len(parcels)} parcels loaded")

    storage.start_scan("SEED", DEMO_REGION + " — demo regen (top N)")

    print()
    print("→ Fetching Group 2 overlays (best-effort; failures OK)…")
    distress = _safe_overpass("distress elements", fetch_distress_elements)
    estates  = _safe_overpass("named estates",     fetch_named_estates)
    tourism  = _safe_overpass("tourism nodes",     fetch_tourism_nodes)

    print()
    print("→ Re-annotating Group 2 signals on all parcels…")
    parcels = annotate_group2(parcels, distress, estates, tourism)

    print("→ Running every free layer on all parcels…")
    parcels = run_all_layers(parcels)

    # run_all_layers sets the per-signal flags but NOT opportunity_score —
    # score_parcel() does that, only counting signals that are currently active.
    for p in parcels:
        p["opportunity_score"] = score_parcel(p)
        p["signals_fired"]     = sum(1 for k in ALL_SIGNAL_KEYS if p.get(k))
    parcels.sort(key=lambda x: x["opportunity_score"], reverse=True)

    parcels = parcels[:TOP_N]
    print()
    print(f"→ Top {len(parcels)} parcels by opportunity_score:")
    for i, p in enumerate(parcels, 1):
        name = p.get("name") or p.get("gps_coordinates", "?")
        print(f"   {i}. score={p.get('opportunity_score', 0):.0f}  {name}")

    out = {
        "parcels":   parcels,
        "total_raw": total_raw,
        "saved_at":  datetime.now().isoformat(timespec="seconds"),
        "region":    DEMO_REGION,
    }
    with open(SNAPSHOT_PATH, "w", encoding="utf-8") as fh:
        json.dump(out, fh, default=str)

    elapsed = time.time() - t0
    print()
    print(f"✓ Wrote {SNAPSHOT_PATH}  ({len(parcels)} parcels, {elapsed:.0f}s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
