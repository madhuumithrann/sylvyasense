"""Map layer catalogue.

Defines every layer the UI can switch on, which grid backs it, and how it is
painted. The catalogue is served to the frontend so the layer panel and the
legends are generated from the same definition the tiles are rendered from.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import numpy as np

from app.analysis.pipeline import AnalysisResult
from app.science.carbon import CARBON_FRACTION
from app.science.confidence import GEDI_SUPPORT_RADIUS_CELLS


@dataclass(frozen=True)
class LayerSpec:
    key: str
    label: str
    group: str
    kind: str                 # "continuous" | "categorical" | "rgb"
    ramp: str | None
    description: str
    source: str
    requires: str = "analysis"   # "analysis" | "change"
    default_opacity: float = 0.85

    def as_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "label": self.label,
            "group": self.group,
            "kind": self.kind,
            "ramp": self.ramp,
            "description": self.description,
            "source": self.source,
            "requires": self.requires,
            "default_opacity": self.default_opacity,
        }


LAYERS: tuple[LayerSpec, ...] = (
    # --- Optical ---------------------------------------------------------
    LayerSpec("truecolor", "True colour", "Optical", "rgb", None,
              "Red / green / blue surface reflectance composite", "Sentinel-2 L2A"),
    LayerSpec("falsecolor", "False colour (NIR)", "Optical", "rgb", None,
              "Near-infrared / red / green — vegetation reads bright red", "Sentinel-2 L2A"),
    LayerSpec("ndvi", "NDVI", "Optical", "continuous", "ndvi",
              "Normalised Difference Vegetation Index", "Sentinel-2 L2A"),
    LayerSpec("evi", "EVI", "Optical", "continuous", "evi",
              "Enhanced Vegetation Index — resists canopy saturation", "Sentinel-2 L2A"),
    LayerSpec("ndmi", "NDMI (moisture)", "Optical", "continuous", "ndmi",
              "Canopy moisture content", "Sentinel-2 L2A"),

    # --- Radar -----------------------------------------------------------
    LayerSpec("vv", "VV backscatter", "Radar", "continuous", "vv",
              "Co-polarised C-band backscatter", "Sentinel-1 GRD"),
    LayerSpec("vh", "VH backscatter", "Radar", "continuous", "vh",
              "Cross-polarised backscatter — tracks canopy volume", "Sentinel-1 GRD"),
    LayerSpec("rvi", "Radar vegetation index", "Radar", "continuous", "rvi",
              "Dual-pol RVI (Kim & van Zyl 2009)", "Sentinel-1 GRD"),

    # --- Forest ----------------------------------------------------------
    LayerSpec("canopy_cover", "Canopy cover", "Forest", "continuous", "canopy_cover",
              "Fractional canopy cover from scaled NDVI", "Derived — Sentinel-2"),
    LayerSpec("agb", "Aboveground biomass", "Forest", "continuous", "agb",
              "Modelled biomass density", "SylvaSense model"),
    LayerSpec("carbon", "Carbon density", "Forest", "continuous", "carbon",
              "Aboveground carbon, IPCC carbon fraction 0.47", "SylvaSense model"),
    LayerSpec("worldcover", "Land cover", "Forest", "categorical", "worldcover",
              "ESA WorldCover classes", "ESA WorldCover v200"),

    # --- Quality ---------------------------------------------------------
    LayerSpec("confidence", "Confidence score", "Quality", "continuous", "confidence",
              "Composite confidence in the biomass estimate", "SylvaSense model"),
    LayerSpec("confidence_class", "Confidence class", "Quality", "categorical",
              "confidence_class", "High / survey recommended / insufficient",
              "SylvaSense model"),
    LayerSpec("agb_sd", "Biomass uncertainty", "Quality", "continuous", "agb_sd",
              "Standard deviation implied by the 90% prediction interval",
              "SylvaSense model"),
    LayerSpec("gedi_density", "GEDI coverage", "Quality", "continuous", "gedi_density",
              "Calibration footprint density", "GEDI L4A"),
    LayerSpec("cloud", "Clear observations", "Quality", "continuous", "cloud",
              "Share of observations that were cloud-free", "Sentinel-2 L2A"),

    # --- Terrain ---------------------------------------------------------
    LayerSpec("elevation", "Elevation", "Terrain", "continuous", "elevation",
              "Ground elevation", "Copernicus DEM GLO-30"),
    LayerSpec("slope", "Slope", "Terrain", "continuous", "slope",
              "Terrain slope", "Copernicus DEM GLO-30"),

    # --- Change ----------------------------------------------------------
    LayerSpec("agb_change", "Biomass change", "Change", "continuous", "agb_change",
              "Change in biomass between two epochs", "SylvaSense model",
              requires="change"),
    LayerSpec("carbon_change", "Carbon change", "Change", "continuous", "carbon_change",
              "Change in carbon between two epochs", "SylvaSense model",
              requires="change"),
    LayerSpec("change_class", "Change significance", "Change", "categorical",
              "change_class", "Per-cell change significance at 95%",
              "SylvaSense model", requires="change"),
)

LAYER_INDEX = {layer.key: layer for layer in LAYERS}


def _gedi_density_grid(result: AnalysisResult) -> np.ndarray:
    """Footprint counts per cell, box-summed over the support radius."""
    b = result.bundle
    n_lat, n_lon = b.shape
    counts = np.zeros((n_lat, n_lon), dtype=np.float64)
    if b.gedi is None or len(b.gedi) == 0:
        return np.where(b.mask, counts, np.nan)

    col = np.clip(np.searchsorted(b.lons, b.gedi.lon) - 1, 0, n_lon - 1)
    row = np.clip(np.searchsorted(-b.lats, -b.gedi.lat) - 1, 0, n_lat - 1)
    np.add.at(counts, (row, col), 1.0)

    r = GEDI_SUPPORT_RADIUS_CELLS
    padded = np.pad(counts, r + 1, mode="constant")
    integral = padded.cumsum(axis=0).cumsum(axis=1)
    size = 2 * r + 1
    local = (
        integral[size:, size:]
        - integral[:-size, size:]
        - integral[size:, :-size]
        + integral[:-size, :-size]
    )[:n_lat, :n_lon]
    return np.where(b.mask, local, np.nan)


#: How each single-grid layer is obtained from a completed analysis.
GRID_RESOLVERS: dict[str, Callable[[AnalysisResult], np.ndarray | None]] = {
    "ndvi": lambda r: r.stack.get("ndvi"),
    "evi": lambda r: r.stack.get("evi"),
    "ndmi": lambda r: r.stack.get("ndmi"),
    "vv": lambda r: r.stack.get("vv_db"),
    "vh": lambda r: r.stack.get("vh_db"),
    "rvi": lambda r: r.stack.get("rvi"),
    "canopy_cover": lambda r: (
        r.stack["canopy_cover"] * 100.0 if "canopy_cover" in r.stack else None
    ),
    "agb": lambda r: r.biomass.agb,
    "agb_sd": lambda r: r.biomass.agb_sd,
    "carbon": lambda r: r.biomass.agb * CARBON_FRACTION,
    "confidence": lambda r: r.confidence.score,
    "confidence_class": lambda r: r.confidence.classes.astype(np.float64),
    "gedi_density": _gedi_density_grid,
    "cloud": lambda r: (
        r.bundle.optical.valid_fraction * 100.0 if r.bundle.optical else None
    ),
    "elevation": lambda r: (
        r.bundle.terrain.elevation_m if r.bundle.terrain else None
    ),
    "slope": lambda r: r.bundle.terrain.slope_deg if r.bundle.terrain else None,
    "worldcover": lambda r: (
        r.bundle.landcover.classes if r.bundle.landcover else None
    ),
}

#: Band triples for the RGB composites.
RGB_RESOLVERS: dict[str, tuple[str, str, str]] = {
    "truecolor": ("B4", "B3", "B2"),
    "falsecolor": ("B8", "B4", "B3"),
}


def masked(result: AnalysisResult, grid: np.ndarray | None) -> np.ndarray | None:
    """Blank everything outside the AOI so tiles never bleed past the polygon."""
    if grid is None:
        return None
    out = np.asarray(grid, dtype=np.float64).copy()
    out[~result.bundle.mask] = np.nan
    return out


def catalogue(available_change: bool = False) -> dict[str, Any]:
    groups: dict[str, list[dict[str, Any]]] = {}
    for layer in LAYERS:
        if layer.requires == "change" and not available_change:
            continue
        groups.setdefault(layer.group, []).append(layer.as_dict())
    return {
        "groups": [
            {"name": name, "layers": layers} for name, layers in groups.items()
        ]
    }
