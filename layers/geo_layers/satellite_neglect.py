#!/usr/bin/env python3
"""
layers/geo_layers/satellite_neglect.py — Layer 1: Satellite Neglect Index

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
THESIS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Healthy, actively managed vineyards maintain consistently high NDVI
(Normalized Difference Vegetation Index — a satellite-measured greenness
score, where 0.0 = bare soil and 1.0 = dense healthy canopy) through the
growing season.

A parcel that scores 0.15+ NDVI units below its immediate neighbors has
almost certainly received less irrigation, fertiliser, and canopy management.
That gap — the "Vigor Delta" — is the agricultural equivalent of deferred
maintenance: the first observable sign of absentee ownership before the
estate hits the market (if it ever does formally).

We calculate:
    vigor_delta = neighborhood_mean_ndvi - parcel_ndvi
    A positive delta means the parcel is underperforming its neighbors.
    Values > 0.10 are flagged as a mild neglect signal.
    Values > 0.20 are flagged as a strong neglect signal.

DATA SOURCE
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Sentinel Hub Statistical API — https://www.sentinel-hub.com/
• Satellite: Sentinel-2 L2A (10m resolution, free with registration)
• Bands used: B08 (Near-Infrared, 842 nm) and B04 (Red, 665 nm)
• Formula:   NDVI = (B08 - B04) / (B08 + B04)
• Auth:      OAuth 2.0 client credentials (free 30-day trial)
             After login: User Settings → OAuth clients → New client

The Statistical API lets us request pre-computed NDVI stats (mean, min, max,
stdev) over a bounding box without downloading raw satellite images or needing
GDAL / rasterio — making it practical inside a pure-Python script.

HOW TO ACTIVATE
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
1. Register at https://www.sentinel-hub.com/
2. Go to User Settings → OAuth clients → Create new client
3. Copy the Client ID and Client Secret
4. Paste both into config.py:
       SENTINEL_HUB_CLIENT_ID     = "your-client-id"
       SENTINEL_HUB_CLIENT_SECRET = "your-client-secret"
5. Ensure LAYERS["satellite_neglect"] = True in config.py

When credentials are absent the layer returns a placeholder — no crash,
no data loss, all other layers keep running normally.
"""

import sys
import os
import math

# ── Allow imports from project root regardless of how the file is invoked ──
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

import requests
import config
from layers.base import BaseLayer


# ── Sentinel Hub endpoints ────────────────────────────────────────────────────
_TOKEN_URL = "https://services.sentinel-hub.com/oauth/token"
_STATS_URL = "https://services.sentinel-hub.com/api/v1/statistics"

# ── NDVI evalscript — sent to Sentinel Hub to compute the index on their side ─
# An evalscript is a short JavaScript snippet that tells the satellite's
# cloud-processing service which bands to load and how to combine them.
# We never download the raw satellite image — just the computed statistics.
_EVALSCRIPT = """
//VERSION=3
function setup() {
  return {
    input: [{ bands: ["B04", "B08"], units: "DN" }],
    output: [{ id: "ndvi", bands: 1, sampleType: "FLOAT32" }]
  };
}
function evaluatePixel(sample) {
  // NDVI: (Near-Infrared minus Red) / (Near-Infrared plus Red)
  // Near-Infrared = B08, Red = B04
  let ndvi = (sample.B08 - sample.B04) / (sample.B08 + sample.B04);
  return [ndvi];
}
"""

# ── Thresholds ────────────────────────────────────────────────────────────────
MILD_NEGLECT_DELTA   = 0.10   # vigor delta that raises a mild flag
STRONG_NEGLECT_DELTA = 0.20   # vigor delta that raises a strong flag

# Neighborhood expansion: how far outside the parcel bbox we look for the
# "neighbor" NDVI baseline. 0.01° ≈ 1 km at Tuscany's latitude.
NEIGHBORHOOD_EXPANSION_DEG = 0.01


def _get_token() -> str:
    """
    Request an OAuth 2.0 bearer token from Sentinel Hub.
    This is like showing your ID at the door — you trade your credentials
    for a temporary pass that lets you make API calls.
    """
    resp = requests.post(
        _TOKEN_URL,
        data={
            "grant_type":    "client_credentials",
            "client_id":     config.SENTINEL_HUB_CLIENT_ID,
            "client_secret": config.SENTINEL_HUB_CLIENT_SECRET,
        },
        timeout=15,
    )
    resp.raise_for_status()
    return resp.json()["access_token"]


def _stats_request(token: str, bbox: list, date_from: str, date_to: str) -> dict:
    """
    Call the Sentinel Hub Statistical API for the given bounding box and date range.
    Returns the raw JSON response dict.

    bbox format: [west_lon, south_lat, east_lon, north_lat]  (EPSG:4326)
    """
    payload = {
        "input": {
            "bounds": {
                "properties": {"crs": "http://www.opengis.net/def/crs/OGC/1.3/CRS84"},
                "bbox": bbox,
            },
            "data": [{
                "type": "sentinel-2-l2a",
                "dataFilter": {
                    "timeRange": {"from": f"{date_from}T00:00:00Z",
                                  "to":   f"{date_to}T23:59:59Z"},
                    "maxCloudCoverage": 20,   # skip cloudy images
                },
            }],
        },
        "aggregation": {
            "timeRange": {"from": f"{date_from}T00:00:00Z",
                          "to":   f"{date_to}T23:59:59Z"},
            "aggregationInterval": {"of": "P1D"},   # ISO 8601: 1-day buckets
            "evalscript": _EVALSCRIPT,
            "resx": 10,   # 10 m per pixel — Sentinel-2 native resolution
            "resy": 10,
        },
        "calculations": {
            "ndvi": {
                "histograms": {"default": {"nBins": 20, "lowEdge": -1.0, "highEdge": 1.0}},
                "statistics":  {"default": {"percentiles": {"k": [25, 50, 75]}}},
            }
        },
    }
    resp = requests.post(
        _STATS_URL,
        json=payload,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type":  "application/json",
        },
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()


def _mean_ndvi_from_response(data: dict) -> float:
    """
    Walk the Sentinel Hub Statistical API response tree and return the
    mean NDVI across all valid observation days.

    The response nests statistics inside data → intervals → outputs → bands.
    Days with no valid pixels (complete cloud cover) are skipped.
    """
    intervals = data.get("data", {}).get("intervals", [])
    means = []
    for interval in intervals:
        outputs = interval.get("outputs", {})
        ndvi_output = outputs.get("ndvi", {})
        bands = ndvi_output.get("bands", {})
        b0 = bands.get("B0", {})
        stats = b0.get("stats", {})
        mean = stats.get("mean")
        if mean is not None and not math.isnan(mean):
            means.append(mean)
    if not means:
        return None
    return sum(means) / len(means)


def _parcel_bbox(parcel: dict, expand: float = 0.0) -> list:
    """
    Build a bounding box from the parcel's centroid ± a small offset.
    A parcel in OSM is a polygon, but we have its centroid (lat/lon center point).
    We approximate the bbox by expanding outward from the centroid using
    the parcel's area to estimate the radius.

    expand (degrees): extra padding added on all four sides (for neighborhoods).
    Returns [west_lon, south_lat, east_lon, north_lat].
    """
    lat = parcel["lat"]
    lon = parcel["lon"]
    # Approximate parcel half-side in degrees.
    # 1° latitude ≈ 111 km; 1° longitude ≈ 111 km × cos(lat)
    area_sqm = parcel.get("parcel_sqm", 10_000)
    half_m   = math.sqrt(area_sqm) / 2
    half_lat = (half_m / 111_000)
    half_lon = (half_m / (111_000 * math.cos(math.radians(lat))))
    return [
        round(lon - half_lon - expand, 6),   # west
        round(lat - half_lat - expand, 6),   # south
        round(lon + half_lon + expand, 6),   # east
        round(lat + half_lat + expand, 6),   # north
    ]


class SatelliteNeglectLayer(BaseLayer):
    """
    Layer 1 — Satellite Neglect Index

    Compares the parcel's NDVI (vegetation health) against its immediate
    neighborhood. A meaningful negative gap (low parcel, healthy neighbors)
    is the first quantitative signal of neglect and potential absentee ownership.
    """
    name  = "satellite_neglect"
    label = "Satellite Neglect Index"
    paid  = False   # Sentinel Hub has a free 30-day trial; thereafter ~€25/month

    # Growing season dates — May through September captures peak vine canopy.
    # Adjust for other crop types if needed.
    DATE_FROM = "2024-05-01"
    DATE_TO   = "2024-09-30"

    def run(self, parcel: dict) -> dict:
        """
        1. Check credentials — return stub if missing.
        2. Authenticate with Sentinel Hub → get bearer token.
        3. Fetch NDVI stats for the parcel bbox.
        4. Fetch NDVI stats for an expanded neighborhood bbox.
        5. Calculate vigor_delta = neighborhood_mean - parcel_mean.
        6. Flag if delta > threshold.
        """
        # ── Credential check ─────────────────────────────────────────────────
        if not (config.SENTINEL_HUB_CLIENT_ID and config.SENTINEL_HUB_CLIENT_SECRET):
            return self._empty_result(
                detail="Sentinel Hub credentials not set — add SENTINEL_HUB_CLIENT_ID / SECRET to config.py"
            )

        # ── Check layer toggle ────────────────────────────────────────────────
        if not config.LAYERS.get("satellite_neglect", True):
            return self._empty_result(detail="Layer disabled in config.LAYERS")

        try:
            token = _get_token()
        except Exception as exc:
            return self._empty_result(detail=f"Auth failed: {exc.__class__.__name__} — {exc}")

        # ── Bounding boxes ────────────────────────────────────────────────────
        parcel_bbox = _parcel_bbox(parcel, expand=0.0)
        neighbor_bbox = _parcel_bbox(parcel, expand=NEIGHBORHOOD_EXPANSION_DEG)

        # ── Fetch parcel NDVI ─────────────────────────────────────────────────
        try:
            parcel_resp  = _stats_request(token, parcel_bbox,  self.DATE_FROM, self.DATE_TO)
            parcel_ndvi  = _mean_ndvi_from_response(parcel_resp)
        except Exception as exc:
            return self._empty_result(detail=f"Parcel NDVI fetch failed: {exc.__class__.__name__}")

        if parcel_ndvi is None:
            return self._empty_result(detail="No cloud-free observations for parcel in date range")

        # ── Fetch neighborhood NDVI ───────────────────────────────────────────
        try:
            neighbor_resp = _stats_request(token, neighbor_bbox, self.DATE_FROM, self.DATE_TO)
            neighbor_ndvi = _mean_ndvi_from_response(neighbor_resp)
        except Exception as exc:
            return self._empty_result(detail=f"Neighborhood NDVI fetch failed: {exc.__class__.__name__}")

        if neighbor_ndvi is None:
            return self._empty_result(detail="No cloud-free observations for neighborhood in date range")

        # ── Calculate vigor delta ─────────────────────────────────────────────
        # Positive delta = parcel is BELOW its neighborhood = neglect signal
        vigor_delta = neighbor_ndvi - parcel_ndvi

        # ── Classify signal strength ──────────────────────────────────────────
        if vigor_delta >= STRONG_NEGLECT_DELTA:
            signal  = True
            detail  = (f"Strong neglect signal — parcel NDVI {parcel_ndvi:.3f} vs "
                       f"neighborhood {neighbor_ndvi:.3f} (Δ = {vigor_delta:+.3f})")
            score   = self._clamp((vigor_delta - MILD_NEGLECT_DELTA) / 0.30)
        elif vigor_delta >= MILD_NEGLECT_DELTA:
            signal  = True
            detail  = (f"Mild neglect signal — parcel NDVI {parcel_ndvi:.3f} vs "
                       f"neighborhood {neighbor_ndvi:.3f} (Δ = {vigor_delta:+.3f})")
            score   = self._clamp(vigor_delta / STRONG_NEGLECT_DELTA * 0.5)
        else:
            signal  = False
            detail  = (f"Vegetation vigor normal — parcel NDVI {parcel_ndvi:.3f} vs "
                       f"neighborhood {neighbor_ndvi:.3f} (Δ = {vigor_delta:+.3f})")
            score   = 0.0

        return {
            "layer":  self.name,
            "label":  self.label,
            "signal": signal,
            "score":  round(score, 3),
            "detail": detail,
            "data": {
                "parcel_ndvi":       round(parcel_ndvi,  4),
                "neighborhood_ndvi": round(neighbor_ndvi, 4),
                "vigor_delta":       round(vigor_delta,   4),
                "date_range":        f"{self.DATE_FROM} → {self.DATE_TO}",
                "parcel_bbox":       parcel_bbox,
                "neighbor_bbox":     neighbor_bbox,
            },
            "paid": self.paid,
        }
