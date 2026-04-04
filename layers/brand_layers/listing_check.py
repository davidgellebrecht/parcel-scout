#!/usr/bin/env python3
"""
layers/brand_layers/listing_check.py — Layer 13: Gate-Away Listing Check

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
THESIS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
An estate appearing on Gate-Away.com — Italy's leading international
property portal — represents the seller's most public declaration of
intent.  They have:

  • Paid a listing fee (typically €300–800 for a full brochure listing)
  • Agreed to share photos, price, and floor plans with the world
  • Signalled that they want a transaction, not just enquiries

This is the highest-conviction seller-motivation signal in the tool.
The seller has crossed the psychological threshold from "thinking about
it" to "actively selling." They have price anchors in their head and
are mentally prepared to negotiate.

The strategic value to a buyer:
  • You know the price anchor before you walk in the door
  • If the listing has been sitting for 90+ days, that's a stale listing
    with a motivated (read: more negotiable) seller
  • Gate-Away attracts international buyers — if you come in with a
    credible offer while the listing is fresh, you face less competition
    than you might assume (most enquiries are tyre-kickers)

WHY GATE-AWAY SPECIFICALLY
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Gate-Away.com is Italy's largest dedicated rural/wine estate portal.
It aggregates listings from thousands of Italian agencies and private
sellers, with dedicated Tuscany and Umbria sections.

Alternative portals (future improvement):
  • Immobiliare.it — Italy's largest general portal
  • Christie's International Real Estate — ultra-premium estates
  • Sotheby's International Realty Italy
  • Idealista.it

DATA SOURCE
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Direct HTTP GET to gate-away.com search, parsing for estate name matches
in server-rendered HTML.  No API key required.

Rate limit: we add a conservative timeout; Gate-Away may rate-limit
sustained automated requests.  The layer degrades gracefully if blocked.
"""

import sys
import os
import re
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

import requests
import config
from layers.base import BaseLayer

_GATE_AWAY_SEARCH = "https://www.gate-away.com/en/search/"

# Italian estate prefixes to strip for a cleaner search query
_ESTATE_PREFIXES = [
    "tenuta ", "podere ", "fattoria ", "villa ", "castello ",
    "agriturismo ", "azienda agricola ", "cantina ", "vigna ",
    "vigna di ", "il ", "la ", "lo ", "i ", "le ", "gli ",
    "san ", "sant'", "santa ",
]

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}


def _strip_prefixes(name: str) -> str:
    """
    Remove common Italian estate prefixes so 'Tenuta San Felice' searches
    for 'San Felice' — more likely to hit the listing title.
    """
    lower = name.lower()
    for prefix in _ESTATE_PREFIXES:
        if lower.startswith(prefix):
            name = name[len(prefix):]
            lower = name.lower()
            # Only strip one prefix — avoid over-stripping
            break
    return name.strip()


def _search_gate_away(query: str, region: str = "tuscany") -> dict:
    """
    Search Gate-Away for properties matching `query` in `region`.

    Returns: {
        found: bool,
        count: int | None,   # number of listings if parseable
        first_title: str,    # title of first result if present
        url: str,
        error: str | None
    }
    """
    url = _GATE_AWAY_SEARCH
    params = {"q": query, "region": region}
    try:
        resp = requests.get(
            url,
            params=params,
            headers=_HEADERS,
            timeout=12,
            allow_redirects=True,
        )

        if resp.status_code == 429:
            return {"found": False, "count": None, "first_title": None,
                    "url": resp.url, "error": "rate_limited"}
        if resp.status_code == 403:
            return {"found": False, "count": None, "first_title": None,
                    "url": resp.url, "error": "blocked"}
        if resp.status_code != 200:
            return {"found": False, "count": None, "first_title": None,
                    "url": resp.url, "error": f"http_{resp.status_code}"}

        html  = resp.text
        qlow  = query.lower()

        # ── Try to extract result count ────────────────────────────────────────
        # Gate-Away typically shows "42 properties found" or "Trovate 42 proprietà"
        count = None
        count_patterns = [
            r'(\d+)\s+propert(?:y|ies)\s+found',
            r'(\d+)\s+result',
            r'Trovate?\s+(\d+)',
            r'"totalResults"\s*:\s*(\d+)',
            r'data-count="(\d+)"',
        ]
        for pat in count_patterns:
            m = re.search(pat, html, re.IGNORECASE)
            if m:
                count = int(m.group(1))
                break

        # ── Check if the estate name appears in the HTML ───────────────────────
        # A name match in the HTML suggests a listing for that specific estate
        name_found = qlow in html.lower()

        # ── Try to extract the first listing title ────────────────────────────
        first_title = None
        title_patterns = [
            r'<h\d[^>]*class="[^"]*(?:title|name|heading)[^"]*"[^>]*>([^<]{5,80})<',
            r'<a[^>]*class="[^"]*(?:property|listing)[^"]*"[^>]*>([^<]{5,80})<',
        ]
        for pat in title_patterns:
            m = re.search(pat, html, re.IGNORECASE)
            if m:
                first_title = m.group(1).strip()
                break

        found = (count is not None and count > 0) or name_found

        return {
            "found":       found,
            "count":       count,
            "name_match":  name_found,
            "first_title": first_title,
            "url":         resp.url,
            "error":       None,
        }

    except requests.Timeout:
        return {"found": False, "count": None, "first_title": None,
                "url": _GATE_AWAY_SEARCH, "error": "timeout"}
    except Exception as exc:
        return {"found": False, "count": None, "first_title": None,
                "url": _GATE_AWAY_SEARCH, "error": str(exc)[:80]}


class ListingCheckLayer(BaseLayer):
    """
    Layer 13 — Gate-Away Listing Check

    Searches Gate-Away.com (Italy's leading rural estate portal) for the
    parcel's estate name.  A match means the owner has publicly listed the
    property — the strongest possible declaration of seller intent.

    Signal fires when the estate is found in Gate-Away listings.

    Score is 1.0 (maximum) because an actively listed estate is the clearest
    possible acquisition signal — the seller has already decided to transact.

    Free layer — no API key required.
    """
    name  = "listing_check"
    label = "Listed for Sale?"
    paid  = False

    def run(self, parcel: dict) -> dict:
        if not config.LAYERS.get("listing_check", True):
            return self._empty_result(detail="Layer disabled in config.LAYERS")

        estate_name = (parcel.get("name") or "").strip()
        if not estate_name:
            return self._empty_result(
                detail="No estate name in OSM — cannot search Gate-Away without a property name"
            )

        # ── Search with stripped name (more likely to hit listing title) ──────
        stripped = _strip_prefixes(estate_name)
        ga       = _search_gate_away(stripped)

        # ── Fall back to full name if stripped search found nothing ───────────
        if not ga.get("found") and stripped.lower() != estate_name.lower():
            ga_full = _search_gate_away(estate_name)
            if ga_full.get("found"):
                ga = ga_full

        # ── Handle errors ─────────────────────────────────────────────────────
        if ga.get("error"):
            err = ga["error"]
            if err == "rate_limited":
                detail = "Gate-Away rate limit reached — result not available for this parcel"
            elif err == "blocked":
                detail = "Gate-Away blocked automated request — verify manually"
            elif err == "timeout":
                detail = "Gate-Away request timed out — verify manually"
            else:
                detail = f"Gate-Away search failed: {err}"
            return self._empty_result(detail=detail, data={"searched_name": stripped, "error": err})

        # ── Interpret results ─────────────────────────────────────────────────
        if ga["found"]:
            count_str = f"{ga['count']} listing(s) found" if ga.get("count") else "listing(s) found"
            detail = (
                f"'{stripped}' found on Gate-Away.com — {count_str}. "
                f"Owner has publicly listed the estate for sale. "
                f"This is the strongest possible seller-intent signal. "
                f"Search: {ga.get('url', _GATE_AWAY_SEARCH)}"
            )
            signal = True
            score  = 1.0
        else:
            detail = (
                f"'{stripped}' not found on Gate-Away.com. "
                f"Property does not appear to be publicly listed. "
                f"Verify at: {ga.get('url', _GATE_AWAY_SEARCH)}"
            )
            signal = False
            score  = 0.0

        return {
            "layer":  self.name,
            "label":  self.label,
            "signal": signal,
            "score":  round(score, 3),
            "detail": detail,
            "data": {
                "searched_name":  stripped,
                "original_name":  estate_name,
                "listing_count":  ga.get("count"),
                "name_match":     ga.get("name_match", False),
                "first_title":    ga.get("first_title"),
                "gate_away_url":  ga.get("url"),
                "data_source":    "Gate-Away.com (free, web search)",
            },
            "paid": self.paid,
        }
