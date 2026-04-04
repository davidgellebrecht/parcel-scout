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
    "GRS": {"name": "Grosseto Baccarini",       "lat": 42.7597, "lon": 11.0719},
    # GRS covers the Maremma / southern Tuscany area (Morellino, Montecucco, Bolgheri).
    # Small regional airport; charter and light-aircraft traffic common for estate buyers.
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
    "distress_signal":   True,   # EFFIS fire history + OSM abandoned land
    "succession_signal": True,   # named estate (Podere/Tenuta/etc.) on or near parcel
    "lodging_overlay":   True,   # tourism/hospitality node within 750 m
}

# Premium wine zones where top bottles regularly trade at $150+.
# Hardcoded as static geographic facts — OSM carries no DOCG/DOC boundary data.
# Bbox format: (south_lat, west_lon, north_lat, east_lon)
# Bounds are tightened relative to the administrative commune boundaries to reduce
# false positives; they do not perfectly match official DOCG shapefiles (which
# require a paid GIS download from Italy's Mipaaf — a future improvement).
PREMIUM_DOCG_ZONES = {
    "Brunello di Montalcino":       (42.97, 11.35, 43.13, 11.62),  # Biondi Santi, Poggio di Sotto, Argiano, etc.
    "Vino Nobile di Montepulciano": (43.07, 11.75, 43.17, 11.95),  # Avignonesi, Poliziano, Valdipiatta
    "Chianti Classico":             (43.35, 11.10, 43.65, 11.68),  # Brolio, Badia a Coltibuono, Isole e Olena
    "Bolgheri (Super Tuscan)":      (43.17, 10.55, 43.31, 10.80),  # Sassicaia, Ornellaia, Masseto — DOC not DOCG
                                                                     # but consistently trades $150–$500+
    "Morellino di Scansano":        (42.60, 11.20, 42.80, 11.45),  # DOCG 2007; Maremma flagship red.
                                                                     # Top producers (Moris Farms, Rocca di Frassinello)
                                                                     # regularly at $40–80; cellar-door prices suppressed
                                                                     # relative to Montalcino — attractive value gap.
    "Montecucco Sangiovese":        (42.80, 11.25, 42.97, 11.52),  # DOCG 2011; directly north of Montalcino.
                                                                     # Same galestro/alberese soils, fraction of the price.
                                                                     # Collemassari, Salustri — land prices still 30–50%
                                                                     # below Brunello zone; fastest-appreciating area in Tuscany.
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
    # ── Group 1: Geo Layers ────────────────────────────────────────────────────
    "satellite_neglect":   False,  # needs SENTINEL_HUB_CLIENT_ID + SECRET
    "permit_paralysis":    True,   # OSM proxy active; upgrades to Albo Pretorio when key set
    "zoning_alchemy":      True,   # free Zone E (GEOscopio WFS) always runs
    "napa_neighbor":       True,   # free — hardcoded marquee acquisition ripple
    # ── Group 2: Brand / Sentiment Layers ─────────────────────────────────────
    "hospitality_fatigue": False,  # needs TRIPADVISOR_API_KEY
    "digital_ghost":       True,   # free — Wayback CDX + WHOIS domain check
    "succession_stress":   True,   # free — Wayback CDX + OpenCorporates Italian registry
    "terroir_score_delta": False,  # needs WINE_SEARCHER_API_KEY
    # ── Group 3: Legal Layers ─────────────────────────────────────────────────
    "succession_frag":     False,  # needs OPENAPI_IT_KEY
    "owner_relocation":    True,   # free fiscal code + website language always run;
                                   # cadastral contact address upgrades when OPENAPI_IT_KEY set
    # ── Group 4: New Geo + Brand Layers ───────────────────────────────────────
    "elevation_aspect":    True,   # free — OpenTopoData SRTM 90 m (elevation + slope aspect)
    "road_access":         True,   # free — OSM highway tags (access quality proxy)
    "water_access":        True,   # free — OSM waterway/natural/man_made (water source proximity)
    "listing_check":       True,   # free — Gate-Away.com listing check (on-market signal)
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
