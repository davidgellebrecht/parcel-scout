#!/usr/bin/env python3
"""
layers/legal_layers/succession_fragmentation.py — Layer 8: Succession Fragmentation

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
THESIS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Italian inheritance law (successione ereditaria — governed by Articles
565–586 of the Codice Civile) distributes an estate EQUALLY among all
legitimate heirs. For a rural property, this means:

  • 1 founding patriarch/matriarch → 1 clear decision-maker
  • After inheritance → 3, 4, or 5 co-owners (their children)
  • Each co-owner has "diritto di prelazione" (right of first refusal)
    on the others' shares

The co-ownership structure creates a coordination problem: all owners
must agree on capital improvements, annual harvest decisions, insurance,
and asking price. In practice, co-owners who live in different cities
(or different countries) rarely reach consensus quickly, and the property
gradually deteriorates from neglect-by-committee.

A parcel that has moved from 1 owner to 3+ owners in the last 15 years
is statistically MORE likely to sell — and to accept a below-market
offer — because the sale proceeds distributed among co-owners each look
smaller and more "acceptable" than the total sale price would suggest.

This is the legal equivalent of a "motivated seller" multiplied by
the number of co-owners.

DATA SOURCE
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
OpenAPI.it — Catasto / Agenzia delle Entrate (commercial tier)
  • Endpoint: /richiesta/elenco_immobili (same as scout.py owner lookup)
  • Returns: proprietari[] array with name, fiscal code, ownership share %
  • Co-ownership is flagged when proprietari.length > 1

Free tier covers point-in-time lookups. Historical owner tracking
(to detect 1→N transitions) requires the commercial subscription.

⚠️  PAID FEATURE — requires OPENAPI_IT_KEY (commercial tier) in config.py.
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

import requests
import config
from layers.base import BaseLayer

# Minimum owner count to flag co-ownership as a fragmentation signal
FRAGMENTATION_THRESHOLD = 2   # 2+ owners = flagged; 3+ = strong signal

# Maximum share percentage for the largest owner — if one owner holds >90%,
# it's not really fragmented (other owners are token/minor)
DOMINANT_OWNER_MAX_PCT = 90.0


class SuccessionFragmentationLayer(BaseLayer):
    """
    Layer 8 — Succession Fragmentation

    Detects parcels with multiple co-owners — a reliable indicator of
    post-inheritance pressure to liquidate, especially when co-owners
    are geographically dispersed.

    ⚠️  PAID FEATURE — requires OpenAPI.it Catasto commercial API key.
    """
    name  = "succession_frag"
    label = "Succession Fragmentation"
    paid  = True

    def run(self, parcel: dict) -> dict:
        if not config.LAYERS.get("succession_frag", True):
            return self._empty_result(detail="Layer disabled in config.LAYERS")

        api_key = getattr(config, "OPENAPI_IT_KEY", "")
        if not api_key:
            # Provide value even without the key: surface the Group 1 succession
            # signal that scout.py already computed.
            succ_signal = parcel.get("g2_succession_signal", False)
            succ_detail = parcel.get("g2_succession_detail", "")
            if succ_signal:
                detail = (f"OSM succession proxy hit ({succ_detail}). "
                          f"Activate OPENAPI_IT_KEY to confirm cadastral co-ownership.")
            else:
                detail = "No OSM succession proxy. PAID FEATURE — add OPENAPI_IT_KEY to config.py."
            return self._paid_stub() if not succ_signal else self._empty_result(
                signal=True, detail=detail
            )

        # ── Live implementation (when OPENAPI_IT_KEY is set) ──────────────────
        # We reuse the owner lookup infrastructure already in scout.py.
        # Here we extend it to count proprietari and compute shares.
        #
        # Flow:
        # 1. Use Nominatim reverse-geocode → comune + road (already in scout.py)
        # 2. POST /richiesta/elenco_immobili → proprietari[] array
        # 3. Count owners; check if any single owner holds >90% share
        # 4. Flag if owner_count >= FRAGMENTATION_THRESHOLD and no dominant owner
        #
        # proprietari[] item schema:
        #   {
        #       "nome_cognome": "Mario Rossi",
        #       "codice_fiscale": "RSSMRA...",
        #       "quota": "1/3",           ← ownership fraction as a string
        #       "diritto": "Proprietà",   ← ownership type
        #   }
        #
        # Parse "quota" as a fraction: "1/3" → 33.3%, "2/3" → 66.7%
        # Compare against DOMINANT_OWNER_MAX_PCT to detect genuine fragmentation.

        parcel_code = parcel.get("parcel_code", "")
        if not parcel_code:
            return self._empty_result(detail="No cadastral code available — run owner lookup first")

        try:
            headers = {"Authorization": api_key, "User-Agent": "ParcelScout/1.0"}
            # Re-query to get full proprietari data (scout.py only returns first owner)
            foglio, particella = parcel_code.split("/") if "/" in parcel_code else ("", "")
            resp = requests.post(
                "https://catasto.openapi.it/richiesta/elenco_immobili",
                json={"foglio": foglio, "particella": particella,
                      "comune": parcel.get("municipality", "")},
                headers=headers,
                timeout=15,
            )
            if resp.status_code != 200:
                return self._empty_result(detail=f"API error {resp.status_code}")

            immobili    = resp.json().get("immobili", [])
            if not immobili:
                return self._empty_result(detail="No cadastral records returned")

            proprietari = immobili[0].get("proprietari", [])
            owner_count = len(proprietari)

            # Parse ownership shares
            shares = []
            for p in proprietari:
                quota = p.get("quota", "1/1")
                try:
                    num, den = quota.split("/")
                    shares.append(float(num) / float(den) * 100)
                except Exception:
                    shares.append(100.0 / owner_count)

            max_share   = max(shares) if shares else 100.0
            fragmented  = owner_count >= FRAGMENTATION_THRESHOLD and max_share < DOMINANT_OWNER_MAX_PCT
            signal      = fragmented
            score       = self._clamp((owner_count - 1) / 4.0) if fragmented else 0.0

            names = "; ".join(
                p.get("nome_cognome") or p.get("denominazione", "")
                for p in proprietari
            )
            detail = (f"{owner_count} co-owners: {names} "
                      f"(largest share: {max_share:.0f}%)")

            return {
                "layer":  self.name,
                "label":  self.label,
                "signal": signal,
                "score":  round(score, 3),
                "detail": detail,
                "data": {
                    "owner_count":     owner_count,
                    "max_share_pct":   round(max_share, 1),
                    "is_fragmented":   fragmented,
                    "proprietari":     [p.get("nome_cognome", "") for p in proprietari],
                },
                "paid": self.paid,
            }

        except Exception as exc:
            return self._empty_result(detail=f"Error: {exc.__class__.__name__} — {exc}")
