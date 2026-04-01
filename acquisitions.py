#!/usr/bin/env python3
"""
acquisitions.py — Legal Layer Runner (Group 3: Layers 8–9)

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
PURPOSE
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Runs the two legal acquisition signal layers against every parcel in the
most recent scout.py results file and saves annotated output.

Layers applied:
  Layer 8 — Succession Fragmentation  (co-owner count via Catasto)    [PAID]
  Layer 9 — Owner Relocation Signal   (fiscal code decode + proxy)   [PAID + free]

Think of this as the third and final pass: scout.py found the parcels,
sentiment.py flagged operator fatigue, and acquisitions.py adds the legal
intelligence layer — who owns it, how many of them are there, and are
they local?

Usage:
    python3 acquisitions.py                               # uses most recent results JSON
    python3 acquisitions.py results_20260401_120000.json  # use a specific file

    # Stack on top of sentiment output:
    python3 acquisitions.py results_20260401_120000_sentiment.json

Output:
    results_<original_ts>_acquisitions.json
    results_<original_ts>_acquisitions.csv
"""

import csv
import json
import os
import sys
import glob
from datetime import datetime

import config
from layers.legal_layers.succession_fragmentation import SuccessionFragmentationLayer
from layers.legal_layers.owner_relocation         import OwnerRelocationLayer


# ── Layer registry ────────────────────────────────────────────────────────────
LEGAL_LAYERS = [
    SuccessionFragmentationLayer(),
    OwnerRelocationLayer(),
]


def _find_latest_results() -> str:
    """Return the path of the most recently written scout.py results JSON file."""
    project_dir = os.path.dirname(os.path.abspath(__file__))
    pattern     = os.path.join(project_dir, "results_*.json")
    candidates  = [f for f in glob.glob(pattern) if "_acquisitions" not in f]
    if not candidates:
        raise FileNotFoundError(
            "No results_*.json found. Run scout.py first to generate parcel data."
        )
    return max(candidates, key=os.path.getmtime)


def annotate_legal(parcels: list) -> list:
    """
    Run all enabled legal layers against each parcel and attach results.
    Results are flattened into the parcel dict under a `layer_<name>_*` namespace.
    """
    enabled_layers = [
        layer for layer in LEGAL_LAYERS
        if config.LAYERS.get(layer.name, True)
    ]

    print(f"  Legal layers active: {[l.label for l in enabled_layers]}")

    for i, parcel in enumerate(parcels, 1):
        for layer in enabled_layers:
            result = layer.run(parcel)
            prefix = f"layer_{result['layer']}"
            parcel[f"{prefix}_signal"] = result["signal"]
            parcel[f"{prefix}_score"]  = result["score"]
            parcel[f"{prefix}_detail"] = result["detail"]
            parcel[f"{prefix}_paid"]   = result["paid"]
            for k, v in result.get("data", {}).items():
                parcel[f"{prefix}_{k}"] = v

        if i % 10 == 0 or i == len(parcels):
            print(f"  Processed {i}/{len(parcels)} parcels...")

    return parcels


def print_legal_summary(parcels: list):
    """Print a compact console summary of legal layer hits."""
    print(f"\n{'═' * 70}")
    print(f"  Legal Layer Results  ·  {len(parcels)} parcel(s)")
    print(f"{'═' * 70}")

    for layer in LEGAL_LAYERS:
        if not config.LAYERS.get(layer.name, True):
            continue
        prefix  = f"layer_{layer.name}"
        hits    = sum(1 for p in parcels if p.get(f"{prefix}_signal"))
        paid_str = " [PAID FEATURE]" if layer.paid else ""
        print(f"  {layer.label:<30}{paid_str:<16}  {hits}/{len(parcels)} parcels flagged")

    print()

    def _legal_score(p):
        return sum(1 for layer in LEGAL_LAYERS
                   if p.get(f"layer_{layer.name}_signal"))

    ranked = sorted(parcels, key=_legal_score, reverse=True)
    print(f"  {'#':>3}  {'Name / GPS':<35}  {'Signals':>7}  Details")
    print(f"  {'─'*3}  {'─'*35}  {'─'*7}  {'─'*40}")
    for i, p in enumerate(ranked[:10], 1):
        score   = _legal_score(p)
        name    = (p.get("name") or p.get("gps_coordinates", ""))[:35]
        details = []
        for layer in LEGAL_LAYERS:
            if p.get(f"layer_{layer.name}_signal"):
                details.append(layer.label.split()[0])
        print(f"  {i:>3}  {name:<35}  {score:>7}  {', '.join(details)}")
    print()


def export_json(parcels: list, path: str):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(parcels, f, indent=2, ensure_ascii=False)


def export_csv(parcels: list, path: str):
    if not parcels:
        return
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=parcels[0].keys())
        writer.writeheader()
        writer.writerows(parcels)


def main(input_path: str = None):
    print(f"\n{'═' * 70}")
    print(f"  Parcel Scout  ·  Legal Layers  ·  {datetime.now().strftime('%Y-%m-%d  %H:%M:%S')}")
    print(f"{'═' * 70}\n")

    # ── Load parcels ──────────────────────────────────────────────────────────
    if input_path is None:
        input_path = _find_latest_results()
    print(f"  Loading: {os.path.basename(input_path)}")

    with open(input_path, encoding="utf-8") as f:
        parcels = json.load(f)
    print(f"  {len(parcels)} parcel(s) loaded\n")

    # ── Run legal layers ──────────────────────────────────────────────────────
    parcels = annotate_legal(parcels)

    # ── Summary ───────────────────────────────────────────────────────────────
    print_legal_summary(parcels)

    # ── Export ────────────────────────────────────────────────────────────────
    base     = os.path.basename(input_path).replace(".json", "")
    out_json = os.path.join(os.path.dirname(input_path), f"{base}_acquisitions.json")
    out_csv  = out_json.replace(".json", ".csv")
    export_json(parcels, out_json)
    export_csv(parcels, out_csv)
    print(f"  Saved → {os.path.basename(out_json)}")
    print(f"  Saved → {os.path.basename(out_csv)}\n")


if __name__ == "__main__":
    input_file = sys.argv[1] if len(sys.argv) > 1 else None
    main(input_file)
