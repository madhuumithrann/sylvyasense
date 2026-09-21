"""Spectral and radar indices, and fractional canopy cover.

Every formulation here is a published one, cited at its definition, so any
number the UI shows can be traced back to a method rather than to a constant
someone chose.
"""

from __future__ import annotations

import numpy as np

from app.providers.base import ObservationBundle

# Endmember NDVI values for the scaled-NDVI cover retrieval.
# Carlson & Ripley (1997); Gutman & Ignatov (1998).
NDVI_SOIL = 0.12
NDVI_VEG = 0.90


def _safe_ratio(num: np.ndarray, den: np.ndarray) -> np.ndarray:
    out = np.full_like(num, np.nan, dtype=np.float64)
    ok = np.isfinite(num) & np.isfinite(den) & (np.abs(den) > 1e-9)
    out[ok] = num[ok] / den[ok]
    return out


def ndvi(nir: np.ndarray, red: np.ndarray) -> np.ndarray:
    """Normalised Difference Vegetation Index — Rouse et al. (1974)."""
    return _safe_ratio(nir - red, nir + red)


def evi(nir: np.ndarray, red: np.ndarray, blue: np.ndarray) -> np.ndarray:
    """Enhanced Vegetation Index — Huete et al. (2002). Resists canopy saturation."""
    return _safe_ratio(2.5 * (nir - red), nir + 6.0 * red - 7.5 * blue + 1.0)


def savi(nir: np.ndarray, red: np.ndarray, soil_factor: float = 0.5) -> np.ndarray:
    """Soil-Adjusted Vegetation Index — Huete (1988)."""
    return _safe_ratio((nir - red) * (1.0 + soil_factor), nir + red + soil_factor)


def ndmi(nir: np.ndarray, swir1: np.ndarray) -> np.ndarray:
    """Normalised Difference Moisture Index — Gao (1996). Canopy water content."""
    return _safe_ratio(nir - swir1, nir + swir1)


def nbr(nir: np.ndarray, swir2: np.ndarray) -> np.ndarray:
    """Normalised Burn Ratio — Key & Benson (2006)."""
    return _safe_ratio(nir - swir2, nir + swir2)


def ndre(nir: np.ndarray, red_edge: np.ndarray) -> np.ndarray:
    """Normalised Difference Red Edge — Gitelson & Merzlyak (1994)."""
    return _safe_ratio(nir - red_edge, nir + red_edge)


def ndwi(green: np.ndarray, nir: np.ndarray) -> np.ndarray:
    """Normalised Difference Water Index — McFeeters (1996)."""
    return _safe_ratio(green - nir, green + nir)


def fractional_cover(ndvi_arr: np.ndarray) -> np.ndarray:
    """Fractional canopy cover from scaled NDVI.

    fc = ((NDVI - NDVI_soil) / (NDVI_veg - NDVI_soil))^2   — Carlson & Ripley (1997)

    The square accounts for the non-linear relationship between NDVI and the
    green fraction of a pixel.
    """
    scaled = (ndvi_arr - NDVI_SOIL) / (NDVI_VEG - NDVI_SOIL)
    return np.clip(scaled, 0.0, 1.0) ** 2


def radar_vegetation_index(vv_db: np.ndarray, vh_db: np.ndarray) -> np.ndarray:
    """Dual-pol Radar Vegetation Index — Kim & van Zyl (2009).

    RVI = 4·σ°VH / (σ°VV + σ°VH), computed in linear power. Ranges 0 (bare,
    surface-scattering) to ~1 (dense volume-scattering canopy).
    """
    vv_lin = np.power(10.0, vv_db / 10.0)
    vh_lin = np.power(10.0, vh_db / 10.0)
    return np.clip(_safe_ratio(4.0 * vh_lin, vv_lin + vh_lin), 0.0, 4.0)


def cross_pol_ratio(vv_db: np.ndarray, vh_db: np.ndarray) -> np.ndarray:
    """VH/VV in dB — a depolarisation proxy that tracks canopy volume."""
    return vh_db - vv_db


def compute_index_stack(bundle: ObservationBundle) -> dict[str, np.ndarray]:
    """All per-cell predictors derived from one observation bundle."""
    stack: dict[str, np.ndarray] = {}

    if bundle.optical is not None:
        b = bundle.optical.bands
        blue, green, red = b["B2"], b["B3"], b["B4"]
        red_edge, nir, nir_a = b["B5"], b["B8"], b["B8A"]
        swir1, swir2 = b["B11"], b["B12"]

        stack["ndvi"] = ndvi(nir, red)
        stack["evi"] = evi(nir, red, blue)
        stack["savi"] = savi(nir, red)
        stack["ndmi"] = ndmi(nir, swir1)
        stack["nbr"] = nbr(nir, swir2)
        stack["ndre"] = ndre(nir_a, red_edge)
        stack["ndwi"] = ndwi(green, nir)
        stack["canopy_cover"] = fractional_cover(stack["ndvi"])
        stack["red"] = red
        stack["nir"] = nir
        stack["swir1"] = swir1

    if bundle.radar is not None:
        vv, vh = bundle.radar.vv_db, bundle.radar.vh_db
        stack["vv_db"] = vv
        stack["vh_db"] = vh
        stack["rvi"] = radar_vegetation_index(vv, vh)
        stack["cross_pol"] = cross_pol_ratio(vv, vh)

    if bundle.terrain is not None:
        stack["elevation"] = bundle.terrain.elevation_m
        stack["slope"] = bundle.terrain.slope_deg

    return stack


#: Predictors offered to the biomass model, in priority order. Those absent
#: from a given bundle are dropped and the drop is reported in provenance.
MODEL_FEATURES: tuple[str, ...] = (
    "ndvi",
    "evi",
    "savi",
    "ndmi",
    "nbr",
    "ndre",
    "canopy_cover",
    "swir1",
    "vh_db",
    "vv_db",
    "rvi",
    "cross_pol",
    "elevation",
    "slope",
)
