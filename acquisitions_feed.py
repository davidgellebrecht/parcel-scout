#!/usr/bin/env python3
"""
acquisitions_feed.py — Recent-acquisitions feed for Parcel Scout.

Two data paths, both feeding into the same `acquisitions` table:

  Layer A — News-driven:
    Gemini 2.0 Flash + Google Search grounding. Given a prompt describing
    what we want (Tuscan wine/estate acquisitions, last 3 years, with buyer
    names), Gemini does the search and returns structured JSON. Each item
    has buyer, seller, estate, date, price, and the article URL.

  Layer B — Company-formation signal:
    OpenCorporates search for new Italian agricultural LLCs in Tuscan
    provinces. Each new S.r.l. with a wine/olive/farming SIC code is a
    leading indicator that a parcel was (or will be) acquired by that entity.

Both functions are idempotent — they de-duplicate against the DB via a
stable `dedupe_key` so re-running doesn't create duplicate rows.
"""
from __future__ import annotations

import json
import os
import re
from datetime import date, datetime, timedelta
from typing import Optional

import storage
from cost_tracker import tracked_request


# ── Tuscan province codes (provincia abbreviations) ─────────────────────────
# Used to filter company-formation results to the region the app cares about.
TUSCAN_PROVINCES = {"SI", "FI", "GR", "PI", "LU", "AR", "PO", "LI", "MS"}

# ── OpenCorporates SIC codes for agricultural / wine-related businesses ─────
# These are Italian ATECO codes (Italy's version of SIC):
#   01.21 — grape growing
#   01.26 — oleaginous fruit growing (olives)
#   11.02 — wine production
#   01.50 — mixed farming
#   01.41 / 01.42 — livestock (included as adjacent — some wine estates mix)
WINE_AG_ATECO_CODES = ["01.21", "01.26", "11.02", "01.50", "01.11", "01.42"]

_OPENCORPORATES_BASE = "https://api.opencorporates.com/v0.4"


# ─── Layer A: Gemini news search ─────────────────────────────────────────────

_GEMINI_SYSTEM_PROMPT = """You are a real-estate intelligence researcher. Your
job is to find acquisitions of wine estates, vineyards, olive groves, and
agricultural properties in Tuscany, Italy that occurred in the last 3 years.

For each acquisition you find, extract:
- acquisition_date  (ISO date YYYY-MM-DD; if only year is known, use YYYY-01-01)
- buyer_name        (the acquiring party — company or individual)
- buyer_type        ("company" if an LLC/S.r.l./S.p.A./corporation, "individual" if a person, "unknown" if unclear)
- seller_name       (the selling party, if mentioned)
- estate_name       (the name of the estate/vineyard/property)
- location_comune   (the Italian comune, e.g. "Gaiole in Chianti")
- location_province (two-letter Italian province code: SI, FI, GR, PI, LU, AR, PO, LI, MS — only Tuscan provinces)
- estate_type       ("wine" | "olive" | "mixed" | "agricultural")
- price_eur         (integer in euros; null if not disclosed)
- source_url        (the article URL)
- source_title      (the article headline)
- confidence        ("high" if buyer + date are both clearly stated, "medium" if most fields are stated, "low" if uncertain)

Return ONLY a JSON array of objects — no prose, no markdown fences. If you
find no qualifying acquisitions, return an empty array [].

Prioritize:
- Wine-producing estates in DOCG/DOC zones (Chianti Classico, Brunello di
  Montalcino, Vino Nobile di Montepulciano, Bolgheri, Morellino di Scansano,
  Montecucco Sangiovese)
- Deals reported in wine/business press (Decanter, Wine Spectator,
  Wine Business, Gambero Rosso, Il Sole 24 Ore, Corriere della Sera)

Exclude:
- Rumors / unconfirmed deals
- Restaurants, hotels without an estate component
- Deals outside the last 3 years
"""


def fetch_news_acquisitions(
    lookback_years: int = 3,
    max_results:    int = 40,
) -> list[dict]:
    """
    Ask Gemini (with Google Search grounding) to find recent Tuscan estate
    acquisitions. Writes each to the DB, returns the list of new records.

    Requires GEMINI_API_KEY env var. Gracefully no-ops with a diagnostic
    dict if the key or SDK is missing, so the app never crashes.
    """
    key = os.environ.get("GEMINI_API_KEY", "")
    if not key:
        return [{"error": "GEMINI_API_KEY not set — cannot run news search"}]

    try:
        from google import genai
        from google.genai import types as genai_types
    except ImportError:
        return [{"error": "google-genai not installed (pip install google-genai)"}]

    cutoff = (date.today() - timedelta(days=lookback_years * 365)).isoformat()
    user_prompt = (
        f"Find wine estate, vineyard, olive grove, or agricultural property "
        f"acquisitions in Tuscany, Italy that occurred on or after {cutoff}. "
        f"Search Italian and English sources. Return up to {max_results} items "
        f"as a JSON array matching the schema in the system instructions. "
        f"Do not include deals earlier than {cutoff}."
    )

    client = genai.Client(api_key=key)

    # Log the call under the 'gemini' API in cost_tracker.
    # We do this around the SDK call rather than via tracked_request because
    # the Gemini SDK doesn't use plain requests.* under the hood.
    import time as _time
    t0 = _time.monotonic()
    try:
        response = client.models.generate_content(
            model="gemini-2.0-flash",
            contents=user_prompt,
            config=genai_types.GenerateContentConfig(
                system_instruction=_GEMINI_SYSTEM_PROMPT,
                tools=[genai_types.Tool(google_search=genai_types.GoogleSearch())],
                temperature=0.2,
            ),
        )
        text = response.text or ""
        status = 200
    except Exception as exc:
        storage.log_api_call(
            api="gemini", endpoint="generate_content:gemini-2.0-flash",
            status=0, cost_usd=0.0, quota_units=1.0, cached=False,
            duration_ms=int((_time.monotonic() - t0) * 1000),
        )
        return [{"error": f"Gemini call failed: {exc}"}]

    storage.log_api_call(
        api="gemini", endpoint="generate_content:gemini-2.0-flash",
        status=status, cost_usd=0.0, quota_units=1.0, cached=False,
        duration_ms=int((_time.monotonic() - t0) * 1000),
    )

    records = _parse_gemini_json(text)
    return _persist_acquisitions(records, source_type="news", cutoff=cutoff)


def _parse_gemini_json(text: str) -> list[dict]:
    """Extract the JSON array from Gemini's response, tolerating markdown fences."""
    if not text:
        return []
    # Strip markdown code fences if present
    t = text.strip()
    t = re.sub(r"^```(?:json)?\s*", "", t)
    t = re.sub(r"\s*```$", "", t)
    # Find the first '[' and last ']' as a safety net
    start = t.find("[")
    end   = t.rfind("]")
    if start == -1 or end == -1 or end < start:
        return []
    try:
        data = json.loads(t[start:end + 1])
    except json.JSONDecodeError:
        return []
    return data if isinstance(data, list) else []


# ─── Layer B: OpenCorporates company formations ─────────────────────────────

def fetch_company_formations(
    lookback_years: int = 3,
    max_results:    int = 50,
) -> list[dict]:
    """
    Search OpenCorporates for newly-formed Italian agricultural LLCs in Tuscan
    provinces with wine/olive/farming ATECO codes. Each is a proxy acquisition
    signal — a new holding company often means a new owner recently bought (or
    is about to buy) a parcel.
    """
    cutoff_year = date.today().year - lookback_years
    results = []

    for code in WINE_AG_ATECO_CODES:
        try:
            resp = tracked_request(
                "opencorp", "get",
                f"{_OPENCORPORATES_BASE}/companies/search",
                params={
                    "q":                 "",
                    "jurisdiction_code": "it",
                    "industry_codes":    code,
                    "incorporation_date_gte": f"{cutoff_year}-01-01",
                    "per_page":          max_results,
                    "order":             "incorporation_date",
                },
                timeout=15,
                headers={"User-Agent": "ParcelScout/1.0"},
            )
            if resp.status_code != 200:
                continue
            data = resp.json().get("results", {}).get("companies", [])
            for entry in data:
                co = entry.get("company", {})
                # Filter by Tuscan province via registered address heuristic
                addr = (co.get("registered_address_in_full") or "").upper()
                province = _extract_province(addr)
                if province not in TUSCAN_PROVINCES:
                    continue
                inc = co.get("incorporation_date", "")
                results.append({
                    "acquisition_date":  inc,
                    "buyer_name":        co.get("name", ""),
                    "buyer_type":        "company",
                    "seller_name":       None,
                    "estate_name":       None,
                    "location_comune":   None,
                    "location_province": province,
                    "estate_type":       _estate_type_from_ateco(code),
                    "price_eur":         None,
                    "source_type":       "company_formation",
                    "source_url":        co.get("opencorporates_url", ""),
                    "source_title":      f"New {_estate_type_from_ateco(code)} LLC — {co.get('name', '')}",
                    "confidence":        "medium",
                    "ateco_code":        code,
                    "company_number":    co.get("company_number", ""),
                })
        except Exception:
            continue

    cutoff_iso = (date.today() - timedelta(days=lookback_years * 365)).isoformat()
    return _persist_acquisitions(results, source_type="company_formation", cutoff=cutoff_iso)


def _extract_province(address: str) -> str:
    """
    Pull a two-letter Italian province code from a full address string.
    Italian addresses typically end with: "... - 53013 GAIOLE IN CHIANTI SI"
    """
    m = re.search(r"\b([A-Z]{2})\b\s*$", address.strip())
    return m.group(1) if m else ""


def _estate_type_from_ateco(code: str) -> str:
    if code == "01.21":
        return "wine"
    if code == "11.02":
        return "wine"
    if code == "01.26":
        return "olive"
    if code == "01.50":
        return "mixed"
    return "agricultural"


# ─── Persistence + de-dup ────────────────────────────────────────────────────

def _persist_acquisitions(
    records:     list[dict],
    source_type: str,
    cutoff:      str,
) -> list[dict]:
    """
    Write each record to the DB, skipping duplicates (by dedupe_key) and
    anything older than the cutoff. Returns the final list (with db_id set).
    """
    out: list[dict] = []
    for r in records:
        if not isinstance(r, dict):
            continue
        # Skip if source type mismatch (defensive — Gemini occasionally invents)
        r["source_type"] = source_type
        # Skip items older than cutoff (Gemini sometimes returns older ones)
        if r.get("acquisition_date") and r["acquisition_date"] < cutoff:
            continue
        # Build a stable dedupe key
        if source_type == "news":
            r["dedupe_key"] = f"news:{(r.get('source_url') or '').strip()}"
        else:
            r["dedupe_key"] = f"company:{(r.get('company_number') or '').strip()}"
        if not r["dedupe_key"].split(":", 1)[1]:
            continue   # no stable key → skip
        rid, was_new = storage.upsert_acquisition(r)
        r["db_id"]   = rid
        r["was_new"] = was_new
        out.append(r)
    return out


# ─── Combined refresh ───────────────────────────────────────────────────────

def refresh_all(lookback_years: int = 3) -> dict:
    """
    Run both layers and return a summary dict for the UI.
    """
    news   = fetch_news_acquisitions(lookback_years=lookback_years)
    comps  = fetch_company_formations(lookback_years=lookback_years)

    news_ok    = [n for n in news  if "error" not in n]
    news_err   = [n for n in news  if "error" in n]

    return {
        "news_added":   sum(1 for n in news_ok  if n.get("was_new")),
        "news_updated": sum(1 for n in news_ok  if not n.get("was_new")),
        "news_errors":  news_err,
        "comp_added":   sum(1 for c in comps if c.get("was_new")),
        "comp_updated": sum(1 for c in comps if not c.get("was_new")),
        "total_rows":   len(news_ok) + len(comps),
    }
