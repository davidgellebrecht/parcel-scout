#!/usr/bin/env python3
"""
rank.py — Full Pipeline Runner + Opportunity Ranker

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Single command that runs the entire Parcel Scout pipeline end-to-end:

  1. OSM scan          — finds parcels passing all Group 1 hard filters
  2. Group 2 signals   — annotates with wine zone, distress, succession, lodging
  3. All 9 layers      — runs every geo / brand / legal acquisition signal
  4. Opportunity Score — 0–100, equal-weighted across all 13 signals
  5. Ranked output     — ALL parcels printed best-first, exported to CSV + JSON

Usage:
    python3 rank.py

Output files:
    ranked_<timestamp>.csv   — all fields, sorted by opportunity_score desc
    ranked_<timestamp>.json  — same

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
SIGNAL INVENTORY — 13 signals, equal weight (100/13 ≈ 7.69 pts each)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Group 2 (scout.py):
  g2_premium_wine_zone       DOCG zone ($150+ bottles)
  g2_distress_signal         Fire history or abandoned land nearby
  g2_succession_signal       Italian estate naming pattern nearby
  g2_lodging_overlay         Tourism/hospitality precedent nearby

Geo Layers 1–4:
  layer_satellite_neglect    NDVI vigor below neighborhood baseline
  layer_permit_paralysis     Stalled renovation permit applications
  layer_zoning_alchemy       Zone E eligible + agriturismo intent
  layer_napa_neighbor        Within 8 km of marquee estate acquisition

Brand Layers 5–7:
  layer_hospitality_fatigue  Declining review scores / cadence
  layer_digital_ghost        Website / domain decay
  layer_terroir_score_delta  Soil quality vs critic score gap

Legal Layers 8–9:
  layer_succession_frag      Multiple co-owners (fragmented title)
  layer_owner_relocation     Owner fiscal address far from parcel
"""

import csv
import json
import sys
import os
from datetime import datetime

import config

# ── Import scout.py pipeline functions ────────────────────────────────────────
# We call scout.py's individual functions directly rather than running it as a
# subprocess. This keeps everything in memory — no intermediate files needed.
from scout import (
    fetch_airports,
    fetch_historic_sites,
    fetch_agricultural_parcels,
    fetch_broad_landuse,
    fetch_distress_elements,
    fetch_named_estates,
    fetch_tourism_nodes,
    filter_parcels,
    annotate_group2,
    print_banner,
)

# ── Import all 9 layer classes ────────────────────────────────────────────────
from layers.geo_layers.satellite_neglect          import SatelliteNeglectLayer
from layers.geo_layers.permit_paralysis           import PermitParalysisLayer
from layers.geo_layers.zoning_alchemy             import ZoningAlchemyLayer
from layers.geo_layers.napa_neighbor              import NapaNeighborLayer
from layers.brand_layers.hospitality_fatigue      import HospitalityFatigueLayer
from layers.brand_layers.digital_ghost            import DigitalGhostLayer
from layers.brand_layers.succession_stress        import SuccessionStressLayer
from layers.brand_layers.terroir_score_delta      import TerroirScoreDeltaLayer
from layers.legal_layers.succession_fragmentation import SuccessionFragmentationLayer
from layers.legal_layers.owner_relocation         import OwnerRelocationLayer

# ── Layer registry ────────────────────────────────────────────────────────────
# Execution order is intentional:
#   1. Free / instant layers first — no API credits consumed, fast
#   2. Free-tier API layers next — consume monthly/daily quotas, run only when needed
#   3. Partially-paid layers after — free component still runs, paid adds depth
#   4. Fully-paid / no free tier last — skip unless credentials are set
#
# This order means: if the scan is interrupted early, credits are spent
# only on parcels that have already shown promise from the free signals.
ALL_LAYERS = [
    # ── Tier 0: Free, no external API ─────────────────────────────────────────
    NapaNeighborLayer(),              # free — hardcoded proximity math, instant
    DigitalGhostLayer(),              # free — WHOIS + Wayback CDX (public APIs)
    SuccessionStressLayer(),          # free — Wayback CDX + OpenCorporates Italian registry
    # ── Tier 1: Free-tier APIs (quota-based) ──────────────────────────────────
    HospitalityFatigueLayer(),        # free tier — TripAdvisor 5,000 req/month
    TerroirScoreDeltaLayer(),         # free tier — Wine-Searcher 100 req/day ← most constrained
    SuccessionFragmentationLayer(),   # free tier — OpenAPI.it Catasto
    # ── Tier 2: Partially paid (free component always runs) ───────────────────
    ZoningAlchemyLayer(),             # free: Regione Toscana WFS; paid: Albo Pretorio
    OwnerRelocationLayer(),           # free: fiscal code decode; paid: cadastral contact
    # ── Tier 3: Fully paid, no free tier ──────────────────────────────────────
    SatelliteNeglectLayer(),          # paid — Sentinel Hub NDVI (30-day trial)
    PermitParalysisLayer(),           # paid — Albo Pretorio commercial aggregator
]

# ── All 13 signal keys used in the Opportunity Score ─────────────────────────
# Order here is cosmetic only — scoring uses a simple count.
ALL_SIGNAL_KEYS = [
    # Group 2 signals (computed by scout.py)
    "g2_premium_wine_zone",
    "g2_distress_signal",
    "g2_succession_signal",
    "g2_lodging_overlay",
    # Geo layers 1–4
    "layer_satellite_neglect_signal",
    "layer_permit_paralysis_signal",
    "layer_zoning_alchemy_signal",
    "layer_napa_neighbor_signal",
    # Brand layers 5–7
    "layer_hospitality_fatigue_signal",
    "layer_digital_ghost_signal",
    "layer_succession_stress_signal",
    "layer_terroir_score_delta_signal",
    # Legal layers 8–9
    "layer_succession_frag_signal",
    "layer_owner_relocation_signal",
]

# Human-readable short labels matching the same order as ALL_SIGNAL_KEYS.
# Used in the "signals fired" display row under each ranked parcel.
SIGNAL_LABELS = [
    "DOCG zone",
    "Distress",
    "Succession",
    "Lodging",
    "NDVI neglect",
    "Permit stall",
    "Zone E",
    "Napa neighbor",
    "Host. fatigue",
    "Digital ghost",
    "Succession stress",
    "Terroir delta",
    "Co-owners",
    "Owner reloc.",
]


# ─── Scoring ──────────────────────────────────────────────────────────────────

def score_parcel(parcel: dict) -> float:
    """
    Equal-weighted Opportunity Score: each of the 13 signals is worth
    100/13 ≈ 7.69 points. A parcel with no signals scores 0; all signals
    would score 100.

    PAID-feature signals that can't currently fire return signal=False,
    so they simply don't contribute — they never inflate OR deflate scores.
    Adding credentials in future will only push scores upward.
    """
    fired = sum(1 for key in ALL_SIGNAL_KEYS if parcel.get(key))
    return round((fired / len(ALL_SIGNAL_KEYS)) * 100, 1)


def signals_fired_list(parcel: dict) -> list:
    """Return the short labels of every signal that fired for this parcel."""
    return [
        label for key, label in zip(ALL_SIGNAL_KEYS, SIGNAL_LABELS)
        if parcel.get(key)
    ]


# ─── Layer annotation ─────────────────────────────────────────────────────────

def run_all_layers(parcels: list) -> list:
    """
    Run all 9 layers against every parcel and attach result fields.
    Fields are flattened into the parcel dict under `layer_<name>_*` namespace,
    identical to how sentiment.py and acquisitions.py work.
    """
    enabled = [l for l in ALL_LAYERS if config.LAYERS.get(l.name, True)]
    total   = len(parcels)

    for i, parcel in enumerate(parcels, 1):
        for layer in enabled:
            result = layer.run(parcel)
            prefix = f"layer_{result['layer']}"
            parcel[f"{prefix}_signal"] = result["signal"]
            parcel[f"{prefix}_score"]  = result["score"]
            parcel[f"{prefix}_detail"] = result["detail"]
            parcel[f"{prefix}_paid"]   = result["paid"]
            for k, v in result.get("data", {}).items():
                parcel[f"{prefix}_{k}"] = v

        if i % 5 == 0 or i == total:
            sys.stdout.write(f"\r  Running layers... {i}/{total} parcels")
            sys.stdout.flush()

    print()  # newline after progress
    return parcels


# ─── Output ───────────────────────────────────────────────────────────────────

def print_ranked(parcels: list):
    """
    Print every parcel ranked by Opportunity Score, highest first.
    Each entry shows: rank, score, signals/13, crop type, acreage, airport
    distance, name/GPS, then a line showing which specific signals fired.
    """
    total_signals = len(ALL_SIGNAL_KEYS)

    print(f"\n{'═' * 78}")
    print(f"  Parcel Scout  ·  Opportunity Rankings  ·  {config.REGION}")
    print(f"  {datetime.now().strftime('%Y-%m-%d  %H:%M:%S')}  "
          f"·  {len(parcels)} parcel(s) qualifying all hard filters")
    print(f"  Score = signals fired / {total_signals} possible  "
          f"(equal weight, {100/total_signals:.1f} pts each)")
    print(f"{'═' * 78}\n")

    header = (f"  {'Rank':>4}  {'Score':>8}  {'Sigs':>5}  "
              f"{'Crop':^16}  {'Acres':>6}  {'Airport':>7}  Identity")
    divider = (f"  {'─'*4}  {'─'*8}  {'─'*5}  "
               f"{'─'*16}  {'─'*6}  {'─'*7}  {'─'*34}")
    print(header)
    print(divider)

    for rank, p in enumerate(parcels, 1):
        score   = p["opportunity_score"]
        fired   = p["signals_fired"]
        crop    = p.get("primary_crop_type", "")[:16]
        acres   = p.get("parcel_acres", 0)
        airport = p.get("dist_airport_km", 0)
        name    = (p.get("name") or p.get("gps_coordinates", ""))[:34]

        # Score bar: visual fill proportional to score
        bar_len    = 12
        filled     = round(score / 100 * bar_len)
        score_bar  = "█" * filled + "░" * (bar_len - filled)
        score_str  = f"{score:>5.1f}/100"

        print(f"  {rank:>4}  {score_str}  {fired:>2}/{total_signals}  "
              f"{crop:^16}  {acres:>5.1f}a  {airport:>5.1f}km  {name}")

        # Signals row — show exactly which ones fired
        fired_labels = signals_fired_list(p)
        if fired_labels:
            tags = "  ".join(f"[✓] {lbl}" for lbl in fired_labels)
            print(f"        {score_bar}  {tags}")
        else:
            print(f"        {score_bar}  (no signals fired)")

        print()

    # Summary footer
    scored    = [p["opportunity_score"] for p in parcels]
    with_hits = sum(1 for s in scored if s > 0)
    print(f"{'─' * 78}")
    print(f"  {with_hits}/{len(parcels)} parcels have at least one signal  ·  "
          f"Top score: {max(scored):.1f}/100  ·  "
          f"Avg: {sum(scored)/len(scored):.1f}/100\n")


def export_csv(parcels: list, path: str):
    if not parcels:
        return
    # Collect the union of all keys across all parcels — different layers
    # add different sub-fields depending on whether they fired, so parcels
    # won't all have identical key sets.
    all_keys = list(dict.fromkeys(k for p in parcels for k in p.keys()))
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=all_keys, restval="")
        writer.writeheader()
        writer.writerows(parcels)


def export_json(parcels: list, path: str):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(parcels, f, indent=2, ensure_ascii=False)


# ─── Main pipeline ────────────────────────────────────────────────────────────

def main():
    print_banner(config.FILTERS)

    # ── Step 1: OSM scan (reuses scout.py functions directly) ─────────────────
    airports = []
    if config.FILTERS["proximity_to_airport"]:
        airports = fetch_airports()
        names = ", ".join(f"{a['name']} ({a['iata']})" for a in airports)
        print(f"         Airports: {names}\n")

    historic_sites = []
    if config.FILTERS["historical_designation"]:
        historic_sites = fetch_historic_sites()
        print(f"         Found {len(historic_sites):,} historic site(s)\n")

    if config.FILTERS["agricultural_land"]:
        raw = fetch_agricultural_parcels()
    else:
        raw = fetch_broad_landuse()
    print(f"         Retrieved {len(raw):,} raw OSM element(s)\n")

    # ── Step 2: Group 2 data ──────────────────────────────────────────────────
    g2 = config.GROUP2
    distress_elements = fetch_distress_elements() if g2["distress_signal"]   else []
    estate_features   = fetch_named_estates()     if g2["succession_signal"] else []
    tourism_nodes     = fetch_tourism_nodes()     if g2["lodging_overlay"]   else []

    # ── Step 3: Apply Group 1 filters ─────────────────────────────────────────
    print("  Applying filters...")
    parcels, skipped = filter_parcels(raw, airports, historic_sites)
    print(f"  Skipped → no geometry: {skipped['no_geometry']}  |  "
          f"too small: {skipped['area']}  |  "
          f"too far: {skipped['airport']}  |  "
          f"no historic: {skipped['historic']}")
    print(f"\n  {len(parcels)} parcel(s) passed all hard filters\n")

    if not parcels:
        print("  No results. Try relaxing filters in config.py.\n")
        return

    # ── Step 4: Group 2 annotation ────────────────────────────────────────────
    parcels = annotate_group2(parcels, distress_elements, estate_features, tourism_nodes)

    # ── Step 5: Run all 9 acquisition layers ──────────────────────────────────
    print("  Running all 9 acquisition layers...")
    parcels = run_all_layers(parcels)

    # ── Step 6: Score each parcel ─────────────────────────────────────────────
    for p in parcels:
        p["opportunity_score"] = score_parcel(p)
        p["signals_fired"]     = sum(1 for k in ALL_SIGNAL_KEYS if p.get(k))

    # ── Step 7: Rank (best first) ─────────────────────────────────────────────
    parcels.sort(key=lambda p: p["opportunity_score"], reverse=True)

    # ── Step 8: Print ranked table ────────────────────────────────────────────
    print_ranked(parcels)

    # ── Step 9: Export ────────────────────────────────────────────────────────
    ts        = datetime.now().strftime("%Y%m%d_%H%M%S")
    csv_path  = f"ranked_{ts}.csv"
    json_path = f"ranked_{ts}.json"
    export_csv(parcels, csv_path)
    export_json(parcels, json_path)
    print(f"  Saved → {csv_path}")
    print(f"  Saved → {json_path}\n")


if __name__ == "__main__":
    main()
