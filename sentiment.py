#!/usr/bin/env python3
"""
sentiment.py — Brand / Sentiment Layer Runner (Group 2: Layers 5–7)

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
PURPOSE
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Runs the three brand/sentiment acquisition signal layers against every
parcel in the most recent scout.py results file and saves annotated output.

Layers applied:
  Layer 5 — Hospitality Fatigue   (TripAdvisor review velocity)  [PAID]
  Layer 6 — Digital Ghosting      (WHOIS + Wayback CDX web decay) [free]
  Layer 7 — Terroir-to-Score Delta (soil quality vs critic score)  [PAID]

Think of this as a second pass over the scout.py results: scout.py found
the parcels that meet the hard physical requirements; sentiment.py adds
the brand intelligence layer that answers "is the current operator showing
signs of fatigue or disengagement?"

Usage:
    python3 sentiment.py                              # uses most recent results JSON
    python3 sentiment.py results_20260401_120000.json # use a specific file

Output:
    results_<original_ts>_sentiment.json
    results_<original_ts>_sentiment.csv
"""

import csv
import json
import os
import sys
import glob
from datetime import datetime

import config
from layers.brand_layers.hospitality_fatigue import HospitalityFatigueLayer
from layers.brand_layers.digital_ghost       import DigitalGhostLayer
from layers.brand_layers.terroir_score_delta import TerroirScoreDeltaLayer


# ── Layer registry ────────────────────────────────────────────────────────────
# Instantiate each layer once — they're stateless, so a single instance is fine.
SENTIMENT_LAYERS = [
    HospitalityFatigueLayer(),
    DigitalGhostLayer(),
    TerroirScoreDeltaLayer(),
]


def _find_latest_results() -> str:
    """Return the path of the most recently written scout.py results JSON file."""
    project_dir = os.path.dirname(os.path.abspath(__file__))
    pattern     = os.path.join(project_dir, "results_*.json")
    # Exclude files already annotated by this script
    candidates  = [f for f in glob.glob(pattern)
                   if "_sentiment" not in f and "_acquisitions" not in f]
    if not candidates:
        raise FileNotFoundError(
            "No results_*.json found. Run scout.py first to generate parcel data."
        )
    return max(candidates, key=os.path.getmtime)


def annotate_sentiment(parcels: list) -> list:
    """
    Run all enabled sentiment layers against each parcel and attach results.

    For each layer, the result dict is flattened into the parcel under a
    `layer_<name>_*` namespace so the CSV stays readable.
    Example: layer_digital_ghost_signal, layer_digital_ghost_detail, etc.
    """
    enabled_layers = [
        layer for layer in SENTIMENT_LAYERS
        if config.LAYERS.get(layer.name, True)
    ]

    print(f"  Sentiment layers active: {[l.label for l in enabled_layers]}")

    for i, parcel in enumerate(parcels, 1):
        for layer in enabled_layers:
            result = layer.run(parcel)
            prefix = f"layer_{result['layer']}"
            parcel[f"{prefix}_signal"] = result["signal"]
            parcel[f"{prefix}_score"]  = result["score"]
            parcel[f"{prefix}_detail"] = result["detail"]
            parcel[f"{prefix}_paid"]   = result["paid"]
            # Flatten data sub-dict with a deeper prefix
            for k, v in result.get("data", {}).items():
                parcel[f"{prefix}_{k}"] = v

        if i % 10 == 0 or i == len(parcels):
            print(f"  Processed {i}/{len(parcels)} parcels...")

    return parcels


def print_sentiment_summary(parcels: list):
    """Print a compact console summary of sentiment layer hits."""
    print(f"\n{'═' * 70}")
    print(f"  Sentiment Layer Results  ·  {len(parcels)} parcel(s)")
    print(f"{'═' * 70}")

    for layer in SENTIMENT_LAYERS:
        if not config.LAYERS.get(layer.name, True):
            continue
        prefix  = f"layer_{layer.name}"
        hits    = sum(1 for p in parcels if p.get(f"{prefix}_signal"))
        paid_str = " [PAID FEATURE]" if layer.paid else ""
        print(f"  {layer.label:<30}{paid_str:<16}  {hits}/{len(parcels)} parcels flagged")

    print()
    # Show top 10 parcels sorted by total sentiment signals fired
    def _sentiment_score(p):
        return sum(1 for layer in SENTIMENT_LAYERS
                   if p.get(f"layer_{layer.name}_signal"))

    ranked = sorted(parcels, key=_sentiment_score, reverse=True)
    print(f"  {'#':>3}  {'Name / GPS':<35}  {'Signals':>7}  Details")
    print(f"  {'─'*3}  {'─'*35}  {'─'*7}  {'─'*40}")
    for i, p in enumerate(ranked[:10], 1):
        score   = _sentiment_score(p)
        name    = (p.get("name") or p.get("gps_coordinates", ""))[:35]
        details = []
        for layer in SENTIMENT_LAYERS:
            if p.get(f"layer_{layer.name}_signal"):
                details.append(layer.label.split()[0])   # first word of label
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
    print(f"  Parcel Scout  ·  Sentiment Layers  ·  {datetime.now().strftime('%Y-%m-%d  %H:%M:%S')}")
    print(f"{'═' * 70}\n")

    # ── Load parcels ──────────────────────────────────────────────────────────
    if input_path is None:
        input_path = _find_latest_results()
    print(f"  Loading: {os.path.basename(input_path)}")

    with open(input_path, encoding="utf-8") as f:
        parcels = json.load(f)
    print(f"  {len(parcels)} parcel(s) loaded\n")

    # ── Run sentiment layers ───────────────────────────────────────────────────
    parcels = annotate_sentiment(parcels)

    # ── Summary ───────────────────────────────────────────────────────────────
    print_sentiment_summary(parcels)

    # ── Export ────────────────────────────────────────────────────────────────
    base     = os.path.basename(input_path).replace(".json", "")
    out_json = os.path.join(os.path.dirname(input_path), f"{base}_sentiment.json")
    out_csv  = out_json.replace(".json", ".csv")
    export_json(parcels, out_json)
    export_csv(parcels, out_csv)
    print(f"  Saved → {os.path.basename(out_json)}")
    print(f"  Saved → {os.path.basename(out_csv)}\n")


if __name__ == "__main__":
    input_file = sys.argv[1] if len(sys.argv) > 1 else None
    main(input_file)
