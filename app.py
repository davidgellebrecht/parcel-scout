#!/usr/bin/env python3
"""
app.py — Parcel Scout Web Portal
Giovanni Bonelli Group edition — no sidebar, province dropdown, luxury aesthetic.

Run locally:   streamlit run app.py
Deploy:        push to GitHub → share.streamlit.io
"""

import json
import time
from datetime import datetime

import folium
import pandas as pd
import streamlit as st
from streamlit_folium import st_folium

import streamlit_shadcn_ui as ui
import config

# ── Pipeline imports ──────────────────────────────────────────────────────────
from scout import (
    fetch_airports,
    fetch_historic_sites,
    fetch_agricultural_parcels,
    fetch_broad_landuse,
    fetch_distress_elements,
    fetch_named_estates,
    fetch_tourism_nodes,
    filter_parcels,
    annotate_group2,
)
from rank import (
    ALL_LAYERS,
    ALL_SIGNAL_KEYS,
    SIGNAL_LABELS,
    run_all_layers,
    signals_fired_list,
)

# ── Page config ───────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Parcel Scout — Giovanni Bonelli Group",
    page_icon="🏡",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# ── Load Streamlit secrets ────────────────────────────────────────────────────
try:
    config.OPENAPI_IT_KEY              = st.secrets.get("OPENAPI_IT_KEY",             config.OPENAPI_IT_KEY)
    config.SENTINEL_HUB_CLIENT_ID      = st.secrets.get("SENTINEL_HUB_CLIENT_ID",     config.SENTINEL_HUB_CLIENT_ID)
    config.SENTINEL_HUB_CLIENT_SECRET  = st.secrets.get("SENTINEL_HUB_CLIENT_SECRET", config.SENTINEL_HUB_CLIENT_SECRET)
    config.TRIPADVISOR_API_KEY         = st.secrets.get("TRIPADVISOR_API_KEY",        config.TRIPADVISOR_API_KEY)
    config.WINE_SEARCHER_API_KEY       = st.secrets.get("WINE_SEARCHER_API_KEY",      config.WINE_SEARCHER_API_KEY)
except Exception:
    pass

# ── Giovanni Bonelli CSS ──────────────────────────────────────────────────────
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Cormorant+Garamond:ital,wght@0,300;0,400;0,600;1,300;1,400&family=Montserrat:wght@300;400;500;600&display=swap');

/* ── Hide Streamlit chrome ── */
#MainMenu, footer, header            { visibility: hidden; }
.stDeployButton                      { display: none !important; }
section[data-testid="stSidebar"]     { display: none !important; }
[data-testid="collapsedControl"]     { display: none !important; }

/* ── Page background ── */
.stApp {
    background-color: #F4EFE6;
}
.main .block-container {
    padding: 3rem 5rem 4rem 5rem;
    max-width: 1100px;
    margin: 0 auto;
}

/* ── Global typography ── */
html, body, [class*="css"] {
    font-family: 'Montserrat', sans-serif;
    color: #2A2118;
}

/* ── Headings ── */
h1 {
    font-family: 'Cormorant Garamond', serif !important;
    font-weight: 300 !important;
    font-size: 3.2rem !important;
    letter-spacing: 0.06em !important;
    color: #2A2118 !important;
    line-height: 1.1 !important;
    margin-bottom: 0.2rem !important;
}
h2, h3 {
    font-family: 'Cormorant Garamond', serif !important;
    font-weight: 400 !important;
    color: #2A2118 !important;
    letter-spacing: 0.04em !important;
}

/* ── Section labels ── */
.gb-label {
    font-family: 'Cormorant Garamond', serif;
    font-size: 1.1rem;
    font-weight: 400;
    font-style: italic;
    letter-spacing: 0.03em;
    color: #8B6914;
    margin-bottom: 0.15rem;
    margin-top: 0.2rem;
    display: block;
    border-bottom: 1px solid #D4C4A0;
    padding-bottom: 0.3rem;
}

/* ── Divider ── */
hr {
    border: none !important;
    border-top: 1px solid #D4C4A0 !important;
    margin: 2rem 0 !important;
}

/* ── Selectbox ── */
.stSelectbox > div > div {
    background-color: #FFFFFF !important;
    border: 1px solid #D4C4A0 !important;
    border-radius: 0 !important;
    font-family: 'Montserrat', sans-serif !important;
    font-size: 0.85rem !important;
    color: #2A2118 !important;
}

/* ── Checkboxes ── */
.stCheckbox > label,
.stCheckbox > label > div,
.stCheckbox > label > span,
.stCheckbox span[data-testid="stMarkdownContainer"] p {
    font-family: 'Montserrat', sans-serif !important;
    font-size: 0.82rem !important;
    font-weight: 500 !important;
    color: #1A1210 !important;
    letter-spacing: 0.02em !important;
    opacity: 1 !important;
}

/* ── Captions ── */
.stCaption,
[data-testid="stCaptionContainer"] p,
[data-testid="stCaptionContainer"] {
    font-family: 'Montserrat', sans-serif !important;
    font-size: 0.72rem !important;
    color: #3A2E22 !important;
    line-height: 1.55 !important;
    opacity: 1 !important;
}

/* ── Expander header ── */
[data-testid="stExpander"] summary p {
    font-family: 'Montserrat', sans-serif !important;
    font-size: 0.78rem !important;
    font-weight: 500 !important;
    color: #2A2118 !important;
    opacity: 1 !important;
}
/* Hide the Material Icons arrow span entirely — the global font rule overrides
   Material Icons with Montserrat, rendering the glyph as "_arro" literal text.
   Replace with a CSS › character that rotates on open/close instead. */
[data-testid="stExpander"] summary span,
[data-testid="stExpander"] summary svg {
    display: none !important;
}
[data-testid="stExpander"] summary::before {
    content: '›';
    font-family: 'Cormorant Garamond', serif !important;
    font-size: 1.3rem;
    color: #8B6914;
    margin-right: 0.5rem;
    display: inline-block;
    transition: transform 0.2s ease;
    line-height: 1;
    vertical-align: middle;
}
[data-testid="stExpander"] details[open] > summary::before {
    transform: rotate(90deg);
}

/* ── Expander body (open state) ── */
[data-testid="stExpander"] details > div,
[data-testid="stExpander"] .streamlit-expanderContent {
    background-color: #FAF6EF !important;
    border: 1px solid #D4C4A0 !important;
    padding: 1rem !important;
}
/* Expander body text — force dark, override Streamlit's blue-gray defaults */
[data-testid="stExpander"] details > div p,
[data-testid="stExpander"] details > div span,
[data-testid="stExpander"] details > div li,
[data-testid="stExpander"] details > div strong,
[data-testid="stExpander"] details > div a,
[data-testid="stExpander"] .streamlit-expanderContent p,
[data-testid="stExpander"] .streamlit-expanderContent span,
[data-testid="stExpander"] .streamlit-expanderContent strong {
    color: #2A2118 !important;
    font-family: 'Montserrat', sans-serif !important;
    font-size: 0.78rem !important;
    opacity: 1 !important;
}

/* ── Primary button (Run Scan) ── */
.stButton > button[kind="primary"] {
    width: 100% !important;
    background-color: #2A2118 !important;
    color: #F4EFE6 !important;
    font-family: 'Montserrat', sans-serif !important;
    font-size: 0.68rem !important;
    font-weight: 600 !important;
    letter-spacing: 0.22em !important;
    text-transform: uppercase !important;
    border: none !important;
    border-radius: 0 !important;
    padding: 1rem 2rem !important;
    margin-top: 0.5rem !important;
    transition: background-color 0.2s !important;
}
.stButton > button[kind="primary"]:hover {
    background-color: #8B6914 !important;
}

/* ── Dossier / secondary buttons ── */
.stButton > button[kind="secondary"] {
    background-color: #2A2118 !important;
    color: #F4EFE6 !important;
    border: 1px solid #8B6914 !important;
    border-radius: 0 !important;
    font-family: 'Montserrat', sans-serif !important;
    font-size: 0.65rem !important;
    font-weight: 600 !important;
    letter-spacing: 0.18em !important;
    text-transform: uppercase !important;
    padding: 0.7rem 1rem !important;
}
.stButton > button[kind="secondary"]:hover {
    background-color: #8B6914 !important;
    border-color: #8B6914 !important;
}

/* ── Secondary / download buttons ── */
.stDownloadButton > button {
    background-color: transparent !important;
    color: #2A2118 !important;
    border: 1px solid #D4C4A0 !important;
    border-radius: 0 !important;
    font-family: 'Montserrat', sans-serif !important;
    font-size: 0.65rem !important;
    letter-spacing: 0.12em !important;
    text-transform: uppercase !important;
}
.stDownloadButton > button:hover {
    border-color: #2A2118 !important;
    background-color: #2A2118 !important;
    color: #F4EFE6 !important;
}

/* ── Metrics ── */
[data-testid="metric-container"] {
    background: #FFFFFF;
    border: 1px solid #D4C4A0;
    padding: 1.1rem 1.3rem;
}
[data-testid="metric-container"] label {
    font-family: 'Montserrat', sans-serif !important;
    font-size: 0.58rem !important;
    letter-spacing: 0.18em !important;
    text-transform: uppercase !important;
    color: #8B6914 !important;
}
[data-testid="metric-container"] [data-testid="stMetricValue"] {
    font-family: 'Cormorant Garamond', serif !important;
    font-size: 2rem !important;
    font-weight: 400 !important;
    color: #2A2118 !important;
}

/* ── Tabs ── */
.stTabs [data-baseweb="tab-list"] {
    gap: 0;
    border-bottom: 1px solid #D4C4A0;
    background: transparent;
}
.stTabs [data-baseweb="tab"] {
    font-family: 'Montserrat', sans-serif !important;
    font-size: 0.62rem !important;
    font-weight: 500 !important;
    letter-spacing: 0.16em !important;
    text-transform: uppercase !important;
    padding: 0.8rem 1.6rem !important;
    background: transparent !important;
    border: none !important;
    color: #8B6914 !important;
}
.stTabs [aria-selected="true"] {
    background: transparent !important;
    border-bottom: 2px solid #2A2118 !important;
    color: #2A2118 !important;
}

/* ── Info / status box ── */
.stInfo {
    background-color: #F0EBE0 !important;
    border: 1px solid #D4C4A0 !important;
    border-radius: 0 !important;
    font-family: 'Montserrat', sans-serif !important;
    font-size: 0.8rem !important;
    color: #2A2118 !important;
}

/* ── Success boxes (Signals fired) ── */
[data-testid="stAlert"][data-baseweb="notification"]:has(svg[data-testid="stAlertDynamicIcon-success"]),
.stSuccess, [data-testid="stAlert"].stSuccess {
    background-color: #E8F5E9 !important;
    border: 1.5px solid #4A6741 !important;
    border-radius: 0 !important;
    opacity: 1 !important;
}
.stSuccess p, .stSuccess div, .stSuccess span {
    color: #2A4028 !important;
    font-family: 'Montserrat', sans-serif !important;
    font-weight: 600 !important;
    font-size: 0.75rem !important;
    opacity: 1 !important;
}

/* ── Warning box ── */
.stWarning, [data-testid="stAlert"].stWarning,
div[data-baseweb="notification"]:not(.stSuccess):not(.stError):not(.stInfo) {
    background-color: #FFF176 !important;
    border: 1px solid #F9A825 !important;
    border-radius: 0 !important;
    opacity: 1 !important;
}
.stWarning p, .stWarning li, .stWarning strong,
.stWarning span, .stWarning code, .stWarning div {
    color: #1A1200 !important;
    font-family: 'Montserrat', sans-serif !important;
    font-size: 0.78rem !important;
    opacity: 1 !important;
}


/* ── Hero image strip ── */
[data-testid="stImage"] img {
    object-fit: cover;
    height: 200px;
    width: 100%;
    display: block;
}
[data-testid="stImage"] {
    padding: 0 !important;
    margin: 0 !important;
}

/* ── Dataframe ── */
.stDataFrame { border: 1px solid #D4C4A0 !important; }

/* ── Status widget (scan progress) ── */
[data-testid="stStatusWidget"] {
    background-color: #2A2118 !important;
}
[data-testid="stStatusWidget"] p,
[data-testid="stStatusWidget"] span,
[data-testid="stStatusWidget"] div {
    color: #F4EFE6 !important;
    font-family: 'Montserrat', sans-serif !important;
    font-size: 0.78rem !important;
    opacity: 1 !important;
}
/* Status expanded body */
[data-testid="stStatusWidget"] > div:last-child {
    background-color: #FAF6EF !important;
    border: 1px solid #D4C4A0 !important;
    padding: 0.8rem 1rem !important;
}
[data-testid="stStatusWidget"] > div:last-child p,
[data-testid="stStatusWidget"] > div:last-child span {
    color: #2A2118 !important;
    font-size: 0.75rem !important;
}
</style>
""", unsafe_allow_html=True)

# ── Tuscany provinces ─────────────────────────────────────────────────────────
# Bounding box format: (south_lat, west_lon, north_lat, east_lon)
TUSCANY_PROVINCES = {
    "Province of Siena":         (42.63, 10.90, 43.52, 11.93),
    "Province of Florence":      (43.50, 10.89, 44.12, 11.65),
    "Province of Arezzo":        (43.28, 11.42, 43.80, 12.09),
    "Province of Grosseto":      (42.35, 10.83, 43.17, 11.72),
    "Province of Livorno":       (42.95, 10.16, 43.62, 10.80),
    "Province of Lucca":         (43.68, 10.29, 44.15, 10.73),
    "Province of Massa-Carrara": (43.97,  9.82, 44.23, 10.27),
    "Province of Pisa":          (43.35, 10.02, 43.90, 10.84),
    "Province of Pistoia":       (43.77, 10.67, 44.11, 11.15),
    "Province of Prato":         (43.82, 11.01, 44.07, 11.27),
}

# ── Signal metadata ───────────────────────────────────────────────────────────
SIGNAL_META = [
    {
        "key":    "g2_premium_wine_zone",
        "label":  "DOCG Wine Zone",
        "group":  "group2",
        "config": ("GROUP2", "premium_wine_zone"),
        "paid":   False,
        "badge":  "",
        "desc":   "Parcel falls within a premium Italian wine appellation where bottles regularly trade above $150.",
    },
    {
        "key":    "g2_distress_signal",
        "label":  "Distress Signal",
        "group":  "group2",
        "config": ("GROUP2", "distress_signal"),
        "paid":   False,
        "badge":  "",
        "desc":   "Fire history (EU EFFIS satellite data) or abandoned land nearby — a neglect and financial stress proxy.",
    },
    {
        "key":    "g2_succession_signal",
        "label":  "Succession Signal",
        "group":  "group2",
        "config": ("GROUP2", "succession_signal"),
        "paid":   False,
        "badge":  "",
        "desc":   "Italian family estate naming (Podere, Fattoria, Tenuta…) on or near the parcel suggests generational ownership nearing transition.",
    },
    {
        "key":    "g2_lodging_overlay",
        "label":  "Lodging Overlay",
        "group":  "group2",
        "config": ("GROUP2", "lodging_overlay"),
        "paid":   False,
        "badge":  "",
        "desc":   "Existing tourism or hospitality operation nearby signals local planning precedent for agriturismo conversion under Italian Law 96/2006.",
    },
    {
        "key":    "layer_satellite_neglect_signal",
        "label":  "Satellite Neglect",
        "group":  "layer",
        "config": ("LAYERS", "satellite_neglect"),
        "paid":   True,
        "badge":  "paid",
        "desc":   "NDVI satellite data shows vegetation vigor below neighboring parcels — the first measurable sign of absentee ownership.",
    },
    {
        "key":    "layer_permit_paralysis_signal",
        "label":  "Permit Paralysis",
        "group":  "layer",
        "config": ("LAYERS", "permit_paralysis"),
        "paid":   True,
        "badge":  "paid",
        "desc":   "Owner has filed multiple renovation permits over years with no final approval — frustration that often precedes a willingness to sell.",
    },
    {
        "key":    "layer_zoning_alchemy_signal",
        "label":  "Zoning Alchemy",
        "group":  "layer",
        "config": ("LAYERS", "zoning_alchemy"),
        "paid":   True,
        "badge":  "paid + free",
        "desc":   "Parcel is in agricultural Zone E (agriturismo-eligible) and/or shows permit filings using rural conversion keywords.",
    },
    {
        "key":    "layer_napa_neighbor_signal",
        "label":  "Napa Neighbor",
        "group":  "layer",
        "config": ("LAYERS", "napa_neighbor"),
        "paid":   False,
        "badge":  "free",
        "desc":   "Within 8 km of a marquee acquisition (Antinori, LVMH, Frescobaldi) — land values in these ripple zones typically lag the anchor by 2–4 years.",
    },
    {
        "key":    "layer_hospitality_fatigue_signal",
        "label":  "Hospitality Fatigue",
        "group":  "layer",
        "config": ("LAYERS", "hospitality_fatigue"),
        "paid":   True,
        "badge":  "paid",
        "desc":   "Nearby agriturismo or hotel shows declining TripAdvisor scores and review cadence — a leading indicator of owner burnout.",
    },
    {
        "key":    "layer_digital_ghost_signal",
        "label":  "Digital Ghost",
        "group":  "layer",
        "config": ("LAYERS", "digital_ghost"),
        "paid":   False,
        "badge":  "free",
        "desc":   "Estate website has gone stale or domain is near expiry — the digital equivalent of taking down the 'Open' sign.",
    },
    {
        "key":    "layer_terroir_score_delta_signal",
        "label":  "Terroir Delta",
        "group":  "layer",
        "config": ("LAYERS", "terroir_score_delta"),
        "paid":   True,
        "badge":  "paid",
        "desc":   "Soil quality (DOCG zone, galestro geology) outperforms the current producer's critic scores — unlocked value for a new buyer.",
    },
    {
        "key":    "layer_succession_frag_signal",
        "label":  "Succession Fragmentation",
        "group":  "layer",
        "config": ("LAYERS", "succession_frag"),
        "paid":   True,
        "badge":  "paid",
        "desc":   "Cadastral records show multiple co-owners — Italian inheritance law distributes estates equally, creating motivated-seller pressure.",
    },
    {
        "key":    "layer_owner_relocation_signal",
        "label":  "Owner Relocation",
        "group":  "layer",
        "config": ("LAYERS", "owner_relocation"),
        "paid":   True,
        "badge":  "paid + free",
        "desc":   "Owner's fiscal address or website language signals they no longer live near the estate — management burden often exceeds lifestyle benefit.",
    },
]

FILTER_META = [
    {
        "key":   "proximity_to_airport",
        "label": "Airport Proximity",
        "desc":  "Must be within 60 min drive of Pisa (PSA) or Florence (FLR).",
    },
    {
        "key":   "agricultural_land",
        "label": "Agricultural Land",
        "desc":  "Parcel must be mapped as vineyard or olive orchard in OpenStreetMap.",
    },
    {
        "key":   "min_square_footage",
        "label": "Minimum Parcel Size",
        "desc":  "Total land area must exceed 20,000 sqft (~0.46 acres).",
    },
    {
        "key":   "historical_designation",
        "label": "Historic Building On Parcel",
        "desc":  "A renovatable historic structure (castle, chapel, villa…) must sit physically inside the parcel boundary.",
    },
]

# ── Premium layer info (setup instructions, cost, credential mapping) ─────────
# Shown in "Setup & pricing" expanders under each paid layer checkbox,
# and used to build the pre-scan credential warning block.

PREMIUM_LAYER_INFO = {
    "satellite_neglect": {
        "api":       "Sentinel Hub — European Space Agency Copernicus programme",
        "cost":      "Free 30-day trial; paid plans from €25/month",
        "free_tier": "30-day trial available — no credit card required during trial period",
        "setup":     "Register at sentinel-hub.com → create an OAuth client → set SENTINEL_HUB_CLIENT_ID and SENTINEL_HUB_CLIENT_SECRET in Streamlit Secrets (or config.py for local use).",
        "degrades":  False,
    },
    "permit_paralysis": {
        "api":       "Albo Pretorio — Italian municipal permit registry",
        "cost":      "Commercial aggregator required — no public pricing; contact a vendor",
        "free_tier": None,
        "setup":     "Contract a commercial Albo Pretorio data provider, then set ALBO_PRETORIO_API_KEY in Streamlit Secrets (or config.py for local use).",
        "degrades":  False,
    },
    "zoning_alchemy": {
        "api":       "Albo Pretorio (permit intent) + Regione Toscana WFS (Zone E — free)",
        "cost":      "Only the permit-keyword component requires a paid aggregator; Zone E check is always free",
        "free_tier": "Zone E boundary check runs without any credentials",
        "setup":     "Contract a commercial Albo Pretorio data provider, then set ALBO_PRETORIO_API_KEY in Streamlit Secrets (or config.py for local use).",
        "degrades":  True,
    },
    "hospitality_fatigue": {
        "api":       "TripAdvisor Content API",
        "cost":      "Free up to 5,000 requests/month; paid tiers above that",
        "free_tier": "5,000 requests/month — enough for typical scan volumes",
        "setup":     "Register at tripadvisor.com/developers, generate an API key, then set TRIPADVISOR_API_KEY in Streamlit Secrets (or config.py for local use).",
        "degrades":  False,
    },
    "terroir_score_delta": {
        "api":       "Wine-Searcher API",
        "cost":      "Free up to 100 searches/day; paid plans above that",
        "free_tier": "100 searches/day free",
        "setup":     "Register at wine-searcher.com/api, generate an API key, then set WINE_SEARCHER_API_KEY in Streamlit Secrets (or config.py for local use).",
        "degrades":  False,
    },
    "succession_frag": {
        "api":       "OpenAPI.it — Italian Catasto (cadastral co-owner records)",
        "cost":      "Free tier available — no credit card required",
        "free_tier": "Free tier at console.openapi.com",
        "setup":     "Register at console.openapi.com → navigate to the Catasto section → copy your OAuth Bearer token → set OPENAPI_IT_KEY in Streamlit Secrets (or config.py for local use).",
        "degrades":  False,
    },
    "owner_relocation": {
        "api":       "OpenAPI.it — Italian Catasto (cadastral address) + fiscal code decode (always free)",
        "cost":      "Catasto component only — free tier available at console.openapi.com",
        "free_tier": "Fiscal code decode and website language detection run without any credentials",
        "setup":     "Register at console.openapi.com → navigate to the Catasto section → copy your OAuth Bearer token → set OPENAPI_IT_KEY in Streamlit Secrets (or config.py for local use).",
        "degrades":  True,
    },
}

# Maps each paid layer's config key → the credential variable it needs
LAYER_CRED = {
    "satellite_neglect":   "SENTINEL_HUB_CLIENT_ID",
    "permit_paralysis":    "ALBO_PRETORIO_API_KEY",
    "zoning_alchemy":      "ALBO_PRETORIO_API_KEY",
    "hospitality_fatigue": "TRIPADVISOR_API_KEY",
    "terroir_score_delta": "WINE_SEARCHER_API_KEY",
    "succession_frag":     "OPENAPI_IT_KEY",
    "owner_relocation":    "OPENAPI_IT_KEY",
}

# ── Score helpers ─────────────────────────────────────────────────────────────

def rescore(parcels: list, active_keys: list) -> list:
    total = len(active_keys)
    result = []
    for p in parcels:
        p = dict(p)
        fired = sum(1 for k in active_keys if p.get(k)) if total else 0
        p["opportunity_score"] = round((fired / total) * 100, 1) if total else 0.0
        p["signals_fired"]     = fired
        result.append(p)
    return sorted(result, key=lambda x: x["opportunity_score"], reverse=True)


def score_color(score: float) -> str:
    if score >= 30:
        return "#4A6741"
    if score >= 15:
        return "#8B6914"
    return "#7A6A55"


# ── Pipeline runner ───────────────────────────────────────────────────────────

def run_full_scan(filter_state: dict, g2_state: dict, layer_state: dict) -> list:
    for k, v in filter_state.items():
        config.FILTERS[k] = v
    for k, v in g2_state.items():
        config.GROUP2[k] = v
    for k, v in layer_state.items():
        config.LAYERS[k] = v

    st.session_state.scan_log.append("Fetching airport coordinates…")
    airports = fetch_airports() if filter_state["proximity_to_airport"] else []

    st.session_state.scan_log.append("Querying OpenStreetMap for historic sites…")
    historic_sites = fetch_historic_sites() if filter_state["historical_designation"] else []
    st.session_state.scan_log.append(f"  → {len(historic_sites):,} historic site(s) found")

    st.session_state.scan_log.append("Querying OpenStreetMap for agricultural parcels…")
    raw = fetch_agricultural_parcels() if filter_state["agricultural_land"] else fetch_broad_landuse()
    st.session_state.total_raw = len(raw)
    st.session_state.scan_log.append(f"  → {len(raw):,} raw OSM element(s) retrieved")

    distress_elements = []
    estate_features   = []
    tourism_nodes     = []

    if g2_state["distress_signal"]:
        st.session_state.scan_log.append("Fetching EU EFFIS fire history + abandoned land…")
        distress_elements = fetch_distress_elements()
        st.session_state.scan_log.append(f"  → {len(distress_elements)} distress element(s)")

    if g2_state["succession_signal"]:
        st.session_state.scan_log.append("Querying named Italian estates…")
        estate_features = fetch_named_estates()
        st.session_state.scan_log.append(f"  → {len(estate_features):,} named estate(s)")

    if g2_state["lodging_overlay"]:
        st.session_state.scan_log.append("Querying tourism and lodging nodes…")
        tourism_nodes = fetch_tourism_nodes()
        st.session_state.scan_log.append(f"  → {len(tourism_nodes):,} tourism node(s)")

    st.session_state.scan_log.append("Applying hard filters…")
    parcels, skipped = filter_parcels(raw, airports, historic_sites)
    st.session_state.scan_log.append(
        f"  → {len(parcels)} parcel(s) passed  |  "
        f"no geometry: {skipped['no_geometry']}  |  "
        f"too small: {skipped['area']}  |  "
        f"too far: {skipped['airport']}  |  "
        f"no historic: {skipped['historic']}"
    )

    if not parcels:
        return []

    st.session_state.scan_log.append("Running Group 2 signal annotation…")
    parcels = annotate_group2(parcels, distress_elements, estate_features, tourism_nodes)

    st.session_state.scan_log.append("Running acquisition layers…")
    parcels = run_all_layers(parcels)
    st.session_state.scan_log.append("  → All layers complete")

    # ── Count actual API calls made (non-stub, non-disabled results) ──────────
    # This lets the UI show credit usage per service after each scan.
    # A result is a real API call if its detail field is NOT a stub/disabled msg.
    _stub_phrases = ("PAID FEATURE", "Layer disabled", "disabled in config")
    _api_layer_map = {
        "hospitality_fatigue": "TripAdvisor",
        "terroir_score_delta":  "Wine-Searcher",
        "succession_frag":      "OpenAPI.it",
        "owner_relocation":     "OpenAPI.it",
    }
    usage: dict = {}
    for p in parcels:
        for layer_key, service in _api_layer_map.items():
            detail = p.get(f"layer_{layer_key}_detail", "")
            if detail and not any(ph in detail for ph in _stub_phrases):
                usage[service] = usage.get(service, 0) + 1
    st.session_state.api_usage = usage

    return parcels


# ── Map builder ───────────────────────────────────────────────────────────────

def build_map(parcels: list) -> folium.Map:
    if not parcels:
        return folium.Map(location=[43.1, 11.4], zoom_start=9)

    lats   = [p["lat"] for p in parcels]
    lons   = [p["lon"] for p in parcels]
    center = [sum(lats) / len(lats), sum(lons) / len(lons)]
    m      = folium.Map(location=center, zoom_start=10, tiles="CartoDB positron")

    for p in parcels:
        score   = p.get("opportunity_score", 0)
        color   = "#4A6741" if score >= 30 else "#8B6914" if score >= 15 else "#9CA3AF"
        name    = p.get("name") or p.get("gps_coordinates", "")
        signals = signals_fired_list(p)
        sig_html = "".join(
            f'<span style="background:#f0ebe0;color:#2A2118;padding:2px 6px;'
            f'border:1px solid #D4C4A0;font-size:10px;margin:2px;display:inline-block;">{s}</span>'
            for s in signals
        ) or "<em style='color:#7A6A55'>no signals</em>"

        popup_html = f"""
        <div style="font-family:'Montserrat',sans-serif;min-width:230px;color:#2A2118;
                    background:#F4EFE6;padding:14px;border:1px solid #D4C4A0;">
          <div style="font-family:'Cormorant Garamond',serif;font-size:22px;
                      font-weight:400;color:{color};">{score:.1f}
            <span style="font-size:12px;color:#7A6A55;">/100</span>
          </div>
          <div style="font-size:12px;font-weight:500;margin:4px 0 8px;">{name[:50]}</div>
          <div style="font-size:10px;color:#7A6A55;margin-bottom:6px;">
            {p.get('primary_crop_type','').title()} &nbsp;·&nbsp;
            {p.get('parcel_acres',0):.1f} acres &nbsp;·&nbsp;
            {p.get('dist_airport_km',0):.1f} km to {p.get('airport_iata','')}
          </div>
          <div style="margin-top:8px;">{sig_html}</div>
          <div style="margin-top:10px;font-size:10px;">
            <a href="{p.get('osm_url','')}" target="_blank"
               style="color:#8B6914;text-decoration:none;">View on OpenStreetMap ↗</a>
          </div>
        </div>
        """
        folium.CircleMarker(
            location=[p["lat"], p["lon"]],
            radius=10 + score / 10,
            color=color,
            fill=True,
            fill_color=color,
            fill_opacity=0.7,
            popup=folium.Popup(popup_html, max_width=280),
            tooltip=f"{score:.1f}/100 — {name[:35]}",
        ).add_to(m)

    return m


# ── Rankings table builder ────────────────────────────────────────────────────

def build_rankings_df(parcels: list) -> pd.DataFrame:
    rows = []
    for rank, p in enumerate(parcels, 1):
        fired   = signals_fired_list(p)
        rows.append({
            "Rank":       rank,
            "Score":      p.get("opportunity_score", 0),
            "Signals":    f"{p.get('signals_fired',0)}/{len(ALL_SIGNAL_KEYS)}",
            "Fired":      " · ".join(fired) if fired else "—",
            "Crop":       p.get("primary_crop_type", "").title(),
            "Acres":      int(round(p.get("parcel_acres", 0))),
            "Airport":    f"{p.get('dist_airport_km',0):.0f} km ({p.get('airport_iata','')})",
            "Heritage":   f"{p.get('closest_historic_tag','').title()} ({p.get('heritage_confidence','')})",
            "Name / GPS": p.get("name") or p.get("gps_coordinates", ""),
            "OSM URL":    p.get("osm_url", ""),
        })
    return pd.DataFrame(rows)


# ═══════════════════════════════════════════════════════════════════════════════
#  PAGE LAYOUT — no sidebar, all controls on main page
# ═══════════════════════════════════════════════════════════════════════════════

# ── Header ────────────────────────────────────────────────────────────────────
st.markdown('<span class="gb-label">Giovanni Bonelli Group</span>', unsafe_allow_html=True)
st.markdown("# Parcel Scout")
st.markdown("*Off-market acquisition intelligence — Tuscany, Italy*")

# ── Hero image strip ──────────────────────────────────────────────────────────
HERO_IMAGES = [
    "assets/024_YountLeapEstate.webp",
    "assets/026_YountLeapEstate.webp",
    "assets/058_YountLeapEstate.webp",
    "assets/36-Napa-Valley-Luxury-Home-Hillary-Ryan.webp",
]
img_cols = st.columns(4, gap="small")
for col, path in zip(img_cols, HERO_IMAGES):
    col.image(path, use_container_width=True)

st.markdown("---")

# ── Region selector ───────────────────────────────────────────────────────────
st.markdown('<span class="gb-label">Region</span>', unsafe_allow_html=True)

province_names = list(TUSCANY_PROVINCES.keys())
default_idx    = province_names.index("Province of Siena")

selected_province = st.selectbox(
    "Province",
    options=province_names,
    index=default_idx,
    label_visibility="collapsed",
)

# Patch config for selected province
config.REGION      = f"{selected_province}, Italy"
config.REGION_BBOX = TUSCANY_PROVINCES[selected_province]

st.markdown("---")

# ── Hard Filters ──────────────────────────────────────────────────────────────
st.markdown('<span class="gb-label">Hard Filters</span>', unsafe_allow_html=True)
st.caption("All enabled filters must pass — failing any one excludes the parcel.")

fc1, fc2 = st.columns(2)
filter_state = {}
for i, fm in enumerate(FILTER_META):
    col = fc1 if i % 2 == 0 else fc2
    with col:
        _on = st.session_state.get(f"filter_{fm['key']}", config.FILTERS[fm["key"]])
        filter_state[fm["key"]] = ui.switch(
            default_checked=config.FILTERS[fm["key"]],
            label=f"{'🟢' if _on else '⚪'}  {fm['label']}",
            key=f"filter_{fm['key']}",
        )
        st.caption(fm["desc"])

st.markdown("---")

# ── Signals (all free — group2 + free layers combined) ────────────────────────
st.markdown('<span class="gb-label">Signals</span>', unsafe_allow_html=True)
st.caption("All free — annotation only, never excludes parcels. Toggle to adjust the Opportunity Score.")

g2_state     = {}
layer_state  = {}
free_signals = [sm for sm in SIGNAL_META if not sm["paid"]]

sc1, sc2, sc3 = st.columns(3)
for i, sm in enumerate(free_signals):
    group, cfg_key = sm["config"]
    col = [sc1, sc2, sc3][i % 3]
    with col:
        if sm["group"] == "group2":
            _default = getattr(config, group)[cfg_key]
            _on = st.session_state.get(f"sig_{sm['key']}", _default)
            g2_state[cfg_key] = ui.switch(
                default_checked=_default,
                label=f"{'🟢' if _on else '⚪'}  {sm['label']}",
                key=f"sig_{sm['key']}",
            )
        else:
            _on = st.session_state.get(f"layer_{sm['key']}", True)
            layer_state[cfg_key] = ui.switch(
                default_checked=True,
                label=f"{'🟢' if _on else '⚪'}  {sm['label']}",
                key=f"layer_{sm['key']}",
            )
        st.caption(sm["desc"])

st.markdown("---")

# ── Premium Layers ────────────────────────────────────────────────────────────
st.markdown('<span class="gb-label">Premium Layers</span>', unsafe_allow_html=True)
st.caption("Require API credentials — disabled by default. Enable when credentials are configured.")

paid_layers = [sm for sm in SIGNAL_META if sm["paid"]]

# Pre-seed session state to default paid layers OFF
for sm in paid_layers:
    if f"layer_{sm['key']}" not in st.session_state:
        st.session_state[f"layer_{sm['key']}"] = False

pl1, pl2, pl3 = st.columns(3)
for i, sm in enumerate(paid_layers):
    _, cfg_key = sm["config"]
    col = [pl1, pl2, pl3][i % 3]
    info = PREMIUM_LAYER_INFO.get(cfg_key, {})
    with col:
        _on = st.session_state.get(f"layer_{sm['key']}", False)
        layer_state[cfg_key] = ui.switch(
            default_checked=False,
            label=f"{'🟢' if _on else '⚪'}  {sm['label']}",
            key=f"layer_{sm['key']}",
        )
        st.caption(sm["desc"])
        if info:
            with st.expander("Setup & pricing ›"):
                st.markdown(f"**API source:** {info['api']}")
                st.markdown(f"**Cost:** {info['cost']}")
                if info.get("free_tier"):
                    st.markdown(f"**Free tier:** {info['free_tier']}")
                else:
                    st.markdown("**Free tier:** None")
                st.markdown(f"**Without credentials:** {'Returns limited data (free components still run)' if info['degrades'] else 'Returns no data — layer contributes nothing to the score'}")
                st.markdown(f"**Setup:** {info['setup']}")

# ── Premium layer reference table ────────────────────────────────────────────
with st.expander("Premium Layer Reference — costs, free tiers & setup guide"):
    td = 'style="padding:0.55rem 0.9rem; border-bottom:1px solid #EDE6D8; vertical-align:top;"'
    th = 'style="padding:0.65rem 0.9rem; text-align:left; font-weight:600; letter-spacing:0.08em; text-transform:uppercase; font-size:0.60rem; color:#F4EFE6;"'

    header = (
        '<table style="width:100%;border-collapse:collapse;font-family:Montserrat,sans-serif;'
        'font-size:0.75rem;color:#2A2118;border:1px solid #D4C4A0;">'
        '<thead><tr style="background:#2A2118;">'
        f'<th {th}>Layer</th>'
        f'<th {th}>API Source</th>'
        f'<th {th}>Cost</th>'
        f'<th {th}>Free Tier</th>'
        f'<th {th}>Without Key</th>'
        f'<th {th}>Credential</th>'
        '</tr></thead><tbody>'
    )

    body = ""
    for i, sm in enumerate(paid_layers):
        _, cfg_key = sm["config"]
        info      = PREMIUM_LAYER_INFO.get(cfg_key, {})
        free_tier = info.get("free_tier") or '<span style="color:#7A6A55;">None</span>'
        without   = (
            '<span style="color:#8B6914;font-weight:600;">Limited data</span>'
            ' — free components still run'
            if info.get("degrades") else
            '<span style="color:#9B3A2A;font-weight:600;">No data</span>'
            ' — layer inactive'
        )
        row_bg = "#FFFFFF" if i % 2 == 0 else "#FAF6EF"
        cred   = f'<code style="font-size:0.68rem;color:#8B6914;">{LAYER_CRED.get(cfg_key, "—")}</code>'
        body += (
            f'<tr style="background:{row_bg};">'
            f'<td {td} style="padding:0.55rem 0.9rem;border-bottom:1px solid #EDE6D8;'
            f'vertical-align:top;font-weight:600;white-space:nowrap;">{sm["label"]}</td>'
            f'<td {td}>{info.get("api", "—")}</td>'
            f'<td {td}>{info.get("cost", "—")}</td>'
            f'<td {td}>{free_tier}</td>'
            f'<td {td}>{without}</td>'
            f'<td {td}>{cred}</td>'
            '</tr>'
        )

    footer = (
        '</tbody></table>'
        '<p style="font-size:0.65rem;color:#7A6A55;margin-top:0.6rem;">'
        'Set credentials in <strong>Streamlit Secrets</strong> (cloud) or '
        '<code style="color:#8B6914;">config.py</code> (local).'
        '</p>'
    )

    st.markdown(header + body + footer, unsafe_allow_html=True)

# ── Credential warning block ──────────────────────────────────────────────────
missing_creds = []
for cfg_key, cred_var in LAYER_CRED.items():
    if layer_state.get(cfg_key) and not getattr(config, cred_var, ""):
        info = PREMIUM_LAYER_INFO[cfg_key]
        label = next(sm["label"] for sm in SIGNAL_META if sm["config"][1] == cfg_key)
        missing_creds.append((label, cred_var, info))

if missing_creds:
    n = len(missing_creds)
    rows_html = ""
    for label, cred_var, info in missing_creds:
        impact = "Limited data — free components still run" if info["degrades"] else "No data — layer contributes nothing to scores"
        rows_html += (
            f'<li style="margin-bottom:0.5rem;">'
            f'<strong style="color:#1A1200;">{label}</strong>'
            f' &mdash; needs <code style="background:#FFF0A0;padding:1px 4px;border-radius:2px;color:#8B4513;font-size:0.72rem;">{cred_var}</code>'
            f' &mdash; {impact}<br>'
            f'<span style="color:#5C4A00;font-size:0.72rem;">↳ {info["setup"]}</span>'
            f'</li>'
        )
    st.markdown(
        f'<div style="background:#FFF9C4;border:1.5px solid #F9A825;padding:1rem 1.2rem;margin:0.5rem 0;">'
        f'<p style="color:#1A1200;font-weight:700;margin:0 0 0.4rem 0;font-family:Montserrat,sans-serif;font-size:0.82rem;">'
        f'⚠ {n} premium layer{"s" if n > 1 else ""} enabled without credentials.</p>'
        f'<p style="color:#1A1200;margin:0 0 0.6rem 0;font-family:Montserrat,sans-serif;font-size:0.78rem;">'
        f'The scan will still run — but these layers will be inactive:</p>'
        f'<ul style="color:#1A1200;font-family:Montserrat,sans-serif;font-size:0.78rem;margin:0;padding-left:1.2rem;">'
        f'{rows_html}</ul></div>',
        unsafe_allow_html=True,
    )

st.markdown("---")

# ── Run Scan button ───────────────────────────────────────────────────────────
if st.session_state.get("scan_time"):
    elapsed = st.session_state.get("scan_elapsed", 0)
    st.caption(
        f"Last scan: {st.session_state.scan_time.strftime('%Y-%m-%d  %H:%M')}  "
        f"({elapsed:.0f}s)  ·  Region: {st.session_state.get('scan_region', '')}"
    )

run_btn = st.button("Run Off-Market Scan", type="primary", use_container_width=True)

# ── Trigger scan ──────────────────────────────────────────────────────────────
if run_btn:
    st.session_state.scan_log    = []
    st.session_state.scan_region = config.REGION
    t0 = time.time()

    with st.status("Running Parcel Scout scan…", expanded=True) as scan_status:
        log_placeholder = st.empty()

        import builtins
        original_print = builtins.print

        def ui_print(*args, **kwargs):
            msg = " ".join(str(a) for a in args)
            st.session_state.scan_log.append(msg)
            log_placeholder.markdown(
                "\n".join(f"› {line}" for line in st.session_state.scan_log[-8:])
            )
            original_print(*args, **kwargs)

        builtins.print = ui_print
        try:
            parcels = run_full_scan(filter_state, g2_state, layer_state)
        finally:
            builtins.print = original_print

        elapsed = time.time() - t0
        st.session_state.parcels      = parcels
        st.session_state.scan_time    = datetime.now()
        st.session_state.scan_elapsed = elapsed

        total_raw = st.session_state.get("total_raw", 0)
        if parcels:
            scan_status.update(
                label=(
                    f"Scan complete — scanned {total_raw:,} parcels in {config.REGION}, "
                    f"found {len(parcels)} matching your filters  ({elapsed:.0f}s)"
                ),
                state="complete",
            )
        else:
            scan_status.update(
                label=f"Scan complete — scanned {total_raw:,} parcels, none passed all hard filters",
                state="error",
            )

# ── Display results ───────────────────────────────────────────────────────────
st.markdown("---")

if "parcels" not in st.session_state or not st.session_state.parcels:
    if not st.session_state.get("parcels"):
        st.info(
            "Configure your parameters above and click **Run Off-Market Scan** to begin.  \n"
            "The scan queries OpenStreetMap and takes approximately 3–4 minutes for a full province."
        )
    else:
        st.warning("No parcels passed all hard filters. Try relaxing some filters above.")
else:
    # Determine active signal keys from current toggle state
    active_keys = [
        sm["key"]
        for sm in SIGNAL_META
        if (
            (sm["group"] == "group2" and g2_state.get(sm["config"][1], True))
            or (sm["group"] == "layer"  and layer_state.get(sm["config"][1], True))
        )
    ]

    # Re-score instantly from cached signals — no re-scan
    parcels = rescore(st.session_state.parcels, active_keys)

    # ── Summary metrics ───────────────────────────────────────────────────────
    scores    = [p["opportunity_score"] for p in parcels]
    total_raw = st.session_state.get("total_raw", 0)
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Parcels Matched",  len(parcels), help=f"{total_raw:,} total parcels scanned")
    m2.metric("Top Score",        f"{max(scores):.1f}/100")
    m3.metric("Average Score",    f"{sum(scores)/len(scores):.1f}/100")
    m4.metric("Signals Active",   f"{len(active_keys)}/13")
    if total_raw:
        st.caption(
            f"Scanned **{total_raw:,}** total parcels in {st.session_state.get('scan_region', config.REGION)}"
            f" — **{len(parcels)}** matched all required filters."
        )

    # ── API credit usage (shown only when at least one paid API was called) ───
    api_usage = st.session_state.get("api_usage", {})
    if api_usage:
        _monthly_limits = {
            "TripAdvisor":   ("5,000",  "month"),
            "Wine-Searcher": ("100",    "day"),
            "OpenAPI.it":    ("varies", "month"),
        }
        usage_parts = []
        for service, calls in api_usage.items():
            limit, period = _monthly_limits.get(service, ("?", ""))
            usage_parts.append(f"**{service}**: {calls} call{'s' if calls != 1 else ''} (free limit: {limit}/{period})")
        st.caption("API credits used this scan — " + "  ·  ".join(usage_parts))

    st.markdown("---")

    # ── Export buttons ────────────────────────────────────────────────────────
    df_full   = build_rankings_df(parcels)
    csv_data  = df_full.to_csv(index=False).encode("utf-8")
    json_data = json.dumps(parcels, indent=2, default=str).encode("utf-8")
    ts        = datetime.now().strftime("%Y%m%d_%H%M")

    ec1, ec2, _ = st.columns([1, 1, 4])
    ec1.download_button(
        "Export CSV",
        csv_data,
        file_name=f"parcel_scout_{ts}.csv",
        mime="text/csv",
    )
    ec2.download_button(
        "Export JSON",
        json_data,
        file_name=f"parcel_scout_{ts}.json",
        mime="application/json",
    )

    st.markdown("---")

    # ── Tabs ──────────────────────────────────────────────────────────────────
    tab_rank, tab_map, tab_raw = st.tabs(["Rankings", "Map", "Raw Data"])

    # ── Property Cards ────────────────────────────────────────────────────────
    with tab_rank:
        active_dossier = st.session_state.get("active_dossier", None)
        card_cols = st.columns(3)

        for idx, p in enumerate(parcels):
            col       = card_cols[idx % 3]
            score     = p["opportunity_score"]
            name      = (p.get("name") or "").strip() or f"{p.get('primary_crop_type','').replace('_',' ').title()} Parcel" or f"Parcel #{idx+1}"
            lat       = p.get("lat", 43.45)
            lon       = p.get("lon", 11.48)
            fired     = signals_fired_list(p)
            acres     = int(round(p.get("parcel_acres", 0)))
            airport   = f"{int(round(p.get('dist_airport_km', 0)))} km · {p.get('airport_iata', '')}"
            crop      = p.get("primary_crop_type", "").replace("_", " ").title() or "—"
            heritage  = p.get("closest_historic_tag", "").title() or "—"
            score_clr = "#4A6741" if score >= 30 else "#8B6914" if score >= 15 else "#7A6A55"
            is_open   = (active_dossier == idx)

            with col:
                # ── Map thumbnail ──────────────────────────────────────────
                map_url = f"https://staticmap.openstreetmap.de/staticmap.php?center={lat},{lon}&zoom=14&size=400x220"
                st.markdown(
                    f'<div style="width:100%;height:155px;overflow:hidden;background:#D4C4A0;margin-bottom:0;">'
                    f'<img src="{map_url}" style="width:100%;height:155px;object-fit:cover;display:block;" /></div>',
                    unsafe_allow_html=True,
                )

                # ── Score + title ──────────────────────────────────────────
                st.markdown(
                    f'<div style="padding:0.75rem 0 0.5rem;border-bottom:1px solid #EDE6D8;">'
                    f'<div style="font-family:Montserrat,sans-serif;font-size:0.56rem;font-weight:700;'
                    f'letter-spacing:0.18em;text-transform:uppercase;color:{score_clr};margin-bottom:0.2rem;">'
                    f'Score {score:.1f} / 100</div>'
                    f'<div style="font-family:\'Cormorant Garamond\',serif;font-weight:400;font-size:1.35rem;'
                    f'color:#2A2118;line-height:1.25;">{name[:55]}</div>'
                    f'</div>',
                    unsafe_allow_html=True,
                )

                # ── Key Intel ──────────────────────────────────────────────
                st.markdown(
                    f'<div style="padding:0.6rem 0;border-bottom:1px solid #EDE6D8;">'
                    f'<div style="font-family:Montserrat,sans-serif;font-size:0.52rem;font-weight:700;'
                    f'letter-spacing:0.2em;text-transform:uppercase;color:#8B6914;margin-bottom:0.4rem;">Key Intel</div>'
                    f'<table style="width:100%;border-collapse:collapse;font-family:Montserrat,sans-serif;font-size:0.72rem;color:#3A2E22;">'
                    f'<tr><td style="padding:2px 0;width:1.2rem;">⬜</td><td style="padding:2px 4px;color:#7A6A55;">Footprint</td><td style="padding:2px 0;text-align:right;font-weight:500;">{acres} acres</td></tr>'
                    f'<tr><td style="padding:2px 0;">🌿</td><td style="padding:2px 4px;color:#7A6A55;">Soil / Use</td><td style="padding:2px 0;text-align:right;font-weight:500;">{crop}</td></tr>'
                    f'<tr><td style="padding:2px 0;">✈</td><td style="padding:2px 4px;color:#7A6A55;">Airport</td><td style="padding:2px 0;text-align:right;font-weight:500;">{airport}</td></tr>'
                    f'<tr><td style="padding:2px 0;">🏛</td><td style="padding:2px 4px;color:#7A6A55;">Heritage</td><td style="padding:2px 0;text-align:right;font-weight:500;">{heritage}</td></tr>'
                    f'</table></div>',
                    unsafe_allow_html=True,
                )

                # ── Signal chips ───────────────────────────────────────────
                if fired:
                    chips = "".join(
                        f'<span style="display:inline-block;background:#E8F5E9;color:#2A4028;'
                        f'border:1px solid #4A6741;font-family:Montserrat,sans-serif;'
                        f'font-size:0.58rem;padding:2px 6px;margin:2px 2px 0 0;">✓ {sig}</span>'
                        for sig in fired
                    )
                    st.markdown(f'<div style="padding:0.5rem 0 0.6rem;">{chips}</div>', unsafe_allow_html=True)
                else:
                    st.markdown(
                        '<div style="padding:0.5rem 0 0.6rem;font-family:Montserrat,sans-serif;'
                        'font-size:0.7rem;color:#7A6A55;font-style:italic;">No signals fired</div>',
                        unsafe_allow_html=True,
                    )

                # ── Dossier button ─────────────────────────────────────────
                btn_label = "Close Dossier  ✕" if is_open else "View Intelligence Dossier"
                if st.button(btn_label, key=f"dossier_btn_{idx}", use_container_width=True):
                    st.session_state.active_dossier = None if is_open else idx
                    st.rerun()

        # ── Full-width Intelligence Dossier panel ─────────────────────────────
        if active_dossier is not None and active_dossier < len(parcels):
            p     = parcels[active_dossier]
            score = p["opportunity_score"]
            name  = (p.get("name") or p.get("gps_coordinates", f"Parcel #{active_dossier+1}"))
            fired = signals_fired_list(p)
            score_clr = "#4A6741" if score >= 30 else "#8B6914" if score >= 15 else "#7A6A55"

            st.markdown("---")
            st.markdown(
                f'<div style="margin-bottom:1.2rem;">'
                f'<div style="font-family:Montserrat,sans-serif;font-size:0.56rem;font-weight:700;'
                f'letter-spacing:0.2em;text-transform:uppercase;color:#8B6914;">Intelligence Dossier</div>'
                f'<div style="font-family:\'Cormorant Garamond\',serif;font-size:2.4rem;font-weight:300;'
                f'color:#2A2118;line-height:1.1;margin-top:0.15rem;">{name}</div>'
                f'<div style="font-family:Montserrat,sans-serif;font-size:0.68rem;color:{score_clr};'
                f'font-weight:600;margin-top:0.25rem;letter-spacing:0.05em;">'
                f'Opportunity Score: {score:.1f} / 100</div></div>',
                unsafe_allow_html=True,
            )

            dc1, dc2, dc3 = st.columns(3)
            dc1.metric("Opportunity Score", f"{score:.1f}/100",
                help="0–100 score: each of the 13 signals is worth ~7.7 pts.")
            dc1.metric("Crop Type", p.get("primary_crop_type", "").title(),
                help="Primary land-use type from OpenStreetMap tags.")
            dc2.metric("Parcel Size", f"{p.get('parcel_acres',0):.0f} acres",
                help="Parcel area calculated from the OSM polygon geometry.")
            dc2.metric("Airport", f"{p.get('dist_airport_km',0):.0f} km ({p.get('airport_iata','')})",
                help="Straight-line distance to nearest target airport (PSA or FLR).")
            dc3.metric("Heritage", p.get("closest_historic_tag", "").title() or "N/A",
                help="Historic structure type physically inside the parcel boundary.")
            dc3.metric("Confidence", p.get("heritage_confidence", "").title() or "N/A",
                help="High = named type · Medium = type uncertain · Low = 'historic=yes' only")

            st.markdown("**Signals fired:**")
            if fired:
                sig_cols = st.columns(min(len(fired), 4))
                for i, sig in enumerate(fired):
                    sig_cols[i % 4].success(f"✓ {sig}")
            else:
                st.caption("No signals fired for this parcel.")

            unfired = [sm["label"] for sm in SIGNAL_META if sm["key"] in active_keys and not p.get(sm["key"])]
            if unfired:
                st.markdown("**Not triggered:**")
                st.caption("  ·  ".join(unfired))

            st.markdown(
                f"**[View on OpenStreetMap ↗]({p.get('osm_url','')})**  ·  GPS: `{p.get('gps_coordinates','')}`"
            )

            with st.expander("Full signal details"):
                detail_rows = []
                for sm in SIGNAL_META:
                    if sm["key"] not in active_keys:
                        continue
                    detail_key = sm["key"].replace("_signal", "_detail")
                    detail_rows.append({
                        "Signal": sm["label"],
                        "Fired":  "✓" if p.get(sm["key"]) else "—",
                        "Detail": str(p.get(detail_key, "")),
                    })
                st.dataframe(pd.DataFrame(detail_rows), use_container_width=True, hide_index=True)

    # ── Map ───────────────────────────────────────────────────────────────────
    with tab_map:
        st.caption(
            "Pins sized and coloured by Opportunity Score.  "
            "Olive ≥ 30  ·  Gold 15–29  ·  Grey < 15.  Click any pin for details."
        )
        m = build_map(parcels)
        st_folium(m, use_container_width=True, height=560)

    # ── Raw Data ──────────────────────────────────────────────────────────────
    with tab_raw:
        st.caption("Complete field dump for all parcels, sorted by Opportunity Score.")
        all_keys = list(dict.fromkeys(k for p in parcels for k in p.keys()))
        # Convert every value to string — parcel dicts contain mixed types
        # (None, lists, dicts from layer data) that pyarrow can't serialize.
        df_raw = pd.DataFrame([
            {k: str(p.get(k, "")) if p.get(k) is not None else "" for k in all_keys}
            for p in parcels
        ])
        st.dataframe(df_raw, use_container_width=True, height=500)

# ── Footer ────────────────────────────────────────────────────────────────────
st.markdown("---")
st.markdown(
    '<p style="font-family:\'Cormorant Garamond\',serif;font-size:0.9rem;'
    'color:#7A6A55;text-align:center;letter-spacing:0.08em;">'
    'Giovanni Bonelli Group &nbsp;·&nbsp; Parcel Scout &nbsp;·&nbsp; Tuscany Acquisition Intelligence'
    '</p>',
    unsafe_allow_html=True,
)
