#!/usr/bin/env python3
"""
layers/geo_layers/elevation_aspect.py — Layer 10: Elevation & Slope Aspect

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
THESIS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
South-facing slopes at 150–600 m elevation are the sweet spot for
Sangiovese and other Tuscan varietals.  They:

  • Receive more solar radiation → higher sugar accumulation
  • Drain cold air overnight → lower frost risk
  • Face the prevailing warm southerly winds

A parcel scoring well on both axes is objectively superior to a flat
or north-facing neighbour — yet these characteristics are invisible in a
simple land-registry search.  We quantify them via free public elevation
data and flag the combination.

Why 150–600 m?
  • Below 150 m: flat valley floors, frost pockets, clay-heavy soils that
    hold too much moisture for premium red grapes
  • Above 600 m: too cold for consistent Sangiovese ripening in most years
    (exceptions: some Brunello at 500–600 m on south-facing slopes)
  • Sweet spot: 250–450 m covers the core of Chianti Classico DOCG hill country

Why 135–225° aspect?
  • Centres on due South (180°) — maximum daily solar exposure in the
    Northern Hemisphere
  • ±45° tolerance captures SE (morning sun, dries dew early) and SW
    (afternoon warmth, finishes ripening)
  • North-facing slopes (315–45°) can lag in ripening by 2–3 weeks —
    meaningful in short growing seasons

DATA SOURCE
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
OpenTopoData SRTM 90 m API — free public API, no authentication required.
  Endpoint: https://api.opentopodata.org/v1/srtm90m
  Resolution: 90 m horizontal (USGS SRTM v3, void-filled)
  Rate limit: 1 request/second, 100 locations/request (burst allowed)

We sample 5 points per parcel:
  centre + north/south/east/west offsets at ~100 m spacing
This is enough to compute slope direction (aspect) at low computational cost.
"""

import sys
import os
import math
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

import requests
import config
from layers.base import BaseLayer

_OPENTOPODATA_URL = "https://api.opentopodata.org/v1/srtm90m"
_DELTA_DEG        = 0.0009   # ~100 m at Tuscan latitudes (1° lat ≈ 111 km)

# Ideal elevation window for Tuscan premium wine production (metres)
ELEV_MIN_M = 150
ELEV_MAX_M = 600

# South-facing window: 135° (SE) to 225° (SW), centred on 180° (due South)
ASPECT_SOUTH_MIN = 135
ASPECT_SOUTH_MAX = 225


def _fetch_elevations(lat: float, lon: float) -> dict:
    """
    Query OpenTopoData for 5 points: centroid + N/S/E/W offsets (~100 m apart).
    Returns a dict with keys centre/north/south/east/west, or {"error": ...}.
    """
    points = [
        (lat,              lon           ),   # centre
        (lat + _DELTA_DEG, lon           ),   # north
        (lat - _DELTA_DEG, lon           ),   # south
        (lat,              lon + _DELTA_DEG), # east
        (lat,              lon - _DELTA_DEG), # west
    ]
    loc_str = "|".join(f"{la},{lo}" for la, lo in points)

    try:
        resp = requests.get(
            _OPENTOPODATA_URL,
            params={"locations": loc_str},
            timeout=15,
            headers={"User-Agent": "ParcelScout/1.0"},
        )
        if resp.status_code == 429:
            return {"error": "rate_limited"}
        if resp.status_code != 200:
            return {"error": f"http_{resp.status_code}"}

        results = resp.json().get("results", [])
        if len(results) < 5:
            return {"error": "incomplete_response"}

        elevs = [r.get("elevation") for r in results]
        if any(e is None for e in elevs):
            return {"error": "null_elevation_data"}

        return {
            "centre": round(elevs[0], 1),
            "north":  round(elevs[1], 1),
            "south":  round(elevs[2], 1),
            "east":   round(elevs[3], 1),
            "west":   round(elevs[4], 1),
        }
    except Exception as exc:
        return {"error": str(exc)[:80]}


def _compute_aspect(north: float, south: float, east: float, west: float) -> float:
    """
    Compute slope aspect (0–360°, compass bearing) from cardinal elevations.

    Derivation:
      ns = north_elev - south_elev  (positive → north is higher → slope faces south)
      ew = east_elev  - west_elev   (positive → east is higher  → slope faces west)

      aspect = atan2(ew, ns) + 180°   (mod 360°)

    Verification:
      ns=+1, ew=0  → atan2(0,  1)=0°    → 0+180=180° (south)  ✓
      ns=0,  ew=+1 → atan2(1,  0)=90°   → 90+180=270° (west)  ✓
      ns=-1, ew=0  → atan2(0, -1)=180°  → 180+180=360°=0° (north) ✓
      ns=0,  ew=-1 → atan2(-1, 0)=-90°  → -90+180=90° (east)  ✓
    """
    ns = north - south
    ew = east  - west
    return (math.degrees(math.atan2(ew, ns)) + 180.0) % 360.0


def _aspect_label(deg: float) -> str:
    """Return a compass cardinal/intercardinal label for an aspect angle."""
    directions = ["N", "NE", "E", "SE", "S", "SW", "W", "NW", "N"]
    idx = round(deg / 45) % 8
    return directions[idx]


class ElevationAspectLayer(BaseLayer):
    """
    Layer 10 — Elevation & Slope Aspect

    Flags parcels at ideal Tuscan wine-production elevation (150–600 m) on
    south-facing slopes (135–225°). Both conditions together indicate land
    with inherently superior terroir that may be underutilised by the
    current operator.

    Free layer — OpenTopoData SRTM 90 m API.  No API key required.
    """
    name  = "elevation_aspect"
    label = "Elevation & Aspect"
    paid  = False

    def run(self, parcel: dict) -> dict:
        if not config.LAYERS.get("elevation_aspect", True):
            return self._empty_result(detail="Layer disabled in config.LAYERS")

        elevs = _fetch_elevations(parcel["lat"], parcel["lon"])

        # ── API error handling ────────────────────────────────────────────────
        if "error" in elevs:
            err = elevs["error"]
            if err == "rate_limited":
                detail = "OpenTopoData rate limit reached — try again in a few seconds"
            else:
                detail = f"Elevation lookup failed: {err}"
            return self._empty_result(detail=detail)

        centre_m = elevs["centre"]
        aspect   = _compute_aspect(
            elevs["north"], elevs["south"], elevs["east"], elevs["west"]
        )
        aspect_dir = _aspect_label(aspect)

        # ── Evaluate conditions ────────────────────────────────────────────────
        good_elev   = ELEV_MIN_M <= centre_m <= ELEV_MAX_M
        south_facing = ASPECT_SOUTH_MIN <= aspect <= ASPECT_SOUTH_MAX

        # Signal fires only when BOTH conditions are met — the combination is
        # what makes a parcel genuinely special.  Either alone is too common.
        signal = good_elev and south_facing

        # Score: 1.0 = both ideal, 0.5 = one condition met, 0.0 = neither
        if signal:
            # Boost score when closer to the ideal centre (300 m, 180°)
            elev_proximity = 1.0 - abs(centre_m - 300) / 300
            aspect_proximity = 1.0 - abs(aspect - 180) / 45
            score = self._clamp(0.5 + 0.25 * elev_proximity + 0.25 * aspect_proximity)
        elif good_elev or south_facing:
            score = 0.4
        else:
            score = 0.0

        # ── Build detail string ────────────────────────────────────────────────
        elev_tag   = "✓ ideal elevation" if good_elev   else f"✗ outside 150–600 m range"
        aspect_tag = "✓ south-facing"    if south_facing else f"✗ {aspect_dir}-facing"

        if signal:
            detail = (
                f"Ideal terroir profile: {centre_m:.0f} m elevation ({elev_tag}), "
                f"{aspect:.0f}° {aspect_dir} aspect ({aspect_tag}). "
                f"Sweet spot for Sangiovese ripening."
            )
        else:
            detail = (
                f"{centre_m:.0f} m elevation ({elev_tag}), "
                f"{aspect:.0f}° {aspect_dir} aspect ({aspect_tag})."
            )

        return {
            "layer":  self.name,
            "label":  self.label,
            "signal": signal,
            "score":  round(score, 3),
            "detail": detail,
            "data": {
                "elevation_m":   centre_m,
                "aspect_deg":    round(aspect, 1),
                "aspect_dir":    aspect_dir,
                "good_elevation": good_elev,
                "south_facing":   south_facing,
                "data_source":   "OpenTopoData SRTM 90m (free)",
            },
            "paid": self.paid,
        }
