#!/usr/bin/env python3
"""
layers/brand_layers/succession_stress.py — Layer: Succession Stress Index

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
THESIS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
An estate showing two or more of the following is under "succession stress"
— its owners are likely disengaged, aging, or spread across multiple heirs:

  1. DIGITAL STALENESS: Website hasn't been crawled by the Wayback Machine
     in 365+ days, or no web presence exists at all. Active operators refresh
     their online presence to attract wine tourists and press.

  2. DISSOLVED / DORMANT COMPANY: The estate is registered in the Italian
     company registry (Registro Imprese) as Dissolved, Inactive, or Dormant.
     A live estate should show "Active."

  3. AGING COMPANY: The operating company was incorporated 25+ years ago.
     Without a documented ownership transition, this suggests the founder
     generation is still in control and succession has not been planned.

  4. FRAGMENTED DIRECTORSHIP: 3 or more registered directors typically
     indicates the company was inherited by multiple siblings or cousins —
     the classic Italian succession fragmentation pattern.

DATA SOURCES — both free, no API key required
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  • Wayback Machine CDX API  — https://web.archive.org/cdx/search/cdx
    Free, no authentication, no rate limit documented.

  • OpenCorporates API       — https://api.opencorporates.com/v0.4/
    500 requests/month unauthenticated. Italian jurisdiction_code: "it".
    Covers the Italian Registro Imprese (Chambers of Commerce data).
    Optional: register at opencorporates.com for higher limits.

RATE LIMIT NOTE
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
OpenCorporates makes at most 2 calls per named parcel (1 search + 1
officers lookup if the company is found). Parcels with no OSM name tag
make zero calls. Typical Chianti scan: ~5–15 named parcels = 10–30 calls.
Monthly budget of 500 is rarely approached.
"""

import sys
import os
import re
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

import requests
import config
from layers.base import BaseLayer
from datetime import date, datetime

# ── Constants ─────────────────────────────────────────────────────────────────
_WAYBACK_CDX         = "https://web.archive.org/cdx/search/cdx"
_OPENCORPORATES_BASE = "https://api.opencorporates.com/v0.4"
_STALE_DAYS          = 365    # website not crawled in this many days = stale
_OLD_COMPANY_YEARS   = 25     # company incorporated 25+ years ago = aging risk
_MANY_DIRECTORS      = 3      # 3+ directors = fragmented control likely

# Italian estate name prefixes to strip before doing a company search
# ("Tenuta San Felice" → search "San Felice" for better registry match)
_ESTATE_PREFIXES = (
    "podere", "fattoria", "tenuta", "castello", "villa", "cascina",
    "masseria", "casale", "azienda", "pieve", "rocca", "borgo",
    "monte", "colle", "il ", "la ", "lo ", "le ", "i ", "gli ",
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _strip_prefix(name: str) -> str:
    """Remove leading Italian estate prefixes to get the core name."""
    lower = name.lower()
    for prefix in _ESTATE_PREFIXES:
        if lower.startswith(prefix):
            name = name[len(prefix):].strip()
            lower = name.lower()
    return name


def _guess_domain(name: str) -> str:
    """
    Build a plausible .it domain from an estate name.
    "Tenuta San Felice" → "tenutasanfelice.it"
    """
    slug = re.sub(r"[^a-z0-9]", "", name.lower())
    return f"{slug}.it"


def _check_wayback(domain: str) -> dict:
    """
    Check when the Wayback Machine last successfully crawled this domain.
    Returns: {last_snapshot, snapshot_count, days_since_crawl, stale}
    """
    try:
        resp = requests.get(
            _WAYBACK_CDX,
            params={
                "url":      domain,
                "output":   "json",
                "limit":    5,
                "fl":       "timestamp,statuscode",
                "filter":   "statuscode:200",
                "collapse": "digest",
            },
            timeout=10,
            headers={"User-Agent": "ParcelScout/1.0"},
        )
        if resp.status_code != 200 or not resp.text.strip():
            return {"last_snapshot": None, "snapshot_count": 0,
                    "days_since_crawl": None, "stale": True}

        rows = resp.json()
        data_rows = [r for r in rows if r[0] != "timestamp"]
        if not data_rows:
            return {"last_snapshot": None, "snapshot_count": 0,
                    "days_since_crawl": None, "stale": True}

        last_ts   = data_rows[-1][0]
        last_date = datetime.strptime(last_ts[:8], "%Y%m%d").date()
        days_ago  = (date.today() - last_date).days

        return {
            "last_snapshot":    str(last_date),
            "snapshot_count":   len(data_rows),
            "days_since_crawl": days_ago,
            "stale":            days_ago > _STALE_DAYS,
        }
    except Exception:
        return {"last_snapshot": None, "snapshot_count": 0,
                "days_since_crawl": None, "stale": True}


def _check_opencorporates(name: str) -> dict:
    """
    Search the Italian company registry via OpenCorporates.
    Strips estate prefixes first for a better match rate.
    Returns: {found, company_name, status, incorporation_year,
              company_age_years, director_count, oc_url}
    """
    search_name = _strip_prefix(name).strip()
    if not search_name:
        return {"found": False}

    try:
        resp = requests.get(
            f"{_OPENCORPORATES_BASE}/companies/search",
            params={
                "q":               search_name,
                "jurisdiction_code": "it",
                "per_page":        1,
            },
            timeout=12,
            headers={"User-Agent": "ParcelScout/1.0"},
        )
        if resp.status_code == 429:
            return {"found": False, "rate_limited": True}
        if resp.status_code != 200:
            return {"found": False}

        companies = (resp.json()
                     .get("results", {})
                     .get("companies", []))
        if not companies:
            return {"found": False}

        co = companies[0].get("company", {})
        status = co.get("current_status", "") or ""
        inc_raw = co.get("incorporation_date", "") or ""
        inc_year = None
        age_years = None
        if inc_raw:
            try:
                inc_year  = int(inc_raw[:4])
                age_years = date.today().year - inc_year
            except ValueError:
                pass

        # ── Optional: fetch officer count ─────────────────────────────────
        director_count = None
        co_number      = co.get("company_number", "")
        if co_number:
            try:
                off_resp = requests.get(
                    f"{_OPENCORPORATES_BASE}/companies/it/{co_number}/officers",
                    params={"per_page": 50},
                    timeout=10,
                    headers={"User-Agent": "ParcelScout/1.0"},
                )
                if off_resp.status_code == 200:
                    officers = (off_resp.json()
                                .get("results", {})
                                .get("officers", []))
                    director_count = len(officers)
            except Exception:
                pass

        return {
            "found":              True,
            "company_name":       co.get("name", ""),
            "status":             status,
            "incorporation_year": inc_year,
            "company_age_years":  age_years,
            "director_count":     director_count,
            "oc_url":             co.get("opencorporates_url", ""),
        }

    except Exception:
        return {"found": False}


# ── Layer class ───────────────────────────────────────────────────────────────

class SuccessionStressLayer(BaseLayer):
    """
    Succession Stress Index — detects estates under ownership pressure
    through digital staleness and Italian company registry signals.

    Free layer — Wayback Machine CDX + OpenCorporates (500 req/month free).
    Only runs on parcels that have an OSM name tag (estate name required).
    """
    name  = "succession_stress"
    label = "Succession Stress"
    paid  = False

    def run(self, parcel: dict) -> dict:
        if not config.LAYERS.get("succession_stress", True):
            return self._empty_result(detail="Layer disabled in config.LAYERS")

        estate_name = parcel.get("name", "").strip()
        if not estate_name:
            return self._empty_result(
                detail="No OSM name tag — cannot assess digital presence or registry status"
            )

        stress_flags = []
        data         = {"estate_name": estate_name}

        # ── 1. Website freshness via Wayback Machine ──────────────────────
        domain = _guess_domain(estate_name)
        wb     = _check_wayback(domain)
        data.update({f"wb_{k}": v for k, v in wb.items()})

        if wb.get("snapshot_count", 0) == 0:
            stress_flags.append("no web presence found in Wayback Machine archive")
        elif wb.get("stale"):
            days = wb.get("days_since_crawl", "?")
            stress_flags.append(f"website stale — last crawled {days} days ago")

        # ── 2. Italian company registry via OpenCorporates ────────────────
        oc = _check_opencorporates(estate_name)
        data.update({f"oc_{k}": v for k, v in oc.items()})

        if oc.get("found"):
            status = oc.get("status", "")
            if status and status.lower() in ("dissolved", "inactive", "dormant"):
                stress_flags.append(
                    f"company {status.lower()} in Italian registry "
                    f"({oc.get('company_name', estate_name)})"
                )
            age = oc.get("company_age_years")
            if age and age >= _OLD_COMPANY_YEARS:
                stress_flags.append(
                    f"company est. {oc.get('incorporation_year')} "
                    f"({age} yrs — succession not yet documented)"
                )
            directors = oc.get("director_count")
            if directors and directors >= _MANY_DIRECTORS:
                stress_flags.append(
                    f"{directors} registered directors — fragmented control likely"
                )
        elif oc.get("rate_limited"):
            data["oc_note"] = "OpenCorporates rate limit reached — try again later"

        # ── Stress level + signal ─────────────────────────────────────────
        n = len(stress_flags)
        if n >= 2:
            stress_level, signal, score = "High",   True,  0.90
        elif n == 1:
            stress_level, signal, score = "Medium",  True,  0.50
        else:
            stress_level, signal, score = "Low",     False, 0.10

        if stress_flags:
            detail = f"Stress: {stress_level} — " + "; ".join(stress_flags)
        else:
            detail = f"Stress: Low — no indicators found for '{estate_name}'"

        data["stress_level"] = stress_level
        data["stress_flags"] = stress_flags

        return {
            "layer":  self.name,
            "label":  self.label,
            "signal": signal,
            "score":  round(score, 3),
            "detail": detail,
            "data":   data,
            "paid":   self.paid,
        }
