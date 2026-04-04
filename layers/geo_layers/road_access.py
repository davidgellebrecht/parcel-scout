#!/usr/bin/env python3
"""
layers/geo_layers/road_access.py — Layer 11: Road Access Quality

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
THESIS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Road access quality is a two-sided acquisition signal:

  POOR ACCESS → parcel is undervalued (hard to reach = lower asking price).
  The cost to upgrade a gravel track or private road is quantifiable
  and finite — a motivated buyer can factor it into the offer. Meanwhile,
  the seller sees the road condition as a liability, which suppresses
  their price expectations.

  ISOLATED PARCELS → owner frustration. Maintenance is difficult, guests
  are put off, deliveries are complicated. An owner who inherited a
  wine estate accessible only by unsealed track is far more likely to
  want to sell than one with a tarmac approach road.

WHY THIS MATTERS FOR TUSCANY
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Chianti Classico hill country is criss-crossed with strade bianche —
unsealed white gravel roads that are charming to cycle but challenging
to operate an estate from.  Many prime vineyard parcels are 1–2 km down
a track off the nearest paved road.

The road classification hierarchy we use (best → worst):
  primary / secondary / tertiary → paved, public, year-round access
  residential / living_street    → paved, lighter duty
  unclassified                   → usually paved, quality varies
  service                        → private/access road, often paved
  track                          → typically unsealed, condition varies
  path / footway / bridleway     → unmotorised, impassable for deliveries

DATA SOURCE
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
OpenStreetMap via Overpass API — free, no authentication required.
Queries for all highway=* elements within ~300 m of the parcel centroid.
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

import requests
import config
from layers.base import BaseLayer

_OSM_BUFFER_DEG = 0.003   # ~300 m at Tuscan latitudes

# Road quality tiers (best first within each tier)
_GOOD_ROAD_TYPES = {
    "motorway", "trunk", "primary", "secondary", "tertiary",
    "residential", "living_street",
}
_FAIR_ROAD_TYPES = {
    "unclassified", "service",
}
_POOR_ROAD_TYPES = {
    "track", "path", "footway", "bridleway", "steps", "cycleway",
}


def _classify_access(highway_tags: list) -> tuple[str, str | None]:
    """
    Given a list of highway tag values found nearby, return:
      (access_level, best_road_type)

    Access levels: "good", "fair", "poor", "none"
    """
    if not highway_tags:
        return "none", None

    tag_set = set(highway_tags)
    if tag_set & _GOOD_ROAD_TYPES:
        best = next(t for t in ["primary", "secondary", "tertiary",
                                "residential", "living_street", "trunk",
                                "motorway"] if t in tag_set)
        return "good", best
    if tag_set & _FAIR_ROAD_TYPES:
        best = next(t for t in ["unclassified", "service"] if t in tag_set)
        return "fair", best
    if tag_set & _POOR_ROAD_TYPES:
        best = next(t for t in ["track", "path", "footway",
                                "bridleway", "cycleway"] if t in tag_set)
        return "poor", best

    # Unknown highway type — treat as fair
    return "fair", highway_tags[0]


def _query_roads(lat: float, lon: float) -> dict:
    """
    Query Overpass for all road/path elements within _OSM_BUFFER_DEG of the centroid.
    Returns: {highway_tags, access_level, best_road, road_count, found, error}
    """
    bb = (f"{lat - _OSM_BUFFER_DEG},{lon - _OSM_BUFFER_DEG},"
          f"{lat + _OSM_BUFFER_DEG},{lon + _OSM_BUFFER_DEG}")
    query = f"""
[out:json][timeout:20];
(
  way["highway"]({bb});
  node["highway"="bus_stop"]({bb});
);
out tags;
"""
    for url in config.OVERPASS_FALLBACK_URLS:
        try:
            resp = requests.post(url, data={"data": query}, timeout=25)
            if resp.status_code != 200:
                continue

            elements = resp.json().get("elements", [])
            highway_tags = []
            for el in elements:
                hw = el.get("tags", {}).get("highway")
                if hw and hw != "bus_stop":
                    highway_tags.append(hw)

            access_level, best_road = _classify_access(highway_tags)
            return {
                "found":        len(highway_tags) > 0,
                "highway_tags": list(set(highway_tags))[:8],
                "road_count":   len(highway_tags),
                "access_level": access_level,
                "best_road":    best_road,
                "error":        None,
            }
        except Exception as exc:
            last_err = str(exc)[:60]
            continue

    return {
        "found": False, "highway_tags": [], "road_count": 0,
        "access_level": "unknown", "best_road": None,
        "error": "All Overpass mirrors failed",
    }


class RoadAccessLayer(BaseLayer):
    """
    Layer 11 — Road Access Quality

    Flags parcels with poor or no road access — a key undervaluation driver
    that a motivated buyer can price and potentially remedy.

    Access levels:
      good  — paved public road within 300 m (primary → residential)
      fair  — unclassified or service road (quality variable)
      poor  — track, path, or bridleway only
      none  — no mapped road access at all

    Signal fires when access is "poor" or "none" — these parcels trade at
    a discount relative to their soil quality and terroir, giving a buyer
    with infrastructure budget a clear value-add angle.

    Free layer — OpenStreetMap via Overpass API.  No API key required.
    """
    name  = "road_access"
    label = "Road Access"
    paid  = False

    def run(self, parcel: dict) -> dict:
        if not config.LAYERS.get("road_access", True):
            return self._empty_result(detail="Layer disabled in config.LAYERS")

        result = _query_roads(parcel["lat"], parcel["lon"])

        if result.get("error") and not result.get("found"):
            return self._empty_result(detail=f"Road query failed: {result['error']}")

        access = result["access_level"]
        best   = result["best_road"] or "none mapped"

        # Signal fires for poor or no road access — the acquisition opportunity
        # Signal also fires for "fair" (unclassified) — worth flagging
        signal = access in ("poor", "none", "fair")

        if access == "none":
            score  = 1.0
            detail = (
                "No road access mapped within 300 m — likely private track or field access only. "
                "Significant infrastructure discount; road upgrade cost is quantifiable."
            )
        elif access == "poor":
            score  = 0.8
            detail = (
                f"Only {best.replace('_',' ')} access within 300 m (unsealed/unmotorised). "
                "Estate deliveries and guest access are constrained — a known seller frustration."
            )
        elif access == "fair":
            score  = 0.4
            detail = (
                f"Unclassified or service road access ({best.replace('_',' ')}). "
                "May be paved but quality varies — worth verifying on-site."
            )
        else:  # good
            signal = False
            score  = 0.0
            detail = (
                f"Good road access: {best.replace('_',' ')} within 300 m. "
                f"({result['road_count']} road segment(s) mapped nearby)"
            )

        return {
            "layer":  self.name,
            "label":  self.label,
            "signal": signal,
            "score":  round(score, 3),
            "detail": detail,
            "data": {
                "access_level": access,
                "best_road":    best,
                "road_count":   result["road_count"],
                "highway_tags": result["highway_tags"],
                "data_source":  "OSM via Overpass (free)",
            },
            "paid": self.paid,
        }
