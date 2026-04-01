#!/usr/bin/env python3
"""
layers/legal_layers/owner_relocation.py — Layer 9: Owner Relocation Signal

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
THESIS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Managing a Tuscan vineyard from Milan or London is possible, but it creates
compounding friction: local labor shortages, Italian bureaucracy that requires
in-person signatures, seasonal crises that demand physical presence, and the
psychological burden of owning something beautiful that you rarely get to enjoy.

When the gap between where the owner LIVES and where the estate IS becomes
wide enough — in both kilometers and culture — the management burden quietly
begins to exceed the lifestyle benefit. This is when estates get offered
quietly, before they ever appear on Rightmove or Gate-Away.

We detect owner relocation through three proxy signals:

  1. FISCAL ADDRESS DIVERGENCE: The owner's codice fiscale (Italian tax ID)
     encodes the municipality of birth. If that municipality is 200+ km from
     the parcel, the family didn't originate locally — and may not have
     deep roots that keep them anchored to the land.
     (Note: fiscal code = birth municipality, not current residence)

  2. AIRE REGISTRY PROXY: AIRE (Anagrafe degli Italiani Residenti all'Estero)
     is the official registry of Italians living abroad. There is no public
     API. We proxy this by checking whether the estate's website has an
     English-primary interface (indicating the owner is marketing to
     international guests, which often reflects personal international exposure).

  3. CADASTRAL CONTACT DIVERGENCE: OpenAPI.it Catasto records sometimes
     include a contact address for the owner. If that address is in a
     different province (provincia) from the parcel, it's a direct relocation
     signal.

DATA SOURCE
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  • Fiscal code decode: free, public algorithm (no API needed)
    The Italian fiscal code (codice fiscale) format is standardised.
    Characters 12–15 encode the comune of birth (Belfiore code).
    We decode this to a geographic municipality and compute the distance
    to the parcel centroid.

  • OpenAPI.it Catasto (contact address): PAID FEATURE — same key as Layer 8.

  • Website language detection: free HTTP fetch + html-parser heuristic.

⚠️  PAID FEATURE — full cadastral contact divergence requires OPENAPI_IT_KEY.
   The fiscal code decode component runs free.
"""

import sys
import os
import re
import math
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

import requests
import config
from layers.base import BaseLayer

# Distance threshold beyond which we consider the owner "relocated"
# 200 km ≈ distance from Siena to Milan — a clear management-burden threshold
RELOCATION_DISTANCE_KM = 200.0

# ── Italian Belfiore code → municipality coordinate table ─────────────────────
# The full table has ~8,000 entries. We include a representative subset for
# the most common birth municipalities relevant to Siena-area estate owners.
# A complete lookup can be sourced from: https://www.agenziaentrate.gov.it/
# Format: "BELFIORE_CODE": (lat, lon, "Comune name, Province")
BELFIORE_SAMPLE = {
    "H501": (41.8967, 12.4822, "Roma, RM"),
    "F205": (45.4642, 9.1900,  "Milano, MI"),
    "L736": (45.0793, 7.6762,  "Torino, TO"),
    "D969": (40.8518, 14.2681, "Napoli, NA"),
    "G702": (38.1157, 13.3615, "Palermo, PA"),
    "F839": (43.7696, 11.2558, "Firenze, FI"),
    "I726": (43.3183, 11.3300, "Siena, SI"),
    "E625": (43.8430, 10.5070, "Lucca, LU"),
    "G491": (43.7229, 10.4017, "Pisa, PI"),
    "A944": (43.9167, 11.1167, "Prato, PO"),
    "A509": (44.6488, 10.9255, "Bologna, BO"),
    "L682": (45.6495, 13.7768, "Trieste, TS"),
    "E379": (44.4056, 8.9463,  "Genova, GE"),
    "Z112": (None, None, "Germany"),         # foreign birth — strong relocation signal
    "Z114": (None, None, "UK"),
    "Z110": (None, None, "France"),
    "Z129": (None, None, "USA"),
    "Z136": (None, None, "Switzerland"),
}


def _decode_fiscal_birth_municipality(fiscal_code: str) -> dict:
    """
    Extract the Belfiore municipality code from an Italian codice fiscale.
    The codice fiscale format: SSSNNNYYDDLCCCZ (16 chars)
    Positions 11–14 (0-indexed) are the Belfiore code for the birth municipality.

    Returns: {"belfiore": str, "comune": str, "lat": float, "lon": float, "foreign": bool}
    """
    if not fiscal_code or len(fiscal_code) < 15:
        return {"belfiore": "", "comune": "", "lat": None, "lon": None, "foreign": False}

    belfiore = fiscal_code[11:15].upper()
    foreign  = belfiore.startswith("Z")   # Z-codes are foreign countries

    if belfiore in BELFIORE_SAMPLE:
        entry = BELFIORE_SAMPLE[belfiore]
        return {
            "belfiore": belfiore,
            "comune":   entry[2],
            "lat":      entry[0],
            "lon":      entry[1],
            "foreign":  foreign,
        }

    return {"belfiore": belfiore, "comune": "unknown", "lat": None, "lon": None, "foreign": foreign}


def _haversine_km(lat1, lon1, lat2, lon2) -> float:
    R = 6_371.0
    φ1, φ2 = math.radians(lat1), math.radians(lat2)
    dφ = math.radians(lat2 - lat1)
    dλ = math.radians(lon2 - lon1)
    a  = math.sin(dφ/2)**2 + math.cos(φ1)*math.cos(φ2)*math.sin(dλ/2)**2
    return R * 2 * math.asin(math.sqrt(a))


def _detect_english_primary_website(url: str) -> bool:
    """
    Heuristic: fetch the estate website and check whether the primary
    language is English (indicating the owner markets internationally).
    Returns True if the site appears to be English-primary.
    """
    if not url:
        return False
    try:
        if not url.startswith("http"):
            url = "https://" + url
        resp = requests.get(url, timeout=8, allow_redirects=True,
                            headers={"User-Agent": "ParcelScout/1.0"})
        if resp.status_code != 200:
            return False
        html = resp.text[:5000].lower()
        # Check lang attribute and common English phrases
        en_signals = ['lang="en"', "lang='en'", "welcome to", "book now",
                      "our wines", "visit us", "contact us", "learn more"]
        it_signals = ['lang="it"', "lang='it'", "benvenuti", "prenota",
                      "i nostri vini", "visitaci", "contattaci", "scopri"]
        en_count = sum(1 for s in en_signals if s in html)
        it_count = sum(1 for s in it_signals if s in html)
        return en_count > it_count
    except Exception:
        return False


class OwnerRelocationLayer(BaseLayer):
    """
    Layer 9 — Owner Relocation Signal

    Detects owners whose fiscal/cadastral profile suggests they no longer
    live near the estate — a leading indicator of management fatigue and
    elevated willingness to sell quietly.

    Free component: fiscal code birth municipality decode.
    Paid component: cadastral contact address divergence (OPENAPI_IT_KEY).
    """
    name  = "owner_relocation"
    label = "Owner Relocation Signal"
    paid  = True   # full implementation requires OPENAPI_IT_KEY

    def run(self, parcel: dict) -> dict:
        if not config.LAYERS.get("owner_relocation", True):
            return self._empty_result(detail="Layer disabled in config.LAYERS")

        parcel_lat = parcel["lat"]
        parcel_lon = parcel["lon"]

        relocation_flags = []
        data = {}

        # ── Free component: fiscal code birth municipality decode ──────────────
        fiscal_code = parcel.get("fiscal_code", "")
        if fiscal_code:
            birth = _decode_fiscal_birth_municipality(fiscal_code)
            data["birth_municipality"] = birth["comune"]
            data["birth_belfiore"]     = birth["belfiore"]

            if birth["foreign"]:
                relocation_flags.append(f"born abroad ({birth['comune']})")
                data["birth_dist_km"] = None
            elif birth["lat"] and birth["lon"]:
                dist_km = _haversine_km(parcel_lat, parcel_lon,
                                        birth["lat"], birth["lon"])
                data["birth_dist_km"] = round(dist_km, 1)
                if dist_km >= RELOCATION_DISTANCE_KM:
                    relocation_flags.append(
                        f"birth municipality {birth['comune']} is "
                        f"{dist_km:.0f} km from parcel"
                    )

        # ── Free component: website language proxy ────────────────────────────
        website = parcel.get("website") or parcel.get("url") or ""
        if website:
            english_primary = _detect_english_primary_website(website)
            data["website_english_primary"] = english_primary
            if english_primary:
                relocation_flags.append("website is English-primary (international marketing)")
        else:
            data["website_english_primary"] = None

        # ── Paid component: cadastral contact address ─────────────────────────
        api_key = getattr(config, "OPENAPI_IT_KEY", "")
        if not api_key:
            data["cadastral_contact"] = "PAID FEATURE"
        else:
            # When OPENAPI_IT_KEY is set:
            # Re-query /richiesta/elenco_immobili for the owner's contact address.
            # Compare the "provincia" field against "SI" (Siena).
            # If provincia != SI → owner is registered in another province → flag.
            data["cadastral_contact"] = "implementation pending — key set, enable in next release"

        # ── Synthesise result ─────────────────────────────────────────────────
        signal = len(relocation_flags) >= 1
        score  = self._clamp(len(relocation_flags) / 3.0)

        if relocation_flags:
            detail = f"Relocation signals: {'; '.join(relocation_flags)}"
        elif not fiscal_code:
            detail = "No fiscal code available — owner lookup required (OPENAPI_IT_KEY)"
        else:
            detail = "No relocation signals detected"

        return {
            "layer":  self.name,
            "label":  self.label,
            "signal": signal,
            "score":  round(score, 3),
            "detail": detail,
            "data":   data,
            "paid":   self.paid,
        }
