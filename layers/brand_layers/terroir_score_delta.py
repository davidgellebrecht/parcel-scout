#!/usr/bin/env python3
"""
layers/brand_layers/terroir_score_delta.py — Layer 7: Terroir-to-Score Delta

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
THESIS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
A vineyard's wine critic score is shaped by TWO factors:

  1. TERROIR QUALITY: Soil composition, slope, aspect (sun exposure),
     drainage, altitude. This is geology — it doesn't change. The best
     Brunello sites sit on galestro schist (crumbling limestone) that
     stresses the vine just enough to concentrate the fruit.

  2. PRODUCER BRAND & EXECUTION: Winemaking skill, marketing investment,
     press relationships, cellar technology, and distribution reach.
     This is craft + commerce — and it CAN change under new ownership.

The "Terroir-to-Score Delta" captures parcels where the soil is
objectively excellent (DOCG zone, elevation, aspect) but the wine scores
lag the zone average by 5+ points. The gap between where the land CAN
produce and where the current producer IS producing represents "unlocked
value" — a motivated buyer with better winemaking could close that gap
and command 40-60% higher bottle prices on the same grapes.

We source:
  • Soil/terroir quality: OSM geological tags + DOCG zone placement
    (already computed in Group 1 + G2 premium wine zone checks)
  • Critic scores: Wine-Searcher API (100 free requests/day) OR Vivino API
    (no public API — requires a commercial data agreement)

⚠️  PAID FEATURE — requires Wine-Searcher or Vivino API access.
   Wine-Searcher: https://www.wine-searcher.com/api
   Vivino: https://www.vivino.com/api (commercial agreement required)

HOW TO ACTIVATE
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Set WINE_SEARCHER_API_KEY in config.py and set
LAYERS["terroir_score_delta"] = True.
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

import config
from layers.base import BaseLayer

# ── Zone-level average Vivino / Wine-Searcher critic scores ──────────────────
# Hardcoded from public Wine Spectator and Vivino zone data as a baseline.
# Update annually as new vintages are scored.
# Scale: 100-point system (Wine Spectator / Wine Advocate standard)
ZONE_AVERAGE_SCORES = {
    "Brunello di Montalcino":       93.0,   # zone benchmark — Biondi Santi, Poggio di Sotto
    "Vino Nobile di Montepulciano": 89.5,   # zone benchmark — Avignonesi, Poliziano
    "Chianti Classico (Siena)":     88.0,   # zone benchmark — Brolio, Badia a Coltibuono
}

# Minimum delta to flag as an opportunity (current producer vs zone average)
SCORE_DELTA_THRESHOLD = 5.0   # 5+ points below zone average


class TerroirScoreDeltaLayer(BaseLayer):
    """
    Layer 7 — Terroir-to-Score Delta

    Identifies vineyards where the soil quality (DOCG zone, galestro/alberese
    geology) should support excellent wines, but the current producer's scores
    lag the zone benchmark — indicating unlocked value for a new buyer.

    ⚠️  PAID FEATURE — requires Wine-Searcher or Vivino API access.
    """
    name  = "terroir_score_delta"
    label = "Terroir-to-Score Delta"
    paid  = True

    def run(self, parcel: dict) -> dict:
        if not config.LAYERS.get("terroir_score_delta", True):
            return self._empty_result(detail="Layer disabled in config.LAYERS")

        api_key = getattr(config, "WINE_SEARCHER_API_KEY", "")
        if not api_key:
            # Even without an API key, we can surface the DOCG zone context
            # using data already computed by scout.py's Group 2 pass.
            zone_name = parcel.get("g2_wine_zone_name", "")
            if zone_name and zone_name in ZONE_AVERAGE_SCORES:
                zone_avg = ZONE_AVERAGE_SCORES[zone_name]
                detail = (f"In {zone_name} (zone avg {zone_avg:.1f} pts). "
                          f"Activate Wine-Searcher API to compare producer score vs zone benchmark.")
            else:
                detail = "Not in a tracked DOCG zone or zone data unavailable."

            return self._empty_result(
                detail=detail + " | PAID FEATURE — configure WINE_SEARCHER_API_KEY to activate"
            )

        # ── Live implementation (when API key is set) ─────────────────────────
        # Flow:
        # 1. Identify the parcel's wine estate name (from OSM name tag)
        # 2. Query Wine-Searcher API for the estate's current average score
        # 3. Compare against the zone average from ZONE_AVERAGE_SCORES
        # 4. Calculate delta = zone_average - producer_score
        # 5. Flag if delta >= SCORE_DELTA_THRESHOLD
        #
        # Wine-Searcher API endpoints (with WINE_SEARCHER_API_KEY):
        #   Search wine by producer: GET https://www.wine-searcher.com/api/v2/wine
        #     Params: api_key, name=<producer_name>, country=Italy, region=Tuscany
        #   Returns: average_rating, num_reviews, price_range
        #
        # NOTE: Vivino has no public API. The commercial data agreement
        # (vivino.com/wine-data-service) provides bulk score exports.
        # Integrate the Vivino CSV export here when the agreement is in place.

        return self._paid_stub()
