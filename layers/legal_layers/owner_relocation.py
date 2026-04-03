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
# The full table has ~8,000 entries. We load it on first use from a
# well-maintained open-data repository (matteocontrini/comuni-json on GitHub)
# which is sourced from the Italian Ministry of the Interior and updated
# regularly. Each entry has the Belfiore code, municipality name, and
# accurate lat/lon from ISTAT.
#
# Foreign births use Z-codes (Z + 3 digits). These are hardcoded below because
# the comuni.json covers only Italian municipalities.
_COMUNI_CACHE: dict = {}   # populated on first call to _load_comuni_index()

_COMUNI_JSON_URL = (
    "https://raw.githubusercontent.com/matteocontrini/comuni-json/master/comuni.json"
)

# Foreign country Z-codes — assigned by the Italian Agenzia delle Entrate.
# Each tuple: (lat, lon, "Country name").  None coords = distance check skipped,
# but the foreign-birth flag still fires.
FOREIGN_Z_CODES = {
    "Z100": (41.3275,  19.8187, "Albania"),
    "Z101": (42.5462,   1.6016, "Andorra"),
    "Z102": (47.5162,  14.5501, "Austria"),
    "Z103": (50.5039,   4.4699, "Belgium"),
    "Z104": (42.7339,  25.4858, "Bulgaria"),
    "Z105": (49.8175,  15.4730, "Czech Republic"),
    "Z106": (56.2639,   9.5018, "Denmark"),
    "Z107": (26.8206,  30.8025, "Egypt"),
    "Z108": (61.9241,  25.7482, "Finland"),
    "Z109": (46.2276,   2.2137, "France"),
    "Z110": (46.2276,   2.2137, "France"),   # legacy code kept for backwards compat
    "Z111": (51.1657,  10.4515, "Germany"),
    "Z112": (51.1657,  10.4515, "Germany"),  # legacy code kept for backwards compat
    "Z113": (39.0742,  21.8243, "Greece"),
    "Z114": (55.3781,  -3.4360, "United Kingdom"),
    "Z115": (47.1625,  19.5033, "Hungary"),
    "Z116": (64.9631, -19.0208, "Iceland"),
    "Z117": (52.1326,   5.2913, "Netherlands"),
    "Z118": (60.4720,   8.4689, "Norway"),
    "Z119": (51.9194,  19.1451, "Poland"),
    "Z120": (39.3999,  -8.2245, "Portugal"),
    "Z121": (45.9432,  24.9668, "Romania"),
    "Z122": (44.0165,  20.9144, "Serbia"),
    "Z123": (48.6690,  19.6990, "Slovakia"),
    "Z124": (46.1512,  14.9955, "Slovenia"),
    "Z125": (40.4637,  -3.7492, "Spain"),
    "Z126": (59.3293,  18.0686, "Sweden"),
    "Z127": (61.5240, 105.3188, "Russia"),
    "Z128": (38.9637,  35.2433, "Turkey"),
    "Z129": (37.0902, -95.7129, "USA"),
    "Z130": (50.4501,  30.5234, "Ukraine"),
    "Z131": (53.9045,  27.5615, "Belarus"),
    "Z133": (41.7151,  44.8271, "Georgia"),
    "Z134": (40.1431,  47.5769, "Azerbaijan"),
    "Z135": (38.9698,  59.5563, "Turkmenistan"),
    "Z136": (46.8182,   8.2275, "Switzerland"),
    "Z138": (53.7098,  -7.9628, "Ireland"),
    "Z139": (42.6026,  20.9030, "Kosovo"),
    "Z140": (41.9981,  21.4254, "North Macedonia"),
    "Z145": (43.9159,  17.6791, "Bosnia-Herzegovina"),
    "Z149": (42.4411,  19.2636, "Montenegro"),
    "Z150": (41.1533,  20.1683, "Albania"),   # duplicate of Z100 in some decrees
    "Z210": (35.8617, 104.1954, "China"),
    "Z217": (36.2048, 138.2529, "Japan"),
    "Z222": (28.0339,   1.6596, "Algeria"),
    "Z225": (31.7917,  -7.0926, "Morocco"),
    "Z232": (33.8869,   9.5375, "Tunisia"),
    "Z301": (-14.2350, -51.9253, "Brazil"),
    "Z307": (-38.4161, -63.6167, "Argentina"),
    "Z322": (4.5709, -74.2973, "Colombia"),
    "Z330": (-9.1900, -75.0152, "Peru"),
    "Z333": (-30.5595,  22.9375, "South Africa"),
    "Z401": (-25.2744, 133.7751, "Australia"),
    "Z402": (-40.9006, 174.8860, "New Zealand"),
    "Z700": (None, None, "Stateless / unknown"),
}


def _load_comuni_index() -> dict:
    """
    Fetch the complete Italian comuni list from GitHub (matteocontrini/comuni-json).
    Returns a dict of {belfiore_code: {"lat": float, "lon": float, "name": str}}.
    Result is cached in _COMUNI_CACHE after the first successful fetch.
    If the fetch fails, falls back to the embedded FOREIGN_Z_CODES only.
    """
    global _COMUNI_CACHE
    if _COMUNI_CACHE:
        return _COMUNI_CACHE

    try:
        resp = requests.get(_COMUNI_JSON_URL, timeout=15,
                            headers={"User-Agent": "ParcelScout/1.0"})
        if resp.status_code == 200:
            comuni = resp.json()
            index = {}
            for c in comuni:
                code = c.get("codiceCatastale", "").strip().upper()
                coords = c.get("coordinate", {})
                lat = coords.get("lat")
                lon = coords.get("lng")
                prov = c.get("sigla", "")
                name = f"{c.get('nome', '')}, {prov}"
                if code and lat and lon:
                    index[code] = {"lat": lat, "lon": lon, "name": name}
            # Merge in foreign Z-codes (not in the comuni.json)
            for zcode, (zlat, zlon, zname) in FOREIGN_Z_CODES.items():
                index[zcode] = {"lat": zlat, "lon": zlon, "name": zname}
            _COMUNI_CACHE = index
            return _COMUNI_CACHE
    except Exception:
        pass

    # Fallback: Z-codes only
    fallback = {
        zcode: {"lat": zlat, "lon": zlon, "name": zname}
        for zcode, (zlat, zlon, zname) in FOREIGN_Z_CODES.items()
    }
    _COMUNI_CACHE = fallback
    return _COMUNI_CACHE


def _decode_fiscal_birth_municipality(fiscal_code: str) -> dict:
    """
    Extract the Belfiore municipality code from an Italian codice fiscale
    and resolve it to geographic coordinates.

    Codice fiscale format: SSSNNNYYDDLCCCZ (16 chars)
    Positions 11–14 (0-indexed) = Belfiore code (birth municipality).

    Returns: {"belfiore": str, "comune": str, "lat": float|None,
              "lon": float|None, "foreign": bool}
    """
    if not fiscal_code or len(fiscal_code) < 15:
        return {"belfiore": "", "comune": "", "lat": None, "lon": None, "foreign": False}

    belfiore = fiscal_code[11:15].upper()
    foreign  = belfiore.startswith("Z")

    index = _load_comuni_index()
    if belfiore in index:
        entry = index[belfiore]
        return {
            "belfiore": belfiore,
            "comune":   entry["name"],
            "lat":      entry["lat"],
            "lon":      entry["lon"],
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
