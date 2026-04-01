#!/usr/bin/env python3
"""
layers/geo_layers/zoning_alchemy.py — Layer 3: Zoning Alchemy

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
THESIS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Agricultural land in Italy sits in a legal sweet spot: it can be converted
to agriturismo (rural hospitality) under national Law 96/2006 with
relatively light planning hurdles compared to full change-of-use in an
urban zone. The key requirement is that >50% of the business revenue must
come from agricultural activity.

"Zoning Alchemy" looks for early signals of this intent — specifically,
small permit filings on the Albo Pretorio that use language associated
with rural conversion:

  • "piccola costruzione rurale" — small rural structure
  • "ristrutturazione fabbricato rurale" — rural building renovation
  • "agriturismo" — explicit conversion keyword
  • "annesso agricolo" — agricultural outbuilding addition

These filings reveal the owner's development intent BEFORE the property
is listed, giving us a window to approach as a buyer while the owner is
still in the "planning" phase rather than the "selling" phase.

The gap between filing intent and formal market listing is often 2–4 years
in Italy — and that gap is our competitive advantage.

DATA SOURCE
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Same as Layer 2 (Permit Paralysis) — Albo Pretorio per Comune.
This layer focuses on KEYWORD ANALYSIS of permit filings rather than
counting stalled applications.

Bonus signal: Regione Toscana GEOscopio WFS (free, public):
  https://www502.regione.toscana.it/geoscopio/servizi/wfs
  Layer: zoning/PRG (Piano Regolatore Generale) boundaries
  Can confirm whether a parcel is already zoned E (agricultural) — a
  prerequisite for the agriturismo conversion pathway.

⚠️  PAID FEATURE — permit keyword search requires the same Albo Pretorio
   commercial API as Layer 2. The GEOscopio WFS component (zoning
   verification) is free and will be added when Layer 2 is activated.
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

import requests
import config
from layers.base import BaseLayer


# ── Conversion intent keywords (Italian) ──────────────────────────────────────
# These phrases in a permit title strongly indicate the owner is exploring
# the agriturismo or rural renovation pathway.
CONVERSION_KEYWORDS = [
    "agriturismo",
    "ristrutturazione",
    "annesso agricolo",
    "fabbricato rurale",
    "piccola costruzione rurale",
    "cambio destinazione",
    "bed and breakfast",
    "ospitalita rurale",
]

# ── Toscana GEOscopio WFS — free zoning data ──────────────────────────────────
_GEOSCOPIO_WFS = "https://www502.regione.toscana.it/geoscopio/servizi/wfs"


def _check_agricultural_zone(lat: float, lon: float) -> dict:
    """
    Query Regione Toscana GEOscopio WFS to confirm the parcel is in
    Zone E (agricultural) under the local PRG (Piano Regolatore Generale).

    Zone E is the prerequisite for the agriturismo conversion pathway under
    Italian Law 96/2006. Finding Zone E doesn't guarantee conversion success,
    but its absence makes conversion legally impossible.

    Returns a dict: {"in_zone_e": bool, "zone_label": str, "source": str}
    """
    try:
        resp = requests.get(
            _GEOSCOPIO_WFS,
            params={
                "service":     "WFS",
                "version":     "1.0.0",
                "request":     "GetFeature",
                "typeName":    "rt_sita:PRG_ZONE",
                "bbox":        f"{lon - 0.001},{lat - 0.001},{lon + 0.001},{lat + 0.001},EPSG:4326",
                "outputFormat": "application/json",
                "maxFeatures": 5,
            },
            timeout=15,
            headers={"User-Agent": "ParcelScout/1.0"},
        )
        if resp.status_code != 200:
            return {"in_zone_e": None, "zone_label": "", "source": "geoscopio_unavailable"}

        features = resp.json().get("features", [])
        for feat in features:
            props = feat.get("properties", {})
            zone = (props.get("ZONA") or props.get("zona") or
                    props.get("TIPO_ZONA") or "").upper()
            if zone.startswith("E"):
                return {"in_zone_e": True, "zone_label": zone, "source": "geoscopio"}
        return {"in_zone_e": False, "zone_label": "", "source": "geoscopio"}

    except Exception:
        return {"in_zone_e": None, "zone_label": "", "source": "geoscopio_error"}


class ZoningAlchemyLayer(BaseLayer):
    """
    Layer 3 — Zoning Alchemy

    Detects agricultural parcels whose owners are actively exploring an
    agriturismo or rural hospitality conversion — the highest-value pathway
    under Italian agricultural zoning law.

    Free component: GEOscopio Zone E confirmation.
    Paid component: Albo Pretorio conversion keyword search.
    """
    name  = "zoning_alchemy"
    label = "Zoning Alchemy"
    paid  = True   # Albo Pretorio keyword search requires paid API

    def run(self, parcel: dict) -> dict:
        if not config.LAYERS.get("zoning_alchemy", True):
            return self._empty_result(detail="Layer disabled in config.LAYERS")

        lat, lon = parcel["lat"], parcel["lon"]

        # ── Free component: Zone E zoning check via GEOscopio ────────────────
        zone_result = _check_agricultural_zone(lat, lon)
        in_zone_e   = zone_result["in_zone_e"]
        zone_label  = zone_result["zone_label"]

        zone_note = ""
        if in_zone_e is True:
            zone_note = f"Zone E confirmed ({zone_label}) — agriturismo conversion eligible"
        elif in_zone_e is False:
            zone_note = "Not in Zone E — agriturismo conversion pathway unavailable"
        else:
            zone_note = "GEOscopio zoning data unavailable"

        # ── Paid component: Albo Pretorio keyword intent search ───────────────
        api_key = getattr(config, "ALBO_PRETORIO_API_KEY", "")
        if not api_key:
            paid_note = "Albo Pretorio permit intent: PAID FEATURE — activate to see conversion filings"
        else:
            # Placeholder — live implementation queries Albo Pretorio
            # for CONVERSION_KEYWORDS within 500m of the parcel
            paid_note = "Albo Pretorio permit intent: (implementation pending)"

        signal = in_zone_e is True
        detail = f"{zone_note} | {paid_note}"

        return {
            "layer":  self.name,
            "label":  self.label,
            "signal": signal,
            "score":  0.5 if signal else 0.0,
            "detail": detail,
            "data": {
                "in_zone_e":      in_zone_e,
                "zone_label":     zone_label,
                "geoscopio_src":  zone_result["source"],
                "permit_intent":  "PAID FEATURE",
            },
            "paid": self.paid,
        }
