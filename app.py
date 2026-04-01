#!/usr/bin/env python3
"""
app.py — Parcel Scout Web Portal

Streamlit interface wrapping the full rank.py pipeline.
Run locally:   streamlit run app.py
Deploy:        push to GitHub → share.streamlit.io
"""

import json
import copy
import time
from datetime import datetime

import folium
import pandas as pd
import streamlit as st
from streamlit_folium import st_folium

import config

# ── Pipeline imports (same functions rank.py uses) ────────────────────────────
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
    page_title="Parcel Scout",
    page_icon="🏡",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Load Streamlit secrets into config (for Streamlit Cloud deployment) ───────
# Credentials set in the Streamlit Cloud dashboard are securely stored in
# st.secrets — they never appear in the source code or git history.
# Wrapped in try/except because st.secrets raises when no secrets file exists
# (local dev without a secrets.toml). Falls back to whatever is in config.py.
try:
    config.OPENAPI_IT_KEY              = st.secrets.get("OPENAPI_IT_KEY",             config.OPENAPI_IT_KEY)
    config.SENTINEL_HUB_CLIENT_ID      = st.secrets.get("SENTINEL_HUB_CLIENT_ID",     config.SENTINEL_HUB_CLIENT_ID)
    config.SENTINEL_HUB_CLIENT_SECRET  = st.secrets.get("SENTINEL_HUB_CLIENT_SECRET", config.SENTINEL_HUB_CLIENT_SECRET)
    config.TRIPADVISOR_API_KEY         = st.secrets.get("TRIPADVISOR_API_KEY",        config.TRIPADVISOR_API_KEY)
    config.WINE_SEARCHER_API_KEY       = st.secrets.get("WINE_SEARCHER_API_KEY",      config.WINE_SEARCHER_API_KEY)
except Exception:
    pass  # no secrets.toml present (local dev) — config.py values are used as-is

# ── Signal metadata ───────────────────────────────────────────────────────────
# One record per signal in the same order as ALL_SIGNAL_KEYS / SIGNAL_LABELS.
# "desc" is the one-sentence explanation shown under each toggle.
SIGNAL_META = [
    # ── Group 2 signals ───────────────────────────────────────────────────────
    {
        "key":    "g2_premium_wine_zone",
        "label":  "DOCG Wine Zone",
        "group":  "group2",
        "config": ("GROUP2", "premium_wine_zone"),
        "paid":   False,
        "desc":   "Parcel falls within a premium Italian wine appellation where bottles regularly trade above $150.",
    },
    {
        "key":    "g2_distress_signal",
        "label":  "Distress Signal",
        "group":  "group2",
        "config": ("GROUP2", "distress_signal"),
        "paid":   False,
        "desc":   "Fire history (EU EFFIS satellite data) or abandoned land nearby — a neglect and financial stress proxy.",
    },
    {
        "key":    "g2_succession_signal",
        "label":  "Succession Signal",
        "group":  "group2",
        "config": ("GROUP2", "succession_signal"),
        "paid":   False,
        "desc":   "Italian family estate naming (Podere, Fattoria, Tenuta…) on or near the parcel suggests generational ownership nearing transition.",
    },
    {
        "key":    "g2_lodging_overlay",
        "label":  "Lodging Overlay",
        "group":  "group2",
        "config": ("GROUP2", "lodging_overlay"),
        "paid":   False,
        "desc":   "Existing tourism or hospitality operation nearby signals local planning precedent for agriturismo conversion under Italian Law 96/2006.",
    },
    # ── Acquisition layers ────────────────────────────────────────────────────
    {
        "key":    "layer_satellite_neglect_signal",
        "label":  "Satellite Neglect",
        "group":  "layer",
        "config": ("LAYERS", "satellite_neglect"),
        "paid":   False,
        "badge":  "free trial",
        "desc":   "NDVI satellite data shows vegetation vigor below neighboring parcels — the first measurable sign of absentee ownership.",
    },
    {
        "key":    "layer_permit_paralysis_signal",
        "label":  "Permit Paralysis",
        "group":  "layer",
        "config": ("LAYERS", "permit_paralysis"),
        "paid":   True,
        "badge":  "PAID",
        "desc":   "Owner has filed multiple renovation permits over years with no final approval — frustration that often precedes a willingness to sell.",
    },
    {
        "key":    "layer_zoning_alchemy_signal",
        "label":  "Zoning Alchemy",
        "group":  "layer",
        "config": ("LAYERS", "zoning_alchemy"),
        "paid":   True,
        "badge":  "PAID + free",
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
        "badge":  "PAID",
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
        "badge":  "PAID",
        "desc":   "Soil quality (DOCG zone, galestro geology) outperforms the current producer's critic scores — unlocked value for a new buyer.",
    },
    {
        "key":    "layer_succession_frag_signal",
        "label":  "Succession Fragmentation",
        "group":  "layer",
        "config": ("LAYERS", "succession_frag"),
        "paid":   True,
        "badge":  "PAID",
        "desc":   "Cadastral records show multiple co-owners — Italian inheritance law distributes estates equally, creating motivated-seller pressure.",
    },
    {
        "key":    "layer_owner_relocation_signal",
        "label":  "Owner Relocation",
        "group":  "layer",
        "config": ("LAYERS", "owner_relocation"),
        "paid":   True,
        "badge":  "PAID + free",
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

# ── Score helpers ─────────────────────────────────────────────────────────────

def rescore(parcels: list, active_keys: list) -> list:
    """
    Recompute opportunity_score using only the currently-active signal keys.
    This is instant — all signal values are already stored in the parcel dicts
    from the original scan. No Overpass queries or layer calls needed.
    """
    total = len(active_keys)
    result = []
    for p in parcels:
        p = dict(p)  # shallow copy so we don't mutate session state
        fired = sum(1 for k in active_keys if p.get(k)) if total else 0
        p["opportunity_score"] = round((fired / total) * 100, 1) if total else 0.0
        p["signals_fired"]     = fired
        result.append(p)
    return sorted(result, key=lambda x: x["opportunity_score"], reverse=True)


def score_color(score: float) -> str:
    if score >= 30:
        return "#4CAF82"   # green
    if score >= 15:
        return "#F6C026"   # amber
    return "#6B7280"       # grey


# ── Pipeline runner ───────────────────────────────────────────────────────────

def run_full_scan(filter_state: dict, g2_state: dict, layer_state: dict) -> list:
    """
    Run the complete Parcel Scout pipeline and return a ranked parcel list.
    All heavy Overpass queries happen here — results cached in session_state.
    """
    # Patch config from UI state
    for k, v in filter_state.items():
        config.FILTERS[k] = v
    for k, v in g2_state.items():
        config.GROUP2[k] = v
    for k, v in layer_state.items():
        config.LAYERS[k] = v

    # ── Step 1: Airports ──────────────────────────────────────────────────────
    st.session_state.scan_log.append("Fetching airport coordinates…")
    airports = fetch_airports() if filter_state["proximity_to_airport"] else []

    # ── Step 2: Historic sites ────────────────────────────────────────────────
    st.session_state.scan_log.append("Querying OpenStreetMap for historic sites…")
    historic_sites = fetch_historic_sites() if filter_state["historical_designation"] else []
    st.session_state.scan_log.append(f"  → {len(historic_sites):,} historic site(s) found")

    # ── Step 3: Agricultural parcels ──────────────────────────────────────────
    st.session_state.scan_log.append("Querying OpenStreetMap for agricultural parcels…")
    raw = fetch_agricultural_parcels() if filter_state["agricultural_land"] else fetch_broad_landuse()
    st.session_state.scan_log.append(f"  → {len(raw):,} raw OSM element(s) retrieved")

    # ── Step 4: Group 2 data ──────────────────────────────────────────────────
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

    # ── Step 5: Hard filters ──────────────────────────────────────────────────
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

    # ── Step 6: Group 2 annotation ────────────────────────────────────────────
    st.session_state.scan_log.append("Running Group 2 signal annotation…")
    parcels = annotate_group2(parcels, distress_elements, estate_features, tourism_nodes)

    # ── Step 7: All 9 acquisition layers ─────────────────────────────────────
    st.session_state.scan_log.append("Running all 9 acquisition layers…")
    parcels = run_all_layers(parcels)
    st.session_state.scan_log.append("  → All layers complete")

    return parcels


# ── Map builder ───────────────────────────────────────────────────────────────

def build_map(parcels: list) -> folium.Map:
    """
    Build a Folium map with one circle marker per parcel, colored by score tier.
    Clicking a marker shows a popup with the key details.
    """
    if not parcels:
        return folium.Map(location=[43.1, 11.4], zoom_start=9)

    lats = [p["lat"] for p in parcels]
    lons = [p["lon"] for p in parcels]
    center = [sum(lats) / len(lats), sum(lons) / len(lons)]
    m = folium.Map(location=center, zoom_start=10, tiles="CartoDB dark_matter")

    for p in parcels:
        score   = p.get("opportunity_score", 0)
        color   = "#4CAF82" if score >= 30 else "#F6C026" if score >= 15 else "#9CA3AF"
        name    = p.get("name") or p.get("gps_coordinates", "")
        signals = signals_fired_list(p)
        sig_html = "".join(
            f'<span style="background:#1f2937;color:#4CAF82;padding:2px 6px;'
            f'border-radius:4px;font-size:11px;margin:2px;">{s}</span>'
            for s in signals
        ) or "<em style='color:#6b7280'>no signals</em>"

        popup_html = f"""
        <div style="font-family:sans-serif;min-width:220px;color:#f0f2f6;background:#0e1117;padding:12px;border-radius:8px;">
          <div style="font-size:18px;font-weight:700;color:{color};">{score:.1f}<span style="font-size:12px;color:#9ca3af;">/100</span></div>
          <div style="font-size:13px;font-weight:600;margin:4px 0 8px;">{name[:50]}</div>
          <div style="font-size:11px;color:#9ca3af;margin-bottom:6px;">
            {p.get('primary_crop_type','').title()} &nbsp;·&nbsp;
            {p.get('parcel_acres',0):.1f} acres &nbsp;·&nbsp;
            {p.get('dist_airport_km',0):.1f} km to {p.get('airport_iata','')}
          </div>
          <div style="font-size:11px;color:#9ca3af;margin-bottom:8px;">
            Heritage: <strong style="color:#f0f2f6;">{p.get('closest_historic_tag','').title() or 'N/A'}</strong>
            ({p.get('heritage_confidence','')})
          </div>
          <div style="margin-top:6px;">{sig_html}</div>
          <div style="margin-top:8px;">
            <a href="{p.get('osm_url','')}" target="_blank"
               style="font-size:10px;color:#4CAF82;">View on OpenStreetMap ↗</a>
          </div>
        </div>
        """
        folium.CircleMarker(
            location=[p["lat"], p["lon"]],
            radius=10 + score / 10,
            color=color,
            fill=True,
            fill_color=color,
            fill_opacity=0.75,
            popup=folium.Popup(popup_html, max_width=280),
            tooltip=f"{score:.1f}/100 — {name[:35]}",
        ).add_to(m)

    return m


# ── Rankings table builder ────────────────────────────────────────────────────

def build_rankings_df(parcels: list) -> pd.DataFrame:
    rows = []
    for rank, p in enumerate(parcels, 1):
        score    = p.get("opportunity_score", 0)
        fired    = signals_fired_list(p)
        sig_str  = " · ".join(fired) if fired else "—"
        rows.append({
            "Rank":        rank,
            "Score":       score,
            "Signals":     f"{p.get('signals_fired',0)}/{len(ALL_SIGNAL_KEYS)}",
            "Fired":       sig_str,
            "Crop":        p.get("primary_crop_type", "").title(),
            "Acres":       round(p.get("parcel_acres", 0), 1),
            "Airport":     f"{p.get('dist_airport_km',0):.1f} km ({p.get('airport_iata','')})",
            "Heritage":    f"{p.get('closest_historic_tag','').title()} ({p.get('heritage_confidence','')})",
            "Name / GPS":  p.get("name") or p.get("gps_coordinates", ""),
            "OSM URL":     p.get("osm_url", ""),
        })
    return pd.DataFrame(rows)


# ═══════════════════════════════════════════════════════════════════════════════
#  SIDEBAR
# ═══════════════════════════════════════════════════════════════════════════════

with st.sidebar:
    st.markdown("## 🏡 Parcel Scout")
    st.caption("Off-market Italian estate acquisition intelligence")
    st.divider()

    # ── Region ────────────────────────────────────────────────────────────────
    st.markdown("**Region**")
    region_display = st.text_input(
        "Region name (display only)",
        value=config.REGION,
        label_visibility="collapsed",
    )

    st.divider()

    # ── Hard Filters ──────────────────────────────────────────────────────────
    st.markdown("**Hard Filters**")
    st.caption("All enabled filters must pass — failing any one excludes the parcel.")

    filter_state = {}
    for fm in FILTER_META:
        filter_state[fm["key"]] = st.checkbox(
            fm["label"],
            value=config.FILTERS[fm["key"]],
            key=f"filter_{fm['key']}",
        )
        st.caption(fm["desc"])

    st.divider()

    # ── Acquisition Signals (Group 2) ─────────────────────────────────────────
    st.markdown("**Acquisition Signals**")
    st.caption("Annotation only — parcels are never excluded by these.")

    g2_state  = {}
    layer_state = {}

    for sm in SIGNAL_META:
        group, cfg_key = sm["config"]
        badge = sm.get("badge", "")
        badge_html = (
            f' <span style="font-size:10px;color:#9CA3AF;">[{badge}]</span>'
            if badge else ""
        )

        if sm["group"] == "group2":
            g2_state[cfg_key] = st.checkbox(
                sm["label"],
                value=getattr(config, group)[cfg_key],
                key=f"sig_{sm['key']}",
            )
            st.caption(sm["desc"])

    st.divider()

    # ── Acquisition Layers ────────────────────────────────────────────────────
    st.markdown("**Acquisition Layers**")
    st.caption("Toggle layers to adjust the Opportunity Score in real time.")

    for i, sm in enumerate(SIGNAL_META):
        if sm["group"] != "layer":
            continue
        group, cfg_key = sm["config"]
        badge = sm.get("badge", "")
        label = f"Layer {i-3} — {sm['label']}"   # layers start at index 4 (after 4 group2 items)
        paid_note = f" [{badge}]" if badge else ""

        layer_state[cfg_key] = st.checkbox(
            label + paid_note,
            value=getattr(config, group).get(cfg_key, True),
            key=f"layer_{sm['key']}",
        )
        st.caption(sm["desc"])

    st.divider()

    # ── Run Scan button ───────────────────────────────────────────────────────
    run_btn = st.button("🔍  Run Scan", type="primary", use_container_width=True)
    if st.session_state.get("scan_time"):
        elapsed = st.session_state.get("scan_elapsed", 0)
        st.caption(
            f"Last scan: {st.session_state.scan_time.strftime('%Y-%m-%d %H:%M')}  "
            f"({elapsed:.0f}s)"
        )


# ═══════════════════════════════════════════════════════════════════════════════
#  MAIN AREA
# ═══════════════════════════════════════════════════════════════════════════════

st.markdown("# Parcel Scout")
st.markdown(f"**{region_display}** — Off-market acquisition intelligence")

# ── Trigger scan ──────────────────────────────────────────────────────────────
if run_btn:
    st.session_state.scan_log = []
    t0 = time.time()

    with st.status("Running Parcel Scout scan…", expanded=True) as scan_status:
        log_placeholder = st.empty()

        # Monkey-patch the scan log to surface messages in the UI
        original_print = __builtins__.__dict__["print"] if isinstance(__builtins__, dict) else print

        def ui_print(*args, **kwargs):
            msg = " ".join(str(a) for a in args)
            st.session_state.scan_log.append(msg)
            log_placeholder.markdown(
                "\n".join(f"› {line}" for line in st.session_state.scan_log[-8:])
            )
            original_print(*args, **kwargs)

        import builtins
        builtins.print = ui_print

        try:
            parcels = run_full_scan(filter_state, g2_state, layer_state)
        finally:
            builtins.print = original_print

        elapsed = time.time() - t0
        st.session_state.parcels       = parcels
        st.session_state.scan_time     = datetime.now()
        st.session_state.scan_elapsed  = elapsed
        st.session_state.filter_state  = filter_state
        st.session_state.g2_state      = g2_state
        st.session_state.layer_state   = layer_state

        if parcels:
            scan_status.update(
                label=f"✅  Scan complete — {len(parcels)} parcel(s) found in {elapsed:.0f}s",
                state="complete",
            )
        else:
            scan_status.update(
                label="⚠️  Scan complete — no parcels passed all hard filters",
                state="error",
            )

# ── Display results ───────────────────────────────────────────────────────────
if "parcels" not in st.session_state or not st.session_state.parcels:
    if not st.session_state.get("parcels"):
        st.info(
            "Configure your filters and layers in the sidebar, then click **🔍 Run Scan** to begin.\n\n"
            "The scan queries OpenStreetMap and takes approximately 3–4 minutes for the full "
            "Province of Siena region."
        )
    else:
        st.warning("No parcels passed all hard filters. Try relaxing some filters in the sidebar.")
else:
    # Determine which signal keys are currently active (based on sidebar state)
    active_keys = [
        sm["key"]
        for sm in SIGNAL_META
        if (
            (sm["group"] == "group2" and g2_state.get(sm["config"][1], True))
            or (sm["group"] == "layer" and layer_state.get(sm["config"][1], True))
        )
    ]

    # Re-score with current toggle state (instant — no re-scan)
    parcels = rescore(st.session_state.parcels, active_keys)

    # ── Summary metrics ───────────────────────────────────────────────────────
    scores   = [p["opportunity_score"] for p in parcels]
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Parcels found",  len(parcels))
    col2.metric("Top score",      f"{max(scores):.1f}/100")
    col3.metric("Average score",  f"{sum(scores)/len(scores):.1f}/100")
    col4.metric("Signals active", f"{len(active_keys)}/13")

    # ── Export buttons ────────────────────────────────────────────────────────
    df_full  = build_rankings_df(parcels)
    csv_data = df_full.to_csv(index=False).encode("utf-8")
    json_data = json.dumps(parcels, indent=2, default=str).encode("utf-8")

    ecol1, ecol2, _ = st.columns([1, 1, 4])
    ecol1.download_button(
        "⬇ Export CSV",
        csv_data,
        file_name=f"parcel_scout_{datetime.now().strftime('%Y%m%d_%H%M')}.csv",
        mime="text/csv",
    )
    ecol2.download_button(
        "⬇ Export JSON",
        json_data,
        file_name=f"parcel_scout_{datetime.now().strftime('%Y%m%d_%H%M')}.json",
        mime="application/json",
    )

    st.divider()

    # ── Tabs ──────────────────────────────────────────────────────────────────
    tab_rank, tab_map, tab_raw = st.tabs(["📊  Rankings", "🗺  Map", "🗂  Raw Data"])

    # ── Tab 1: Rankings ───────────────────────────────────────────────────────
    with tab_rank:
        df_display = build_rankings_df(parcels)

        # Color the Score column
        def color_score(val):
            if val >= 30:
                return "color: #4CAF82; font-weight: 700;"
            if val >= 15:
                return "color: #F6C026; font-weight: 700;"
            return "color: #9CA3AF;"

        styled = (
            df_display.style
            .applymap(color_score, subset=["Score"])
            .format({"Score": "{:.1f}"})
            .hide(axis="index")
        )
        st.dataframe(styled, use_container_width=True, height=420)

        st.divider()
        st.markdown("### Parcel Detail")
        st.caption("Click any row above or expand a card below to view full signal breakdown.")

        for rank, p in enumerate(parcels, 1):
            score   = p["opportunity_score"]
            color   = score_color(score)
            name    = p.get("name") or p.get("gps_coordinates", "")
            fired   = signals_fired_list(p)

            with st.expander(
                f"#{rank}  {name[:55]}  —  **{score:.1f}/100**",
                expanded=(rank == 1),
            ):
                dc1, dc2, dc3 = st.columns(3)
                dc1.metric("Opportunity Score", f"{score:.1f}/100")
                dc1.metric("Crop Type",  p.get("primary_crop_type", "").title())
                dc2.metric("Parcel Size", f"{p.get('parcel_acres',0):.1f} acres")
                dc2.metric("Airport",    f"{p.get('dist_airport_km',0):.1f} km ({p.get('airport_iata','')})")
                dc3.metric("Heritage",   p.get("closest_historic_tag", "").title() or "N/A")
                dc3.metric("Confidence", p.get("heritage_confidence", "").title() or "N/A")

                st.markdown("**Signals fired:**")
                if fired:
                    sig_cols = st.columns(min(len(fired), 4))
                    for i, sig in enumerate(fired):
                        sig_cols[i % 4].success(f"✓ {sig}")
                else:
                    st.caption("No signals fired for this parcel.")

                unfired = [
                    sm["label"] for sm in SIGNAL_META
                    if sm["key"] in active_keys and not p.get(sm["key"])
                ]
                if unfired:
                    st.markdown("**Not triggered:**")
                    st.caption("  ·  ".join(unfired))

                st.markdown(
                    f"**[View on OpenStreetMap ↗]({p.get('osm_url','')})**  ·  "
                    f"GPS: `{p.get('gps_coordinates','')}`"
                )

                # Full signal detail table
                with st.expander("Full signal details"):
                    detail_rows = []
                    for sm in SIGNAL_META:
                        if sm["key"] not in active_keys:
                            continue
                        fired_flag = "✓" if p.get(sm["key"]) else "—"
                        detail_key = sm["key"].replace("_signal", "_detail")
                        detail_rows.append({
                            "Signal":  sm["label"],
                            "Fired":   fired_flag,
                            "Detail":  p.get(detail_key, ""),
                        })
                    st.dataframe(pd.DataFrame(detail_rows), use_container_width=True, hide_index=True)

    # ── Tab 2: Map ────────────────────────────────────────────────────────────
    with tab_map:
        st.caption(
            "Pins are sized and colored by Opportunity Score. "
            "Green ≥ 30 · Amber 15–29 · Grey < 15. Click any pin for details."
        )
        m = build_map(parcels)
        st_folium(m, use_container_width=True, height=560)

    # ── Tab 3: Raw Data ───────────────────────────────────────────────────────
    with tab_raw:
        st.caption("Complete field dump for all parcels, sorted by Opportunity Score.")
        all_keys = list(dict.fromkeys(k for p in parcels for k in p.keys()))
        df_raw   = pd.DataFrame([{k: p.get(k, "") for k in all_keys} for p in parcels])
        st.dataframe(df_raw, use_container_width=True, height=500)
