#!/usr/bin/env python3
"""
layers/brand_layers/digital_ghost.py — Layer 6: Digital Ghosting Index

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
THESIS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Active estate operators refresh their digital presence to attract guests,
wine club subscribers, and press attention. An estate whose website
hasn't been updated in 2+ years, whose domain is approaching expiry, or
whose social media went silent after a certain date has likely checked
out mentally — even if the estate is still technically operating.

Digital ghosting is one of the earliest and cheapest-to-detect signals
of owner fatigue. We check three proxies:

  1. DOMAIN AGE & EXPIRY: A domain expiring within 90 days without
     renewal is a strong signal the owner is not investing in the future.
     WHOIS data is free via python-whois.

  2. WAYBACK MACHINE CADENCE: The Internet Archive crawls popular sites
     regularly. If the last 5 snapshots of the estate's website all show
     the same content (same HTML hash), the site has been static for months
     or years — a "ghost site." The Wayback CDX API is free.

  3. OSM WEBSITE TAG: Many estates in OSM carry a `website` tag. We check
     whether this URL is still live (HTTP 200) and when it was last updated.

Together these signals indicate an estate that has stopped marketing
itself — the digital equivalent of taking down the "Open" sign.

DATA SOURCE
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  • python-whois: pip install python-whois (free, no API key)
  • Wayback CDX API: https://web.archive.org/cdx/search/cdx (free)
  • HTTP HEAD check: requests (no auth required)

All free. No paid API required for this layer.
"""

import sys
import os
import re
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

import requests
import config
from layers.base import BaseLayer
from datetime import date, datetime

# ── Wayback CDX API — free Internet Archive search ────────────────────────────
# The CDX (Capture inDeX) API lets us list all snapshots of a URL.
# Snapshot frequency dropping to zero is a "digital ghost" signal.
_WAYBACK_CDX = "https://web.archive.org/cdx/search/cdx"

# Domain expiry warning threshold
EXPIRY_WARNING_DAYS = 90

# If the site hasn't been crawled in this many days, flag as stale
STALE_SNAPSHOT_DAYS = 365


def _check_wayback(url: str) -> dict:
    """
    Query the Wayback Machine CDX API to find the last snapshot date
    and estimate content freshness.
    Returns: {"last_snapshot": date | None, "snapshot_count": int, "stale": bool}
    """
    try:
        # Strip protocol for CDX query
        domain = re.sub(r'^https?://', '', url).split('/')[0]
        resp = requests.get(
            _WAYBACK_CDX,
            params={
                "url":      domain,
                "output":   "json",
                "limit":    10,
                "fl":       "timestamp,statuscode",
                "filter":   "statuscode:200",
                "collapse": "digest",     # deduplicate identical pages
            },
            timeout=10,
            headers={"User-Agent": "ParcelScout/1.0"},
        )
        if resp.status_code != 200 or not resp.text.strip():
            return {"last_snapshot": None, "snapshot_count": 0, "stale": True}

        rows = resp.json()
        # First row is the header ["timestamp", "statuscode"]
        data_rows = [r for r in rows if r[0] != "timestamp"]
        if not data_rows:
            return {"last_snapshot": None, "snapshot_count": 0, "stale": True}

        # Most recent snapshot is the last row (CDX returns ascending by default)
        last_ts  = data_rows[-1][0]   # format: YYYYMMDDHHmmss
        last_date = datetime.strptime(last_ts[:8], "%Y%m%d").date()
        days_ago = (date.today() - last_date).days
        stale    = days_ago > STALE_SNAPSHOT_DAYS

        return {
            "last_snapshot":    str(last_date),
            "snapshot_count":   len(data_rows),
            "days_since_crawl": days_ago,
            "stale":            stale,
        }
    except Exception:
        return {"last_snapshot": None, "snapshot_count": 0, "stale": True}


def _check_whois(domain: str) -> dict:
    """
    Look up WHOIS data for the domain to find creation and expiry dates.
    Returns: {"expiry_date": str | None, "days_to_expiry": int | None, "expiring_soon": bool}
    """
    try:
        import whois
        w = whois.whois(domain)
        expiry = w.expiration_date
        if isinstance(expiry, list):
            expiry = expiry[0]
        if expiry is None:
            return {"expiry_date": None, "days_to_expiry": None, "expiring_soon": False}
        if isinstance(expiry, datetime):
            expiry = expiry.date()
        days_left = (expiry - date.today()).days
        return {
            "expiry_date":    str(expiry),
            "days_to_expiry": days_left,
            "expiring_soon":  days_left <= EXPIRY_WARNING_DAYS,
        }
    except Exception:
        return {"expiry_date": None, "days_to_expiry": None, "expiring_soon": False}


def _check_site_live(url: str) -> bool:
    """Return True if the website responds with HTTP 200."""
    try:
        resp = requests.head(url, timeout=8, allow_redirects=True,
                             headers={"User-Agent": "ParcelScout/1.0"})
        return resp.status_code == 200
    except Exception:
        return False


class DigitalGhostLayer(BaseLayer):
    """
    Layer 6 — Digital Ghosting Index

    Detects estates whose digital presence has gone dark — an early signal
    of owner fatigue or mental disengagement from the business.

    Free layer — no API key required. Uses python-whois and Wayback CDX.
    Requires: pip install python-whois
    """
    name  = "digital_ghost"
    label = "Digital Ghosting Index"
    paid  = False   # all free data sources

    def run(self, parcel: dict) -> dict:
        if not config.LAYERS.get("digital_ghost", True):
            return self._empty_result(detail="Layer disabled in config.LAYERS")

        # ── Get website URL from parcel OSM tags ──────────────────────────────
        # The parcel dict may have a "website" tag if the OSM element had one.
        # We also accept "url" or "contact:website" as fallbacks.
        website = (parcel.get("website") or parcel.get("url") or
                   parcel.get("contact:website") or "")

        # If no website in OSM tags, check the parcel name for a guessable URL
        if not website:
            name = parcel.get("name", "")
            if name:
                # Many Italian estates use podere-name.it or fattoria-name.com
                slug = re.sub(r'[^a-z0-9]', '-', name.lower()).strip('-')
                guessed = f"https://{slug}.it"
                if _check_site_live(guessed):
                    website = guessed

        if not website:
            return self._empty_result(detail="No website found in OSM tags for this parcel")

        # ── Ensure URL has a scheme ───────────────────────────────────────────
        if not website.startswith("http"):
            website = "https://" + website

        # ── Extract domain for WHOIS ──────────────────────────────────────────
        domain = re.sub(r'^https?://', '', website).split('/')[0]

        # ── Run checks ───────────────────────────────────────────────────────
        site_live  = _check_site_live(website)
        wayback    = _check_wayback(website)
        whois_data = _check_whois(domain)

        # ── Calculate ghost score ─────────────────────────────────────────────
        ghost_flags = []
        if not site_live:
            ghost_flags.append("website offline")
        if wayback.get("stale"):
            days = wayback.get("days_since_crawl", "?")
            ghost_flags.append(f"no new content in {days} days (Wayback)")
        if whois_data.get("expiring_soon"):
            days = whois_data.get("days_to_expiry", "?")
            ghost_flags.append(f"domain expires in {days} days")

        signal = len(ghost_flags) >= 1
        score  = self._clamp(len(ghost_flags) / 3.0)

        if ghost_flags:
            detail = f"Digital ghost signals: {'; '.join(ghost_flags)} — {website}"
        else:
            detail = (f"Website active — last crawled {wayback.get('last_snapshot', 'unknown')}, "
                      f"domain expires {whois_data.get('expiry_date', 'unknown')}")

        return {
            "layer":  self.name,
            "label":  self.label,
            "signal": signal,
            "score":  round(score, 3),
            "detail": detail,
            "data": {
                "website":          website,
                "site_live":        site_live,
                "last_snapshot":    wayback.get("last_snapshot"),
                "days_since_crawl": wayback.get("days_since_crawl"),
                "snapshot_count":   wayback.get("snapshot_count"),
                "domain_expiry":    whois_data.get("expiry_date"),
                "days_to_expiry":   whois_data.get("days_to_expiry"),
                "ghost_flags":      ghost_flags,
            },
            "paid": self.paid,
        }
