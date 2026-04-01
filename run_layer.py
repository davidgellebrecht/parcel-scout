#!/usr/bin/env python3
"""
run_layer.py — Single-Layer CLI

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
PURPOSE
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Runs ONE acquisition layer against the most recent scout.py results and
prints a summary. Useful for testing a new layer or checking a specific
signal without re-running the full scout.py pipeline.

Think of it like a single instrument playing a chord on its own — you can
check the tuning before the full orchestra starts.

Usage:
    python3 run_layer.py <layer_name>
    python3 run_layer.py <layer_name> --json <path/to/results.json>
    python3 run_layer.py --list

Examples:
    python3 run_layer.py napa_neighbor
    python3 run_layer.py satellite_neglect
    python3 run_layer.py digital_ghost --json results_20260401_120000.json
    python3 run_layer.py --list

Available layer names:
    satellite_neglect     permit_paralysis      zoning_alchemy
    napa_neighbor         hospitality_fatigue   digital_ghost
    terroir_score_delta   succession_frag       owner_relocation
"""

import json
import os
import sys
import glob
from datetime import datetime

import config

# ── Layer registry ────────────────────────────────────────────────────────────
# Import all layers so we can look them up by name.
from layers.geo_layers.satellite_neglect      import SatelliteNeglectLayer
from layers.geo_layers.permit_paralysis       import PermitParalysisLayer
from layers.geo_layers.zoning_alchemy         import ZoningAlchemyLayer
from layers.geo_layers.napa_neighbor          import NapaNeighborLayer
from layers.brand_layers.hospitality_fatigue  import HospitalityFatigueLayer
from layers.brand_layers.digital_ghost        import DigitalGhostLayer
from layers.brand_layers.terroir_score_delta  import TerroirScoreDeltaLayer
from layers.legal_layers.succession_fragmentation import SuccessionFragmentationLayer
from layers.legal_layers.owner_relocation     import OwnerRelocationLayer

ALL_LAYERS = {
    layer.name: layer for layer in [
        SatelliteNeglectLayer(),
        PermitParalysisLayer(),
        ZoningAlchemyLayer(),
        NapaNeighborLayer(),
        HospitalityFatigueLayer(),
        DigitalGhostLayer(),
        TerroirScoreDeltaLayer(),
        SuccessionFragmentationLayer(),
        OwnerRelocationLayer(),
    ]
}


def _find_latest_results() -> str:
    """Return the path of the most recently written scout.py results JSON."""
    project_dir = os.path.dirname(os.path.abspath(__file__))
    pattern     = os.path.join(project_dir, "results_*.json")
    # Exclude annotated outputs
    candidates  = [f for f in glob.glob(pattern)
                   if "_sentiment" not in f and "_acquisitions" not in f]
    if not candidates:
        raise FileNotFoundError(
            "No results_*.json found. Run scout.py first to generate parcel data."
        )
    return max(candidates, key=os.path.getmtime)


def list_layers():
    """Print a table of all available layers."""
    print(f"\n  {'Layer Name':<26}  {'Label':<32}  Cost    Group")
    print(f"  {'─'*26}  {'─'*32}  {'─'*6}  {'─'*7}")
    groups = {
        ("satellite_neglect","permit_paralysis","zoning_alchemy","napa_neighbor"): "Geo",
        ("hospitality_fatigue","digital_ghost","terroir_score_delta"):             "Brand",
        ("succession_frag","owner_relocation"):                                    "Legal",
    }
    for names, group in groups.items():
        for name in names:
            layer = ALL_LAYERS[name]
            cost  = "PAID" if layer.paid else "free"
            on    = "ON " if config.LAYERS.get(layer.name, True) else "OFF"
            print(f"  {layer.name:<26}  {layer.label:<32}  {cost:<6}  {group} [{on}]")
    print()


def run_layer(layer_name: str, input_path: str = None):
    """Run a single named layer against all parcels and print results."""
    if layer_name not in ALL_LAYERS:
        print(f"\n  ERROR: Unknown layer '{layer_name}'")
        print(f"  Run 'python3 run_layer.py --list' to see available layers.\n")
        sys.exit(1)

    layer = ALL_LAYERS[layer_name]

    # ── Load results ──────────────────────────────────────────────────────────
    if input_path is None:
        input_path = _find_latest_results()

    print(f"\n{'═' * 70}")
    print(f"  {layer.label}  ·  {datetime.now().strftime('%Y-%m-%d  %H:%M:%S')}")
    if layer.paid:
        print(f"  ⚠  PAID FEATURE — see layer docstring for API setup instructions")
    print(f"{'═' * 70}")
    print(f"  Input: {os.path.basename(input_path)}")

    with open(input_path, encoding="utf-8") as f:
        parcels = json.load(f)
    print(f"  {len(parcels)} parcel(s) loaded\n")

    # ── Run layer ─────────────────────────────────────────────────────────────
    results = []
    for parcel in parcels:
        result = layer.run(parcel)
        results.append((parcel, result))

    # ── Summary table ─────────────────────────────────────────────────────────
    hits      = [r for _, r in results if r["signal"]]
    total     = len(results)
    hit_count = len(hits)

    print(f"  {'#':>3}  {'Signal':>7}  {'Score':>6}  {'Name / GPS':<35}  Detail")
    print(f"  {'─'*3}  {'─'*7}  {'─'*6}  {'─'*35}  {'─'*40}")

    for i, (parcel, result) in enumerate(results, 1):
        name   = (parcel.get("name") or parcel.get("gps_coordinates", ""))[:35]
        flag   = "  YES  " if result["signal"] else "   no  "
        score  = f"{result['score']:.2f}" if result["score"] is not None else "  —  "
        detail = result["detail"][:60]
        print(f"  {i:>3}  {flag}  {score:>6}  {name:<35}  {detail}")

    print(f"\n  {hit_count}/{total} parcels fired this layer")
    if hit_count > 0:
        print("\n  Top signals:")
        ranked = sorted(
            [(p, r) for p, r in results if r["signal"]],
            key=lambda x: (x[1]["score"] or 0),
            reverse=True,
        )
        for parcel, result in ranked[:5]:
            name = (parcel.get("name") or parcel.get("gps_coordinates", ""))[:50]
            print(f"    • {name}")
            print(f"      {result['detail']}")
    print()


def main():
    args = sys.argv[1:]

    if not args or "--list" in args:
        print("\n  Parcel Scout — 9-Layer Acquisition Engine")
        list_layers()
        if not args:
            print("  Usage: python3 run_layer.py <layer_name> [--json <path>]\n")
        return

    layer_name = args[0]
    input_path = None

    if "--json" in args:
        idx = args.index("--json")
        if idx + 1 < len(args):
            input_path = args[idx + 1]
        else:
            print("  ERROR: --json flag requires a file path argument.\n")
            sys.exit(1)

    run_layer(layer_name, input_path)


if __name__ == "__main__":
    main()
