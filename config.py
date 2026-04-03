# ─── Parcel Scout — Configuration ────────────────────────────────────────────
# Toggle each filter True (on) or False (off).
# All enabled filters are applied as AND conditions.

FILTERS = {
    "proximity_to_airport":   True,   # parcel centroid within AIRPORT_MAX_DRIVE_MINS drive
    "agricultural_land":      True,   # vineyard or olive orchard
    "min_square_footage":     True,   # total land parcel area (way/relation geometry) >= MIN_AREA_SQFT
    "historical_designation": True,   # historic building/site must be physically ON the parcel (point-in-polygon)
}

# ─── Region ───────────────────────────────────────────────────────────────────
REGION = "Chianti Classico (mini demo)"
# Bounding box: (south_lat, west_lon, north_lat, east_lon)
# MINI DEMO BBOX — ~9×10 km around Gaiole in Chianti, fastest possible query
# Revert to (43.35, 11.35, 43.50, 11.65) for full demo area
# Revert to (42.63, 10.90, 43.52, 11.93) for full Province of Siena
REGION_BBOX = (43.41, 11.42, 43.48, 11.55)

# ─── Thresholds ───────────────────────────────────────────────────────────────
AIRPORT_MAX_DRIVE_MINS   = 60      # minutes
AIRPORT_AVG_SPEED_KMH    = 70      # assumed average road speed (km/h)
MIN_AREA_SQFT            = 20_000  # square feet
# Target airports: parcel must be within AIRPORT_MAX_KM of at least one.
# Hardcoded to avoid an extra Overpass round-trip for two well-known fixed points.
TARGET_AIRPORTS = {
    "PSA": {"name": "Pisa Galileo Galilei",    "lat": 43.6839, "lon": 10.3927},
    "FLR": {"name": "Florence Peretola",        "lat": 43.8099, "lon": 11.2051},
    "SAY": {"name": "Siena Ampugnano",          "lat": 43.2260, "lon": 11.2570},
}

# ─── Derived constants (do not edit) ──────────────────────────────────────────
AIRPORT_MAX_KM = (AIRPORT_MAX_DRIVE_MINS / 60) * AIRPORT_AVG_SPEED_KMH  # ~70 km straight-line proxy
MIN_AREA_SQM   = MIN_AREA_SQFT * 0.092903                                # 1 sqft = 0.092903 m²
# Tuscany's hilly terrain means actual road distance is ~30% longer than haversine straight-line.
# Applied to the haversine result before comparing against AIRPORT_MAX_KM so the gate reflects
# real drive distance. The displayed dist_airport_km value stays as honest straight-line km.
ROAD_DISTANCE_FACTOR = 1.30

# ─── Group 2 — Opportunistic Signals (annotation only, no parcels excluded) ──
# Set any toggle to False to skip that signal's query and leave the column blank.
GROUP2 = {
    "premium_wine_zone": True,   # parcel falls within a Siena DOCG zone where wines sell at $150+
    "distress_signal":   False,  # TEMP disabled — EFFIS fire query times out; re-enable for full scan
    "succession_signal": False,  # TEMP DEMO OFF — skips extra Overpass query to keep demo fast
    "lodging_overlay":   False,  # TEMP DEMO OFF — skips extra Overpass query to keep demo fast
}

# Premium DOCG zones in Province of Siena where top bottles regularly trade at $150+.
# Hardcoded as static geographic facts — OSM carries no DOCG boundary data for this region.
# Bbox format: (south_lat, west_lon, north_lat, east_lon)
PREMIUM_DOCG_ZONES = {
    "Brunello di Montalcino":       (42.82, 11.35, 43.15, 11.70),  # Biondi Santi, Poggio di Sotto, etc.
    "Vino Nobile di Montepulciano": (43.07, 11.75, 43.17, 11.95),  # Avignonesi, Poliziano
    "Chianti Classico (Siena)":     (43.28, 11.27, 43.52, 11.68),  # Brolio, Badia a Coltibuono, etc.
}

DISTRESS_SEARCH_RADIUS_M   = 500   # metres — OSM abandoned element must be within this distance
FIRE_SEARCH_RADIUS_M       = 2000  # metres — EFFIS fire perimeter centroid within this distance
LODGING_SEARCH_RADIUS_M    = 750   # metres — tourism node must be within this distance
SUCCESSION_SEARCH_RADIUS_M = 300   # metres — estate-named OSM feature within this distance
FIRE_LOOKBACK_YEARS        = 10    # years of EFFIS fire history to include

# ─── External API credentials ─────────────────────────────────────────────────
# OpenAPI.it — free tier available at https://console.openapi.com (no credit card needed).
# Register, navigate to the Catasto section, and paste your OAuth Bearer token below.
# Example: OPENAPI_IT_KEY = "Bearer eyJ0eXAiOiJKV1QiLCJhbGci..."
OPENAPI_IT_KEY = ""

# ─── API ──────────────────────────────────────────────────────────────────────
# Three public Overpass mirrors — tried in order if the first is overloaded.
OVERPASS_FALLBACK_URLS = [
    "https://overpass-api.de/api/interpreter",        # primary (DE)
    "https://overpass.kumi.systems/api/interpreter",   # mirror (AT)
    "https://overpass.openstreetmap.ru/api/interpreter",  # mirror (RU)
]
OVERPASS_TIMEOUT = 60    # seconds per attempt; 3 attempts × 3 URLs before giving up

# ─── 9-Layer Acquisition Engine ───────────────────────────────────────────────
# Toggle each layer True (active) or False (skip).
# Layers marked PAID FEATURE require a commercial API subscription to return real data.
# When credentials are absent they return a safe placeholder — no crash, no data loss.
LAYERS = {
    # ── Group 1: Geo Layers — run via scout.py ─────────────────────────────────
    "satellite_neglect":   False,  # TEMP DEMO OFF — Sentinel Hub OAuth too slow without credentials
    "permit_paralysis":    False,  # PAID FEATURE — no key configured
    "zoning_alchemy":      False,  # PAID FEATURE — no key configured
    "napa_neighbor":       True,   # LVMH/Antinori proximity ripple — free, hardcoded math, instant
    # ── Group 2: Brand / Sentiment Layers — run via sentiment.py ──────────────
    "hospitality_fatigue": False,  # PAID FEATURE — no key configured
    "digital_ghost":       False,  # TEMP DEMO OFF — WHOIS + Wayback per parcel too slow for demo
    "terroir_score_delta": False,  # PAID FEATURE — no key configured
    # ── Group 3: Legal Layers — run via acquisitions.py ───────────────────────
    "succession_frag":     False,  # PAID FEATURE — no key configured
    "owner_relocation":    False,  # PAID FEATURE — no key configured
}

# ─── Layer credentials ────────────────────────────────────────────────────────
# Sentinel Hub — free 30-day trial at https://www.sentinel-hub.com/
# After login: User Settings → OAuth clients → New client → copy ID and secret.
SENTINEL_HUB_CLIENT_ID     = ""
SENTINEL_HUB_CLIENT_SECRET = ""

# TripAdvisor Content API — free tier (5,000 req/month) at https://www.tripadvisor.com/developers
TRIPADVISOR_API_KEY = ""

# Wine-Searcher API — https://www.wine-searcher.com/api (100 free searches/day)
WINE_SEARCHER_API_KEY = ""

# Albo Pretorio — no unified public API; set when a commercial aggregator is contracted
ALBO_PRETORIO_API_KEY = ""
