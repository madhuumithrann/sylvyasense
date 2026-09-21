"""Colour ramps for the analysis raster layers.

Each ramp is defined by hex stops plus the physical range it spans and the unit
it is in, so the frontend can render a correct legend from the same definition
the tiles were painted with — the legend can never drift from the pixels.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

import numpy as np


def _hex_to_rgb(value: str) -> tuple[int, int, int]:
    value = value.lstrip("#")
    return (int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16))


@dataclass(frozen=True)
class Ramp:
    key: str
    label: str
    unit: str
    vmin: float
    vmax: float
    stops: Sequence[str]
    description: str = ""
    reverse_is_bad: bool = False

    def lut(self, n: int = 256) -> np.ndarray:
        """(n, 3) uint8 lookup table interpolated between the stops."""
        rgb = np.array([_hex_to_rgb(s) for s in self.stops], dtype=np.float64)
        positions = np.linspace(0.0, 1.0, len(self.stops))
        target = np.linspace(0.0, 1.0, n)
        out = np.empty((n, 3), dtype=np.float64)
        for channel in range(3):
            out[:, channel] = np.interp(target, positions, rgb[:, channel])
        return np.clip(out, 0, 255).astype(np.uint8)

    def legend(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "label": self.label,
            "unit": self.unit,
            "vmin": self.vmin,
            "vmax": self.vmax,
            "stops": list(self.stops),
            "description": self.description,
        }


@dataclass(frozen=True)
class CategoryRamp:
    key: str
    label: str
    categories: Sequence[tuple[int, str, str]]  # (code, colour, label)
    description: str = ""

    def color_for(self, code: int) -> tuple[int, int, int] | None:
        for value, colour, _ in self.categories:
            if value == code:
                return _hex_to_rgb(colour)
        return None

    def legend(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "label": self.label,
            "categorical": True,
            "categories": [
                {"code": code, "color": colour, "label": label}
                for code, colour, label in self.categories
            ],
            "description": self.description,
        }


# --- Continuous ramps ---------------------------------------------------

VIRIDIS = ("#440154", "#414487", "#2a788e", "#22a884", "#7ad151", "#fde725")
MAGMA = ("#000004", "#3b0f70", "#8c2981", "#de4968", "#fe9f6d", "#fcfdbf")
GREENS = ("#08301c", "#12543a", "#1f7d4f", "#4caf50", "#9ccc65", "#e8f5b7")
NDVI_RAMP = ("#a6611a", "#d8b365", "#f5f5c8", "#a7d96a", "#4d9221", "#0d5c1f")
GREY = ("#0b0f14", "#39424d", "#6d7681", "#a8b0b8", "#dfe4e8")
DIVERGING_LOSS_GAIN = ("#b2182b", "#ef8a62", "#f7f7f7", "#8fcf8a", "#1a7837")
CONFIDENCE_RAMP = ("#8b1a1a", "#c1440e", "#e0a526", "#9bbf3c", "#2e7d32")
DENSITY = ("#1a0b2e", "#4a1f7c", "#8b3fa8", "#c96bb0", "#f0a8c0", "#ffe0e8")
CLOUD = ("#0a1420", "#1f3a52", "#4a6b85", "#8fa8bc", "#e8eff4")

RAMPS: dict[str, Ramp] = {
    "ndvi": Ramp(
        "ndvi", "NDVI", "index", -0.2, 1.0, NDVI_RAMP,
        "Normalised Difference Vegetation Index (Rouse et al. 1974)",
    ),
    "evi": Ramp(
        "evi", "EVI", "index", 0.0, 1.0, NDVI_RAMP,
        "Enhanced Vegetation Index (Huete et al. 2002)",
    ),
    "ndmi": Ramp(
        "ndmi", "NDMI", "index", -0.4, 0.6, ("#7f3b08", "#e0b080", "#f7f7f7", "#7fb8d4", "#08519c"),
        "Canopy moisture (Gao 1996)",
    ),
    "canopy_cover": Ramp(
        "canopy_cover", "Canopy cover", "%", 0.0, 100.0, GREENS,
        "Fractional canopy cover from scaled NDVI (Carlson & Ripley 1997)",
    ),
    "agb": Ramp(
        "agb", "Aboveground biomass", "Mg/ha", 0.0, 400.0, VIRIDIS,
        "Modelled aboveground biomass density",
    ),
    "agb_sd": Ramp(
        "agb_sd", "Biomass uncertainty", "Mg/ha", 0.0, 160.0, MAGMA,
        "Standard deviation implied by the 90% prediction interval",
    ),
    "carbon": Ramp(
        "carbon", "Carbon density", "tC/ha", 0.0, 190.0, MAGMA,
        "Aboveground carbon, IPCC carbon fraction 0.47",
    ),
    "vv": Ramp(
        "vv", "Sentinel-1 VV", "dB", -25.0, 0.0, GREY,
        "Co-polarised C-band backscatter",
    ),
    "vh": Ramp(
        "vh", "Sentinel-1 VH", "dB", -30.0, -5.0, GREY,
        "Cross-polarised C-band backscatter — tracks canopy volume",
    ),
    "rvi": Ramp(
        "rvi", "Radar vegetation index", "index", 0.0, 1.2, GREENS,
        "Dual-pol RVI (Kim & van Zyl 2009)",
    ),
    "confidence": Ramp(
        "confidence", "Confidence", "score", 0.0, 1.0, CONFIDENCE_RAMP,
        "Composite confidence in the biomass estimate",
    ),
    "gedi_density": Ramp(
        "gedi_density", "GEDI coverage", "footprints/cell", 0.0, 30.0, DENSITY,
        "Calibration footprint density",
    ),
    "cloud": Ramp(
        "cloud", "Clear observations", "%", 0.0, 100.0, CLOUD,
        "Share of observations that were cloud-free at each cell",
    ),
    "elevation": Ramp(
        "elevation", "Elevation", "m", 0.0, 2000.0,
        ("#0b3d2e", "#2e7d4f", "#a8b545", "#c98c3c", "#8c5a3c", "#f2f2f2"),
        "Copernicus DEM GLO-30",
    ),
    "slope": Ramp(
        "slope", "Slope", "°", 0.0, 45.0, MAGMA, "Terrain slope",
    ),
    "agb_change": Ramp(
        "agb_change", "Biomass change", "Mg/ha", -120.0, 120.0, DIVERGING_LOSS_GAIN,
        "Change in aboveground biomass between two epochs",
    ),
    "carbon_change": Ramp(
        "carbon_change", "Carbon change", "tC/ha", -56.0, 56.0, DIVERGING_LOSS_GAIN,
        "Change in aboveground carbon between two epochs",
    ),
    "canopy_change": Ramp(
        "canopy_change", "Canopy change", "%", -40.0, 40.0, DIVERGING_LOSS_GAIN,
        "Change in fractional canopy cover between two epochs",
    ),
}

# --- Categorical ramps ---------------------------------------------------

CATEGORY_RAMPS: dict[str, CategoryRamp] = {
    "confidence_class": CategoryRamp(
        "confidence_class",
        "Confidence class",
        (
            (2, "#2e7d32", "High confidence"),
            (1, "#e0a526", "Survey recommended"),
            (0, "#b3261e", "Insufficient data"),
        ),
        "Confidence banded into action classes",
    ),
    "change_class": CategoryRamp(
        "change_class",
        "Change class",
        (
            (1, "#b2182b", "Significant loss"),
            (2, "#1a7837", "Significant gain"),
            (0, "#5a6472", "No significant change"),
        ),
        "Per-cell change significance at 95%",
    ),
    "worldcover": CategoryRamp(
        "worldcover",
        "Land cover",
        (
            (10, "#1f7d4f", "Tree cover"),
            (20, "#ffbb22", "Shrubland"),
            (30, "#ffff4c", "Grassland"),
            (40, "#f096ff", "Cropland"),
            (50, "#fa0000", "Built-up"),
            (60, "#b4b4b4", "Bare / sparse"),
            (70, "#f0f0f0", "Snow and ice"),
            (80, "#0064c8", "Water"),
            (90, "#0096a0", "Wetland"),
            (95, "#00cf75", "Mangroves"),
            (100, "#fae6a0", "Moss and lichen"),
        ),
        "ESA WorldCover classes",
    ),
}


def legends() -> dict[str, Any]:
    return {
        **{k: v.legend() for k, v in RAMPS.items()},
        **{k: v.legend() for k, v in CATEGORY_RAMPS.items()},
    }
