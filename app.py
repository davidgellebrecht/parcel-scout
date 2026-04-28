#!/usr/bin/env python3
"""
app.py — Parcel Scout Web Portal
Giovanni Bonelli Group edition — no sidebar, province dropdown, luxury aesthetic.

Run locally:   streamlit run app.py
Deploy:        push to GitHub → share.streamlit.io
"""

import io
import json
import re
import time
from datetime import datetime

import folium
import pandas as pd
import streamlit as st
from streamlit_folium import st_folium

try:
    from fpdf import FPDF
    _PDF_AVAILABLE = True
except ImportError:
    _PDF_AVAILABLE = False


import config
import storage

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

# ── Demo mode ─────────────────────────────────────────────────────────────────
# Set to False to hide the demo button entirely.
DEMO_MODE = True

# ── Theme toggle ──────────────────────────────────────────────────────────────
# "dark"    → Stitch-inspired dark charcoal + sage green (current)
# "classic" → original warm cream + gold palette
# To undo the dark theme, change this one line to "classic".
THEME = "dark"

# ── Colour map for Folium (iframe — CSS custom properties don't reach inside) ─
if THEME == "dark":
    CLR_MAP = {
        "score_high":   "#adceb9",   # sage green (score ≥ 30)
        "score_mid":    "#c9b96a",   # warm gold  (score 15–29)
        "score_low":    "#6e6e6e",   # grey        (score < 15)
        "popup_bg":     "#1e2838",
        "popup_border": "#2d3d52",
        "popup_text":   "#c8c3bc",
        "popup_muted":  "#6e7a8a",
        "chip_bg":      "#1a3320",
        "chip_text":    "#7ecf9a",
        "chip_border":  "#2d6044",
    }
else:
    CLR_MAP = {
        "score_high":   "#4A6741",
        "score_mid":    "#8B6914",
        "score_low":    "#7A6A55",
        "popup_bg":     "#F4EFE6",
        "popup_border": "#D4C4A0",
        "popup_text":   "#2A2118",
        "popup_muted":  "#7A6A55",
        "chip_bg":      "#E8F5E9",
        "chip_text":    "#2A4028",
        "chip_border":  "#4A6741",
    }

# ── Material Symbols icon map (one per signal key) ────────────────────────────
SIGNAL_ICON_MAP = {
    "g2_premium_wine_zone":              "wine_bar",
    "g2_distress_signal":                "warning",
    "g2_succession_signal":              "family_history",
    "g2_lodging_overlay":                "hotel",
    "layer_satellite_neglect_signal":    "satellite_alt",
    "layer_permit_paralysis_signal":     "gavel",
    "layer_zoning_alchemy_signal":       "layers",
    "layer_napa_neighbor_signal":        "emoji_events",
    "layer_hospitality_fatigue_signal":  "sentiment_dissatisfied",
    "layer_digital_ghost_signal":        "visibility_off",
    "layer_succession_stress_signal":    "person_off",
    "layer_terroir_score_delta_signal":  "diamond",
    "layer_succession_frag_signal":      "account_tree",
    "layer_owner_relocation_signal":     "near_me",
    "layer_elevation_aspect_signal":     "terrain",
    "layer_road_access_signal":          "add_road",
    "layer_water_access_signal":         "water_drop",
    "layer_listing_check_signal":        "storefront",
}

# ── Page config ───────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Parcel Scout — Giovanni Bonelli Group",
    page_icon="🏡",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# ── Access-password gate (Fly.io deployment) ──────────────────────────────────
# On Fly, we set PARCEL_SCOUT_ACCESS_PASSWORD as a secret — only users who
# enter it see the app. Locally the env var is unset, so the gate is disabled
# and `streamlit run app.py` just works.
import os as _os
_REQUIRED_PASSWORD = _os.environ.get("PARCEL_SCOUT_ACCESS_PASSWORD", "")
if _REQUIRED_PASSWORD:
    if not st.session_state.get("_auth_ok"):
        st.markdown(
            "<div style='max-width:420px;margin:4rem auto;padding:2rem;"
            "background:#1e2838;border:1px solid #2d3d52;border-radius:4px;"
            "color:#c8c3bc;font-family:Manrope,system-ui,sans-serif;'>"
            "<h3 style='font-family:Noto Serif,Georgia,serif;margin-top:0;'>"
            "Parcel Scout</h3>"
            "<p style='color:#a8a49f;font-size:0.85rem;'>"
            "Giovanni Bonelli Group · Private access</p>",
            unsafe_allow_html=True,
        )
        _pw = st.text_input("Access password", type="password", key="_auth_pw_input")
        if st.button("Sign in", key="_auth_submit_btn", type="primary"):
            if _pw == _REQUIRED_PASSWORD:
                st.session_state["_auth_ok"] = True
                st.rerun()
            else:
                st.error("Incorrect password.")
        st.markdown("</div>", unsafe_allow_html=True)
        st.stop()

# ── Load Streamlit secrets ────────────────────────────────────────────────────
# Two sources, in order:
#   1. st.secrets (Streamlit Cloud + local .streamlit/secrets.toml)
#   2. environment variables (how Fly.io injects `flyctl secrets set` values)
# Env vars win if both are present — lets Fly override anything baked into secrets.toml.
def _resolve_secret(key: str, fallback: str) -> str:
    try:
        val = st.secrets.get(key, "")
    except Exception:
        val = ""
    return _os.environ.get(key, val) or fallback

try:
    config.OPENAPI_IT_KEY              = _resolve_secret("OPENAPI_IT_KEY",             config.OPENAPI_IT_KEY)
    config.SENTINEL_HUB_CLIENT_ID      = _resolve_secret("SENTINEL_HUB_CLIENT_ID",     config.SENTINEL_HUB_CLIENT_ID)
    config.SENTINEL_HUB_CLIENT_SECRET  = _resolve_secret("SENTINEL_HUB_CLIENT_SECRET", config.SENTINEL_HUB_CLIENT_SECRET)
    config.TRIPADVISOR_API_KEY         = _resolve_secret("TRIPADVISOR_API_KEY",        config.TRIPADVISOR_API_KEY)
    config.WINE_SEARCHER_API_KEY       = _resolve_secret("WINE_SEARCHER_API_KEY",      config.WINE_SEARCHER_API_KEY)
except Exception:
    pass

# ── Material Symbols icon font (used in signal chips and cards) ───────────────
st.markdown(
    '<link href="https://fonts.googleapis.com/css2?family=Material+Symbols+Outlined'
    ':wght,FILL@100..700,0..1&display=swap" rel="stylesheet"/>',
    unsafe_allow_html=True,
)

# ── Parcel Scout CSS — themed via CSS custom properties ───────────────────────
_CSS_ROOT_DARK = """
:root {
    --bg:             #1e2838;
    --surface:        #243047;
    --surface-high:   #2d3a52;
    --surface-low:    #192030;
    --surface-card:   #141c2b;
    --text:           #c8c3bc;
    --text-mid:       #a8a49f;
    --text-muted:     #6e7a8a;
    --accent:         #adceb9;
    --accent-text:    #183627;
    --accent-dim:     rgba(173,206,185,0.12);
    --border:         #2d3d52;
    --border-light:   rgba(255,255,255,0.06);
    --success-bg:     #1a3320;
    --success-text:   #7ecf9a;
    --success-border: #2d6044;
    --warn-bg:        #2a1f00;
    --warn-text:      #ffd280;
    --warn-border:    #7a5500;
    --score-high:     #adceb9;
    --score-mid:      #c9b96a;
    --score-low:      #6e6e6e;
    --serif:          'Noto Serif', Georgia, serif;
    --sans:           'Manrope', system-ui, sans-serif;
}
"""
_CSS_ROOT_CLASSIC = """
:root {
    --bg:             #F4EFE6;
    --surface:        #FAF6EF;
    --surface-high:   #FFFFFF;
    --surface-low:    #F0EBE0;
    --surface-card:   #E8E0CE;
    --text:           #2A2118;
    --text-mid:       #3A2E22;
    --text-muted:     #7A6A55;
    --accent:         #8B6914;
    --accent-text:    #F4EFE6;
    --accent-dim:     rgba(139,105,20,0.08);
    --border:         #D4C4A0;
    --border-light:   rgba(0,0,0,0.06);
    --success-bg:     #E8F5E9;
    --success-text:   #2A4028;
    --success-border: #4A6741;
    --warn-bg:        #FFF9E6;
    --warn-text:      #1A1200;
    --warn-border:    #C8860A;
    --score-high:     #4A6741;
    --score-mid:      #8B6914;
    --score-low:      #7A6A55;
    --serif:          'Cormorant Garamond', Georgia, serif;
    --sans:           'Montserrat', system-ui, sans-serif;
}
"""

_CSS_ROOT = _CSS_ROOT_DARK if THEME == "dark" else _CSS_ROOT_CLASSIC

st.markdown(f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=Noto+Serif:ital,wght@0,400;0,700;1,400&family=Manrope:wght@300;400;500;600;700;800&family=Cormorant+Garamond:ital,wght@0,300;0,400;0,600;1,300;1,400&family=Montserrat:wght@300;400;500;600&display=swap');
{_CSS_ROOT}

/* ── Hide Streamlit chrome ── */
#MainMenu, footer, header            {{ visibility: hidden; }}
.stDeployButton                      {{ display: none !important; }}
section[data-testid="stSidebar"]     {{ display: none !important; }}
[data-testid="collapsedControl"]     {{ display: none !important; }}

/* ── Page background ── */
.stApp {{
    background-color: var(--bg);
}}
.main .block-container {{
    padding: 3rem 5rem 4rem 5rem;
    max-width: 1100px;
    margin: 0 auto;
}}

/* ── Global typography ── */
html, body, [class*="css"] {{
    font-family: var(--sans);
    color: var(--text);
}}

/* ── Headings ── */
h1 {{
    font-family: var(--serif) !important;
    font-weight: 300 !important;
    font-size: 3.2rem !important;
    letter-spacing: 0.06em !important;
    color: var(--text) !important;
    line-height: 1.1 !important;
    margin-bottom: 0.2rem !important;
}}
h2, h3 {{
    font-family: var(--serif) !important;
    font-weight: 400 !important;
    color: var(--text) !important;
    letter-spacing: 0.04em !important;
}}

/* ── Section labels ── */
.gb-label {{
    font-family: var(--serif);
    font-size: 1.1rem;
    font-weight: 400;
    font-style: italic;
    letter-spacing: 0.03em;
    color: var(--accent);
    margin-bottom: 0.15rem;
    margin-top: 0.2rem;
    display: block;
    border-bottom: 1px solid var(--border);
    padding-bottom: 0.3rem;
}}

/* ── Divider ── */
hr {{
    border: none !important;
    border-top: 1px solid var(--border) !important;
    margin: 2rem 0 !important;
}}

/* ── Selectbox ── */
.stSelectbox > div > div {{
    background-color: var(--surface-high) !important;
    border: 1px solid var(--border) !important;
    border-radius: 0 !important;
    font-family: var(--sans) !important;
    font-size: 0.85rem !important;
    color: var(--text) !important;
}}

/* ── Checkboxes ── */
.stCheckbox > label,
.stCheckbox > label > div,
.stCheckbox > label > span,
.stCheckbox span[data-testid="stMarkdownContainer"] p {{
    font-family: var(--sans) !important;
    font-size: 0.82rem !important;
    font-weight: 500 !important;
    color: var(--text) !important;
    letter-spacing: 0.02em !important;
    opacity: 1 !important;
}}

/* ── Captions ── */
.stCaption,
[data-testid="stCaptionContainer"] p,
[data-testid="stCaptionContainer"] {{
    font-family: var(--sans) !important;
    font-size: 0.72rem !important;
    color: var(--text-mid) !important;
    line-height: 1.55 !important;
    opacity: 1 !important;
}}

/* ── Expander header (Setup & pricing, Premium Reference, etc.) ── */
[data-testid="stExpander"] summary p {{
    font-family: var(--sans) !important;
    font-size: 0.78rem !important;
    font-weight: 500 !important;
    color: var(--text) !important;
    line-height: 1.4 !important;
    opacity: 1 !important;
}}
/* Tint the SVG chevron to accent colour */
[data-testid="stExpander"] summary svg {{
    color: var(--accent) !important;
    fill: var(--accent) !important;
}}

/* ── All expander summaries — clearly styled as clickable ── */
[data-testid="stExpander"] summary {{
    padding: 0.55rem 0.9rem !important;
    border: 1px solid var(--border) !important;
    border-radius: 2px !important;
    background: var(--surface-high) !important;
    cursor: pointer !important;
    transition: background 0.15s, border-color 0.15s !important;
    margin-top: 0.4rem !important;
}}
[data-testid="stExpander"] summary:hover {{
    background: var(--accent-dim) !important;
    border-color: var(--accent) !important;
}}
[data-testid="stExpander"] summary p {{
    color: var(--accent) !important;
    font-weight: 600 !important;
    letter-spacing: 0.06em !important;
}}

/* ── Expander body (open state) ── */
[data-testid="stExpander"] details > div,
[data-testid="stExpander"] .streamlit-expanderContent {{
    background-color: var(--surface) !important;
    border: 1px solid var(--border) !important;
    padding: 1rem !important;
}}
/* Expander body text */
[data-testid="stExpander"] details > div p,
[data-testid="stExpander"] details > div span,
[data-testid="stExpander"] details > div li,
[data-testid="stExpander"] details > div strong,
[data-testid="stExpander"] details > div a,
[data-testid="stExpander"] .streamlit-expanderContent p,
[data-testid="stExpander"] .streamlit-expanderContent span,
[data-testid="stExpander"] .streamlit-expanderContent strong {{
    color: var(--text) !important;
    font-family: var(--sans) !important;
    font-size: 0.78rem !important;
    opacity: 1 !important;
}}

/* ── Primary button (Run Scan) ── */
.stButton > button[kind="primary"] {{
    width: 100% !important;
    background-color: var(--accent) !important;
    color: var(--accent-text) !important;
    font-family: var(--sans) !important;
    font-size: 0.68rem !important;
    font-weight: 700 !important;
    letter-spacing: 0.22em !important;
    text-transform: uppercase !important;
    border: none !important;
    border-radius: 0 !important;
    padding: 1rem 2rem !important;
    margin-top: 0.5rem !important;
    transition: filter 0.2s !important;
}}
.stButton > button[kind="primary"]:hover {{
    filter: brightness(1.15) !important;
}}

/* ── Dossier / secondary buttons ── */
.stButton > button[kind="secondary"] {{
    background-color: var(--surface-low) !important;
    color: var(--text) !important;
    border: 1px solid var(--accent) !important;
    border-radius: 0 !important;
    font-family: var(--sans) !important;
    font-size: 0.65rem !important;
    font-weight: 600 !important;
    letter-spacing: 0.18em !important;
    text-transform: uppercase !important;
    padding: 0.7rem 1rem !important;
}}
.stButton > button[kind="secondary"]:hover {{
    background-color: var(--accent) !important;
    color: var(--accent-text) !important;
    border-color: var(--accent) !important;
}}

/* ── Secondary / download buttons ── */
.stDownloadButton > button {{
    background-color: transparent !important;
    color: var(--text) !important;
    border: 1px solid var(--border) !important;
    border-radius: 0 !important;
    font-family: var(--sans) !important;
    font-size: 0.65rem !important;
    letter-spacing: 0.12em !important;
    text-transform: uppercase !important;
}}
.stDownloadButton > button:hover {{
    border-color: var(--accent) !important;
    background-color: var(--accent) !important;
    color: var(--accent-text) !important;
}}

/* ── Metrics — hardcoded hex avoids CSS-var resolution issues ── */
[data-testid="metric-container"] {{
    background: var(--surface);
    border: 1px solid var(--border);
    padding: 1.1rem 1.3rem;
}}
/* Labels — every selector Streamlit might use */
[data-testid="stMetricLabel"],
[data-testid="stMetricLabel"] *,
[data-testid="stMetricLabel"] p,
[data-testid="stMetricLabel"] label,
[data-testid="stMetricLabel"] div {{
    font-family: var(--sans) !important;
    font-size: 0.58rem !important;
    letter-spacing: 0.18em !important;
    text-transform: uppercase !important;
    color: {CLR_MAP["popup_muted"]} !important;
    opacity: 1 !important;
}}
/* Values */
[data-testid="stMetricValue"],
[data-testid="stMetricValue"] *,
[data-testid="stMetricValue"] > div,
[data-testid="stMetricValue"] p {{
    font-family: var(--serif) !important;
    font-size: 2rem !important;
    font-weight: 400 !important;
    color: {CLR_MAP["popup_text"]} !important;
    opacity: 1 !important;
}}

/* ── Tabs ── */
.stTabs [data-baseweb="tab-list"] {{
    gap: 0;
    border-bottom: 1px solid var(--border);
    background: transparent;
}}
.stTabs [data-baseweb="tab"] {{
    font-family: var(--sans) !important;
    font-size: 0.62rem !important;
    font-weight: 500 !important;
    letter-spacing: 0.16em !important;
    text-transform: uppercase !important;
    padding: 0.8rem 1.6rem !important;
    background: transparent !important;
    border: none !important;
    color: var(--accent) !important;
}}
.stTabs [aria-selected="true"] {{
    background: transparent !important;
    border-bottom: 2px solid var(--text) !important;
    color: var(--text) !important;
}}

/* ── Info / status box ── */
.stInfo {{
    background-color: var(--surface-low) !important;
    border: 1px solid var(--border) !important;
    border-radius: 0 !important;
    font-family: var(--sans) !important;
    font-size: 0.8rem !important;
    color: var(--text) !important;
}}

/* ── Success boxes (Signals fired) ── */
[data-testid="stAlert"][data-baseweb="notification"]:has(svg[data-testid="stAlertDynamicIcon-success"]),
.stSuccess, [data-testid="stAlert"].stSuccess {{
    background-color: var(--success-bg) !important;
    border: 1.5px solid var(--success-border) !important;
    border-radius: 0 !important;
    opacity: 1 !important;
}}
.stSuccess p, .stSuccess div, .stSuccess span {{
    color: var(--success-text) !important;
    font-family: var(--sans) !important;
    font-weight: 600 !important;
    font-size: 0.75rem !important;
    opacity: 1 !important;
}}

/* ── Warning box ── */
.stWarning, [data-testid="stAlert"].stWarning,
[data-testid="stAlert"]:has([data-testid="stAlertDynamicIcon-warning"]) {{
    background-color: var(--warn-bg) !important;
    border: 1px solid var(--warn-border) !important;
    border-radius: 0 !important;
    opacity: 1 !important;
}}
.stWarning p, .stWarning li, .stWarning strong,
.stWarning span, .stWarning code, .stWarning div {{
    color: var(--warn-text) !important;
    font-family: var(--sans) !important;
    font-size: 0.78rem !important;
    opacity: 1 !important;
}}

/* ── Material Symbols glyphs (in Streamlit alert boxes) ── */
.material-symbols-outlined {{
    font-family: 'Material Symbols Outlined' !important;
    font-variation-settings: 'FILL' 0, 'wght' 300, 'GRAD' 0, 'opsz' 24;
    vertical-align: middle;
    line-height: 1;
}}

/* ── Demo button (red, only in the column that has .demo-marker) ── */
[data-testid="column"]:has(.demo-marker) button {{
    background-color: #B71C1C !important;
    color: #FFFFFF !important;
    font-family: var(--sans) !important;
    font-size: 0.62rem !important;
    font-weight: 700 !important;
    letter-spacing: 0.14em !important;
    text-transform: uppercase !important;
    border: none !important;
    border-radius: 0 !important;
    width: 100% !important;
    padding: 0.9rem 1rem !important;
    animation: demo-pulse 2.5s ease-in-out infinite;
}}
[data-testid="column"]:has(.demo-marker) button:hover {{
    background-color: #7F0000 !important;
}}
@keyframes demo-pulse {{
    0%, 100% {{ box-shadow: 0 0 0 0 rgba(183,28,28,0.5); }}
    50%       {{ box-shadow: 0 0 0 6px rgba(183,28,28,0); }}
}}

/* ── Hero image strip ── */
[data-testid="stImage"] img {{
    object-fit: cover;
    height: 200px;
    width: 100%;
    display: block;
}}
[data-testid="stImage"] {{
    padding: 0 !important;
    margin: 0 !important;
}}

/* ── Dataframe ── */
.stDataFrame {{ border: 1px solid var(--border) !important; }}

/* ── Status widget (scan progress) ── */
/* NOTE: do NOT include stExpander here — expanders have their own rules above */
[data-testid="stStatusWidget"],
[data-testid="stStatusContainer"],
div[class*="StatusWidget"],
div[class*="stStatus"] {{
    background: var(--surface-low) !important;
    border: 1px solid var(--border) !important;
}}
[data-testid="stStatusWidget"] *,
[data-testid="stStatusContainer"] * {{
    color: var(--text) !important;
    font-family: var(--sans) !important;
    font-size: 0.78rem !important;
    opacity: 1 !important;
}}
/* Expanded body / log area */
[data-testid="stStatusWidget"] > div:last-child,
[data-testid="stStatusContainer"] > div:last-child {{
    background-color: var(--surface) !important;
    border-top: 1px solid var(--border) !important;
    padding: 0.8rem 1rem !important;
}}
</style>
""", unsafe_allow_html=True)

# ── Tuscany provinces ─────────────────────────────────────────────────────────
# Bounding box format: (south_lat, west_lon, north_lat, east_lon)
TUSCANY_PROVINCES = {
    "Chianti Classico, Siena (DEMO)": (43.28, 11.27, 43.52, 11.68),
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
        "proxy":  False,
        "proxy_upgrade": "",
        "desc":   "Parcel falls within a premium Italian wine appellation where bottles regularly trade above $150.",
    },
    {
        "key":    "g2_distress_signal",
        "label":  "Distress Signal",
        "group":  "group2",
        "config": ("GROUP2", "distress_signal"),
        "paid":   False,
        "badge":  "",
        "proxy":  False,
        "proxy_upgrade": "",
        "desc":   "Fire history (EU EFFIS satellite data) or abandoned land nearby — a neglect and financial stress proxy.",
    },
    {
        "key":    "g2_succession_signal",
        "label":  "Succession Signal",
        "group":  "group2",
        "config": ("GROUP2", "succession_signal"),
        "paid":   False,
        "badge":  "",
        "proxy":  False,
        "proxy_upgrade": "",
        "desc":   "Italian family estate naming (Podere, Fattoria, Tenuta…) on or near the parcel suggests generational ownership nearing transition.",
    },
    {
        "key":    "g2_lodging_overlay",
        "label":  "Lodging Overlay",
        "group":  "group2",
        "config": ("GROUP2", "lodging_overlay"),
        "paid":   False,
        "badge":  "",
        "proxy":  False,
        "proxy_upgrade": "",
        "desc":   "Existing tourism or hospitality operation nearby signals local planning precedent for agriturismo conversion under Italian Law 96/2006.",
    },
    {
        "key":    "layer_satellite_neglect_signal",
        "label":  "Satellite Neglect",
        "group":  "layer",
        "config": ("LAYERS", "satellite_neglect"),
        "paid":   True,
        "badge":  "paid",
        "proxy":  False,
        "proxy_upgrade": "",
        "desc":   "NDVI satellite data shows vegetation vigor below neighboring parcels — the first measurable sign of absentee ownership.",
    },
    {
        "key":    "layer_permit_paralysis_signal",
        "label":  "Permit Paralysis",
        "group":  "layer",
        "config": ("LAYERS", "permit_paralysis"),
        "paid":   True,
        "badge":  "paid",
        "proxy":  True,
        "proxy_upgrade": "Albo Pretorio permit records (set ALBO_PRETORIO_API_KEY) — shows actual filed applications and approval status per parcel",
        "desc":   "Owner has filed multiple renovation permits over years with no final approval — frustration that often precedes a willingness to sell.",
    },
    {
        "key":    "layer_zoning_alchemy_signal",
        "label":  "Zoning Alchemy",
        "group":  "layer",
        "config": ("LAYERS", "zoning_alchemy"),
        "paid":   True,
        "badge":  "paid + free",
        "proxy":  False,
        "proxy_upgrade": "",
        "desc":   "Parcel is in agricultural Zone E (agriturismo-eligible) and/or shows permit filings using rural conversion keywords.",
    },
    {
        "key":    "layer_napa_neighbor_signal",
        "label":  "Napa Neighbor",
        "group":  "layer",
        "config": ("LAYERS", "napa_neighbor"),
        "paid":   False,
        "badge":  "free",
        "proxy":  False,
        "proxy_upgrade": "",
        "desc":   "Within 8 km of a marquee acquisition (Antinori, LVMH, Frescobaldi) — land values in these ripple zones typically lag the anchor by 2–4 years.",
    },
    {
        "key":    "layer_hospitality_fatigue_signal",
        "label":  "Hospitality Fatigue",
        "group":  "layer",
        "config": ("LAYERS", "hospitality_fatigue"),
        "paid":   True,
        "badge":  "paid",
        "proxy":  False,
        "proxy_upgrade": "",
        "desc":   "Nearby agriturismo or hotel shows declining TripAdvisor scores and review cadence — a leading indicator of owner burnout.",
    },
    {
        "key":    "layer_digital_ghost_signal",
        "label":  "Digital Ghost",
        "group":  "layer",
        "config": ("LAYERS", "digital_ghost"),
        "paid":   False,
        "badge":  "free",
        "proxy":  False,
        "proxy_upgrade": "",
        "desc":   "Estate website has gone stale or domain is near expiry — the digital equivalent of taking down the 'Open' sign.",
    },
    {
        "key":    "layer_succession_stress_signal",
        "label":  "Succession Stress",
        "group":  "layer",
        "config": ("LAYERS", "succession_stress"),
        "paid":   False,
        "badge":  "free",
        "proxy":  False,
        "proxy_upgrade": "",
        "desc":   "Combines website staleness (Wayback Machine) with Italian company registry data (OpenCorporates) to flag estates under ownership pressure — aging companies, dissolved entities, or fragmented directorships signal a motivated seller.",
    },
    {
        "key":    "layer_terroir_score_delta_signal",
        "label":  "Terroir Delta",
        "group":  "layer",
        "config": ("LAYERS", "terroir_score_delta"),
        "paid":   True,
        "badge":  "paid",
        "proxy":  False,
        "proxy_upgrade": "",
        "desc":   "Soil quality (DOCG zone, galestro geology) outperforms the current producer's critic scores — unlocked value for a new buyer.",
    },
    {
        "key":    "layer_succession_frag_signal",
        "label":  "Succession Fragmentation",
        "group":  "layer",
        "config": ("LAYERS", "succession_frag"),
        "paid":   True,
        "badge":  "paid",
        "proxy":  False,
        "proxy_upgrade": "",
        "desc":   "Cadastral records show multiple co-owners — Italian inheritance law distributes estates equally, creating motivated-seller pressure.",
    },
    {
        "key":    "layer_owner_relocation_signal",
        "label":  "Owner Relocation",
        "group":  "layer",
        "config": ("LAYERS", "owner_relocation"),
        "paid":   True,
        "badge":  "paid + free",
        "proxy":  True,
        "proxy_upgrade": "OpenAPI.it cadastral contact address (set OPENAPI_IT_KEY) — shows the owner's registered mailing address vs parcel location, replacing the birth-municipality approximation",
        "desc":   "Owner's fiscal address or website language signals they no longer live near the estate — management burden often exceeds lifestyle benefit.",
    },
    # ── New free geo + brand layers ────────────────────────────────────────────
    {
        "key":    "layer_elevation_aspect_signal",
        "label":  "Elevation & Aspect",
        "group":  "layer",
        "config": ("LAYERS", "elevation_aspect"),
        "paid":   False,
        "badge":  "free",
        "proxy":  False,
        "proxy_upgrade": "",
        "desc":   "Parcel sits at ideal Tuscan wine elevation (150–600 m) on a south-facing slope (135–225°) — the geological sweet spot for Sangiovese that commands a premium under skilled management.",
    },
    {
        "key":    "layer_road_access_signal",
        "label":  "Road Access",
        "group":  "layer",
        "config": ("LAYERS", "road_access"),
        "paid":   False,
        "badge":  "free",
        "proxy":  False,
        "proxy_upgrade": "",
        "desc":   "Only track, path, or no mapped road access within 300 m — parcel is likely priced at a discount for infrastructure reasons a motivated buyer can remedy.",
    },
    {
        "key":    "layer_water_access_signal",
        "label":  "Water Access",
        "group":  "layer",
        "config": ("LAYERS", "water_access"),
        "paid":   False,
        "badge":  "free",
        "proxy":  False,
        "proxy_upgrade": "",
        "desc":   "Natural spring, river, stream, or well within 500 m — embedded water rights and irrigation potential that is extremely difficult to acquire after purchase.",
    },
    {
        "key":    "layer_listing_check_signal",
        "label":  "Listed for Sale?",
        "group":  "layer",
        "config": ("LAYERS", "listing_check"),
        "paid":   False,
        "badge":  "free",
        "proxy":  False,
        "proxy_upgrade": "",
        "desc":   "Estate found on Gate-Away.com — owner has publicly listed the property for sale, the strongest possible declaration of seller intent.",
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
        "cost":      "Free 30-day trial (no credit card during trial); paid plans from approx. €25/month after trial",
        "free_tier": "30-day trial — register at sentinel-hub.com, no credit card required until trial ends",
        "setup":     (
            "1. Register at sentinel-hub.com (free, no credit card for trial). "
            "2. After login: User Settings → OAuth clients → Create new client → name it 'Parcel Scout'. "
            "3. Copy the Client ID and Client Secret shown on that page. "
            "4. On Streamlit Cloud: open your app → Settings → Secrets → add both values: "
            "SENTINEL_HUB_CLIENT_ID = \"your-id\" and SENTINEL_HUB_CLIENT_SECRET = \"your-secret\". "
            "5. In config.py: set LAYERS['satellite_neglect'] = True. "
            "What it unlocks: real Sentinel-2 satellite NDVI imagery — parcels whose vegetation is "
            "measurably less healthy than their neighbours are flagged as potentially absentee-managed."
        ),
        "degrades":  False,
    },
    "permit_paralysis": {
        "api":       "Albo Pretorio — Italian municipal permit registry (no unified national API)",
        "cost":      (
            "No free tier. Requires a commercial contract with an Albo Pretorio data aggregator "
            "(e.g. Maggioli or Halley Informatica — the two main vendors of Italian municipal CMS software). "
            "Pricing is negotiated per contract, not published. "
            "The free OSM proxy (building condition / construction tags) runs without any key."
        ),
        "free_tier": None,
        "setup":     (
            "1. Contact Maggioli (maggioli.it) or Halley Informatica (halley.it) for a data access quote. "
            "2. Sign their commercial information agreement. "
            "3. Once you receive your API key, set ALBO_PRETORIO_API_KEY in Streamlit Secrets. "
            "4. In config.py: LAYERS['permit_paralysis'] is already True — the OSM proxy runs now; "
            "the paid layer activates automatically once the key is present. "
            "Note: each Italian Comune runs its own portal — the aggregator normalises them all."
        ),
        "degrades":  True,
    },
    "zoning_alchemy": {
        "api":       "Albo Pretorio (permit keyword search) + Regione Toscana GEOscopio WFS (Zone E — always free)",
        "cost":      (
            "Zone E boundary check: always free (Regione Toscana public WFS). "
            "Permit keyword component: same commercial Albo Pretorio contract as Permit Paralysis — "
            "no additional cost if you already have that contract."
        ),
        "free_tier": "Zone E agricultural zoning check runs without any credentials",
        "setup":     (
            "Zone E (free) is already active — no setup needed. "
            "For permit keyword search: obtain the Albo Pretorio contract (see Permit Paralysis setup above), "
            "then set ALBO_PRETORIO_API_KEY in Streamlit Secrets. "
            "The layer automatically upgrades from Zone E only to Zone E + permit keywords once the key is present."
        ),
        "degrades":  True,
    },
    "hospitality_fatigue": {
        "api":       "TripAdvisor Content API — tripadvisor.com/developers",
        "cost":      (
            "First 5,000 requests/month: $0.00. "
            "Beyond that: $0.01 per request (5,001–20,000), then $0.0093 (20,001–100,000). "
            "A typical Parcel Scout scan uses ~60 calls for 20 parcels — well inside the free tier. "
            "You would need to run 80+ full scans per month before any charge appears. "
            "⚠️ Requires a credit card on file even for the free tier — TripAdvisor holds it as a payment "
            "method but does not charge it within 5,000 calls/month."
        ),
        "free_tier": "5,000 calls/month free — credit card required on file but not charged within free tier",
        "setup":     (
            "1. Go to tripadvisor.com/developers and sign in with a TripAdvisor account. "
            "2. Click 'Pay as you grow' → enter billing info (card held on file, not charged). "
            "3. Click 'Confirm order' ($0.00 due today). "
            "4. From your dashboard ('My API' tab), copy your API key. "
            "5. On Streamlit Cloud: open your app → Settings → Secrets → add: TRIPADVISOR_API_KEY = \"your-key\". "
            "6. In config.py: set LAYERS['hospitality_fatigue'] = True. "
            "What it unlocks: live TripAdvisor review scores and cadence for nearby agritourism — "
            "a declining score velocity flags owner burnout before the property hits the market."
        ),
        "degrades":  False,
    },
    "terroir_score_delta": {
        "api":       "Wine-Searcher API — wine-searcher.com/api",
        "cost":      (
            "⚠️ Free trial only (not an ongoing free tier): 100 searches/day for 5 days, then paid plan required. "
            "Paid tiers (as of 2025): Enthusiast $9.99/mo (1,000/day) · Professional $29.99/mo (10,000/day) · "
            "Commercial from $99/mo (100,000+/day, SLA, bulk endpoints). "
            "For typical scan volumes (20 named parcels/run), the Enthusiast tier at $9.99/mo is sufficient."
        ),
        "free_tier": "5-day trial only (100 searches/day) — paid plan required after trial",
        "setup":     (
            "1. Go to wine-searcher.com/api and click 'Get API Key'. "
            "2. Create an account and start the 5-day free trial, or subscribe to the Enthusiast plan ($9.99/mo). "
            "3. Copy your API key from the dashboard. "
            "4. On Streamlit Cloud: open your app → Settings → Secrets → add: WINE_SEARCHER_API_KEY = \"your-key\". "
            "5. In config.py: set LAYERS['terroir_score_delta'] = True. "
            "What it unlocks: actual critic scores (Wine Spectator / Wine Advocate) for each named estate, "
            "compared against the DOCG zone benchmark — a gap of 5+ points signals underperforming land "
            "that a better operator could unlock."
        ),
        "degrades":  False,
    },
    "succession_frag": {
        "api":       "OpenAPI.it — Italian Cadastre API (catasto.openapi.it)",
        "cost":      (
            "Address lookup (POST /indirizzo): free — 1,440 calls/day free tier. "
            "Ownership lookup (POST /richiesta): €0.30 per call at base rate; "
            "€0.08 per call with a subscription plan. "
            "For 20 parcels per scan: ~€6.00 at base, ~€1.60 with subscription. "
            "⚠️ Requires two things before any calls work: "
            "(1) ID card upload for identity verification, and "
            "(2) signing a commercial information contract with OpenAPI.it. "
            "This is not a quick sign-up — allow a few business days for approval."
        ),
        "free_tier": None,
        "setup":     (
            "1. Register at openapi.com and log in. "
            "2. Go to Authentication → copy your Prod API key (plain string, no 'Bearer' prefix needed). "
            "3. Go to API Library → search 'Catasto' → click GO on 'Italian cadastre'. "
            "4. Click the Subscription tab and select a plan. "
            "5. Complete ID card upload (required by Italian data protection law). "
            "6. Sign the commercial information contract presented during signup. "
            "7. Once approved: set OPENAPI_IT_KEY = \"your-key\" in Streamlit Secrets. "
            "8. In config.py: set LAYERS['succession_frag'] = True. "
            "Tip: turn on the Sandbox first (Authentication page, green button) — "
            "it gives you a parallel test environment with virtual credits at no charge."
        ),
        "degrades":  False,
    },
    "owner_relocation": {
        "api":       "OpenAPI.it — Italian Cadastre API (cadastral contact address) + fiscal code decode (always free)",
        "cost":      (
            "Fiscal code birth-municipality decode and website language detection: always free, no key needed. "
            "Cadastral contact address upgrade: same OpenAPI.it contract as Succession Fragmentation above — "
            "€0.30 per lookup at base rate, €0.08 with subscription. No additional signup required "
            "if you already have the Succession Fragmentation contract in place."
        ),
        "free_tier": "Fiscal code decode + website language check always run — no credentials required",
        "setup":     (
            "Free components already active — owner birth municipality and website language are checked on every scan. "
            "For the cadastral contact address upgrade (removes the ⚡ proxy label): "
            "follow the same OpenAPI.it setup as Succession Fragmentation above, "
            "then set OPENAPI_IT_KEY in Streamlit Secrets. "
            "The layer automatically upgrades from proxy to authoritative once the key is present."
        ),
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
    # Score out of active signals only — "passed X of X checks you ran"
    total = len(active_keys)
    result = []
    for p in parcels:
        p = dict(p)
        fired = sum(1 for k in active_keys if p.get(k)) if total else 0
        p["opportunity_score"] = round((fired / total) * 100, 1) if total else 0.0
        p["signals_fired"]     = fired
        p["signals_total"]     = total
        result.append(p)
    return sorted(result, key=lambda x: x["opportunity_score"], reverse=True)


def score_color(score: float) -> str:
    """Return a CSS expression for the score tier colour.
    Streamlit DOM: returns CSS custom property var() references.
    Folium context (iframe): use CLR_MAP directly instead of calling this."""
    if score >= 30:
        return "var(--score-high)"
    if score >= 15:
        return "var(--score-mid)"
    return "var(--score-low)"


def score_color_map(score: float) -> str:
    """Concrete hex colour for use inside Folium iframes (CSS vars don't reach)."""
    if score >= 30:
        return CLR_MAP["score_high"]
    if score >= 15:
        return CLR_MAP["score_mid"]
    return CLR_MAP["score_low"]


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
        f"no historic: {skipped['historic']}  |  "
        f"duplicates merged: {skipped.get('duplicates', 0)}"
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


# ── PDF report generator ──────────────────────────────────────────────────────

def _pdf_safe(text: str) -> str:
    """Sanitize a string for fpdf2 built-in fonts (latin-1 only).

    fpdf2's built-in fonts (Helvetica, Times, Courier) are latin-1 encoded.
    Any character outside that range raises FPDFUnicodeEncodingException.
    This helper swaps known Unicode symbols for readable ASCII equivalents,
    then silently drops anything else that still can't encode.
    """
    _SUBS = {
        "\u2713": "OK",       # ✓ check mark
        "\u2717": "X",        # ✗ ballot X
        "\u26a1": "[proxy]",  # ⚡ lightning
        "\u2022": "-",        # • bullet
        "\u00b7": ".",        # · middle dot  (latin-1 safe but replace for consistency)
        "\u2014": "-",        # — em dash
        "\u2013": "-",        # – en dash
        "\u2018": "'",        # ' left single quote
        "\u2019": "'",        # ' right single quote
        "\u201c": '"',        # " left double quote
        "\u201d": '"',        # " right double quote
        "\u2026": "...",      # … ellipsis
        "\u2192": "->",       # → right arrow
        "\u2190": "<-",       # ← left arrow
        "\u2197": "->",       # ↗ north-east arrow
        "\u00b0": " deg",     # ° degree sign
        "\u20ac": "EUR",      # € euro
    }
    for ch, sub in _SUBS.items():
        text = text.replace(ch, sub)
    return text.encode("latin-1", errors="ignore").decode("latin-1")


def generate_pdf(p: dict, active_keys: list) -> bytes | None:
    """
    Generate a single-parcel Intelligence Report PDF using fpdf2.
    Returns raw PDF bytes, or None if fpdf2 is not installed.

    Layout:
      Page 1 — Header, key metrics, signals fired, GPS / OSM link
      Page 2 — Full signal detail table (one row per active signal)
    """
    if not _PDF_AVAILABLE:
        return None

    score     = p.get("opportunity_score", 0)
    name      = (p.get("name") or p.get("gps_coordinates", "Unknown Parcel"))[:60]
    crop      = p.get("primary_crop_type", "").title() or "—"
    acres     = f"{p.get('parcel_acres', 0):.1f}"
    airport   = f"{p.get('dist_airport_km', 0):.0f} km ({p.get('airport_iata', '')})"
    heritage  = p.get("closest_historic_tag", "").title() or "—"
    gps       = p.get("gps_coordinates", "")
    osm_url   = p.get("osm_url", "")
    region    = p.get("region", config.REGION)
    gen_date  = datetime.now().strftime("%Y-%m-%d %H:%M")

    # Compute fired / not-fired
    proxy_labels = {sm["label"] for sm in SIGNAL_META if sm.get("proxy")}
    fired_rows = []
    other_rows = []
    for sm in SIGNAL_META:
        if sm["key"] not in active_keys:
            continue
        detail_key = sm["key"].replace("_signal", "_detail")
        is_fired   = bool(p.get(sm["key"]))
        is_proxy   = sm.get("proxy", False)
        row = {
            "label":   sm["label"],
            "fired":   is_fired,
            "proxy":   is_proxy,
            "detail":  str(p.get(detail_key, ""))[:120],
        }
        if is_fired:
            fired_rows.append(row)
        else:
            other_rows.append(row)

    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()

    # ── Brand header ──────────────────────────────────────────────────────────
    pdf.set_fill_color(42, 33, 24)          # #2A2118
    pdf.rect(0, 0, 210, 18, "F")
    pdf.set_font("Helvetica", "B", 9)
    pdf.set_text_color(244, 239, 230)       # #F4EFE6
    pdf.set_xy(10, 5)
    pdf.cell(0, 8, _pdf_safe("Giovanni Bonelli Group  |  Parcel Scout  |  Tuscany Acquisition Intelligence"))

    # ── Title block ───────────────────────────────────────────────────────────
    pdf.set_text_color(42, 33, 24)
    pdf.set_xy(10, 24)
    pdf.set_font("Helvetica", "B", 7)
    pdf.set_text_color(139, 105, 20)        # #8B6914
    pdf.cell(0, 5, "INTELLIGENCE REPORT", ln=True)

    pdf.set_xy(10, 30)
    pdf.set_font("Helvetica", "B", 18)
    pdf.set_text_color(42, 33, 24)
    pdf.cell(0, 10, _pdf_safe(name), ln=True)

    pdf.set_xy(10, 41)
    score_clr = (74, 103, 65) if score >= 30 else (139, 105, 20) if score >= 15 else (122, 106, 85)
    pdf.set_font("Helvetica", "B", 11)
    pdf.set_text_color(*score_clr)
    fired_n = p.get("signals_fired", 0)
    total_n = p.get("signals_total", len(active_keys))
    pdf.cell(0, 7, _pdf_safe(f"Opportunity Score: {score:.0f}%  ({fired_n} of {total_n} signals fired)"), ln=True)

    # ── Divider ───────────────────────────────────────────────────────────────
    pdf.set_draw_color(212, 196, 160)       # #D4C4A0
    pdf.set_line_width(0.3)
    pdf.line(10, 50, 200, 50)

    # ── Key metrics grid ──────────────────────────────────────────────────────
    pdf.set_text_color(42, 33, 24)
    pdf.set_xy(10, 54)
    pdf.set_font("Helvetica", "B", 7)
    pdf.set_text_color(139, 105, 20)
    pdf.cell(0, 5, "KEY METRICS", ln=True)

    metrics = [
        ("Crop / Land Use",  crop),
        ("Parcel Size",      f"{acres} acres"),
        ("Nearest Airport",  airport),
        ("Historic Feature", heritage),
        ("GPS Coordinates",  gps),
    ]
    pdf.set_font("Helvetica", "", 9)
    pdf.set_text_color(42, 33, 24)
    for label, value in metrics:
        pdf.set_x(10)
        pdf.set_font("Helvetica", "B", 9)
        pdf.cell(45, 7, _pdf_safe(label + ":"), border=0)
        pdf.set_font("Helvetica", "", 9)
        pdf.cell(0, 7, _pdf_safe(value), ln=True)

    # ── Divider ───────────────────────────────────────────────────────────────
    y = pdf.get_y() + 3
    pdf.line(10, y, 200, y)

    # ── Signals fired ─────────────────────────────────────────────────────────
    pdf.set_xy(10, y + 4)
    pdf.set_font("Helvetica", "B", 7)
    pdf.set_text_color(139, 105, 20)
    pdf.cell(0, 5, "SIGNALS FIRED", ln=True)

    if fired_rows:
        for row in fired_rows:
            pdf.set_x(10)
            label_txt = row["label"]
            if row["proxy"]:
                label_txt += " (proxy)"
            pdf.set_font("Helvetica", "B", 9)
            pdf.set_text_color(74, 103, 65)
            pdf.cell(55, 6, _pdf_safe(f"[OK]  {label_txt}"), border=0)
            pdf.set_font("Helvetica", "", 8)
            pdf.set_text_color(42, 33, 24)
            pdf.multi_cell(0, 6, _pdf_safe(row["detail"][:100]))
    else:
        pdf.set_font("Helvetica", "I", 9)
        pdf.set_text_color(122, 106, 85)
        pdf.set_x(10)
        pdf.cell(0, 6, "No signals fired for this parcel.", ln=True)

    # ── OSM link ──────────────────────────────────────────────────────────────
    if osm_url:
        y2 = pdf.get_y() + 2
        pdf.line(10, y2, 200, y2)
        pdf.set_xy(10, y2 + 4)
        pdf.set_font("Helvetica", "B", 7)
        pdf.set_text_color(139, 105, 20)
        pdf.cell(30, 5, "OpenStreetMap URL:")
        pdf.set_font("Helvetica", "", 8)
        pdf.set_text_color(42, 33, 24)
        pdf.cell(0, 5, _pdf_safe(osm_url[:90]), ln=True)

    # ── Page 2: full signal detail table ─────────────────────────────────────
    pdf.add_page()
    pdf.set_fill_color(42, 33, 24)
    pdf.rect(0, 0, 210, 18, "F")
    pdf.set_font("Helvetica", "B", 9)
    pdf.set_text_color(244, 239, 230)
    pdf.set_xy(10, 5)
    pdf.cell(0, 8, _pdf_safe(f"Intelligence Report | Full Signal Detail | {name[:50]}"))

    pdf.set_text_color(42, 33, 24)
    pdf.set_xy(10, 22)
    pdf.set_font("Helvetica", "B", 7)
    pdf.set_text_color(139, 105, 20)
    pdf.cell(0, 5, "ALL SIGNAL DETAILS", ln=True)

    col_widths = [48, 14, 22, 106]   # Signal, Fired, Quality, Detail
    headers    = ["Signal", "Fired", "Data Quality", "Detail"]
    pdf.set_fill_color(42, 33, 24)
    pdf.set_text_color(244, 239, 230)
    pdf.set_font("Helvetica", "B", 7)
    pdf.set_x(10)
    for w, h in zip(col_widths, headers):
        pdf.cell(w, 7, h, border=0, fill=True)
    pdf.ln()

    fill = False
    for row in (fired_rows + other_rows):
        fill_clr = (250, 246, 239) if fill else (255, 255, 255)
        pdf.set_fill_color(*fill_clr)
        pdf.set_text_color(42, 33, 24)
        row_y = pdf.get_y()

        pdf.set_x(10)
        pdf.set_font("Helvetica", "B" if row["fired"] else "", 8)
        pdf.cell(col_widths[0], 6, _pdf_safe(row["label"][:28]), fill=True)

        pdf.set_font("Helvetica", "B", 8)
        pdf.set_text_color((74, 103, 65) if row["fired"] else (122, 106, 85))
        pdf.cell(col_widths[1], 6, "OK" if row["fired"] else "-", fill=True)

        pdf.set_font("Helvetica", "", 7)
        pdf.set_text_color(42, 33, 24)
        quality = "[proxy]" if row["proxy"] else "authoritative"
        pdf.cell(col_widths[2], 6, quality, fill=True)

        # Detail may be long — use multi_cell to wrap
        x_before = pdf.get_x()
        pdf.set_font("Helvetica", "", 7)
        pdf.multi_cell(col_widths[3], 6, _pdf_safe(row["detail"][:110] or "-"), fill=True)
        fill = not fill

    # ── Footer ────────────────────────────────────────────────────────────────
    pdf.set_y(-18)
    pdf.set_font("Helvetica", "I", 7)
    pdf.set_text_color(122, 106, 85)
    pdf.cell(0, 5,
             _pdf_safe(f"Generated {gen_date}  |  Giovanni Bonelli Group  |  Parcel Scout  |  {region}"),
             align="C")

    return bytes(pdf.output())


# ── Map builder ───────────────────────────────────────────────────────────────

def build_map(parcels: list) -> folium.Map:
    if not parcels:
        return folium.Map(location=[43.1, 11.4], zoom_start=9)

    lats   = [p["lat"] for p in parcels]
    lons   = [p["lon"] for p in parcels]
    center = [sum(lats) / len(lats), sum(lons) / len(lons)]

    # Dark mode uses CartoDB dark matter tiles; classic uses positron
    tiles  = "CartoDB dark_matter" if THEME == "dark" else "CartoDB positron"
    m      = folium.Map(location=center, zoom_start=10, tiles=tiles)

    # Colours from CLR_MAP — concrete hex because Folium renders inside an iframe
    # where CSS custom properties from the Streamlit page cannot reach.
    _pb = CLR_MAP["popup_bg"]
    _pt = CLR_MAP["popup_text"]
    _pm = CLR_MAP["popup_muted"]
    _pb2= CLR_MAP["popup_border"]
    _ca = CLR_MAP["score_high"]   # accent colour for links
    _cb = CLR_MAP["chip_bg"]
    _ct = CLR_MAP["chip_text"]
    _cbr= CLR_MAP["chip_border"]

    for p in parcels:
        score   = p.get("opportunity_score", 0)
        color   = score_color_map(score)    # concrete hex via CLR_MAP
        name    = p.get("name") or p.get("gps_coordinates", "")
        signals = signals_fired_list(p)
        sig_html = "".join(
            f'<span style="background:{_cb};color:{_ct};padding:2px 6px;'
            f'border:1px solid {_cbr};font-size:10px;margin:2px;display:inline-block;">{s}</span>'
            for s in signals
        ) or f"<em style='color:{_pm}'>no signals</em>"

        # ── Data quality badge ────────────────────────────────────────────
        q_score = p.get("quality_score", 0)
        q_label = p.get("quality_label", "")
        q_color = ("#4CAF50" if q_score >= 80 else
                   "#FFC107" if q_score >= 50 else
                   "#FF9800" if q_score >= 20 else "#9E9E9E")
        q_badge = (
            f'<span style="background:{q_color};color:#fff;padding:1px 6px;'
            f'font-size:9px;font-weight:700;">'
            f'DATA {q_score}/100 — {q_label}</span>'
        ) if q_label else ""

        cad_id   = p.get("cadastral_id", "")
        cad_line = (
            f'<div style="font-size:10px;color:{_pm};margin-top:4px;">'
            f'Catasto: {cad_id} &nbsp;·&nbsp; '
            f'Official area: {p.get("cadastral_area_sqm", "N/A")} m²'
            f'</div>'
        ) if cad_id else ""

        disc_pct = p.get("area_discrepancy_pct")
        disc_line = ""
        if disc_pct is not None:
            disc_color = "#4CAF50" if disc_pct < 5 else "#FFC107" if disc_pct < 15 else "#FF5722"
            disc_line = (
                f'<div style="font-size:10px;margin-top:2px;">'
                f'Area discrepancy: <span style="color:{disc_color};font-weight:600;">'
                f'{disc_pct:.1f}%</span></div>'
            )

        corine_line = ""
        corine_label = p.get("corine_label", "")
        corine_match = p.get("corine_match", "")
        if corine_label:
            cm_color = "#4CAF50" if corine_match == "confirmed" else "#FF9800" if corine_match == "mismatch" else _pm
            corine_line = (
                f'<div style="font-size:10px;color:{_pm};margin-top:2px;">'
                f'CORINE: {corine_label} '
                f'<span style="color:{cm_color};font-weight:600;">({corine_match})</span>'
                f'</div>'
            )

        popup_html = f"""
        <div style="font-family:'Manrope',system-ui,sans-serif;min-width:230px;
                    color:{_pt};background:{_pb};padding:14px;border:1px solid {_pb2};">
          <div style="font-size:22px;font-weight:700;color:{color};">{score:.1f}
            <span style="font-size:12px;color:{_pm};">/100</span>
            &nbsp;{q_badge}
          </div>
          <div style="font-size:12px;font-weight:500;margin:4px 0 8px;">{name[:50]}</div>
          <div style="font-size:10px;color:{_pm};margin-bottom:6px;">
            {p.get('primary_crop_type','').title()} &nbsp;·&nbsp;
            {p.get('parcel_acres',0):.0f} acres &nbsp;·&nbsp;
            {p.get('dist_airport_km',0):.0f} km to {p.get('airport_iata','')}
          </div>
          {cad_line}{disc_line}{corine_line}
          <div style="margin-top:8px;">{sig_html}</div>
          <div style="margin-top:10px;font-size:10px;">
            <a href="{p.get('osm_url','')}" target="_blank"
               style="color:{_ca};text-decoration:none;">View on OpenStreetMap ↗</a>
          </div>
        </div>
        """
        poly_coords = p.get("polygon_coords", [])
        if poly_coords:
            folium.Polygon(
                locations=poly_coords,
                color=color,
                weight=2,
                fill=True,
                fill_color=color,
                fill_opacity=0.28,
                popup=folium.Popup(popup_html, max_width=280),
                tooltip=f"{score:.1f}/100 — {name[:35]}",
            ).add_to(m)
            # ── Cadastral overlay: official boundary as dashed outline ─────
            cad_coords = p.get("cadastral_polygon_coords", [])
            if cad_coords:
                folium.Polygon(
                    locations=cad_coords,
                    color="#FFD700",      # gold for official boundary
                    weight=2,
                    dash_array="6 4",     # dashed to distinguish from OSM solid
                    fill=False,
                    tooltip=f"Catasto: {p.get('cadastral_id', '')}",
                ).add_to(m)
            # Centroid dot — visible at low zoom
            folium.CircleMarker(
                location=[p["lat"], p["lon"]],
                radius=5,
                color=color,
                fill=True,
                fill_color=color,
                fill_opacity=0.9,
                tooltip=f"{score:.1f}/100 — {name[:35]}",
            ).add_to(m)
            # Score label — DivIcon floating above centroid dot
            label_bg = "rgba(30,40,56,0.88)" if THEME == "dark" else "rgba(244,239,230,0.88)"
            folium.Marker(
                location=[p["lat"], p["lon"]],
                icon=folium.DivIcon(
                    html=(
                        f'<div style="font-family:Manrope,system-ui,sans-serif;'
                        f'font-size:10px;font-weight:700;color:{color};'
                        f'background:{label_bg};'
                        f'padding:1px 5px;border:1px solid {color};'
                        f'border-radius:2px;white-space:nowrap;'
                        f'pointer-events:none;line-height:1.4;">'
                        f'{score:.0f}</div>'
                    ),
                    icon_size=(30, 18),
                    icon_anchor=(15, -8),
                ),
            ).add_to(m)
        else:
            # Fallback for parcels without polygon geometry
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

    # ── Soil Lithology WMS overlay (ISPRA) ────────────────────────────────────
    folium.WmsTileLayer(
        url="https://sinacloud.isprambiente.it/arcgisgeo/services/geo/SGI_ISPRA_Geologia25k/MapServer/WMSServer",
        layers="0",
        fmt="image/png",
        transparent=True,
        name="Soil Lithology (ISPRA)",
        show=False,
        opacity=0.65,
        attr='<a href="https://portalesgi.isprambiente.it" target="_blank">ISPRA — Carta Geologica d\'Italia 1:25,000</a>',
        min_zoom=11,
    ).add_to(m)

    # ── Italian Land Registry overlay (Catasto) ───────────────────────────────
    folium.WmsTileLayer(
        url="https://wms.cartografia.agenziaentrate.gov.it/inspire/wms/ows01.php",
        layers="CP.CadastralParcel",
        fmt="image/png",
        transparent=True,
        name="Cadastral Parcels (Catasto)",
        show=False,
        opacity=0.80,
        attr='<a href="https://www.agenziaentrate.gov.it" target="_blank">Agenzia delle Entrate — Catasto d\'Italia</a>',
        min_zoom=15,
    ).add_to(m)

    folium.LayerControl(collapsed=False, position="topright").add_to(m)

    # ── Soil legend (themed) ──────────────────────────────────────────────────
    _legend_bg     = "#1e2838" if THEME == "dark" else "#F4EFE6"
    _legend_border = "#2d3d52" if THEME == "dark" else "#D4C4A0"
    _legend_text   = "#c8c3bc" if THEME == "dark" else "#2A2118"
    _legend_muted  = "#6e7a8a" if THEME == "dark" else "#7A6A55"
    legend_html = f"""
    <div style="position:fixed;bottom:30px;left:12px;z-index:9999;
                background:{_legend_bg};border:1px solid {_legend_border};padding:10px 14px;
                font-family:'Manrope',system-ui,sans-serif;font-size:11px;color:{_legend_text};
                border-radius:3px;max-width:195px;box-shadow:0 2px 6px rgba(0,0,0,.3);">
      <div style="font-weight:700;margin-bottom:5px;letter-spacing:0.05em;">Soil Lithology (ISPRA)</div>
      <div><span style="color:#C0392B;font-size:14px;">&#9632;</span> Volcanic / igneous</div>
      <div><span style="color:#7F8C8D;font-size:14px;">&#9632;</span> Limestone / carbonate</div>
      <div><span style="color:#D4AC0D;font-size:14px;">&#9632;</span> Clay / sedimentary</div>
      <div><span style="color:#5DADE2;font-size:14px;">&#9632;</span> Alluvial / fluvial</div>
      <div style="margin-top:6px;font-size:9px;color:{_legend_muted};line-height:1.4;">
        Enable "Soil Lithology" ↗ to see geology.<br>
        <strong>Zoom in to load tiles.</strong><br>
        Coverage gaps = survey not yet published by ISPRA.
      </div>
    </div>
    """
    m.get_root().html.add_child(folium.Element(legend_html))

    return m


# ── Rankings table builder ────────────────────────────────────────────────────

def build_rankings_df(parcels: list) -> pd.DataFrame:
    rows = []
    for rank, p in enumerate(parcels, 1):
        fired   = signals_fired_list(p)
        rows.append({
            "Rank":       rank,
            "Score":      p.get("opportunity_score", 0),
            "Quality":    f"{p.get('quality_score', 0)}/100",
            "Signals":    f"{p.get('signals_fired',0)}/{len(ALL_SIGNAL_KEYS)}",
            "Fired":      " · ".join(fired) if fired else "—",
            "Crop":       p.get("primary_crop_type", "").title(),
            "Acres":      int(round(p.get("parcel_acres", 0))),
            "Catasto":    p.get("cadastral_id", "") or "—",
            "Area Δ":     f"{p.get('area_discrepancy_pct', 0):.0f}%" if p.get("area_discrepancy_pct") is not None else "—",
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

_SUBTITLE_HTML = (
    '<p style="font-family:var(--sans);font-size:0.95rem;font-weight:500;'
    'color:var(--text);letter-spacing:0.01em;margin:-0.4rem 0 0.9rem 0;">'
    'Off-market acquisition intelligence — Tuscany, Italy</p>'
)

if DEMO_MODE:
    _h_left, _h_right = st.columns([2, 1])
    with _h_left:
        st.markdown("# Parcel Scout")
        st.markdown(_SUBTITLE_HTML, unsafe_allow_html=True)
    with _h_right:
        st.markdown('<div class="demo-marker"></div>', unsafe_allow_html=True)
        demo_btn = st.button(
            "▶  Demo for Michael Kennedy — Click Here",
            key="demo_kennedy_btn",
            use_container_width=True,
        )
else:
    st.markdown("# Parcel Scout")
    st.markdown(_SUBTITLE_HTML, unsafe_allow_html=True)
    demo_btn = False

# ── View toggle: Parcel Scan ↔ Recent Acquisitions ───────────────────────────
# Tab-like switcher. Default view is the parcel scan (what the app has always
# done). Flipping to "Recent Acquisitions" shows the news + company-formation
# feed and halts rendering of the scan UI via st.stop().
_view = st.radio(
    "View",
    ["🔍 Parcel Scan", "📰 Recent Acquisitions"],
    horizontal=True,
    label_visibility="collapsed",
    key="_view_toggle",
)

if _view == "📰 Recent Acquisitions":
    import acquisitions_feed

    st.markdown(
        '<p style="font-family:var(--sans);color:var(--text-mid);'
        'font-size:0.85rem;margin:0.2rem 0 1rem 0;">'
        'Recent wine estate, vineyard, olive grove, and agricultural property '
        'acquisitions in Tuscany — news-sourced or inferred from new-LLC formations. '
        'Refresh to pull the latest.</p>',
        unsafe_allow_html=True,
    )

    _refresh_cols = st.columns([1, 1, 2])
    _do_refresh   = _refresh_cols[0].button(
        "↻  Refresh feed",
        type="primary",
        use_container_width=True,
        help="Runs a Gemini news search + OpenCorporates company-formation search. "
             "Results persist in the database — you don't need to refresh every visit.",
    )
    _lookback = _refresh_cols[1].selectbox(
        "Lookback",
        [1, 2, 3, 5],
        index=2,
        format_func=lambda y: f"{y} year{'s' if y > 1 else ''}",
        label_visibility="collapsed",
    )

    if _do_refresh:
        with st.status("Searching for recent Tuscan estate acquisitions…", expanded=True) as _rstatus:
            st.write("📰  Querying Gemini with Google Search grounding…")
            summary = acquisitions_feed.refresh_all(lookback_years=_lookback)
            if summary.get("news_errors"):
                for _err in summary["news_errors"]:
                    st.warning(f"⚠ News search: {_err.get('error', 'unknown error')}")
            st.write(f"📰  News: {summary['news_added']} new · {summary['news_updated']} updated")
            st.write(f"🏢  Company formations: {summary['comp_added']} new · {summary['comp_updated']} updated")
            _rstatus.update(
                label=f"Feed refreshed — {summary['total_rows']} total rows processed",
                state="complete",
            )

    # ── Filters ───────────────────────────────────────────────────────────────
    _filter_cols = st.columns([1, 1, 2])
    _src_filter  = _filter_cols[0].selectbox(
        "Source",
        ["All", "News only", "Company formations only"],
        key="_acq_src_filter",
    )
    _date_filter = _filter_cols[1].selectbox(
        "Since",
        ["All 3 years", "Last 12 months", "Last 6 months", "Last 30 days"],
        key="_acq_date_filter",
    )

    _src_map = {
        "All":                       "",
        "News only":                 "news",
        "Company formations only":   "company_formation",
    }
    from datetime import datetime as _dt, timedelta as _td
    _date_map = {
        "All 3 years":      (_dt.utcnow() - _td(days=3 * 365)).date().isoformat(),
        "Last 12 months":   (_dt.utcnow() - _td(days=365)).date().isoformat(),
        "Last 6 months":    (_dt.utcnow() - _td(days=182)).date().isoformat(),
        "Last 30 days":     (_dt.utcnow() - _td(days=30)).date().isoformat(),
    }

    _rows = storage.list_acquisitions(
        source_type=_src_map[_src_filter],
        since_date=_date_map[_date_filter],
        limit=500,
    )

    if not _rows:
        st.info(
            "No acquisitions in the database yet. Click **Refresh feed** to populate "
            "it — the first run typically finds 15–30 deals."
        )
    else:
        # Pretty formatter — convert to a clean display DataFrame
        _display_rows = []
        for r in _rows:
            _display_rows.append({
                "Date":      r.get("acquisition_date") or "—",
                "Buyer":     r.get("buyer_name") or "—",
                "Type":      r.get("buyer_type") or "—",
                "Estate":    r.get("estate_name") or "—",
                "Seller":    r.get("seller_name") or "—",
                "Location":  " · ".join(
                    x for x in [r.get("location_comune"), r.get("location_province")] if x
                ) or "—",
                "Category":  r.get("estate_type") or "—",
                "Price €":   f"{r['price_eur']:,}" if r.get("price_eur") else "—",
                "Source":    "📰 News" if r.get("source_type") == "news" else "🏢 LLC formation",
                "Confidence": r.get("confidence") or "—",
                "Link":      r.get("source_url") or "",
            })

        st.caption(f"Showing {len(_rows)} acquisition(s). Click any column header to sort.")
        st.dataframe(
            _display_rows,
            use_container_width=True,
            hide_index=True,
            column_config={
                "Link": st.column_config.LinkColumn("Source link", display_text="Open ↗"),
                "Price €": st.column_config.Column(width="small"),
                "Confidence": st.column_config.Column(width="small"),
            },
        )

        st.caption(
            "📰 News rows come from Gemini web search over wine/real-estate press. "
            "🏢 LLC-formation rows come from OpenCorporates — these are *proxy* signals "
            "(a new agricultural LLC in a Tuscan province often means someone just "
            "bought a parcel through it, but not always)."
        )

    st.stop()   # Halt rendering — the scan UI below does not run.

# ── Demo preset — fires when demo button is clicked ───────────────────────────
if demo_btn:
    # Province
    st.session_state["province_select"] = "Chianti Classico, Siena (DEMO)"
    # Hard filters — all ON
    st.session_state["filter_proximity_to_airport"]  = True
    st.session_state["filter_agricultural_land"]     = True
    st.session_state["filter_min_square_footage"]    = True
    st.session_state["filter_historical_designation"] = True
    # Free signals — only DOCG wine zone and Napa Neighbor (fast, no extra queries)
    st.session_state["sig_g2_premium_wine_zone"]  = True
    st.session_state["sig_g2_distress_signal"]    = False
    st.session_state["sig_g2_succession_signal"]  = False
    st.session_state["sig_g2_lodging_overlay"]    = False
    st.session_state["layer_layer_napa_neighbor_signal"]  = True
    st.session_state["layer_layer_digital_ghost_signal"]  = False
    # Premium layers — all OFF
    st.session_state["layer_layer_satellite_neglect_signal"]   = False
    st.session_state["layer_layer_permit_paralysis_signal"]    = False
    st.session_state["layer_layer_zoning_alchemy_signal"]      = False
    st.session_state["layer_layer_hospitality_fatigue_signal"] = False
    st.session_state["layer_layer_terroir_score_delta_signal"] = False
    st.session_state["layer_layer_succession_frag_signal"]     = False
    st.session_state["layer_layer_owner_relocation_signal"]    = False
    # Flag to auto-fire the scan on next rerun
    st.session_state["demo_run_trigger"] = True
    st.rerun()

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
    key="province_select",
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
        filter_state[fm["key"]] = st.checkbox(
            fm["label"],
            value=config.FILTERS[fm["key"]],
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
            g2_state[cfg_key] = st.checkbox(
                sm["label"],
                value=_default,
                key=f"sig_{sm['key']}",
            )
        else:
            layer_state[cfg_key] = st.checkbox(
                sm["label"],
                value=True,
                key=f"layer_{sm['key']}",
            )
        st.caption(sm["desc"])
        if sm.get("proxy"):
            st.caption(f"⚡ Proxy data — upgrade to: {sm['proxy_upgrade']}")

st.markdown("---")

# ── Premium Layers ────────────────────────────────────────────────────────────
st.markdown('<span class="gb-label">Premium Layers</span>', unsafe_allow_html=True)
st.caption("Require API credentials — disabled by default. Enable when credentials are configured.")

paid_layers = [sm for sm in SIGNAL_META if sm["paid"]]

pl1, pl2, pl3 = st.columns(3)
for i, sm in enumerate(paid_layers):
    _, cfg_key = sm["config"]
    col = [pl1, pl2, pl3][i % 3]
    info = PREMIUM_LAYER_INFO.get(cfg_key, {})
    with col:
        layer_state[cfg_key] = st.checkbox(
            sm["label"],
            value=False,
            key=f"layer_{sm['key']}",
        )
        st.caption(sm["desc"])
        if sm.get("proxy"):
            st.caption(f"⚡ Proxy data — upgrade to: {sm['proxy_upgrade']}")
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
    td = 'style="padding:0.55rem 0.9rem;border-bottom:1px solid var(--border);vertical-align:top;"'
    th = 'style="padding:0.65rem 0.9rem;text-align:left;font-weight:600;letter-spacing:0.08em;text-transform:uppercase;font-size:0.60rem;color:var(--accent);"'

    header = (
        '<table style="width:100%;border-collapse:collapse;font-family:var(--sans);'
        'font-size:0.75rem;color:var(--text);border:1px solid var(--border);">'
        '<thead><tr style="background:var(--surface-low);">'
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
        free_tier = info.get("free_tier") or '<span style="color:var(--text-muted);">None</span>'
        without   = (
            '<span style="color:var(--accent);font-weight:600;">Limited data</span>'
            ' — free components still run'
            if info.get("degrades") else
            '<span style="color:#e57373;font-weight:600;">No data</span>'
            ' — layer inactive'
        )
        row_bg = "var(--surface-high)" if i % 2 == 0 else "var(--surface)"
        cred   = f'<code style="font-size:0.68rem;color:var(--accent);">{LAYER_CRED.get(cfg_key, "—")}</code>'
        body += (
            f'<tr style="background:{row_bg};">'
            f'<td {td} style="padding:0.55rem 0.9rem;border-bottom:1px solid var(--border);'
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
        '<p style="font-size:0.65rem;color:var(--text-muted);margin-top:0.6rem;">'
        'Set credentials in <strong>Streamlit Secrets</strong> (cloud) or '
        '<code style="color:var(--accent);">config.py</code> (local).'
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
            f'<strong style="color:var(--warn-text);">{label}</strong>'
            f' &mdash; needs <code style="background:var(--surface-low);padding:1px 4px;'
            f'border-radius:2px;color:var(--accent);font-size:0.72rem;">{cred_var}</code>'
            f' &mdash; {impact}<br>'
            f'<span style="color:var(--text-muted);font-size:0.72rem;">↳ {info["setup"]}</span>'
            f'</li>'
        )
    st.markdown(
        f'<div style="background:var(--warn-bg);border:1.5px solid var(--warn-border);'
        f'padding:1rem 1.2rem;margin:0.5rem 0;">'
        f'<p style="color:var(--warn-text);font-weight:700;margin:0 0 0.4rem 0;'
        f'font-family:var(--sans);font-size:0.82rem;">'
        f'⚠ {n} premium layer{"s" if n > 1 else ""} enabled without credentials.</p>'
        f'<p style="color:var(--warn-text);margin:0 0 0.6rem 0;'
        f'font-family:var(--sans);font-size:0.78rem;">'
        f'The scan will still run — but these layers will be inactive:</p>'
        f'<ul style="color:var(--warn-text);font-family:var(--sans);font-size:0.78rem;'
        f'margin:0;padding-left:1.2rem;">'
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

# Single "Run Scan" button. Every scan upserts new/existing parcels and marks
# any that vanished from OSM as INACTIVE. Two buttons were redundant — OSM
# parcel geometry rarely changes, but the 14 layer signals (listings, domains,
# company status, fires, permits) are re-evaluated every run, which is the
# real reason to run a scan.
run_btn = st.button(
    "▶  Run Scan",
    type="primary",
    use_container_width=True,
    help="Scan the region. New parcels are added, existing ones re-scored, "
         "vanished ones marked INACTIVE.",
)

# ── Trigger scan ──────────────────────────────────────────────────────────────
_demo_trigger = st.session_state.pop("demo_run_trigger", False)
if run_btn or _demo_trigger:
    # Every run behaves like a REFRESH — upsert + mark-inactive. On the first
    # run against an empty DB, mark-inactive is simply a no-op.
    _scan_mode = "REFRESH"
    st.session_state.scan_log    = []
    st.session_state.scan_region = config.REGION
    st.session_state.scan_mode   = _scan_mode
    try:
        st.session_state.scan_id = storage.start_scan(_scan_mode, config.REGION)
    except Exception as _exc:
        st.session_state.scan_id = None
        st.warning(f"Storage unavailable — scan will run but won't be saved: {_exc}")
    t0 = time.time()

    with st.status("Running Parcel Scout scan…", expanded=True) as scan_status:
        log_placeholder = st.empty()

        import builtins
        original_print = builtins.print

        def ui_print(*args, **kwargs):
            msg = " ".join(str(a) for a in args)
            # Show meaningful progress in the UI; suppress verbose API warnings
            # (they still reach the terminal via original_print for debugging)
            _is_noise = (
                "WARNING:" in msg          # Overpass retry warnings (old format)
                or "[Overpass]" in msg     # Overpass retry warnings (new format)
                or "\r" in msg             # carriage-return progress counters
            )
            if not _is_noise:
                st.session_state.scan_log.append(msg)
                log_placeholder.markdown(
                    "\n".join(f"› {line}" for line in st.session_state.scan_log[-12:])
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

        # ── Persist to SQLite: upsert every matched parcel ───────────────────
        # On SEED: all are inserted (or updated if the DB already had them).
        # On REFRESH: anything in the DB for this region that was NOT seen this
        # run gets flagged INACTIVE, so the living list reflects OSM reality.
        db_added = db_updated = db_removed = 0
        try:
            seen_ids: set = set()
            for _p in parcels:
                _pid, _new = storage.upsert_parcel(_p, region=config.REGION)
                seen_ids.add(_pid)
                if _new:
                    db_added += 1
                else:
                    db_updated += 1
            if _scan_mode == "REFRESH":
                db_removed = storage.mark_inactive(config.REGION, seen_ids)
            storage.end_scan(added=db_added, updated=db_updated, removed=db_removed)
        except Exception as _exc:
            st.session_state.scan_log.append(f"  ⚠ DB persist failed: {_exc}")

        st.session_state.scan_db_summary = {
            "added": db_added, "updated": db_updated, "removed": db_removed
        }

        total_raw = st.session_state.get("total_raw", 0)
        if parcels:
            scan_status.update(
                label=(
                    f"{_scan_mode} complete — scanned {total_raw:,} parcels in {config.REGION}, "
                    f"found {len(parcels)} matching  ·  DB: {db_added} added · "
                    f"{db_updated} updated · {db_removed} inactive  ({elapsed:.0f}s)"
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
        st.markdown(
            '<div style="background:var(--surface-low);border:1px solid var(--border);'
            'padding:1rem 1.2rem;">'
            '<p style="color:var(--text);font-family:var(--sans);'
            'font-size:0.82rem;margin:0 0 0.3rem 0;">'
            'Configure your parameters above and click <strong>Run Off-Market Scan</strong> to begin.</p>'
            '<p style="color:var(--text-muted);font-family:var(--sans);'
            'font-size:0.78rem;margin:0;">'
            'The scan queries OpenStreetMap and takes approximately 3–4 minutes for a full province.</p>'
            '</div>',
            unsafe_allow_html=True,
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
    n_active = len(active_keys)
    m2.metric("Top Score",        f"{max(scores):.0f}%", help=f"Percentage of active signals fired ({n_active} signals running)")
    m3.metric("Average Score",    f"{sum(scores)/len(scores):.0f}%")
    m4.metric("Signals Active",   f"{n_active} of {len(ALL_SIGNAL_KEYS)}", help="Enable more signals to deepen the analysis")
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

        def render_report(idx, p):
            """Render the full-width Intelligence Report panel for a parcel."""
            score     = p["opportunity_score"]
            name      = (p.get("name") or p.get("gps_coordinates", f"Parcel #{idx+1}"))
            fired     = signals_fired_list(p)
            score_clr = score_color(score)

            st.markdown(
                f'<div style="margin:0.8rem 0 1rem;padding:1.2rem 1.4rem;'
                f'background:var(--surface-low);border:1px solid var(--border);border-top:3px solid var(--accent);">'
                f'<div style="font-family:var(--sans);font-size:0.56rem;font-weight:700;'
                f'letter-spacing:0.2em;text-transform:uppercase;color:var(--accent);">Intelligence Report</div>'
                f'<div style="font-family:var(--serif);font-size:2.2rem;font-weight:300;'
                f'color:var(--text);line-height:1.1;margin-top:0.15rem;">{name}</div>'
                f'<div style="font-family:var(--sans);font-size:0.68rem;color:{score_clr};'
                f'font-weight:600;margin-top:0.25rem;letter-spacing:0.05em;">'
                f'Opportunity Score: {score:.0f}% ({p.get("signals_fired",0)} of {p.get("signals_total", len(active_keys))} signals)'
                f'</div></div>',
                unsafe_allow_html=True,
            )

            dc1, dc2, dc3 = st.columns(3)
            dc1.metric("Opportunity Score", f"{score:.0f}%",
                help="Percentage of active signals that fired for this parcel.")
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

            # ── Cadastral cross-validation metrics ───────────────────────
            cad_id = p.get("cadastral_id", "")
            if cad_id or p.get("quality_score"):
                st.markdown("---")
                st.markdown("**Data Quality (Catasto cross-validation)**")
                qc1, qc2, qc3 = st.columns(3)
                qc1.metric("Quality Score", f"{p.get('quality_score', 0)}/100",
                    help=f"Data confidence: {p.get('quality_label', 'N/A')}. "
                         f"Cadastral: {p.get('quality_cadastral_pts', 0)}/30 · "
                         f"Area: {p.get('quality_area_pts', 0)}/20 · "
                         f"CORINE: {p.get('quality_corine_pts', 0)}/15 · "
                         f"OSM: {p.get('quality_osm_pts', 0)}/15 · "
                         f"Geometry: {p.get('quality_geom_pts', 0)}/20")
                qc1.metric("Catasto Ref", cad_id or "—",
                    help="Official foglio/particella from the Italian land registry (Agenzia delle Entrate).")
                qc2.metric("Official Area", f"{p.get('cadastral_area_sqm', '—')} m²" if p.get("cadastral_area_sqm") else "—",
                    help="Area registered in the official Catasto.")
                disc = p.get("area_discrepancy_pct")
                qc2.metric("Area Discrepancy", f"{disc:.1f}%" if disc is not None else "—",
                    help="Difference between OSM polygon area and official Catasto area. <5% is excellent.")
                qc3.metric("CORINE Land Use", p.get("corine_label", "") or "—",
                    help="EU satellite-derived land classification (100m resolution).")
                qc3.metric("CORINE Match", (p.get("corine_match", "") or "—").title(),
                    help="Does CORINE agree with the OSM crop tag? 'Confirmed' = high confidence.")

            # Build a quick label→proxy lookup for badge rendering
            _proxy_labels = {sm["label"] for sm in SIGNAL_META if sm.get("proxy")}

            st.markdown("**Signals fired:**")
            if fired:
                sig_cols = st.columns(min(len(fired), 4))
                for i, sig in enumerate(fired):
                    sm_match = next((s for s in SIGNAL_META if s["label"] == sig), None)
                    icon = SIGNAL_ICON_MAP.get(sm_match["key"], "check_circle") if sm_match else "check_circle"
                    if sig in _proxy_labels:
                        sig_cols[i % 4].warning(f"⚡ {sig}  *(proxy)*")
                    else:
                        sig_cols[i % 4].markdown(
                            f'<div style="background:var(--success-bg);border:1.5px solid var(--success-border);'
                            f'padding:0.4rem 0.6rem;border-radius:2px;margin-bottom:0.3rem;">'
                            f'<span class="material-symbols-outlined" style="font-size:13px;vertical-align:middle;'
                            f'color:var(--success-text);">{icon}</span>'
                            f'<span style="font-family:var(--sans);font-size:0.72rem;color:var(--success-text);'
                            f'font-weight:600;margin-left:4px;">{sig}</span></div>',
                            unsafe_allow_html=True,
                        )
            else:
                st.caption("No signals fired for this parcel.")

            unfired = [sm["label"] for sm in SIGNAL_META if sm["key"] in active_keys and not p.get(sm["key"])]
            if unfired:
                st.markdown("**Not triggered:**")
                st.caption("  ·  ".join(unfired))

            st.markdown(
                f"**[View on OpenStreetMap ↗]({p.get('osm_url','')})**  ·  GPS: `{p.get('gps_coordinates','')}`"
            )

            with st.expander("▼  Full Signal Details — click to expand"):
                detail_rows = []
                for sm in SIGNAL_META:
                    if sm["key"] not in active_keys:
                        continue
                    detail_key = sm["key"].replace("_signal", "_detail")
                    fired_flag = p.get(sm["key"])
                    is_proxy   = sm.get("proxy", False)
                    detail_rows.append({
                        "Signal":       sm["label"],
                        "Fired":        "✓" if fired_flag else "—",
                        "Data Quality": "⚡ proxy" if is_proxy else "authoritative",
                        "Detail":       str(p.get(detail_key, "")),
                    })
                st.dataframe(pd.DataFrame(detail_rows), use_container_width=True, hide_index=True)
                if any(sm.get("proxy") for sm in SIGNAL_META if sm["key"] in active_keys):
                    st.caption(
                        "⚡ Proxy signals use indirect data as a stand-in for the authoritative source. "
                        "They are directionally correct but less precise. "
                        "See signal descriptions above for upgrade paths."
                    )

            # ── Audit trail: every decision this parcel went through ─────────
            # Pulled live from the DB — shows what passed, what failed, and why.
            # If the parcel isn't yet in the DB (loaded from an old session or
            # pre-storage-upgrade run), we silently upsert it so it joins the
            # living roster — future re-scans will then accumulate real audit.
            with st.expander("▼  Audit Trail — why this score?"):
                _pid = storage.parcel_key(p)
                _audit_rows = storage.get_parcel_audit(_pid, limit=200)
                if not _audit_rows:
                    # Not in DB yet — backfill so this parcel is tracked going forward.
                    try:
                        storage.upsert_parcel(p, region=config.REGION)
                        st.caption(
                            f"Parcel ID in DB: `{_pid}`  ·  Just added to the living "
                            f"roster — no historical audit yet. A Refresh will populate the trail."
                        )
                    except Exception as _e:
                        st.caption(f"Parcel not in DB and backfill failed: {_e}")
                else:
                    st.caption(f"Parcel ID in DB: `{_pid}`  ·  {len(_audit_rows)} decision(s) logged")
                    st.dataframe(
                        pd.DataFrame(_audit_rows).rename(columns={
                            "ts": "When (UTC)", "step": "Step",
                            "outcome": "Outcome", "detail": "Detail",
                            "scan_id": "Scan #",
                        }),
                        use_container_width=True, hide_index=True,
                    )

            # ── PDF download ──────────────────────────────────────────────────
            if _PDF_AVAILABLE:
                pdf_bytes = generate_pdf(p, active_keys)
                if pdf_bytes:
                    safe_name = re.sub(r"[^\w\s-]", "", name).strip().replace(" ", "_")[:40]
                    st.download_button(
                        "⬇  Download Intelligence Report (PDF)",
                        data=pdf_bytes,
                        file_name=f"parcel_scout_{safe_name}.pdf",
                        mime="application/pdf",
                        key=f"pdf_dl_{idx}",
                    )
            else:
                st.caption("Install fpdf2 to enable PDF downloads: `pip install fpdf2`")

        # Render cards in rows of 3; inject report immediately after the active row
        row_size = 3
        for row_start in range(0, len(parcels), row_size):
            row_parcels = parcels[row_start:row_start + row_size]
            cols = st.columns(row_size)

            for col_idx, (col, p) in enumerate(zip(cols, row_parcels)):
                idx       = row_start + col_idx
                score     = p["opportunity_score"]
                name      = (p.get("name") or "").strip() or f"{p.get('primary_crop_type','').replace('_',' ').title()} Parcel" or f"Parcel #{idx+1}"
                lat       = p.get("lat", 43.45)
                lon       = p.get("lon", 11.48)
                fired     = signals_fired_list(p)
                acres     = int(round(p.get("parcel_acres", 0)))
                airport   = f"{int(round(p.get('dist_airport_km', 0)))} km · {p.get('airport_iata', '')}"
                crop      = p.get("primary_crop_type", "").replace("_", " ").title() or "—"
                heritage  = p.get("closest_historic_tag", "").title() or "—"
                score_clr = score_color(score)
                is_open   = (active_dossier == idx)

                with col:
                    osm_link = p.get("osm_url", f"https://www.openstreetmap.org/#map=15/{lat}/{lon}")
                    st.markdown(
                        f'<a href="{osm_link}" target="_blank" style="text-decoration:none;">'
                        f'<div style="width:100%;height:155px;background:var(--surface-card);margin-bottom:0;'
                        f'display:flex;flex-direction:column;align-items:center;justify-content:center;'
                        f'border:1px solid var(--border);cursor:pointer;">'
                        f'<div style="font-size:1.6rem;margin-bottom:0.4rem;">🗺</div>'
                        f'<div style="font-family:var(--sans);font-size:0.6rem;font-weight:600;'
                        f'letter-spacing:0.12em;text-transform:uppercase;color:var(--text-mid);margin-bottom:0.25rem;">'
                        f'{lat:.4f}, {lon:.4f}</div>'
                        f'<div style="font-family:var(--sans);font-size:0.55rem;color:var(--accent);'
                        f'letter-spacing:0.08em;">View on OpenStreetMap ↗</div>'
                        f'</div></a>',
                        unsafe_allow_html=True,
                    )
                    st.markdown(
                        f'<div style="padding:0.75rem 0 0.5rem;border-bottom:1px solid var(--border);">'
                        f'<div style="font-family:var(--sans);font-size:0.56rem;font-weight:700;'
                        f'letter-spacing:0.18em;text-transform:uppercase;color:{score_clr};margin-bottom:0.2rem;">'
                        f'Score {score:.0f}% ({p.get("signals_fired",0)} of {p.get("signals_total", len(active_keys))})</div>'
                        f'<div style="font-family:var(--serif);font-weight:400;font-size:1.35rem;'
                        f'color:var(--text);line-height:1.25;">{name[:55]}</div>'
                        f'</div>',
                        unsafe_allow_html=True,
                    )
                    st.markdown(
                        f'<div style="padding:0.6rem 0;border-bottom:1px solid var(--border);">'
                        f'<div style="font-family:var(--sans);font-size:0.52rem;font-weight:700;'
                        f'letter-spacing:0.2em;text-transform:uppercase;color:var(--accent);margin-bottom:0.4rem;">Key Intel</div>'
                        f'<table style="width:100%;border-collapse:collapse;font-family:var(--sans);font-size:0.72rem;color:var(--text-mid);">'
                        f'<tr><td style="padding:2px 0;width:1.2rem;">⬜</td><td style="padding:2px 4px;color:var(--text-muted);">Footprint</td><td style="padding:2px 0;text-align:right;font-weight:500;">{acres} acres</td></tr>'
                        f'<tr><td style="padding:2px 0;">🌿</td><td style="padding:2px 4px;color:var(--text-muted);">Soil / Use</td><td style="padding:2px 0;text-align:right;font-weight:500;">{crop}</td></tr>'
                        f'<tr><td style="padding:2px 0;">✈</td><td style="padding:2px 4px;color:var(--text-muted);">Airport</td><td style="padding:2px 0;text-align:right;font-weight:500;">{airport}</td></tr>'
                        f'<tr><td style="padding:2px 0;">🏛</td><td style="padding:2px 4px;color:var(--text-muted);">Heritage</td><td style="padding:2px 0;text-align:right;font-weight:500;">{heritage}</td></tr>'
                        f'</table></div>',
                        unsafe_allow_html=True,
                    )
                    if fired:
                        chips = "".join(
                            f'<span style="display:inline-block;background:var(--success-bg);color:var(--success-text);'
                            f'border:1px solid var(--success-border);font-family:var(--sans);'
                            f'font-size:0.58rem;padding:2px 6px;margin:2px 2px 0 0;">✓ {sig}</span>'
                            for sig in fired
                        )
                        st.markdown(f'<div style="padding:0.5rem 0 0.6rem;">{chips}</div>', unsafe_allow_html=True)
                    else:
                        st.markdown(
                            '<div style="padding:0.5rem 0 0.6rem;font-family:var(--sans);'
                            'font-size:0.7rem;color:var(--text-muted);font-style:italic;">No signals fired</div>',
                            unsafe_allow_html=True,
                        )
                    btn_label = "Close Report  ✕" if is_open else "View Intelligence Report"
                    if st.button(btn_label, key=f"dossier_btn_{idx}", use_container_width=True):
                        st.session_state.active_dossier = None if is_open else idx
                        st.rerun()

            # After each row: inject report if this row contains the active card
            if active_dossier is not None and row_start <= active_dossier < row_start + row_size:
                render_report(active_dossier, parcels[active_dossier])

    # ── Map ───────────────────────────────────────────────────────────────────
    with tab_map:
        st.caption(
            "Parcels drawn to scale · coloured by Opportunity Score.  "
            "Olive ≥ 30  ·  Gold 15–29  ·  Grey < 15.  Click any parcel for details."
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
    '<p style="font-family:var(--serif);font-size:0.9rem;'
    'color:var(--text-muted);text-align:center;letter-spacing:0.08em;">'
    'Giovanni Bonelli Group &nbsp;·&nbsp; Parcel Scout &nbsp;·&nbsp; Tuscany Acquisition Intelligence'
    '</p>',
    unsafe_allow_html=True,
)
