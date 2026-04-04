#!/usr/bin/env python3
"""
layers/geo_layers/water_access.py — Layer 12: Water Source Proximity

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
THESIS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Water access is one of the most underappreciated value drivers for
Tuscan agricultural estate buyers:

  • IRRIGATION: Gravity-fed irrigation from a spring or stream dramatically
    reduces operating costs relative to pumping from a municipal supply.
    Premium olive groves and vineyards often rely on on-site water.

  • WATER RIGHTS: Italian water rights (diritti d'acqua) are attached to
    the land, not the owner, and are extremely difficult to acquire after
    purchase. Buying a parcel with riparian rights or a registered spring
    is buying irreplaceable infrastructure.

  • AGRITURISMO & HOSPITALITY: Swimming pools, garden irrigation, and
    guest water supply for an agriturismo are all far cheaper with
    on-site water. This directly affects the ROI of a hospitality conversion.

  • NATURAL BOUNDARY: Streams and rivers often serve as natural legal
    boundaries (confini catastali), reducing the cost of boundary disputes.

WATER SOURCE TYPES (ranked by acquisition value):
  spring (natural=spring)          — highest value; year-round gravity source
  river/stream (waterway=*)        — riparian rights potential; irrigation
  lake/reservoir (natural=water)   — seasonal storage; amenity value
  well (man_made=water_well)       — existing infrastructure; drilling costs avoided
  canal (waterway=canal)           — irrigation canal; shared rights

DATA SOURCE
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
OpenStreetMap via Overpass API — free, no authentication required.
Queries within ~500 m of the parcel centroid (wider than road check because
water features are rarer and smaller streams often flow some distance from
the nearest mapped road).
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

import requests
import config
from layers.base import BaseLayer

_OSM_BUFFER_DEG = 0.005   # ~500 m at Tuscan latitudes — wider than road check

# Ordered by acquisition value (highest first)
_WATER_PRIORITY = ["spring", "river", "stream", "canal", "ditch", "water", "water_well"]

_SOURCE_LABELS = {
    "spring":     "natural spring",
    "river":      "river",
    "stream":     "stream / creek",
    "canal":      "irrigation canal",
    "ditch":      "drainage ditch",
    "water":      "lake / pond / reservoir",
    "water_well": "water well",
}

_SOURCE_SCORES = {
    "spring":     1.0,
    "river":      0.9,
    "stream":     0.8,
    "water":      0.7,
    "canal":      0.6,
    "water_well": 0.6,
    "ditch":      0.3,
}


def _query_water_sources(lat: float, lon: float) -> dict:
    """
    Query Overpass for all water features within _OSM_BUFFER_DEG of centroid.
    Returns: {found, sources, best_source, source_count, names, error}
    """
    bb = (f"{lat - _OSM_BUFFER_DEG},{lon - _OSM_BUFFER_DEG},"
          f"{lat + _OSM_BUFFER_DEG},{lon + _OSM_BUFFER_DEG}")
    query = f"""
[out:json][timeout:20];
(
  way["waterway"~"river|stream|canal|ditch"]({bb});
  node["waterway"~"river|stream|canal|ditch"]({bb});
  node["natural"="spring"]({bb});
  way["natural"="water"]({bb});
  relation["natural"="water"]({bb});
  node["man_made"="water_well"]({bb});
);
out tags center;
"""
    for url in config.OVERPASS_FALLBACK_URLS:
        try:
            resp = requests.post(url, data={"data": query}, timeout=25)
            if resp.status_code != 200:
                continue

            elements = resp.json().get("elements", [])
            found_types = []
            names       = []

            for el in elements:
                tags = el.get("tags", {})
                # Determine the water type
                wtype = None
                if tags.get("waterway") in ("river", "stream", "canal", "ditch"):
                    wtype = tags["waterway"]
                elif tags.get("natural") == "spring":
                    wtype = "spring"
                elif tags.get("natural") == "water":
                    wtype = "water"
                elif tags.get("man_made") == "water_well":
                    wtype = "water_well"

                if wtype:
                    found_types.append(wtype)
                    if tags.get("name"):
                        names.append(tags["name"][:40])

            # Deduplicate; pick best type
            unique_types = list(dict.fromkeys(found_types))
            best = next(
                (t for t in _WATER_PRIORITY if t in unique_types),
                unique_types[0] if unique_types else None,
            )

            return {
                "found":        bool(unique_types),
                "sources":      unique_types[:5],
                "best_source":  best,
                "source_count": len(found_types),
                "names":        list(dict.fromkeys(names))[:3],
                "error":        None,
            }
        except Exception as exc:
            last_err = str(exc)[:60]
            continue

    return {
        "found": False, "sources": [], "best_source": None,
        "source_count": 0, "names": [],
        "error": "All Overpass mirrors failed",
    }


class WaterAccessLayer(BaseLayer):
    """
    Layer 12 — Water Source Proximity

    Flags parcels with natural or engineered water sources within 500 m —
    springs, rivers, streams, lakes, canals, and wells.

    Water access is a positive acquisition indicator: it reduces operating
    costs, may carry embedded water rights, and adds significant value to
    agriturismo conversions.

    Signal fires when any water source is found nearby.
    Score scales with water quality:
      spring > river > stream > lake/water body > canal > well > ditch

    Free layer — OpenStreetMap via Overpass API.  No API key required.
    """
    name  = "water_access"
    label = "Water Access"
    paid  = False

    def run(self, parcel: dict) -> dict:
        if not config.LAYERS.get("water_access", True):
            return self._empty_result(detail="Layer disabled in config.LAYERS")

        result = _query_water_sources(parcel["lat"], parcel["lon"])

        if result.get("error") and not result.get("found"):
            return self._empty_result(detail=f"Water query failed: {result['error']}")

        if not result["found"]:
            return {
                "layer":  self.name,
                "label":  self.label,
                "signal": False,
                "score":  0.0,
                "detail": "No water sources mapped within 500 m.",
                "data": {
                    "found":        False,
                    "sources":      [],
                    "best_source":  None,
                    "source_count": 0,
                    "data_source":  "OSM via Overpass (free)",
                },
                "paid": self.paid,
            }

        best    = result["best_source"]
        label   = _SOURCE_LABELS.get(best, best.replace("_", " "))
        score   = _SOURCE_SCORES.get(best, 0.5)
        sources = result["sources"]
        names   = result["names"]

        source_list = ", ".join(_SOURCE_LABELS.get(s, s) for s in sources[:4])
        name_str    = f" ({', '.join(names[:2])})" if names else ""

        detail = (
            f"Water access confirmed — {label}{name_str} within 500 m. "
            f"Water sources mapped: {source_list}. "
            f"May include irrigation rights — verify with cadastral records."
        )

        return {
            "layer":  self.name,
            "label":  self.label,
            "signal": True,
            "score":  round(score, 3),
            "detail": detail,
            "data": {
                "found":        True,
                "best_source":  best,
                "sources":      sources,
                "source_count": result["source_count"],
                "water_names":  names,
                "data_source":  "OSM via Overpass (free)",
            },
            "paid": self.paid,
        }
