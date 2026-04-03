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

import requests
import config
from layers.base import BaseLayer

# ── Zone-level average critic scores (Wine Spectator / Wine Advocate scale) ──
# Sourced from public WS/WA zone data. Update annually as new vintages score.
# Both the canonical name and common aliases are included for robust matching
# against the g2_wine_zone_name field computed by scout.py.
ZONE_AVERAGE_SCORES = {
    "Brunello di Montalcino":       93.0,   # Biondi Santi, Poggio di Sotto, Argiano
    "Vino Nobile di Montepulciano": 89.5,   # Avignonesi, Poliziano, Valdipiatta
    "Chianti Classico":             88.0,   # Brolio, Badia a Coltibuono, Isole e Olena
    "Chianti Classico (Siena)":     88.0,   # alias used by g2 zone check
    "Bolgheri (Super Tuscan)":      91.0,   # Sassicaia, Ornellaia, Masseto — 90–97 range
    "Morellino di Scansano":        85.5,   # Rocca di Frassinello, Moris Farms — rising
    "Montecucco Sangiovese":        87.0,   # Collemassari, Salustri — fastest-improving zone
}

# Minimum gap (zone benchmark − producer score) to fire the signal
SCORE_DELTA_THRESHOLD = 5.0   # 5+ points below zone average = unlocked potential

_WINE_SEARCHER_BASE = "https://www.wine-searcher.com/api/v2"


def _search_wine_searcher(producer_name: str, api_key: str) -> dict:
    """
    Search Wine-Searcher for wines from this producer and return the
    average critic score across the top results.

    API endpoint: GET https://www.wine-searcher.com/api/v2/wine
    Params: api_key, name (producer/wine name), country, num (max results)
    Response: JSON with "search_results" list; each result has a "ratings"
    list with {"critic": str, "score": int, "num_reviews": int}.

    Returns: {
        "found": bool,
        "avg_score": float|None,    # mean score across rated wines
        "num_wines": int,           # total results returned
        "wines": list[str],         # first 3 wine names found
        "error": str|None           # set on API failure
    }
    """
    try:
        resp = requests.get(
            f"{_WINE_SEARCHER_BASE}/wine",
            params={
                "api_key": api_key,
                "name":    producer_name,
                "country": "Italy",
                "num":     10,
            },
            timeout=12,
            headers={"User-Agent": "ParcelScout/1.0"},
        )
        if resp.status_code == 401:
            return {"found": False, "error": "invalid_api_key"}
        if resp.status_code == 429:
            return {"found": False, "error": "rate_limited"}
        if resp.status_code != 200:
            return {"found": False, "error": f"http_{resp.status_code}"}

        data    = resp.json()
        results = data.get("search_results", [])
        if not results:
            return {"found": False}

        scores     = []
        wine_names = []
        for result in results[:5]:   # top 5 results only
            wname = result.get("wine_name", "")
            if wname:
                wine_names.append(wname)
            for rating in result.get("ratings", []):
                s = rating.get("score")
                if s and isinstance(s, (int, float)) and 50 <= float(s) <= 100:
                    scores.append(float(s))

        return {
            "found":     True,
            "avg_score": round(sum(scores) / len(scores), 1) if scores else None,
            "num_wines": len(results),
            "wines":     wine_names[:3],
            "error":     None,
        }
    except Exception as exc:
        return {"found": False, "error": str(exc)[:100]}


# Minimum delta to flag as an opportunity (current producer vs zone average)
# (kept here for backwards compat — defined above near ZONE_AVERAGE_SCORES)


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

        api_key       = getattr(config, "WINE_SEARCHER_API_KEY", "")
        zone_name     = parcel.get("g2_wine_zone_name", "")
        producer_name = parcel.get("name", "").strip()
        zone_avg      = ZONE_AVERAGE_SCORES.get(zone_name)

        # ── No API key: surface DOCG zone context as a free annotation ────────
        if not api_key:
            if zone_name and zone_avg is not None:
                detail = (
                    f"In {zone_name} (zone benchmark {zone_avg:.1f} pts). "
                    f"Set WINE_SEARCHER_API_KEY to compare this producer's score "
                    f"against the zone average."
                )
            else:
                detail = (
                    "Not in a tracked DOCG zone. "
                    "Set WINE_SEARCHER_API_KEY to activate producer score comparison."
                )
            return self._empty_result(detail=detail)

        # ── No estate name: cannot search Wine-Searcher ───────────────────────
        if not producer_name:
            return self._empty_result(
                detail="No OSM name tag — cannot search Wine-Searcher without a producer name"
            )

        # ── Call Wine-Searcher ────────────────────────────────────────────────
        ws = _search_wine_searcher(producer_name, api_key)

        if not ws.get("found"):
            err = ws.get("error", "no results")
            if err == "rate_limited":
                detail = "Wine-Searcher daily quota reached (100 searches/day on free tier)"
            elif err == "invalid_api_key":
                detail = "Wine-Searcher API key rejected — check WINE_SEARCHER_API_KEY in config.py"
            else:
                detail = f"'{producer_name}' not found on Wine-Searcher ({err})"
            return self._empty_result(
                detail=detail,
                data={"producer_name": producer_name, "zone_name": zone_name},
            )

        producer_score = ws.get("avg_score")

        # ── Compute delta and fire signal ─────────────────────────────────────
        signal = False
        score  = 0.0
        delta  = None

        if producer_score is not None and zone_avg is not None:
            delta = round(zone_avg - producer_score, 1)
            if delta >= SCORE_DELTA_THRESHOLD:
                signal = True
                # Scale: 5-pt gap = 0.5 score; 10-pt gap = 1.0 (capped)
                score  = self._clamp(delta / 10.0)
                detail = (
                    f"{producer_name}: {producer_score:.1f} pts vs "
                    f"{zone_name} avg {zone_avg:.1f} pts "
                    f"({delta:+.1f} pts — underperforming zone potential)"
                )
            else:
                detail = (
                    f"{producer_name}: {producer_score:.1f} pts vs "
                    f"{zone_name} avg {zone_avg:.1f} pts (within zone range)"
                )
        elif producer_score is not None:
            detail = (
                f"{producer_name}: {producer_score:.1f} pts "
                f"(no zone benchmark available for comparison)"
            )
        else:
            detail = f"'{producer_name}' found on Wine-Searcher but no critic score available"

        return {
            "layer":  self.name,
            "label":  self.label,
            "signal": signal,
            "score":  round(score, 3),
            "detail": detail,
            "data": {
                "producer_name":  producer_name,
                "producer_score": producer_score,
                "zone_name":      zone_name,
                "zone_avg":       zone_avg,
                "score_delta":    delta,
                "wines_found":    ws.get("wines", []),
                "num_wines":      ws.get("num_wines", 0),
            },
            "paid": self.paid,
        }
