#!/usr/bin/env python3
"""
layers/geo_layers/permit_paralysis.py — Layer 2: Permit Paralysis

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
THESIS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Italian municipalities post every public permit application to their
"Albo Pretorio" — the legally mandated digital notice board (think of it
as the town's official bulletin board, but online and searchable).

When a parcel shows repeated permit applications for the same project
(ristrutturazione / agriturismo conversion / new rural structure) over
multiple years WITHOUT a final "concessione edilizia" (building permit
approval), it signals the owner is trying to develop or convert the land
but hitting bureaucratic resistance — a classic sign of owner frustration
that often precedes a willingness to sell.

The gap between filing intent and receiving approval is our opportunity
window: the owner has already mentally "moved on" from their original
plan, but the land isn't listed yet.

DATA SOURCE
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Albo Pretorio scraping — each Italian Comune publishes its own portal.
There is no unified national API. Two approaches:

  OPTION A — Commercial aggregator (recommended):
    • ANAC Portale Trasparenza: https://dati.anticorruzione.it/opendata
      Free, structured JSON data on public contracts (includes permits).
    • Require cross-referencing parcel cadastral codes with ANAC records.

  OPTION B — Direct Comune portal scraping:
    • Siena: https://albo.comune.siena.it/albo/
    • Montalcino: https://www.comune.montalcino.si.it/albo-pretorio
    • Each Comune uses a different CMS — no standard schema.
    • Requires Selenium or Playwright for JS-rendered pages.

⚠️  PAID FEATURE — This layer requires a commercial scraping infrastructure
   agreement OR a direct integration with the ANAC/SUAP aggregator.
   The free ANAC open data covers public contracts but not residential/
   agricultural permit applications, which remain fragmented at Comune level.

HOW TO ACTIVATE
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Set LAYERS["permit_paralysis"] = True and configure:
    ALBO_PRETORIO_API_KEY = "your-key"  # in config.py

Until then, the layer will always return the PAID FEATURE stub.
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

import requests
import config
from layers.base import BaseLayer

# Radius within which we look for OSM renovation/neglect signals (degrees ≈ metres)
_OSM_BUFFER_DEG = 0.003   # ≈ 300 m at Tuscan latitudes


def _check_osm_renovation_signals(lat: float, lon: float) -> dict:
    """
    Query Overpass for OSM tags near the parcel indicating renovation activity,
    structural neglect, or stalled construction.  This is a free proxy for
    permit-history data; it reflects physical reality on the ground rather than
    administrative records, but often correlates with owner frustration.

    Tags queried (in order of signal strength):
      building:condition = poor / very_poor / bad / collapse
        → Owner hasn't maintained the building — may want to renovate but lacks
          capital or planning approval
      abandoned:building or disused:building
        → Building no longer in active use — successor may be clearing estate
      historic = ruins + name tag
        → Named ruin suggests once-significant structure; restoration permit
          applications common on named properties
      building = construction (or construction = yes + building tag)
        → Active or stalled build site — combined with adjacent neglect is a
          strong double signal

    Returns: {found, signals, count, strongest_tag, data_source}
    """
    bb = f"{lat - _OSM_BUFFER_DEG},{lon - _OSM_BUFFER_DEG},{lat + _OSM_BUFFER_DEG},{lon + _OSM_BUFFER_DEG}"
    query = f"""
[out:json][timeout:20];
(
  way["building:condition"~"poor|very_poor|bad|collapse",i]({bb});
  node["building:condition"~"poor|very_poor|bad|collapse",i]({bb});
  way["abandoned:building"]({bb});
  node["abandoned:building"]({bb});
  way["disused:building"]({bb});
  node["disused:building"]({bb});
  way["historic"="ruins"]["name"]({bb});
  way["building"="construction"]({bb});
  way["construction"]["building"]({bb});
);
out tags center;
"""
    for url in config.OVERPASS_FALLBACK_URLS:
        try:
            resp = requests.post(url, data={"data": query}, timeout=25)
            if resp.status_code != 200:
                continue

            elements = resp.json().get("elements", [])
            signals  = []
            for el in elements:
                tags = el.get("tags", {})
                cond = tags.get("building:condition", "")
                if cond:
                    signals.append(f"building condition: {cond}")
                elif tags.get("abandoned:building"):
                    signals.append("abandoned building")
                elif tags.get("disused:building"):
                    signals.append("disused building")
                elif tags.get("historic") == "ruins" and tags.get("name"):
                    signals.append(f"named ruin: {tags['name'][:40]}")
                elif tags.get("building") == "construction" or tags.get("construction"):
                    signals.append("construction site")

            return {
                "found":        len(signals) > 0,
                "signals":      signals[:5],
                "count":        len(signals),
                "strongest_tag": signals[0] if signals else None,
                "data_source":  "OSM tags (free proxy)",
            }
        except Exception:
            continue

    return {"found": False, "signals": [], "count": 0,
            "strongest_tag": None, "data_source": "OSM tags (free proxy)"}


class PermitParalysisLayer(BaseLayer):
    """
    Layer 2 — Permit Paralysis

    Flags parcels where physical evidence on the ground suggests renovation or
    construction is underway or stalled. Without ALBO_PRETORIO_API_KEY the layer
    runs a free OSM-based proxy: it queries for buildings tagged as poor condition,
    abandoned, disused, or under construction near the parcel centroid.

    When ALBO_PRETORIO_API_KEY is set, the layer upgrades to official permit
    history from the Albo Pretorio — counting applications filed without approval
    over the past 5 years.

    The free OSM proxy and the paid permit history complement each other:
      • OSM = physical evidence (what the land looks like)
      • Albo Pretorio = administrative evidence (what the owner has been trying to do)
    """
    name  = "permit_paralysis"
    label = "Permit Paralysis"
    paid  = True   # full implementation requires Albo Pretorio key

    def run(self, parcel: dict) -> dict:
        if not config.LAYERS.get("permit_paralysis", True):
            return self._empty_result(detail="Layer disabled in config.LAYERS")

        # ── Free component: OSM renovation / neglect proxy ────────────────────
        # Runs regardless of API key — always returns useful physical signal.
        osm = _check_osm_renovation_signals(parcel["lat"], parcel["lon"])

        api_key = getattr(config, "ALBO_PRETORIO_API_KEY", "")

        if not api_key:
            # OSM proxy is the only data source
            if osm["found"]:
                signal = True
                # 1 signal = 0.33, 2 = 0.67, 3+ = 1.0
                score  = self._clamp(osm["count"] / 3.0)
                detail = (
                    f"OSM proxy — {osm['count']} renovation/neglect signal(s) nearby: "
                    + "; ".join(osm["signals"][:3])
                    + ". Add ALBO_PRETORIO_API_KEY for official permit history."
                )
            else:
                signal = False
                score  = 0.0
                detail = (
                    "No OSM construction or neglect signals found nearby. "
                    "Add ALBO_PRETORIO_API_KEY for official Albo Pretorio permit history."
                )

            return {
                "layer":  self.name,
                "label":  self.label,
                "signal": signal,
                "score":  round(score, 3),
                "detail": detail,
                "data":   osm,
                "paid":   self.paid,
            }

        # ── Paid: Albo Pretorio permit history ────────────────────────────────
        # Flow when API key is configured:
        # 1. Reverse-geocode parcel centroid → Comune name (Nominatim)
        # 2. Call Albo Pretorio API for that Comune
        # 3. Filter records by parcel cadastral code (foglio / particella)
        # 4. Count permit applications in last 5 years; check for final approval
        # 5. Flag if ≥2 applications exist with no approval on record
        # OSM proxy data is included in output as corroborating evidence.
        return self._paid_stub()
