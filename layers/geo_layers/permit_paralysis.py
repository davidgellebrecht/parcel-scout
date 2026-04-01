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

import config
from layers.base import BaseLayer


class PermitParalysisLayer(BaseLayer):
    """
    Layer 2 — Permit Paralysis

    Flags parcels where the owner has filed multiple permit applications
    (renovation, agriturismo conversion, new rural outbuilding) without
    receiving final approval — a signal of bureaucratic frustration and
    elevated sale probability.

    ⚠️  PAID FEATURE — requires Albo Pretorio API access.
    """
    name  = "permit_paralysis"
    label = "Permit Paralysis"
    paid  = True

    def run(self, parcel: dict) -> dict:
        if not config.LAYERS.get("permit_paralysis", True):
            return self._empty_result(detail="Layer disabled in config.LAYERS")

        # Check for API key (config attribute may not exist yet)
        api_key = getattr(config, "ALBO_PRETORIO_API_KEY", "")
        if not api_key:
            return self._paid_stub()

        # ── Live implementation placeholder ───────────────────────────────────
        # When the API key is available, the flow is:
        # 1. Reverse-geocode parcel centroid → Comune name (via Nominatim)
        # 2. Call the Albo Pretorio API / ANAC endpoint for that Comune
        # 3. Filter records by parcel cadastral code (foglio/particella)
        # 4. Count applications in the last 5 years and check for a final approval
        # 5. Flag if ≥2 applications exist with no approval on record
        return self._paid_stub()
