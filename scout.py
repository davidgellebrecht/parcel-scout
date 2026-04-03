#!/usr/bin/env python3
"""
Parcel Scout — off-market Italian estate finder.

Queries OpenStreetMap via the Overpass API and filters physical land parcels
in Tuscany based on the toggles defined in config.py.

Usage:
    python scout.py

Output:
    results_<timestamp>.csv  and  results_<timestamp>.json
"""

import csv
import json
import math
import sys
import time
from datetime import datetime, date

import requests

import config


# ─── Overpass API ─────────────────────────────────────────────────────────────

def _overpass(query: str, retries: int = 3, backoff: int = 15) -> dict:
    """POST an Overpass QL query and return the parsed JSON response.

    Tries each URL in config.OVERPASS_FALLBACK_URLS in turn. For each URL,
    retries up to `retries` times on timeouts or 5xx errors. If every URL
    is exhausted, returns an empty result set instead of crashing the app.
    """
    http_timeout = config.OVERPASS_TIMEOUT + 10  # extra buffer for HTTP overhead

    for url in config.OVERPASS_FALLBACK_URLS:
        for attempt in range(1, retries + 1):
            try:
                resp = requests.post(url, data={"data": query}, timeout=http_timeout)
                resp.raise_for_status()
                return resp.json()
            except requests.exceptions.Timeout:
                print(f"  WARNING: Overpass timed out at {url} (attempt {attempt}/{retries}).")
                if attempt < retries:
                    time.sleep(backoff)
            except requests.exceptions.HTTPError as exc:
                code = resp.status_code
                if code == 429:
                    wait = backoff * 2
                    print(f"  WARNING: Overpass rate-limited at {url} (attempt {attempt}/{retries}) — waiting {wait}s...")
                    if attempt < retries:
                        time.sleep(wait)
                elif code >= 500:
                    print(f"  WARNING: Overpass {code} at {url} (attempt {attempt}/{retries}) — retrying in {backoff}s...")
                    if attempt < retries:
                        time.sleep(backoff)
                else:
                    print(f"  WARNING: Overpass HTTP {code} at {url} — skipping to next mirror.")
                    break  # non-retriable error; try next URL immediately
            except requests.exceptions.RequestException as exc:
                print(f"  WARNING: Overpass request failed at {url} (attempt {attempt}/{retries}) — {exc}")
                if attempt < retries:
                    time.sleep(backoff)
        print(f"  WARNING: Exhausted all attempts at {url} — trying next mirror...")

    print("  ERROR: All Overpass mirrors failed. Returning empty result set — parcel data may be incomplete.")
    return {"elements": []}


def _bbox() -> str:
    s, w, n, e = config.REGION_BBOX
    return f"{s},{w},{n},{e}"


# ─── Geometry ─────────────────────────────────────────────────────────────────

def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in kilometres."""
    R = 6_371.0
    φ1, φ2 = math.radians(lat1), math.radians(lat2)
    dφ = math.radians(lat2 - lat1)
    dλ = math.radians(lon2 - lon1)
    a = math.sin(dφ / 2) ** 2 + math.cos(φ1) * math.cos(φ2) * math.sin(dλ / 2) ** 2
    return R * 2 * math.asin(math.sqrt(a))


def polygon_area_sqm(nodes: list) -> float:
    """
    Approximate area in square metres for a lat/lon polygon.
    Uses the spherical excess formula — accurate for parcel-sized areas.
    """
    if len(nodes) < 3:
        return 0.0
    R = 6_371_000.0
    n = len(nodes)
    total = 0.0
    for i in range(n):
        j = (i + 1) % n
        lat1 = math.radians(nodes[i]["lat"])
        lat2 = math.radians(nodes[j]["lat"])
        lon1 = math.radians(nodes[i]["lon"])
        lon2 = math.radians(nodes[j]["lon"])
        total += (lon2 - lon1) * (2 + math.sin(lat1) + math.sin(lat2))
    return abs(total) * R * R / 2


def centroid(nodes: list) -> tuple:
    """Return the mean (lat, lon) of a list of geometry nodes."""
    lats = [n["lat"] for n in nodes]
    lons = [n["lon"] for n in nodes]
    return sum(lats) / len(lats), sum(lons) / len(lons)


# ─── OSM Queries ──────────────────────────────────────────────────────────────

def fetch_airports() -> list:
    """
    Returns hardcoded coordinates for the target airports (PSA and FLR).
    No Overpass query needed — these are fixed, well-known points.
    """
    return [
        {"iata": code, "name": info["name"], "lat": info["lat"], "lon": info["lon"]}
        for code, info in config.TARGET_AIRPORTS.items()
    ]


def fetch_historic_sites() -> list:
    """
    Fetch any element carrying a historic or heritage tag — intentionally broad.
    Captures: ruins, chapels, barns, castles, monasteries, villas, monuments,
    designated heritage assets, and anything else tagged historic=* or heritage=*.
    Returns list of dicts: {lat, lon, name, tag_type}.
    """
    bb = _bbox()
    query = f"""
[out:json][timeout:{config.OVERPASS_TIMEOUT}];
(
  node["historic"]({bb});
  way["historic"]({bb});
  relation["historic"]({bb});
  node["heritage"]({bb});
  way["heritage"]({bb});
  node["building"~"castle|monastery|chapel|church|villa|barn|ruins|farmhouse|house|mill|granary|stable|tower"]({bb});
  way["building"~"castle|monastery|chapel|church|villa|barn|ruins|farmhouse|house|mill|granary|stable|tower"]({bb});
  node["building"="historic"]({bb});
  way["building"="historic"]({bb});
  node["ruins"="yes"]({bb});
  way["ruins"="yes"]({bb});
);
out center tags;
"""
    print("  Querying historic sites...")
    data = _overpass(query)
    sites = []
    for el in data.get("elements", []):
        lat = el.get("lat") or el.get("center", {}).get("lat")
        lon = el.get("lon") or el.get("center", {}).get("lon")
        if lat and lon:
            tags         = el.get("tags", {})
            historic_val = tags.get("historic", "")
            heritage_val = tags.get("heritage", "")
            building_val = tags.get("building", "")
            # Resolve tag_type: if historic=yes but a building=* tag is present,
            # use the building value — it's more specific ("chapel", "barn", etc.)
            if historic_val and historic_val != "yes":
                tag_type = historic_val
            elif historic_val == "yes" and building_val:
                tag_type = building_val   # promote generic "yes" to real structure type
            elif heritage_val:
                tag_type = heritage_val
            elif building_val:
                tag_type = building_val
            elif tags.get("ruins") == "yes":
                tag_type = "ruins"
            else:
                tag_type = "yes"          # genuinely unclassified; confidence = low
            sites.append({
                "lat":        lat,
                "lon":        lon,
                "name":       tags.get("name", ""),
                "tag_type":   tag_type,
                "confidence": _heritage_confidence(tag_type),
            })
    return sites


def fetch_agricultural_parcels() -> list:
    """
    Fetch vineyard and olive-orchard areas from OSM.
    Returns raw OSM elements (ways and relations) with geometry.
    """
    bb = _bbox()
    query = f"""
[out:json][timeout:{config.OVERPASS_TIMEOUT}];
(
  way["landuse"="vineyard"]({bb});
  way["landuse"="orchard"]["trees"="olive_trees"]({bb});
  way["landuse"="orchard"]["crop"="olive"]({bb});
  way["landuse"="orchard"]["produce"~"olive",i]({bb});
  way["landuse"="orchard"]({bb});
  way["landuse"="farmland"]["crop"~"grape|grapes|vite|vines",i]({bb});
  way["landuse"="farmland"]["produce"~"wine|grape|olive",i]({bb});
  way["landuse"="farmland"]["trees"~"olive",i]({bb});
  way["landuse"="grass"]({bb});
  way["landuse"="meadow"]({bb});
  relation["landuse"="vineyard"]({bb});
  relation["landuse"="orchard"]({bb});
  relation["landuse"="farmland"]({bb});
);
out body geom;
"""
    print("  Querying agricultural land (vineyards, olive orchards, farmland, grass, meadow)...")
    data = _overpass(query)
    return data.get("elements", [])


def fetch_broad_landuse() -> list:
    """
    Fallback query when agricultural_land filter is OFF.
    Fetches any sizeable landuse area so the other filters still apply.
    """
    bb = _bbox()
    query = f"""
[out:json][timeout:{config.OVERPASS_TIMEOUT}];
(
  way["landuse"~"farmland|vineyard|orchard|meadow|grass"]({bb});
  relation["landuse"~"farmland|vineyard|orchard"]({bb});
);
out body geom;
"""
    print("  Querying broad landuse areas (agricultural filter is OFF)...")
    data = _overpass(query)
    return data.get("elements", [])


# ─── Group 2 Queries ──────────────────────────────────────────────────────────

def _geojson_centroid(geometry: dict):
    """Return (lat, lon) centroid of a GeoJSON Point, Polygon, or MultiPolygon."""
    gtype  = geometry.get("type", "")
    coords = geometry.get("coordinates", [])
    if gtype == "Point":
        return coords[1], coords[0]
    if gtype == "Polygon" and coords:
        ring = coords[0]
        return sum(c[1] for c in ring) / len(ring), sum(c[0] for c in ring) / len(ring)
    if gtype == "MultiPolygon" and coords:
        ring = coords[0][0]
        return sum(c[1] for c in ring) / len(ring), sum(c[0] for c in ring) / len(ring)
    return None, None


def fetch_distress_elements() -> list:
    """
    Returns distress elements from two sources, merged into a single list of
    {lat, lon, signal, source} dicts:

    1. EU EFFIS / GWIS — historical fire perimeters (publicly accessible WFS, no auth).
       Endpoint: https://maps.effis.emergency.copernicus.eu/gwis/wfs
       Layer: ms:modis_burned_area_full_dataset  (MODIS 250m, detects fires ≥ ~40 ha)
       Lookback: config.FIRE_LOOKBACK_YEARS years, proximity: FIRE_SEARCH_RADIUS_M

    2. OSM — abandoned or disused land parcels (Overpass API).
       Proximity: DISTRESS_SEARCH_RADIUS_M

    NOTE — financial distress integration:
      InfoCamere TELEMACO API: https://www.infocamere.it/prodotti/telemaco
      Requires a commercial agreement. Once in place, query:
        POST https://webtelemaco.infocamere.it/wt2/TelemacoPricesIT/service
      Returns: insolvency filings, company status, UBO registry.
    """
    elements = []
    cutoff_year = date.today().year - config.FIRE_LOOKBACK_YEARS

    # ── 1. EFFIS fire history ─────────────────────────────────────────────────
    print("  [G2] Querying EFFIS fire history...")
    s, w, n, e = config.REGION_BBOX
    try:
        resp = requests.get(
            "https://maps.effis.emergency.copernicus.eu/gwis/wfs",
            params={
                "service":      "WFS",
                "version":      "2.0.0",
                "request":      "GetFeature",
                "typeName":     "ms:modis_burned_area_full_dataset",
                "bbox":         f"{w},{s},{e},{n},EPSG:4326",
                "outputFormat": "application/json",
                "count":        500,
            },
            timeout=30,
            headers={"User-Agent": "ParcelScout/1.0"},
        )
        if resp.status_code == 200:
            features = resp.json().get("features", [])
            for feat in features:
                props = feat.get("properties", {})
                # EFFIS date field may be ig_date, firedate, or acq_date
                raw_date = (props.get("ig_date") or props.get("firedate")
                            or props.get("acq_date") or "")
                fire_year = int(str(raw_date)[:4]) if raw_date and str(raw_date)[:4].isdigit() else 0
                if fire_year < cutoff_year:
                    continue
                area_ha = props.get("area_ha") or props.get("burned_area") or 0
                lat, lon = _geojson_centroid(feat.get("geometry", {}))
                if lat and lon:
                    elements.append({
                        "lat":    lat,
                        "lon":    lon,
                        "signal": f"fire {fire_year} ({float(area_ha):.0f} ha)",
                        "source": "fire",
                    })
            print(f"         EFFIS: {len([e for e in elements if e['source']=='fire'])} fire event(s) since {cutoff_year}")
        else:
            print(f"  [G2] EFFIS returned {resp.status_code} — skipping fire data")
    except Exception as exc:
        print(f"  [G2] EFFIS unavailable ({exc.__class__.__name__}) — skipping fire data")

    # ── 2. OSM abandoned / disused land ──────────────────────────────────────
    bb = _bbox()
    query = f"""
[out:json][timeout:{config.OVERPASS_TIMEOUT}];
(
  way["abandoned"="yes"]["landuse"]({bb});
  way["abandoned:landuse"]({bb});
  node["abandoned:landuse"]({bb});
  way["disused:landuse"]({bb});
  way["landuse"]["overgrown"="yes"]({bb});
);
out center tags;
"""
    print("  [G2] Querying OSM abandoned/disused land...")
    data = _overpass(query)
    for el in data.get("elements", []):
        lat = el.get("lat") or el.get("center", {}).get("lat")
        lon = el.get("lon") or el.get("center", {}).get("lon")
        if lat and lon:
            tags   = el.get("tags", {})
            signal = (
                tags.get("abandoned:landuse")
                or tags.get("disused:landuse")
                or ("abandoned " + tags.get("landuse", "")).strip()
            )
            elements.append({"lat": lat, "lon": lon, "signal": signal, "source": "abandoned"})

    return elements


def fetch_named_estates() -> list:
    """
    Query OSM for named places carrying Italian family estate prefixes
    (Podere, Fattoria, Tenuta, Castello, Villa, Cascina, Masseria, Casale).
    Proximity to one of these suggests family ownership and potential succession.
    Returns list of {lat, lon, name}.

    NOTE — for confirmed ownership generation data, integrate the Visura Catastale
    (Agenzia delle Entrate) when the owner layer is built out.
    """
    bb = _bbox()
    prefixes = "Podere|Fattoria|Tenuta|Castello|Villa|Cascina|Masseria|Casale|Azienda|Pieve|Rocca|Borgo|Monte|Colle"
    query = f"""
[out:json][timeout:{config.OVERPASS_TIMEOUT}];
(
  node["name"~"{prefixes}",i]({bb});
  way["name"~"{prefixes}",i]({bb});
  relation["name"~"{prefixes}",i]({bb});
);
out center tags;
"""
    print("  [G2] Querying named estates (Podere/Fattoria/Tenuta patterns)...")
    data = _overpass(query)
    estates = []
    for el in data.get("elements", []):
        lat = el.get("lat") or el.get("center", {}).get("lat")
        lon = el.get("lon") or el.get("center", {}).get("lon")
        if lat and lon:
            estates.append({"lat": lat, "lon": lon, "name": el.get("tags", {}).get("name", "")})
    return estates


def fetch_tourism_nodes() -> list:
    """
    Query OSM for tourism/accommodation nodes (hotels, guest houses, B&Bs, etc.).
    Proximity to an existing tourism operation suggests the local Comune is
    permissive toward lodging and 'change of use' under Italian Law 96/2006
    (Legge sull'agriturismo — any azienda agricola with >50% agricultural
    revenue may apply for agriturismo status).

    NOTE — for definitive zoning confirmation, query the Comune's PRG (Piano
    Regolatore Generale) or SIT (Sistema Informativo Territoriale) API directly.
    """
    s, w, n, e = config.REGION_BBOX
    bb = f"{s - 0.03},{w - 0.03},{n + 0.03},{e + 0.03}"
    query = f"""
[out:json][timeout:{config.OVERPASS_TIMEOUT}];
(
  node["tourism"~"hotel|guest_house|hostel|chalet|apartment|bed_and_breakfast|camp_site",i]({bb});
  way["tourism"~"hotel|guest_house|chalet|apartment",i]({bb});
  node["amenity"~"hotel|hostel",i]({bb});
);
out center tags;
"""
    print("  [G2] Querying tourism/lodging nodes...")
    data = _overpass(query)
    nodes = []
    for el in data.get("elements", []):
        lat = el.get("lat") or el.get("center", {}).get("lat")
        lon = el.get("lon") or el.get("center", {}).get("lon")
        if lat and lon:
            tags = el.get("tags", {})
            nodes.append({
                "lat":  lat,
                "lon":  lon,
                "name": tags.get("name", ""),
                "type": tags.get("tourism") or tags.get("amenity", ""),
            })
    return nodes


# ─── Geometry extraction ──────────────────────────────────────────────────────

def extract_nodes(element: dict) -> list:
    """
    Pull geometry nodes from a way, or the outer ring of a relation.
    Returns a list of {lat, lon} dicts, or [] if geometry is unavailable.
    """
    if element["type"] == "way":
        return element.get("geometry", [])
    elif element["type"] == "relation":
        for member in element.get("members", []):
            if member.get("role") == "outer" and "geometry" in member:
                return member["geometry"]
    return []


def classify_ag_type(tags: dict) -> str:
    landuse = tags.get("landuse", "")
    trees   = tags.get("trees", "").lower()
    crop    = tags.get("crop", "").lower()
    produce = tags.get("produce", "").lower()
    if landuse == "vineyard":
        return "vineyard"
    if "olive" in trees or "olive" in crop or "olive" in produce:
        return "olive orchard"
    if landuse == "orchard":
        return "orchard"
    if landuse == "farmland":
        if any(k in crop for k in ("grape", "grapes", "vite", "vine")):
            return "vineyard (farmland)"
        if any(k in produce for k in ("wine", "grape")):
            return "vineyard (farmland)"
        if "olive" in trees:
            return "olive orchard (farmland)"
        return "farmland"
    if landuse in ("grass", "meadow"):
        return landuse
    return landuse or "unknown"


_WINE_OLIVE_CROPS   = {"grape", "grapes", "vite", "vines", "olive"}
_WINE_OLIVE_PRODUCE = {"wine", "grape", "grapes", "olive", "olives"}
_WINE_OLIVE_TREES   = {"olive_trees", "olive"}


def _qualifies_as_agricultural(tags: dict) -> bool:
    """
    Gate for the agricultural_land filter when new landuse types are in the result set.
    Vineyard and orchard always pass. Farmland passes only if it has a wine/olive crop,
    produce, or trees subtag. Grass and meadow pass unconditionally (size is the gate).
    """
    landuse = tags.get("landuse", "")
    if landuse in ("vineyard", "orchard"):
        return True
    if landuse == "farmland":
        return (any(k in tags.get("crop", "").lower()    for k in _WINE_OLIVE_CROPS)   or
                any(k in tags.get("produce", "").lower() for k in _WINE_OLIVE_PRODUCE) or
                any(k in tags.get("trees", "").lower()   for k in _WINE_OLIVE_TREES))
    if landuse in ("grass", "meadow"):
        return True
    return False


# ─── Filtering ────────────────────────────────────────────────────────────────

def nearest_airport_km(lat: float, lon: float, airports: list) -> float:
    if not airports:
        return float("inf")
    return min(haversine_km(lat, lon, a["lat"], a["lon"]) for a in airports)


def point_in_polygon(lat: float, lon: float, nodes: list) -> bool:
    """
    Ray casting algorithm — returns True if (lat, lon) falls inside the polygon
    defined by the OSM geometry node list.
    """
    n = len(nodes)
    inside = False
    j = n - 1
    for i in range(n):
        xi, yi = nodes[i]["lon"], nodes[i]["lat"]
        xj, yj = nodes[j]["lon"], nodes[j]["lat"]
        if ((yi > lat) != (yj > lat)) and (lon < (xj - xi) * (lat - yi) / (yj - yi) + xi):
            inside = not inside
        j = i
    return inside


# ── Heritage confidence ───────────────────────────────────────────────────────
# Specific structure types we can be confident are renovatable four-walled buildings.
HIGH_CONFIDENCE_TAGS = {
    "castle", "monastery", "chapel", "church", "villa", "barn",
    "farmhouse", "manor", "tower", "fort", "cathedral", "abbey",
    "palace", "fortification", "city_gate", "crypt", "convent",
    # Common Tuscan rural structure types added from MiC heritage taxonomy:
    "house", "fortified_house", "mill", "granary", "stable", "dovecote",
    "watermill", "windmill", "oratory", "loggia",
}
# Structures that clearly exist but may be ruinous or indeterminate in scale.
MEDIUM_CONFIDENCE_TAGS = {"ruins", "building", "tower", "historic"}


def _heritage_confidence(tag_type: str) -> str:
    """Classify how certain we are that the tag represents a renovatable structure."""
    if tag_type in HIGH_CONFIDENCE_TAGS:
        return "high"
    if tag_type in MEDIUM_CONFIDENCE_TAGS:
        return "medium"
    return "low"   # generic "yes" or unrecognised type


# OSM historic tag values that represent markers or monuments, not structures.
# Parcels whose only on-parcel historic feature matches one of these are excluded —
# a war memorial or roadside cross cannot be renovated into a habitable estate.
NON_RENOVATABLE_TAGS = {
    "memorial",            # war memorials, plaques, statues
    "wayside_cross",       # roadside cross
    "wayside_shrine",      # small roadside shrine
    "boundary_stone",      # property or parish boundary marker
    "milestone",           # distance marker
    "archaeological_site", # may have no standing structure above ground
}


def historic_on_parcel(nodes: list, sites: list):
    """
    Returns the highest-confidence renovatable historic site whose centroid falls
    inside the parcel polygon, or None if no qualifying site is found.
    Non-structural tag types (memorials, crosses, markers) are skipped.
    When multiple structures land on the same parcel, the most specific type wins
    (castle > church > barn > … > generic "yes").
    """
    matches = []
    for site in sites:
        if site["tag_type"] in NON_RENOVATABLE_TAGS:
            continue
        if point_in_polygon(site["lat"], site["lon"], nodes):
            matches.append(site)
    if not matches:
        return None
    order = {"high": 0, "medium": 1, "low": 2}
    best = min(matches, key=lambda s: order[s["confidence"]])
    return {"tag_type": best["tag_type"], "name": best["name"], "confidence": best["confidence"]}


def nearest_historic_info(lat: float, lon: float, sites: list) -> dict:
    """Return distance, tag type, and name of the closest historic element."""
    if not sites:
        return {"dist_m": float("inf"), "tag_type": "", "name": ""}
    best = min(sites, key=lambda h: haversine_km(lat, lon, h["lat"], h["lon"]))
    return {
        "dist_m":   haversine_km(lat, lon, best["lat"], best["lon"]) * 1_000,
        "tag_type": best["tag_type"],
        "name":     best["name"],
    }


def nearest_airport_info(lat: float, lon: float, airports: list) -> dict:
    if not airports:
        return {"name": "N/A", "iata": "", "dist_km": float("inf")}
    best = min(airports, key=lambda a: haversine_km(lat, lon, a["lat"], a["lon"]))
    return {
        "name":    best["name"],
        "iata":    best["iata"],
        "dist_km": haversine_km(lat, lon, best["lat"], best["lon"]),
    }


# ─── Group 2 Signal Checks ────────────────────────────────────────────────────

def check_premium_wine_zone(lat: float, lon: float) -> tuple:
    """Returns (True, zone_name) if the point falls within a hardcoded DOCG zone."""
    for zone_name, (s, w, n, e) in config.PREMIUM_DOCG_ZONES.items():
        if s <= lat <= n and w <= lon <= e:
            return True, zone_name
    return False, ""


def check_distress_signal(lat: float, lon: float, elements: list) -> tuple:
    """
    Returns (True, signal) if any distress element is within its source-specific radius.
    Fire events use FIRE_SEARCH_RADIUS_M; abandoned-land elements use DISTRESS_SEARCH_RADIUS_M.
    """
    for el in elements:
        radius_km = (config.FIRE_SEARCH_RADIUS_M if el.get("source") == "fire"
                     else config.DISTRESS_SEARCH_RADIUS_M) / 1_000
        if haversine_km(lat, lon, el["lat"], el["lon"]) <= radius_km:
            return True, el["signal"]
    return False, ""


def check_succession_signal(lat: float, lon: float, parcel_tags: dict, estate_features: list) -> tuple:
    """
    Returns (True, detail) if:
    - The parcel's own name/operator tags carry an Italian estate prefix, OR
    - A named estate is within SUCCESSION_SEARCH_RADIUS_M.
    """
    PREFIXES = ("podere", "fattoria", "tenuta", "castello", "villa",
                "cascina", "masseria", "casale", "azienda",
                "pieve", "rocca", "borgo", "monte", "colle")
    for field in ("name", "operator", "owner", "brand"):
        val = parcel_tags.get(field, "").lower().strip()
        if val and any(val.startswith(p) or f" {p}" in val for p in PREFIXES):
            return True, f"{field}: {parcel_tags[field]}"

    radius_km = config.SUCCESSION_SEARCH_RADIUS_M / 1_000
    for estate in estate_features:
        if haversine_km(lat, lon, estate["lat"], estate["lon"]) <= radius_km:
            return True, f"nearby: {estate['name']}"
    return False, ""


def check_lodging_overlay(lat: float, lon: float, tourism_nodes: list) -> tuple:
    """
    Returns (True, detail) if a tourism/accommodation node is within LODGING_SEARCH_RADIUS_M.
    Proximity to existing lodging indicates local planning precedent for 'change of use'.
    Under Italian Law 96/2006 all qualifying aziende agricole are eligible to apply.
    """
    radius_km = config.LODGING_SEARCH_RADIUS_M / 1_000
    for node in tourism_nodes:
        if haversine_km(lat, lon, node["lat"], node["lon"]) <= radius_km:
            label = node["name"] or node["type"]
            return True, f"{label} ({round(haversine_km(lat, lon, node['lat'], node['lon']) * 1000)} m)"
    return False, ""


def annotate_group2(parcels: list, distress_elements: list,
                    estate_features: list, tourism_nodes: list) -> list:
    """
    Annotate each Group 1 parcel with Group 2 opportunistic signals.
    Does NOT exclude parcels — adds boolean columns and a composite score.
    """
    g2 = config.GROUP2
    for p in parcels:
        lat, lon = p["lat"], p["lon"]

        in_zone, zone_name = (check_premium_wine_zone(lat, lon)
                              if g2["premium_wine_zone"] else (False, ""))

        is_distress, distress_type = (check_distress_signal(lat, lon, distress_elements)
                                      if g2["distress_signal"] else (False, ""))

        is_succession, succ_detail = (check_succession_signal(
                                          lat, lon,
                                          {"name": p.get("name", "")},
                                          estate_features)
                                      if g2["succession_signal"] else (False, ""))

        is_lodging, lodge_detail = (check_lodging_overlay(lat, lon, tourism_nodes)
                                    if g2["lodging_overlay"] else (False, ""))

        met = sum([in_zone, is_distress, is_succession, is_lodging])

        p["g2_premium_wine_zone"]  = in_zone
        p["g2_wine_zone_name"]     = zone_name
        p["g2_distress_signal"]    = is_distress
        p["g2_distress_type"]      = distress_type
        p["g2_succession_signal"]  = is_succession
        p["g2_succession_detail"]  = succ_detail
        p["g2_lodging_overlay"]    = is_lodging
        p["g2_lodging_detail"]     = lodge_detail
        p["secondary_score"]       = f"{met}/4"   # always out of 4 so scores are comparable across configs
        p["secondary_met"]         = met
        p["secondary_total"]       = 4

    return parcels


_OWNER_PLACEHOLDER = {
    "owner_name":   "N/A — add OPENAPI_IT_KEY to config.py",
    "fiscal_code":  "",
    "parcel_code":  "",
    "municipality": "",
    "encumbrances": "",
}


def fetch_owner_data(lat: float, lon: float) -> dict:
    """
    Live Visura Catastale lookup via OpenAPI.it (Agenzia delle Entrate).
    Returns owner, cadastral codes, and encumbrances for the parcel at (lat, lon).

    Requires config.OPENAPI_IT_KEY — free tier at https://console.openapi.com.
    When the key is empty, returns a placeholder immediately.

    Three-step flow:
      1. Nominatim reverse-geocode lat/lon → comune name + road (OSM, no auth)
      2. OpenAPI.it /indirizzo → id_indirizzo for that address
      3. OpenAPI.it /richiesta/elenco_immobili → property list with owner details

    Rural parcels often have no street address; steps 2–3 are skipped gracefully
    in that case. The Visura Catastale is most useful as a manual follow-up on
    shortlisted parcels rather than a bulk automated call.
    """
    if not config.OPENAPI_IT_KEY:
        return _OWNER_PLACEHOLDER

    headers = {
        "Authorization": config.OPENAPI_IT_KEY,
        "User-Agent":    "ParcelScout/1.0",
    }

    try:
        # ── Step 1: Reverse geocode via Nominatim ─────────────────────────────
        nom = requests.get(
            "https://nominatim.openstreetmap.org/reverse",
            params={"lat": lat, "lon": lon, "format": "json"},
            headers={"User-Agent": "ParcelScout/1.0"},
            timeout=10,
        )
        if nom.status_code != 200:
            return _OWNER_PLACEHOLDER
        addr = nom.json().get("address", {})
        road    = addr.get("road") or addr.get("hamlet") or addr.get("locality", "")
        comune  = (addr.get("village") or addr.get("town")
                   or addr.get("city") or addr.get("municipality", ""))
        if not comune:
            return _OWNER_PLACEHOLDER   # too rural to resolve an address

        # ── Step 2: Normalise address → id_indirizzo ──────────────────────────
        ind = requests.get(
            "https://catasto.openapi.it/indirizzo",
            params={"strada": road, "comune": comune, "provincia": "SI"},
            headers=headers,
            timeout=10,
        )
        if ind.status_code != 200 or not ind.json():
            return _OWNER_PLACEHOLDER
        id_indirizzo = ind.json()[0].get("id_indirizzo")
        if not id_indirizzo:
            return _OWNER_PLACEHOLDER

        # ── Step 3: Property list → owner details ─────────────────────────────
        props = requests.post(
            "https://catasto.openapi.it/richiesta/elenco_immobili",
            json={"id_indirizzo": id_indirizzo},
            headers=headers,
            timeout=15,
        )
        if props.status_code != 200:
            return _OWNER_PLACEHOLDER
        immobili = props.json().get("immobili", [])
        if not immobili:
            return _OWNER_PLACEHOLDER

        p0          = immobili[0]
        proprietari = p0.get("proprietari", [{}])
        owner       = proprietari[0] if proprietari else {}
        return {
            "owner_name":   owner.get("nome_cognome") or owner.get("denominazione", ""),
            "fiscal_code":  owner.get("codice_fiscale", ""),
            "parcel_code":  f"{p0.get('foglio','')}/{p0.get('particella','')}",
            "municipality": comune,
            "encumbrances": p0.get("rendita_catastale", ""),
        }

    except Exception as exc:
        print(f"  [owner] lookup failed ({exc.__class__.__name__}) — using placeholder")
        return _OWNER_PLACEHOLDER


def filter_parcels(raw_elements: list, airports: list, historic_sites: list) -> list:
    """
    Apply all enabled filters to raw OSM elements.

    Area check: computed from the land parcel's own way/relation geometry
    (polygon_area_sqm over its node ring), not from any building footprint.
    """
    filters = config.FILTERS
    results = []
    skipped = {"no_geometry": 0, "area": 0, "non_agricultural": 0, "airport": 0, "historic": 0}

    for el in raw_elements:
        tags  = el.get("tags", {})
        nodes = extract_nodes(el)

        if not nodes:
            skipped["no_geometry"] += 1
            continue

        lat, lon  = centroid(nodes)

        # Area is measured from the land parcel geometry (way or relation outer ring)
        area_sqm  = polygon_area_sqm(nodes)
        area_sqft = area_sqm / 0.092903

        # Filter: min_square_footage — total parcel land area, not building footprint
        if filters["min_square_footage"]:
            if area_sqm < config.MIN_AREA_SQM:
                skipped["area"] += 1
                continue

        # Filter: agricultural_land — secondary gate for farmland/grass/meadow elements
        # that were fetched by the expanded query but lack qualifying crop/produce subtags.
        if filters["agricultural_land"]:
            if not _qualifies_as_agricultural(tags):
                skipped["non_agricultural"] += 1
                continue

        # Filter: proximity_to_airport
        # dist_ap_km is haversine (straight-line). Multiply by ROAD_DISTANCE_FACTOR
        # (~1.30) to correct for Tuscany's hilly terrain before applying the gate.
        # The raw haversine value is stored in the output so displayed km stays honest.
        airport    = nearest_airport_info(lat, lon, airports)
        dist_ap_km = airport["dist_km"]
        if filters["proximity_to_airport"]:
            if dist_ap_km * config.ROAD_DISTANCE_FACTOR > config.AIRPORT_MAX_KM:
                skipped["airport"] += 1
                continue

        # Filter: historical_designation — historic site must be physically inside the parcel polygon
        on_parcel_historic = historic_on_parcel(nodes, historic_sites)
        is_heritage = on_parcel_historic is not None
        if filters["historical_designation"]:
            if not is_heritage:
                skipped["historic"] += 1
                continue

        owner = fetch_owner_data(lat, lon)

        results.append({
            # ── Identity ──────────────────────────────────────────────────────
            "osm_type":             el["type"],
            "osm_id":               el["id"],
            "name":                 tags.get("name", ""),
            "osm_url":              f"https://www.openstreetmap.org/{el['type']}/{el['id']}",
            # ── GPS Coordinates ───────────────────────────────────────────────
            "gps_coordinates":      f"{round(lat, 6)},{round(lon, 6)}",
            "lat":                  round(lat, 6),
            "lon":                  round(lon, 6),
            # ── Polygon geometry (for map rendering) ──────────────────────────
            # Stored as [[lat, lon], ...] — Folium-ready coordinate pairs.
            # The nodes list is discarded after filter_parcels(); saving it here
            # allows build_map() to draw the real field boundary instead of a circle.
            "polygon_coords":       [[n["lat"], n["lon"]] for n in nodes],
            # ── Agriculture ───────────────────────────────────────────────────
            "primary_crop_type":    classify_ag_type(tags),
            # ── Area (total land parcel) ──────────────────────────────────────
            "parcel_sqft":          round(area_sqft),
            "parcel_sqm":           round(area_sqm),
            "parcel_acres":         round(area_sqm / 4_046.86, 2),
            # ── Heritage ──────────────────────────────────────────────────────
            "heritage_asset":        is_heritage,
            "closest_historic_tag":  on_parcel_historic["tag_type"] if is_heritage else "",
            "closest_historic_name": on_parcel_historic["name"] if is_heritage else "",
            "heritage_confidence":   on_parcel_historic["confidence"] if is_heritage else "",
            "dist_historic_m":       "on-parcel" if is_heritage else "N/A",
            # ── Airport ───────────────────────────────────────────────────────
            "nearest_airport":      airport["name"],
            "airport_iata":         airport["iata"],
            "dist_airport_km":      round(dist_ap_km, 1),
            "est_drive_mins":       round((dist_ap_km * config.ROAD_DISTANCE_FACTOR / config.AIRPORT_AVG_SPEED_KMH) * 60),
            # ── Ownership (Visura Catastale — integration pending) ────────────
            "owner_name":           owner["owner_name"],
            "fiscal_code":          owner["fiscal_code"],
            "parcel_code":          owner["parcel_code"],
            "municipality":         owner["municipality"],
            "encumbrances":         owner["encumbrances"],
        })

    return results, skipped


# ─── Output ───────────────────────────────────────────────────────────────────

def export_csv(parcels: list, path: str):
    if not parcels:
        return
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=parcels[0].keys())
        writer.writeheader()
        writer.writerows(parcels)


def export_json(parcels: list, path: str):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(parcels, f, indent=2, ensure_ascii=False)


# ─── Main ─────────────────────────────────────────────────────────────────────

def print_banner(filters: dict):
    print(f"\n{'═' * 62}")
    print(f"  Parcel Scout  ·  {config.REGION}")
    print(f"  {datetime.now().strftime('%Y-%m-%d  %H:%M:%S')}")
    print(f"{'═' * 62}")
    print("  Filters:")
    labels = {
        "proximity_to_airport":   f"{'/'.join(config.TARGET_AIRPORTS.keys())} within {config.AIRPORT_MAX_DRIVE_MINS} min drive (~{config.AIRPORT_MAX_KM:.0f} km)",
        "agricultural_land":       "Vineyard or olive orchard",
        "min_square_footage":      f"Min {config.MIN_AREA_SQFT:,} sqft  ({config.MIN_AREA_SQM:,.0f} m²)",
        "historical_designation":  "Historic building physically on parcel (point-in-polygon)",
    }
    for k, v in filters.items():
        state = "✓ ON " if v else "✗ OFF"
        print(f"    [{state}]  {labels[k]}")

    print("  Group 2 signals (annotation only):")
    g2_labels = {
        "premium_wine_zone": f"DOCG wine zone ($150+ bottles): {', '.join(config.PREMIUM_DOCG_ZONES)}",
        "distress_signal":   f"EFFIS fire ({config.FIRE_LOOKBACK_YEARS}yr, {config.FIRE_SEARCH_RADIUS_M}m) + OSM abandoned ({config.DISTRESS_SEARCH_RADIUS_M}m)",
        "succession_signal": f"Italian estate naming within {config.SUCCESSION_SEARCH_RADIUS_M} m",
        "lodging_overlay":   f"Tourism/lodging node within {config.LODGING_SEARCH_RADIUS_M} m (L.96/2006)",
    }
    for k, v in config.GROUP2.items():
        state = "✓ ON " if v else "✗ OFF"
        print(f"    [{state}]  {g2_labels[k]}")
    print()


def main():
    print_banner(config.FILTERS)

    # ── Airports ──────────────────────────────────────────────────────────────
    airports = []
    if config.FILTERS["proximity_to_airport"]:
        airports = fetch_airports()
        names = ", ".join(f"{a['name']} ({a['iata']})" for a in airports if a["iata"])
        print(f"         Found {len(airports)} airport(s): {names or 'see results'}\n")
    else:
        print("         Airport filter OFF — skipping airport query\n")

    # ── Historic sites ────────────────────────────────────────────────────────
    historic_sites = []
    if config.FILTERS["historical_designation"]:
        historic_sites = fetch_historic_sites()
        print(f"         Found {len(historic_sites):,} historic site(s)\n")
    else:
        print("         Historic filter OFF — skipping historic query\n")

    # ── Agricultural parcels ──────────────────────────────────────────────────
    if config.FILTERS["agricultural_land"]:
        raw = fetch_agricultural_parcels()
    else:
        raw = fetch_broad_landuse()
    print(f"         Retrieved {len(raw):,} raw OSM element(s)\n")

    # ── Group 2 data ──────────────────────────────────────────────────────────
    g2 = config.GROUP2
    distress_elements = fetch_distress_elements() if g2["distress_signal"]   else []
    estate_features   = fetch_named_estates()     if g2["succession_signal"] else []
    tourism_nodes     = fetch_tourism_nodes()     if g2["lodging_overlay"]   else []
    if any(g2.values()):
        print(f"         Secondary signals loaded: {len(distress_elements)} distress, "
              f"{len(estate_features)} named estates, {len(tourism_nodes)} tourism nodes\n")

    # ── Apply filters ─────────────────────────────────────────────────────────
    print("  Applying filters...")
    parcels, skipped = filter_parcels(raw, airports, historic_sites)

    print(f"  Skipped → no geometry: {skipped['no_geometry']}  |  "
          f"too small: {skipped['area']}  |  "
          f"too far from airport: {skipped['airport']}  |  "
          f"no historic nearby: {skipped['historic']}")

    print(f"\n{'═' * 62}")
    print(f"  {len(parcels)} parcel(s) matched all active filters")
    print(f"{'═' * 62}\n")

    if not parcels:
        print("  No results. Try relaxing filters in config.py.\n")
        return

    # ── Annotate Group 2 ──────────────────────────────────────────────────────
    parcels = annotate_group2(parcels, distress_elements, estate_features, tourism_nodes)

    # ── Console preview (top 15) ──────────────────────────────────────────────
    total_2nd = parcels[0].get("secondary_total", 4) if parcels else 4
    print(f"  {'#':>3}  {'Crop Type':<18}  {'Parcel Sqft':>12}  {'Airport':>8}  "
          f"{'Heritage':>12}  {'Secondary Reqs':>14}  Name / GPS")
    print(f"  {'─'*3}  {'─'*18}  {'─'*12}  {'─'*8}  {'─'*12}  {'─'*14}  {'─'*24}")
    for i, p in enumerate(parcels[:15], 1):
        hist_col  = (p["closest_historic_tag"] or "yes")[:12]
        sec_score = p.get("secondary_score", "—")
        sec_label = f"{sec_score} secondary"
        name      = (p["name"] or p["gps_coordinates"])[:28]
        print(
            f"  {i:>3}  {p['primary_crop_type']:<18}  "
            f"{p['parcel_sqft']:>9,.0f} ft²  "
            f"{p['dist_airport_km']:>5.1f} km  "
            f"{hist_col:>12}  "
            f"{sec_label:>14}  {name}"
        )
    if len(parcels) > 15:
        print(f"\n  … and {len(parcels) - 15} more parcel(s) in the output files.")

    # ── Export ────────────────────────────────────────────────────────────────
    ts        = datetime.now().strftime("%Y%m%d_%H%M%S")
    csv_path  = f"results_{ts}.csv"
    json_path = f"results_{ts}.json"
    export_csv(parcels, csv_path)
    export_json(parcels, json_path)
    print(f"\n  Saved → {csv_path}")
    print(f"  Saved → {json_path}\n")


if __name__ == "__main__":
    main()
