#!/usr/bin/env python3
"""
cadastral.py — Italian Catasto cross-validation for Parcel Scout.

Queries the free, public Agenzia delle Entrate (AdE) WFS to retrieve
official cadastral parcel boundaries and identifiers, then cross-checks
them against the OSM-sourced parcel data already in the pipeline.

Think of it like a second opinion from the government land registry:
OpenStreetMap tells us "there's a vineyard here", and the Catasto says
"here is the official boundary the government has on file."

Also queries CORINE Land Cover (EU satellite-derived land classification)
to independently verify that the land use matches what OSM says.

All data sources are free and require no API keys.

Endpoint (CC BY 4.0):
  https://wfs.cartografia.agenziaentrate.gov.it/inspire/wfs/owfs01.php
"""
from __future__ import annotations

import math
import time
import xml.etree.ElementTree as ET

import requests

import config


# ─── AdE WFS Configuration ──────────────────────────────────────────────────

ADE_WFS_URL = "https://wfs.cartografia.agenziaentrate.gov.it/inspire/wfs/owfs01.php"

# GML namespace map — needed to navigate the XML tree returned by the WFS.
# (Namespaces are like address prefixes in XML that prevent tag-name collisions
#  between different standards — gml: is for geometry, CP: is for cadastral parcels.)
NS = {
    "wfs": "http://www.opengis.net/wfs/2.0",
    "gml": "http://www.opengis.net/gml/3.2",
    "CP":  "http://mapserver.gis.umn.edu/mapserver",
}

# Module-level timestamp for rate-limiting (same pattern as Overpass in scout.py)
_last_ade_call: float = 0.0


# ─── CORINE Land Cover Codes ────────────────────────────────────────────────
# CORINE is a Europe-wide satellite survey that classifies every piece of land
# into one of ~44 categories. These are the ones relevant to agriculture in Tuscany.

CORINE_AG_CODES = {
    "211": "Non-irrigated arable land",
    "221": "Vineyards",
    "222": "Fruit trees and berry plantations",
    "223": "Olive groves",
    "231": "Pastures",
    "242": "Complex cultivation patterns",
    "243": "Agriculture with significant natural vegetation",
}

# Map from CORINE code → which OSM crop types it confirms as a match.
# For example, CORINE code 221 (Vineyards) confirms an OSM "vineyard" tag.
CORINE_TO_OSM_MATCH = {
    "221": {"vineyard", "vineyard (farmland)"},
    "222": {"orchard", "olive orchard", "olive orchard (farmland)"},
    "223": {"olive orchard", "olive orchard (farmland)"},
    "211": {"farmland"},
    "231": {"grass", "meadow"},
    "242": {"vineyard", "vineyard (farmland)", "orchard", "olive orchard",
            "olive orchard (farmland)", "farmland"},
    "243": {"vineyard", "vineyard (farmland)", "orchard", "olive orchard",
            "olive orchard (farmland)", "farmland", "grass", "meadow"},
}

# CORINE ArcGIS REST endpoint — the EU's Copernicus programme provides this free.
# We use the ArcGIS "identify" operation (simpler and more reliable than WMS
# GetFeatureInfo) to ask "what land type is at this point?"
CORINE_REST_URL = (
    "https://image.discomap.eea.europa.eu/arcgis/rest/services/"
    "Corine/CLC2018_WM/MapServer/identify"
)


# ─── AdE WFS: Query Official Cadastral Parcels ──────────────────────────────

def query_cadastral_parcels(lat: float, lon: float,
                            buffer_deg: float = None) -> list:
    """
    Ask the Italian government's Catasto WFS: "What official parcels exist
    near this point?"

    Builds a small bounding box around (lat, lon), sends it to the WFS, and
    parses the GML response into a list of dicts — one per cadastral parcel.

    Returns [] on any failure (network error, empty response, parse error)
    so the pipeline can continue with OSM-only data.
    """
    global _last_ade_call

    if not getattr(config, "CADASTRAL_VALIDATION", True):
        return []

    if buffer_deg is None:
        buffer_deg = getattr(config, "CADASTRAL_BUFFER_DEG", 0.001)

    delay = getattr(config, "CADASTRAL_REQUEST_DELAY", 1.0)

    # ── Rate-limit: wait if we called too recently ───────────────────────
    elapsed = time.time() - _last_ade_call
    if elapsed < delay:
        time.sleep(delay - elapsed)

    # ── Build BBOX: lat_min, lon_min, lat_max, lon_max, CRS ─────────────
    # The AdE WFS uses EPSG:6706 (Italy's RDN2008 datum), which is
    # effectively identical to WGS84 at the precision we need.
    bbox = (
        f"{lat - buffer_deg},{lon - buffer_deg},"
        f"{lat + buffer_deg},{lon + buffer_deg},"
        f"urn:ogc:def:crs:EPSG::6706"
    )

    params = {
        "SERVICE":   "WFS",
        "VERSION":   "2.0.0",
        "REQUEST":   "GetFeature",
        "TYPENAMES": "CP:CadastralParcel",
        "BBOX":      bbox,
        "COUNT":     "20",           # plenty for a ~200m square
    }

    try:
        _last_ade_call = time.time()
        resp = requests.get(ADE_WFS_URL, params=params, timeout=15)
        resp.raise_for_status()
        return _parse_cadastral_gml(resp.text)
    except Exception as exc:
        # Graceful degradation — if the WFS is down or returns garbage,
        # the parcel just won't get cadastral cross-validation.
        print(f"  ⚠ Catasto WFS error: {exc}")
        return []


def _parse_cadastral_gml(xml_text: str) -> list:
    """
    Parse the GML/XML response from the AdE WFS into a clean list of dicts.

    Each returned cadastral parcel has:
      - cadastral_ref:  national reference (e.g. "D858_003400.1")
      - admin_unit:     commune code (e.g. "D858" = Gaiole in Chianti)
      - label:          particella number (e.g. "1")
      - foglio:         sheet number extracted from the reference
      - particella:     parcel number within that sheet
      - polygon_nodes:  list of {"lat": float, "lon": float} dicts
      - centroid:       (lat, lon) tuple — mean of all nodes
      - area_sqm:       area computed from the official polygon
    """
    root = ET.fromstring(xml_text)
    parcels = []

    for member in root.findall("wfs:member", NS):
        cp = member.find("CP:CadastralParcel", NS)
        if cp is None:
            continue

        ref   = _text(cp, "CP:NATIONALCADASTRALREFERENCE")
        admin = _text(cp, "CP:ADMINISTRATIVEUNIT")
        label = _text(cp, "CP:LABEL")

        # Extract foglio and particella from the reference string.
        # Format: "D858_003400.1" → commune "D858", foglio "003400", particella "1"
        # Or sometimes: "H501A049400.1" → commune "H501", foglio sheet "A0494", particella "1"
        foglio, particella = _split_cadastral_ref(ref)

        # Parse the polygon geometry from the GML posList element.
        nodes = _extract_polygon_nodes(cp)
        if not nodes:
            continue

        # Compute centroid and area using the same math as scout.py
        c_lat = sum(n["lat"] for n in nodes) / len(nodes)
        c_lon = sum(n["lon"] for n in nodes) / len(nodes)
        area  = _polygon_area_sqm(nodes)

        parcels.append({
            "cadastral_ref":  ref,
            "admin_unit":     admin,
            "label":          label,
            "foglio":         foglio,
            "particella":     particella,
            "polygon_nodes":  nodes,
            "centroid":       (c_lat, c_lon),
            "area_sqm":       area,
        })

    return parcels


def _text(element, tag: str) -> str:
    """Safely extract text from an XML child element."""
    child = element.find(tag, NS)
    return child.text.strip() if child is not None and child.text else ""


def _split_cadastral_ref(ref: str) -> tuple:
    """
    Split a national cadastral reference into foglio and particella.

    Examples:
      "D858_003400.1"   → ("003400", "1")
      "H501A049400.10"  → ("A049400", "10")
    """
    if not ref:
        return ("", "")

    # The particella is always after the last dot
    if "." in ref:
        before_dot, particella = ref.rsplit(".", 1)
    else:
        return (ref, "")

    # The foglio is after the underscore (or after the 4-char commune code)
    if "_" in before_dot:
        foglio = before_dot.split("_", 1)[1]
    elif len(before_dot) > 4:
        foglio = before_dot[4:]     # skip 4-char commune code
    else:
        foglio = before_dot

    return (foglio, particella)


def _extract_polygon_nodes(cp_element) -> list:
    """
    Dig into the GML XML tree to find the polygon coordinates.

    The path is: CP:msGeometry → gml:Polygon → gml:exterior →
                 gml:LinearRing → gml:posList

    The posList contains space-separated numbers: lat1 lon1 lat2 lon2 ...
    (EPSG:6706 axis order is latitude first, longitude second.)
    """
    geom = cp_element.find("CP:msGeometry", NS)
    if geom is None:
        return []

    polygon = geom.find("gml:Polygon", NS)
    if polygon is None:
        # Some parcels use MultiSurface → surfaceMember → Polygon
        ms = geom.find("gml:MultiSurface", NS)
        if ms is not None:
            sm = ms.find("gml:surfaceMember", NS)
            if sm is not None:
                polygon = sm.find("gml:Polygon", NS)
        if polygon is None:
            return []

    exterior = polygon.find("gml:exterior", NS)
    if exterior is None:
        return []

    ring = exterior.find("gml:LinearRing", NS)
    if ring is None:
        return []

    pos_list = ring.find("gml:posList", NS)
    if pos_list is None or not pos_list.text:
        return []

    # Parse "lat1 lon1 lat2 lon2 ..." into [{"lat": ..., "lon": ...}, ...]
    values = pos_list.text.strip().split()
    nodes = []
    for i in range(0, len(values) - 1, 2):
        try:
            nodes.append({"lat": float(values[i]), "lon": float(values[i + 1])})
        except (ValueError, IndexError):
            continue

    return nodes


def _polygon_area_sqm(nodes: list) -> float:
    """
    Approximate area in square metres using the spherical excess formula.
    Same algorithm as scout.py polygon_area_sqm().
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


# ─── Matching: Which cadastral parcel corresponds to our OSM parcel? ─────────

def match_osm_to_cadastral(osm_lat: float, osm_lon: float,
                           osm_nodes: list,
                           cadastral_candidates: list) -> dict | None:
    """
    Given the centroid of an OSM parcel and a list of cadastral candidates
    returned by query_cadastral_parcels(), find the best match.

    Strategy (from most to least confident):
    1. "exact"   — OSM centroid falls inside a cadastral polygon
    2. "overlap" — bounding boxes overlap by more than 30% (IoU > 0.3)
    3. None      — no match found

    Returns the best-matching cadastral dict with an added "match_type" key,
    or None if no match.
    """
    if not cadastral_candidates:
        return None

    # Step 1: check if OSM centroid is inside any cadastral polygon (point-in-polygon)
    for cad in cadastral_candidates:
        if _point_in_polygon(osm_lat, osm_lon, cad["polygon_nodes"]):
            cad["match_type"] = "exact"
            return cad

    # Step 2: bounding box IoU (intersection-over-union) as a fallback
    osm_bbox = _bbox(osm_nodes)
    best_iou  = 0.0
    best_cad  = None

    for cad in cadastral_candidates:
        cad_bbox = _bbox(cad["polygon_nodes"])
        iou = _bbox_iou(osm_bbox, cad_bbox)
        if iou > best_iou:
            best_iou = iou
            best_cad = cad

    if best_cad and best_iou > 0.3:
        best_cad["match_type"] = "overlap"
        return best_cad

    return None


def _point_in_polygon(lat: float, lon: float, nodes: list) -> bool:
    """Ray-casting algorithm — same as scout.py point_in_polygon()."""
    n = len(nodes)
    inside = False
    j = n - 1
    for i in range(n):
        xi, yi = nodes[i]["lon"], nodes[i]["lat"]
        xj, yj = nodes[j]["lon"], nodes[j]["lat"]
        if ((yi > lat) != (yj > lat)) and \
           (lon < (xj - xi) * (lat - yi) / (yj - yi) + xi):
            inside = not inside
        j = i
    return inside


def _bbox(nodes: list) -> tuple:
    """Return (min_lat, min_lon, max_lat, max_lon) for a list of nodes."""
    lats = [n["lat"] for n in nodes]
    lons = [n["lon"] for n in nodes]
    return (min(lats), min(lons), max(lats), max(lons))


def _bbox_iou(a: tuple, b: tuple) -> float:
    """
    Intersection over Union for two axis-aligned bounding boxes.

    Each bbox is (min_lat, min_lon, max_lat, max_lon).
    Returns a float 0.0–1.0 (0 = no overlap, 1 = identical boxes).
    """
    # Intersection rectangle
    inter_min_lat = max(a[0], b[0])
    inter_min_lon = max(a[1], b[1])
    inter_max_lat = min(a[2], b[2])
    inter_max_lon = min(a[3], b[3])

    if inter_min_lat >= inter_max_lat or inter_min_lon >= inter_max_lon:
        return 0.0

    inter_area = (inter_max_lat - inter_min_lat) * (inter_max_lon - inter_min_lon)
    area_a = (a[2] - a[0]) * (a[3] - a[1])
    area_b = (b[2] - b[0]) * (b[3] - b[1])
    union_area = area_a + area_b - inter_area

    if union_area <= 0:
        return 0.0

    return inter_area / union_area


# ─── Area Discrepancy ────────────────────────────────────────────────────────

def compute_area_discrepancy(osm_sqm: float, cadastral_sqm: float) -> float:
    """
    How different is the OSM area from the official cadastral area?

    Returns the percentage difference. For example, if OSM says 10,000 m²
    and the Catasto says 9,000 m², the discrepancy is ~11.1%.

    A low number (<5%) means high confidence in the OSM boundary accuracy.
    """
    if cadastral_sqm <= 0:
        return -1.0    # sentinel: can't compute (no official area)
    return abs(osm_sqm - cadastral_sqm) / cadastral_sqm * 100


# ─── CORINE Land Cover Verification ─────────────────────────────────────────

def query_corine_landuse(lat: float, lon: float) -> dict:
    """
    Ask the EU CORINE Land Cover service: "What type of land is at this point?"

    Uses the ArcGIS REST "identify" operation — we convert lat/lon to Web
    Mercator (the map's native coordinate system) and ask "what's at this
    point?" The server returns the CORINE land classification code.

    Returns a dict with:
      - corine_code:  the numeric code (e.g. "221" for Vineyards)
      - corine_label: human name (e.g. "Vineyards")
      - raw_response: the raw text for debugging

    Returns {"corine_code": "", "corine_label": "", "raw_response": ""}
    on any error, so the pipeline continues.
    """
    # Convert WGS84 lat/lon to Web Mercator (EPSG:3857) — the projection
    # this particular map service uses (like converting between two grids).
    x = lon * 20037508.34 / 180
    y_rad = math.log(math.tan((90 + lat) * math.pi / 360)) / (math.pi / 180)
    y = y_rad * 20037508.34 / 180

    params = {
        "geometry":       f"{x},{y}",
        "geometryType":   "esriGeometryPoint",
        "sr":             "3857",
        "layers":         "all:0",     # Layer 0 = CLC 2018 vector (Europe)
        "tolerance":      "1",
        "mapExtent":      f"{x - 1000},{y - 1000},{x + 1000},{y + 1000}",
        "imageDisplay":   "100,100,96",
        "returnGeometry": "false",
        "f":              "json",
    }

    try:
        resp = requests.get(CORINE_REST_URL, params=params, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        return _parse_corine_response(data)
    except Exception:
        return {"corine_code": "", "corine_label": "", "raw_response": ""}


def _parse_corine_response(data: dict) -> dict:
    """Extract the CORINE land cover code from the ArcGIS identify JSON."""
    result = {"corine_code": "", "corine_label": "", "raw_response": str(data)[:500]}

    results = data.get("results", [])
    if not results:
        return result

    attrs = results[0].get("attributes", {})
    code = str(attrs.get("Code_18", ""))

    if code:
        result["corine_code"] = code
        result["corine_label"] = CORINE_AG_CODES.get(
            code, f"Non-agricultural ({code})"
        )

    return result


def check_corine_match(osm_crop_type: str, corine_code: str) -> str:
    """
    Does the CORINE satellite classification agree with the OSM crop tag?

    Returns:
      "confirmed" — CORINE agrees with OSM (high confidence)
      "mismatch"  — CORINE says something different (flag for review)
      "unknown"   — CORINE data unavailable or not an agricultural code
    """
    if not corine_code:
        return "unknown"

    if corine_code not in CORINE_TO_OSM_MATCH:
        # Non-agricultural CORINE code
        if osm_crop_type and osm_crop_type != "unknown":
            return "mismatch"
        return "unknown"

    matching_types = CORINE_TO_OSM_MATCH[corine_code]
    if osm_crop_type in matching_types:
        return "confirmed"
    else:
        return "mismatch"


# ─── Deduplication ───────────────────────────────────────────────────────────

def deduplicate_parcels(parcels: list) -> tuple:
    """
    Remove duplicate OSM features that represent the same real-world parcel.

    OSM often maps the same vineyard as both a way AND a relation, or a
    vineyard inside a larger farmland polygon. This creates false duplicates
    in our results.

    Strategy:
    1. If two parcels share the same cadastral_id → definite duplicate
    2. If two parcels have centroids within 50 m AND bounding box overlap
       (IoU > 0.5) → likely duplicate

    When duplicates are found, we keep the "better" one:
      - More specific crop type (vineyard > farmland)
      - More polygon nodes (better geometry resolution)
      - Has a name (named > unnamed)

    Returns: (deduplicated_list, count_removed)
    """
    if len(parcels) < 2:
        return parcels, 0

    # ── Pass 1: group by cadastral_id ────────────────────────────────────
    by_cadastral = {}
    no_cadastral = []

    for p in parcels:
        cid = p.get("cadastral_id", "")
        if cid:
            by_cadastral.setdefault(cid, []).append(p)
        else:
            no_cadastral.append(p)

    kept = []
    removed = 0

    # For each cadastral group, keep the best parcel
    for cid, group in by_cadastral.items():
        if len(group) == 1:
            kept.append(group[0])
        else:
            best = _pick_best_parcel(group)
            kept.append(best)
            removed += len(group) - 1

    # ── Pass 2: centroid proximity + bbox overlap for parcels without IDs ─
    used = [False] * len(no_cadastral)
    for i in range(len(no_cadastral)):
        if used[i]:
            continue

        cluster = [no_cadastral[i]]
        lat_i = no_cadastral[i]["lat"]
        lon_i = no_cadastral[i]["lon"]

        for j in range(i + 1, len(no_cadastral)):
            if used[j]:
                continue
            lat_j = no_cadastral[j]["lat"]
            lon_j = no_cadastral[j]["lon"]

            # Quick distance check: ~50 m threshold
            dlat = abs(lat_i - lat_j)
            dlon = abs(lon_i - lon_j)
            if dlat > 0.0005 or dlon > 0.0005:
                continue

            # Check bounding box overlap
            coords_i = no_cadastral[i].get("polygon_coords", [])
            coords_j = no_cadastral[j].get("polygon_coords", [])
            if coords_i and coords_j:
                nodes_i = [{"lat": c[0], "lon": c[1]} for c in coords_i]
                nodes_j = [{"lat": c[0], "lon": c[1]} for c in coords_j]
                iou = _bbox_iou(_bbox(nodes_i), _bbox(nodes_j))
                if iou > 0.5:
                    cluster.append(no_cadastral[j])
                    used[j] = True

        if len(cluster) > 1:
            best = _pick_best_parcel(cluster)
            kept.append(best)
            removed += len(cluster) - 1
            used[i] = True
        elif not used[i]:
            kept.append(no_cadastral[i])

    return kept, removed


# Crop type specificity ranking — more specific types are preferred when deduplicating
_CROP_RANK = {
    "vineyard": 6,
    "vineyard (farmland)": 5,
    "olive orchard": 4,
    "olive orchard (farmland)": 3,
    "orchard": 2,
    "farmland": 1,
}


def _pick_best_parcel(group: list) -> dict:
    """
    From a group of duplicate parcels, pick the one with the best data quality.
    """
    def score(p):
        crop_score = _CROP_RANK.get(p.get("primary_crop_type", ""), 0)
        node_count = len(p.get("polygon_coords", []))
        has_name   = 1 if p.get("name") else 0
        return (crop_score, node_count, has_name)

    return max(group, key=score)


# ─── Data Quality Score ──────────────────────────────────────────────────────

def compute_quality_score(parcel: dict) -> dict:
    """
    Compute a 0–100 data quality score for a parcel, measuring how much
    we can trust the data — separate from the opportunity score which
    measures acquisition potential.

    Components (weighted):
      - Cadastral match   (30 pts): exact=30, overlap=15, none=0
      - Area agreement    (20 pts): <5%=20, 5-15%=15, 15-30%=5, >30%=0
      - CORINE match      (15 pts): confirmed=15, unknown=7, mismatch=0
      - OSM completeness  (15 pts): name=5, crop tags=5, operator=5
      - Geometry quality   (20 pts): >20 nodes=20, 10-20=15, <10=5

    Returns a dict with the total score, label, and per-component breakdown.
    """
    # ── Component 1: Cadastral match ─────────────────────────────────────
    match = parcel.get("cadastral_match", "none")
    if match == "exact":
        cadastral_pts = 30
    elif match == "overlap":
        cadastral_pts = 15
    else:
        cadastral_pts = 0

    # ── Component 2: Area agreement ──────────────────────────────────────
    disc = parcel.get("area_discrepancy_pct")
    if disc is None or disc < 0:
        area_pts = 0          # no cadastral data to compare
    elif disc < 5:
        area_pts = 20
    elif disc < 15:
        area_pts = 15
    elif disc < 30:
        area_pts = 5
    else:
        area_pts = 0

    # ── Component 3: CORINE land use confirmation ────────────────────────
    corine = parcel.get("corine_match", "unknown")
    if corine == "confirmed":
        corine_pts = 15
    elif corine == "unknown":
        corine_pts = 7
    else:
        corine_pts = 0

    # ── Component 4: OSM tag completeness ────────────────────────────────
    osm_pts = 0
    if parcel.get("name"):
        osm_pts += 5
    crop = parcel.get("primary_crop_type", "unknown")
    if crop and crop != "unknown":
        osm_pts += 5
    # We don't have operator tag yet, but leave room for it
    # (tags like operator=, owner= in OSM)

    # ── Component 5: Geometry quality ────────────────────────────────────
    node_count = len(parcel.get("polygon_coords", []))
    if node_count > 20:
        geom_pts = 20
    elif node_count >= 10:
        geom_pts = 15
    else:
        geom_pts = 5

    total = cadastral_pts + area_pts + corine_pts + osm_pts + geom_pts

    # Label
    if total >= 80:
        label = "High confidence"
    elif total >= 50:
        label = "Moderate"
    elif total >= 20:
        label = "Low"
    else:
        label = "Unverified"

    return {
        "quality_score":          total,
        "quality_label":          label,
        "quality_cadastral_pts":  cadastral_pts,
        "quality_area_pts":       area_pts,
        "quality_corine_pts":     corine_pts,
        "quality_osm_pts":        osm_pts,
        "quality_geom_pts":       geom_pts,
    }


# ─── Full Enrichment Pipeline ────────────────────────────────────────────────

def enrich_parcel(parcel: dict, osm_nodes: list) -> dict:
    """
    Run the full cadastral cross-validation pipeline for a single parcel:
    1. Query the AdE WFS for official cadastral data
    2. Match the best cadastral parcel to our OSM parcel
    3. Query CORINE land use classification
    4. Compute data quality score

    Adds ~15 new keys to the parcel dict. All operations are fault-tolerant —
    if any step fails, the parcel proceeds with partial data.
    """
    lat = parcel["lat"]
    lon = parcel["lon"]

    # ── Step 1: Cadastral lookup ─────────────────────────────────────────
    candidates = query_cadastral_parcels(lat, lon)
    match = match_osm_to_cadastral(lat, lon, osm_nodes, candidates)

    if match:
        parcel["cadastral_id"]             = match["cadastral_ref"]
        parcel["cadastral_foglio"]         = match["foglio"]
        parcel["cadastral_particella"]     = match["particella"]
        parcel["cadastral_admin_unit"]     = match["admin_unit"]
        parcel["cadastral_area_sqm"]       = round(match["area_sqm"])
        parcel["cadastral_match"]          = match["match_type"]
        parcel["cadastral_polygon_coords"] = [
            [n["lat"], n["lon"]] for n in match["polygon_nodes"]
        ]

        disc = compute_area_discrepancy(parcel["parcel_sqm"], match["area_sqm"])
        parcel["area_discrepancy_pct"] = round(disc, 1) if disc >= 0 else None
    else:
        parcel["cadastral_id"]             = ""
        parcel["cadastral_foglio"]         = ""
        parcel["cadastral_particella"]     = ""
        parcel["cadastral_admin_unit"]     = ""
        parcel["cadastral_area_sqm"]       = None
        parcel["cadastral_match"]          = "none"
        parcel["cadastral_polygon_coords"] = []
        parcel["area_discrepancy_pct"]     = None

    # ── Step 2: CORINE land use verification ─────────────────────────────
    corine = query_corine_landuse(lat, lon)
    parcel["corine_code"]  = corine["corine_code"]
    parcel["corine_label"] = corine["corine_label"]
    parcel["corine_match"] = check_corine_match(
        parcel.get("primary_crop_type", ""),
        corine["corine_code"]
    )

    # ── Step 3: Data quality score ───────────────────────────────────────
    quality = compute_quality_score(parcel)
    parcel.update(quality)

    return parcel
