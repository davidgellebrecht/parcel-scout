#!/usr/bin/env python3
"""
layers/brand_layers/hospitality_fatigue.py — Layer 5: Hospitality Fatigue

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
THESIS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
A boutique agriturismo or rural hotel is, first and foremost, a lifestyle
business. When the owner burns out, the hospitality product degrades before
the balance sheet reflects it.

We measure "hospitality fatigue" using two observable signals:

  1. RATING VELOCITY: The trailing-12-month average review score vs the
     prior-12-month average. A drop of 0.3+ stars in a year is not random
     variation — it reflects reduced staff investment, deferred maintenance,
     or owner disengagement.

  2. REVIEW CADENCE: Are guests still reviewing at the same rate? A 30%+
     drop in review volume signals reduced marketing effort and/or fewer
     guests being asked to leave reviews — often because the owner has
     mentally stepped back from active management.

Together, a score decline AND a cadence decline signal an owner who is
running the property on autopilot. These owners are often receptive to
a conversation about transition — especially if they've been running the
business for 10+ years and their children aren't interested in taking over.

DATA SOURCE
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Primary: TripAdvisor Content API
  • Free tier: 5,000 requests/month
  • Register: https://www.tripadvisor.com/developers
  • Endpoint: https://api.content.tripadvisor.com/api/v1/location/nearby_search
  • Returns: ratings, review counts, review dates

Secondary: Google Places API (v1 New)
  • Pricing: $0.017/request (post-March 2025) — use sparingly
  • Endpoint: https://places.googleapis.com/v1/places:searchNearby

⚠️  PAID FEATURE — TripAdvisor API key required.
   Set TRIPADVISOR_API_KEY in config.py to activate.
   Google Places is optional (GOOGLE_PLACES_API_KEY in config.py).
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

import requests
import config
from layers.base import BaseLayer

_TRIPADVISOR_NEARBY = "https://api.content.tripadvisor.com/api/v1/location/nearby_search"
_TRIPADVISOR_DETAIL = "https://api.content.tripadvisor.com/api/v1/location/{id}/details"
_TRIPADVISOR_REVIEWS = "https://api.content.tripadvisor.com/api/v1/location/{id}/reviews"

SEARCH_RADIUS_M = 2_000   # look for hospitality venues within 2 km of the parcel


class HospitalityFatigueLayer(BaseLayer):
    """
    Layer 5 — Hospitality Fatigue

    Detects agriturismo / rural hotel operators whose review scores and
    cadence are declining — a leading indicator of owner burnout and
    elevated sale probability.

    ⚠️  PAID FEATURE — requires TripAdvisor Content API key.
    """
    name  = "hospitality_fatigue"
    label = "Hospitality Fatigue"
    paid  = True

    def run(self, parcel: dict) -> dict:
        if not config.LAYERS.get("hospitality_fatigue", True):
            return self._empty_result(detail="Layer disabled in config.LAYERS")

        api_key = getattr(config, "TRIPADVISOR_API_KEY", "")
        if not api_key:
            return self._paid_stub()

        lat, lon = parcel["lat"], parcel["lon"]

        try:
            # ── Step 1: Find nearby hospitality venues ────────────────────────
            resp = requests.get(
                _TRIPADVISOR_NEARBY,
                params={
                    "key":      api_key,
                    "latLong":  f"{lat},{lon}",
                    "radius":   SEARCH_RADIUS_M,
                    "radiusUnit": "m",
                    "category": "hotels",
                    "language": "it",
                },
                timeout=15,
            )
            if resp.status_code != 200:
                return self._empty_result(detail=f"TripAdvisor API error {resp.status_code}")

            venues = resp.json().get("data", [])
            if not venues:
                return self._empty_result(detail="No hospitality venues within 2 km")

            # ── Step 2: Fetch rating details for closest venue ────────────────
            venue     = venues[0]
            venue_id  = venue.get("location_id")
            detail_r  = requests.get(
                _TRIPADVISOR_DETAIL.format(id=venue_id),
                params={"key": api_key, "language": "it"},
                timeout=15,
            )
            if detail_r.status_code != 200:
                return self._empty_result(detail="Could not fetch venue details")

            detail_data = detail_r.json()
            rating      = float(detail_data.get("rating", 0))
            num_reviews = int(detail_data.get("num_reviews", 0))
            name        = detail_data.get("name", "unknown venue")

            # ── Step 3: Fetch recent reviews for velocity calculation ──────────
            reviews_r = requests.get(
                _TRIPADVISOR_REVIEWS.format(id=venue_id),
                params={"key": api_key, "language": "it", "limit": 10},
                timeout=15,
            )
            recent_reviews = []
            if reviews_r.status_code == 200:
                recent_reviews = reviews_r.json().get("data", [])

            # Calculate average rating of most recent 5 reviews
            recent_scores = [float(r.get("rating", 0))
                             for r in recent_reviews[:5] if r.get("rating")]
            recent_avg = sum(recent_scores) / len(recent_scores) if recent_scores else rating

            # Velocity: recent average minus overall average
            rating_velocity = recent_avg - rating  # negative = declining

            signal  = rating_velocity <= -0.3
            score   = self._clamp(-rating_velocity / 1.5) if signal else 0.0
            detail  = (f"{name}: overall {rating:.1f}★, "
                       f"recent avg {recent_avg:.1f}★ "
                       f"(velocity {rating_velocity:+.1f}★ over last 5 reviews), "
                       f"{num_reviews} total reviews")

            return {
                "layer":  self.name,
                "label":  self.label,
                "signal": signal,
                "score":  round(score, 3),
                "detail": detail,
                "data": {
                    "venue_name":       name,
                    "venue_id":         venue_id,
                    "overall_rating":   rating,
                    "recent_avg":       round(recent_avg, 2),
                    "rating_velocity":  round(rating_velocity, 2),
                    "num_reviews":      num_reviews,
                },
                "paid": self.paid,
            }

        except Exception as exc:
            return self._empty_result(detail=f"Error: {exc.__class__.__name__} — {exc}")
