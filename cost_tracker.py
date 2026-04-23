#!/usr/bin/env python3
"""
cost_tracker.py — Thin wrapper around `requests` that auto-logs every call.

Rather than editing every requests.get()/post() in the project, callers import
`tracked_request` from here and pass a short API name as the first argument.
The wrapper measures duration, catches exceptions, and writes one row to the
api_calls table via storage.log_api_call().

Usage:
    from cost_tracker import tracked_request

    resp = tracked_request("overpass", "post", url, data={"data": query}, timeout=60)

    # For free APIs, that's all you need — cost defaults to $0 and quota=1 call.
    # For paid APIs, pass cost_usd=0.002 (or whatever a single call costs).

Per-API cost/quota defaults live in API_PROFILES below so magic numbers don't
sprinkle through the codebase. Unknown APIs default to free / 1 quota unit.
"""
from __future__ import annotations

import time
from typing import Callable, Optional

import requests

import storage


# ── Per-API cost + quota profile ─────────────────────────────────────────────
# Keys are the short API names callers pass to tracked_request().
# Values:
#   cost_usd    — dollars per call (0 for free APIs)
#   quota_units — how many "credits" this burns against a provider quota
#                 (e.g. TripAdvisor free tier = 5,000 req/month; each call = 1 unit)
#
# This is where you tune the numbers as you learn real per-call pricing.
API_PROFILES: dict[str, dict] = {
    # ── Free public APIs ──────────────────────────────────────────────────
    "overpass":    {"cost_usd": 0.0, "quota_units": 1.0},   # OSM Overpass
    "ade_wfs":     {"cost_usd": 0.0, "quota_units": 1.0},   # Agenzia delle Entrate
    "corine":      {"cost_usd": 0.0, "quota_units": 1.0},   # EU Copernicus CORINE
    "effis":       {"cost_usd": 0.0, "quota_units": 1.0},   # EU fire history WFS
    "nominatim":   {"cost_usd": 0.0, "quota_units": 1.0},   # OSM reverse-geocode
    "wayback":     {"cost_usd": 0.0, "quota_units": 1.0},   # Internet Archive CDX
    "whois":       {"cost_usd": 0.0, "quota_units": 1.0},
    "opentopo":    {"cost_usd": 0.0, "quota_units": 1.0},   # OpenTopoData SRTM
    "opencorp":    {"cost_usd": 0.0, "quota_units": 1.0},   # OpenCorporates free tier
    "gateaway":    {"cost_usd": 0.0, "quota_units": 1.0},   # Gate-Away.com listings
    "regione_wfs": {"cost_usd": 0.0, "quota_units": 1.0},   # Regione Toscana
    "comuni_json": {"cost_usd": 0.0, "quota_units": 1.0},   # GitHub raw comuni index
    "website":     {"cost_usd": 0.0, "quota_units": 1.0},   # generic estate-website probes
    # ── Free-tier APIs (quota-constrained) ────────────────────────────────
    "tripadvisor": {"cost_usd": 0.0, "quota_units": 1.0},   # 5,000 req/month
    "wine_searcher": {"cost_usd": 0.0, "quota_units": 1.0}, # 100 req/day
    "openapi_it":  {"cost_usd": 0.0, "quota_units": 1.0},   # Catasto free tier
    # ── Paid APIs ─────────────────────────────────────────────────────────
    "sentinel_hub":    {"cost_usd": 0.002, "quota_units": 1.0},   # rough per-request
    "albo_pretorio":   {"cost_usd": 0.01,  "quota_units": 1.0},
}


def _profile(api: str) -> dict:
    return API_PROFILES.get(api, {"cost_usd": 0.0, "quota_units": 1.0})


# ── Main wrapper ─────────────────────────────────────────────────────────────

def tracked_request(
    api: str,
    method: str,
    url: str,
    cost_usd: Optional[float] = None,
    quota_units: Optional[float] = None,
    **kwargs,
) -> requests.Response:
    """
    Make an HTTP request via `requests.<method>(url, **kwargs)` and log it.

    Parameters
    ----------
    api : str
        Short key identifying the provider — used for grouping in the cost badge.
    method : str
        'get', 'post', 'put', etc.
    url : str
    cost_usd, quota_units : override the defaults from API_PROFILES.

    Returns the raw `requests.Response`. Exceptions still propagate — callers
    keep their existing try/except logic. On exception we log status=0 so the
    call still shows up in the receipts ledger.
    """
    profile = _profile(api)
    cost    = profile["cost_usd"]    if cost_usd    is None else cost_usd
    units   = profile["quota_units"] if quota_units is None else quota_units

    fn: Callable = getattr(requests, method.lower())
    t0 = time.monotonic()
    status = 0
    try:
        resp: requests.Response = fn(url, **kwargs)
        status = resp.status_code
        return resp
    finally:
        duration_ms = int((time.monotonic() - t0) * 1000)
        try:
            storage.log_api_call(
                api=api,
                endpoint=url,
                status=status,
                cost_usd=cost,
                quota_units=units,
                cached=False,
                duration_ms=duration_ms,
            )
        except Exception:
            # Never let cost logging crash the actual pipeline.
            pass


def log_cached_hit(api: str, endpoint: str = "") -> None:
    """
    Record a cache hit (no real HTTP call). Useful for layers that maintain
    their own in-process cache — we want the badge to show 'served from cache'
    so quota bookkeeping stays honest.
    """
    try:
        storage.log_api_call(
            api=api, endpoint=endpoint, status=200,
            cost_usd=0.0, quota_units=0.0, cached=True, duration_ms=0,
        )
    except Exception:
        pass
