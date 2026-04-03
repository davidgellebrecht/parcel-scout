#!/usr/bin/env python3
"""
layers/geo_layers/napa_neighbor.py — Layer 4: Napa Neighbor Ripple

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
THESIS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
When a marquee buyer — LVMH, Antinori, Frescobaldi, Allegrini — acquires
a vineyard in a region, three things happen within 36 months:

  1. INFRASTRUCTURE LIFT: The new owner invests in road access, irrigation,
     cantina (winery) upgrades, and hospitality facilities that spill over
     to neighboring parcels.

  2. PRESS MAGNETISM: Wine journalists, travel writers, and luxury agencies
     begin covering the area — raising the entire zone's profile.

  3. LAND VALUE APPRECIATION: Comparable parcels within ~8 km (5 miles) of
     the anchor acquisition typically see 15–30% value appreciation as the
     "tide rises" — but THIS APPRECIATION TAKES 2–4 YEARS to fully price in.

The window between the marquee acquisition and the full repricing of
neighboring land is where we operate. A parcel 3 km from a recent
Antinori acquisition is underpriced relative to where it will be in 3 years.

This layer is named for the "Napa Effect" — when Robert Mondavi and later
large estates bought in Napa Valley in the 1970s–80s, they created the
infrastructure and press infrastructure that made the entire valley premium.
The same pattern plays out in Tuscany today.

DATA SOURCE
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Hardcoded marquee acquisition coordinates — updated manually as new
deals are announced in the trade press (Decanter, Wine Spectator, MFF).

No API required. Free to run.

Sources used to compile the list below:
  • Antinori: antinori.it/en/our-estates/
  • LVMH (Hennessy Estates): lvmh.com/houses/wines-spirits/
  • Frescobaldi: frescobaldi.com/en/estates/
  • Allegrini: allegrini.it/en/estate/
  • Wine Spectator acquisition news archive

HOW TO ADD NEW ACQUISITIONS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Add a new entry to MARQUEE_ACQUISITIONS below:
    {
        "name":     "Estate Name",
        "buyer":    "Buyer Corp",
        "lat":      43.0000,
        "lon":      11.0000,
        "year":     2023,
        "source":   "Decanter March 2023",
    }
"""

import sys
import os
import math
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

import config
from layers.base import BaseLayer


# ── Marquee acquisitions in Tuscany ──────────────────────────────────────────
# Coordinates are the approximate centroid of each estate.
# Add new entries here as deals are announced in the trade press.
# Sources: Decanter, Wine Spectator, WineNews, official company announcements.
# NOTE: entries with year <= (current_year - RECENT_YEARS) score 0.1 (zone anchor
# only); entries within the RECENT_YEARS window score on a distance decay curve.
MARQUEE_ACQUISITIONS = [
    # ── Antinori — long-term zone anchors (pre-2016, score 0.1) ───────────────
    {
        "name":   "Pèppoli (Chianti Classico)",
        "buyer":  "Antinori",
        "lat":    43.5070, "lon": 11.4011,
        "year":   1987,
        "source": "antinori.it",
    },
    {
        "name":   "Badia a Passignano (Chianti Classico)",
        "buyer":  "Antinori",
        "lat":    43.5305, "lon": 11.3227,
        "year":   1987,
        "source": "antinori.it",
    },
    {
        "name":   "La Braccesca (Vino Nobile di Montepulciano)",
        "buyer":  "Antinori",
        "lat":    43.1014, "lon": 11.8012,
        "year":   1990,
        "source": "antinori.it",
    },
    # ── Frescobaldi — long-term zone anchors ──────────────────────────────────
    {
        "name":   "Castelgiocondo (Brunello di Montalcino)",
        "buyer":  "Frescobaldi",
        "lat":    42.9804, "lon": 11.4670,
        "year":   1989,
        "source": "frescobaldi.com",
    },
    {
        "name":   "Luce della Vite (Brunello di Montalcino)",
        "buyer":  "Frescobaldi / Mondavi JV",
        "lat":    43.0350, "lon": 11.5020,
        "year":   1995,
        "source": "frescobaldi.com",
    },
    {
        "name":   "Ornellaia (Bolgheri)",
        "buyer":  "Marchesi Frescobaldi",
        "lat":    43.2336, "lon": 10.6170,
        "year":   2005,
        "source": "Wine Spectator 2005",
    },
    # ── Allegrini ─────────────────────────────────────────────────────────────
    {
        "name":   "Il Bruciato / Poggio al Tesoro (Bolgheri)",
        "buyer":  "Allegrini",
        "lat":    43.2040, "lon": 10.6890,
        "year":   2002,
        "source": "allegrini.it",
    },
    # ── Avignonesi — international ownership transfer ─────────────────────────
    {
        "name":   "Avignonesi (Vino Nobile di Montepulciano)",
        "buyer":  "Virginie Saverys (Belgium)",
        "lat":    43.0930, "lon": 11.8470,
        "year":   2009,
        "source": "Vinous / Decanter",
    },
    # ── Argiano — South American capital enters Brunello ──────────────────────
    {
        "name":   "Argiano (Brunello di Montalcino)",
        "buyer":  "André Esteves / BTG Pactual (Brazil)",
        "lat":    43.0080, "lon": 11.4780,
        "year":   2013,
        "source": "Decanter 2013",
    },
    # ── EPI Group (France) — two acquisitions, both in active window ──────────
    {
        "name":   "Biondi Santi — Tenuta Greppo (Brunello di Montalcino)",
        "buyer":  "EPI Group (France)",
        "lat":    43.0510, "lon": 11.4940,
        "year":   2016,
        "source": "Decanter / Wine Spectator 2017",
    },
    {
        "name":   "Isole e Olena (Chianti Classico)",
        "buyer":  "EPI / Christofer Descours (France)",
        "lat":    43.5300, "lon": 11.1700,
        "year":   2022,
        "source": "Wine Industry Advisor / WineNews June 2022",
    },
    # ── AtlasInvest — Belgian private equity enters Brunello ──────────────────
    {
        "name":   "Poggio Antico (Brunello di Montalcino)",
        "buyer":  "AtlasInvest / Marcel Van Poecke (Belgium)",
        "lat":    43.1010, "lon": 11.4370,
        "year":   2017,
        "source": "Decanter / Wine Spectator 2017",
    },
    # ── Castiglion del Bosco — sold by Ferragamo family, new owner undisclosed ─
    {
        "name":   "Castiglion del Bosco (Brunello di Montalcino)",
        "buyer":  "Undisclosed international family office",
        "lat":    43.0955, "lon": 11.4255,
        "year":   2022,
        "source": "WineNews / The Drinks Business March 2022",
    },
    # ── Boutinot — UK trade capital enters Chianti ────────────────────────────
    {
        "name":   "Podere Il Carnasciale (Chianti)",
        "buyer":  "Boutinot Group",
        "lat":    43.4350, "lon": 11.3550,
        "year":   2018,
        "source": "Decanter 2018",
    },
    # ── Valdipiatta — US hospitality capital enters Vino Nobile (2025) ────────
    {
        "name":   "Tenuta Valdipiatta (Vino Nobile di Montepulciano)",
        "buyer":  "Michael Cioffi / Monteverdi Tuscany (USA)",
        "lat":    43.1060, "lon": 11.7940,
        "year":   2025,
        "source": "Wine Spectator / The Drinks Business Jan 2025",
    },
]

# Radius within which we flag the "ripple effect" — 8 km ≈ 5 miles.
# Within this radius, land value appreciation from the marquee acquisition
# is likely but may not yet be fully reflected in listing prices.
RIPPLE_RADIUS_KM = 8.0

# Recent threshold: acquisitions within this many years are considered
# "active" ripple events (still in the appreciation window).
RECENT_YEARS = 10


def _haversine_km(lat1, lon1, lat2, lon2) -> float:
    R = 6_371.0
    φ1, φ2 = math.radians(lat1), math.radians(lat2)
    dφ = math.radians(lat2 - lat1)
    dλ = math.radians(lon2 - lon1)
    a  = math.sin(dφ/2)**2 + math.cos(φ1)*math.cos(φ2)*math.sin(dλ/2)**2
    return R * 2 * math.asin(math.sqrt(a))


class NapaNeighborLayer(BaseLayer):
    """
    Layer 4 — Napa Neighbor Ripple

    Flags parcels within 8 km of a marquee estate acquisition, where land
    values are likely to appreciate as the anchor investor's infrastructure
    and press investments raise the entire zone's profile.
    """
    name  = "napa_neighbor"
    label = "Napa Neighbor Ripple"
    paid  = False   # free — hardcoded coordinates, no API required

    def run(self, parcel: dict) -> dict:
        if not config.LAYERS.get("napa_neighbor", True):
            return self._empty_result(detail="Layer disabled in config.LAYERS")

        lat, lon = parcel["lat"], parcel["lon"]
        from datetime import date
        current_year = date.today().year

        # ── Find all marquee acquisitions within ripple radius ────────────────
        neighbors = []
        for acq in MARQUEE_ACQUISITIONS:
            dist_km = _haversine_km(lat, lon, acq["lat"], acq["lon"])
            if dist_km <= RIPPLE_RADIUS_KM:
                years_ago = current_year - acq["year"]
                neighbors.append({
                    "name":      acq["name"],
                    "buyer":     acq["buyer"],
                    "year":      acq["year"],
                    "years_ago": years_ago,
                    "dist_km":   round(dist_km, 2),
                    "recent":    years_ago <= RECENT_YEARS,
                })

        if not neighbors:
            return self._empty_result(
                detail=f"No marquee acquisitions within {RIPPLE_RADIUS_KM:.0f} km"
            )

        # Sort by distance — closest first
        neighbors.sort(key=lambda x: x["dist_km"])
        closest = neighbors[0]

        # Signal fires if ANY neighbor is a recent acquisition
        recent_neighbors = [n for n in neighbors if n["recent"]]
        signal = len(recent_neighbors) > 0

        # Score: 1.0 if the closest recent acquisition is <2 km, scaling out to 0.0 at 8 km
        if recent_neighbors:
            closest_recent = min(recent_neighbors, key=lambda x: x["dist_km"])
            score = self._clamp(1.0 - (closest_recent["dist_km"] / RIPPLE_RADIUS_KM))
        else:
            score = 0.1  # old acquisitions still provide some zone premium

        names = "; ".join(f"{n['buyer']} — {n['name']} ({n['dist_km']} km, {n['year']})"
                          for n in neighbors[:3])
        detail = (f"{len(neighbors)} marquee estate(s) within {RIPPLE_RADIUS_KM:.0f} km "
                  f"({len(recent_neighbors)} recent): {names}")

        return {
            "layer":  self.name,
            "label":  self.label,
            "signal": signal,
            "score":  round(score, 3),
            "detail": detail,
            "data": {
                "neighbor_count":        len(neighbors),
                "recent_neighbor_count": len(recent_neighbors),
                "closest_name":          closest["name"],
                "closest_buyer":         closest["buyer"],
                "closest_dist_km":       closest["dist_km"],
                "closest_year":          closest["year"],
                "all_neighbors":         neighbors,
            },
            "paid": self.paid,
        }
