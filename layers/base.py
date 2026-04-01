#!/usr/bin/env python3
"""
layers/base.py — BaseLayer

Every acquisition layer inherits from this class and must implement `run()`.
Think of BaseLayer as the contract: every layer promises to accept a parcel dict
and return a standardised result dict so the runner scripts can handle them
all the same way without knowing the internal details of each layer.

Result structure every layer must return:
    {
        "layer":   str,          # machine-readable layer name, e.g. "satellite_neglect"
        "label":   str,          # human-readable label shown in the console
        "signal":  bool,         # True = the layer fired (anomaly / opportunity detected)
        "score":   float | None, # 0.0 – 1.0 confidence / strength (None if not applicable)
        "detail":  str,          # one-line human-readable explanation
        "data":    dict,         # layer-specific raw values for the CSV / JSON
        "paid":    bool,         # True = layer requires a paid API subscription
    }
"""

from abc import ABC, abstractmethod


class BaseLayer(ABC):
    """Abstract base class for all 9 acquisition-signal layers."""

    # Subclasses set these class-level attributes.
    name: str  = "base"          # snake_case layer ID
    label: str = "Base Layer"   # display name
    paid: bool = False           # True if a paid API is required

    @abstractmethod
    def run(self, parcel: dict) -> dict:
        """
        Analyse `parcel` and return a standardised result dict.

        Parameters
        ----------
        parcel : dict
            A parcel dict as produced by scout.py's filter_parcels().
            Guaranteed keys: lat, lon, osm_id, osm_type, name,
            primary_crop_type, parcel_sqm, parcel_acres.

        Returns
        -------
        dict  — see module docstring for the required schema.
        """

    # ── Helpers shared by all layers ─────────────────────────────────────────

    def _empty_result(self, detail: str = "", signal: bool = False) -> dict:
        """Return a valid empty result (used when the layer is skipped or fails)."""
        return {
            "layer":  self.name,
            "label":  self.label,
            "signal": signal,
            "score":  None,
            "detail": detail,
            "data":   {},
            "paid":   self.paid,
        }

    def _paid_stub(self) -> dict:
        """Return a clearly labelled stub when the paid API key is missing."""
        return self._empty_result(
            detail=f"PAID FEATURE — configure credentials in config.py to activate"
        )

    @staticmethod
    def _clamp(value: float, lo: float = 0.0, hi: float = 1.0) -> float:
        """Clamp a float to [lo, hi]."""
        return max(lo, min(hi, value))
