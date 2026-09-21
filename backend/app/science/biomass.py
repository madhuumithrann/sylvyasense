"""Aboveground biomass density (AGBD) estimation.

Two calibration paths, and the active one is always reported:

GEDI-LOCAL (preferred)
    LightGBM gradient boosting trained on the GEDI L4A footprints that actually
    fall inside the AOI, with Sentinel-2 and Sentinel-1 predictors sampled at
    each footprint. Three quantile boosters (alpha 0.05 / 0.50 / 0.95) give a
    genuine 90% prediction interval rather than a symmetric guess. Skill is
    reported from *spatially blocked* cross-validation, because random k-fold
    over autocorrelated footprints reports optimistic scores.

REGIONAL-DEFAULT (fallback)
    When too few usable GEDI shots are present to calibrate locally, a published
    log-linear C-band/optical relationship is used instead. It is not calibrated
    for the site, C-band saturates around 150 Mg/ha, and the result is labelled
    UNCALIBRATED everywhere it appears, with a deliberately wide interval.

If neither path has the inputs it needs, this module raises INSUFFICIENT_DATA.
It never returns a number it cannot justify.
"""

from __future__ import annotations

import warnings
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from app.core.config import get_settings
from app.core.errors import insufficient_data
from app.providers.base import ObservationBundle
from app.science.indices import MODEL_FEATURES

# --- Regional-default coefficients -------------------------------------
# ln(AGB) = A + B·σ°VH(dB) + C·NDMI
# Anchored to the published C-band biomass literature (Mitchard et al. 2009;
# Cartus et al. 2012): ~200 Mg/ha at VH -16 dB / NDMI 0.30, ~50 Mg/ha at
# VH -20 dB / NDMI 0.10.
REGIONAL_SAR_A = 9.742
REGIONAL_SAR_B = 0.2965
REGIONAL_SAR_C = 1.000
#: C-band backscatter stops responding to biomass above roughly this value.
C_BAND_SATURATION_MG_HA = 150.0

# Optical-only fallback: AGB from fractional cover and canopy moisture.
REGIONAL_OPT_A = 3.10
REGIONAL_OPT_B = 2.55
REGIONAL_OPT_C = 1.85

QUANTILES = (0.05, 0.50, 0.95)
#: Side length, in analysis cells, of a spatial CV block.
CV_BLOCK_CELLS = 6
MIN_CV_BLOCKS = 4


@dataclass
class ModelProvenance:
    """Everything the UI needs to say where a biomass number came from."""

    version: str
    calibration: str                 # "gedi-local" | "regional-default"
    algorithm: str
    features: list[str]
    n_training: int
    training_source: str
    cv_r2: float | None = None
    cv_rmse: float | None = None
    cv_folds: int | None = None
    cv_scheme: str | None = None
    feature_importance: dict[str, float] = field(default_factory=dict)
    saturation_note: str | None = None
    caveats: list[str] = field(default_factory=list)
    uncalibrated: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "calibration": self.calibration,
            "algorithm": self.algorithm,
            "features": self.features,
            "n_training": self.n_training,
            "training_source": self.training_source,
            "cv_r2": None if self.cv_r2 is None else round(self.cv_r2, 3),
            "cv_rmse": None if self.cv_rmse is None else round(self.cv_rmse, 2),
            "cv_folds": self.cv_folds,
            "cv_scheme": self.cv_scheme,
            "feature_importance": {
                k: round(v, 4) for k, v in sorted(
                    self.feature_importance.items(), key=lambda kv: -kv[1]
                )
            },
            "saturation_note": self.saturation_note,
            "caveats": self.caveats,
            "uncalibrated": self.uncalibrated,
        }


@dataclass
class BiomassResult:
    agb: np.ndarray                  # Mg/ha per cell, NaN outside the AOI
    agb_p05: np.ndarray
    agb_p95: np.ndarray
    agb_sd: np.ndarray               # derived from the interval half-width
    model: ModelProvenance
    aoi_mean: float
    aoi_p05: float
    aoi_p95: float
    total_stock_mg: float            # total AGB over the AOI, in megagrams
    effective_n: float               # independent spatial units behind the mean

    def as_dict(self) -> dict[str, Any]:
        return {
            "mean_mg_ha": round(self.aoi_mean, 2),
            "p05_mg_ha": round(self.aoi_p05, 2),
            "p95_mg_ha": round(self.aoi_p95, 2),
            "total_stock_mg": round(self.total_stock_mg, 1),
            "effective_n": round(self.effective_n, 1),
            "model": self.model.as_dict(),
        }


# ----------------------------------------------------------------------
# Feature handling
# ----------------------------------------------------------------------


def available_features(stack: dict[str, np.ndarray]) -> list[str]:
    return [f for f in MODEL_FEATURES if f in stack]


def stack_matrix(
    stack: dict[str, np.ndarray], features: list[str]
) -> tuple[np.ndarray, tuple[int, int]]:
    """Flatten the gridded predictors into an (n_cells, n_features) matrix."""
    shape = stack[features[0]].shape
    cols = [np.asarray(stack[f], dtype=np.float64).ravel() for f in features]
    return np.column_stack(cols), shape


def sample_at_points(
    stack: dict[str, np.ndarray],
    features: list[str],
    lons: np.ndarray,
    lats: np.ndarray,
    pt_lon: np.ndarray,
    pt_lat: np.ndarray,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Nearest-cell predictor lookup at footprint locations.

    Returns (X, row_index, col_index) so callers can build spatial CV blocks.
    """
    col = np.clip(np.searchsorted(lons, pt_lon) - 1, 0, lons.size - 1)
    row = np.clip(np.searchsorted(-lats, -pt_lat) - 1, 0, lats.size - 1)
    cols = [np.asarray(stack[f], dtype=np.float64)[row, col] for f in features]
    return np.column_stack(cols), row, col


def _spatial_blocks(row: np.ndarray, col: np.ndarray) -> np.ndarray:
    """Group label per sample, from a coarse grid of square blocks."""
    return (row // CV_BLOCK_CELLS) * 10_000 + (col // CV_BLOCK_CELLS)


# ----------------------------------------------------------------------
# GEDI-calibrated model
# ----------------------------------------------------------------------


def _lgbm_params(n_samples: int) -> dict[str, Any]:
    """Conservative parameters — these training sets are small by ML standards."""
    leaves = int(np.clip(n_samples // 12, 4, 31))
    min_leaf = int(np.clip(n_samples // 25, 5, 40))
    return {
        "objective": "quantile",
        "num_leaves": leaves,
        "min_data_in_leaf": min_leaf,
        "learning_rate": 0.06,
        "n_estimators": 350,
        "subsample": 0.85,
        "subsample_freq": 1,
        "colsample_bytree": 0.85,
        "reg_lambda": 1.0,
        "verbose": -1,
        "n_jobs": 2,
        "random_state": 17,
    }


def _fit_quantile_models(
    X: np.ndarray, y: np.ndarray
) -> dict[float, Any]:
    import lightgbm as lgb

    models: dict[float, Any] = {}
    params = _lgbm_params(X.shape[0])
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        for alpha in QUANTILES:
            model = lgb.LGBMRegressor(**params, alpha=alpha)
            model.fit(X, y)
            models[alpha] = model
    return models


def _spatial_cv(
    X: np.ndarray, y: np.ndarray, groups: np.ndarray
) -> tuple[float | None, float | None, int, str]:
    """Blocked cross-validation on the median model."""
    import lightgbm as lgb
    from sklearn.model_selection import GroupKFold

    unique_blocks = np.unique(groups)
    if unique_blocks.size < MIN_CV_BLOCKS:
        return None, None, 0, "insufficient spatial blocks for blocked CV"

    n_splits = int(min(5, unique_blocks.size))
    splitter = GroupKFold(n_splits=n_splits)
    params = _lgbm_params(X.shape[0])
    params["n_estimators"] = 250

    preds = np.full(y.shape, np.nan)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        for train_idx, test_idx in splitter.split(X, y, groups=groups):
            if train_idx.size < 20 or test_idx.size == 0:
                continue
            model = lgb.LGBMRegressor(**params, alpha=0.5)
            model.fit(X[train_idx], y[train_idx])
            preds[test_idx] = model.predict(X[test_idx])

    ok = np.isfinite(preds)
    if ok.sum() < 20:
        return None, None, n_splits, "too few held-out predictions"

    resid = y[ok] - preds[ok]
    ss_res = float(np.sum(resid**2))
    ss_tot = float(np.sum((y[ok] - np.mean(y[ok])) ** 2))
    r2 = 1.0 - ss_res / ss_tot if ss_tot > 1e-9 else None
    rmse = float(np.sqrt(np.mean(resid**2)))
    return r2, rmse, n_splits, f"GroupKFold over {unique_blocks.size} spatial blocks"


def _fit_gedi_local(
    bundle: ObservationBundle, stack: dict[str, np.ndarray], features: list[str]
) -> tuple[dict[float, Any], ModelProvenance] | None:
    settings = get_settings()
    gedi = bundle.gedi
    if gedi is None or len(gedi) < settings.min_gedi_samples:
        return None

    X, row, col = sample_at_points(
        stack, features, bundle.lons, bundle.lats, gedi.lon, gedi.lat
    )
    y = np.asarray(gedi.agbd, dtype=np.float64)

    finite = np.isfinite(X).all(axis=1) & np.isfinite(y) & (y >= 0)
    X, y, row, col = X[finite], y[finite], row[finite], col[finite]
    if y.size < settings.min_gedi_samples:
        return None

    models = _fit_quantile_models(X, y)
    groups = _spatial_blocks(row, col)
    r2, rmse, folds, scheme = _spatial_cv(X, y, groups)

    median_model = models[0.50]
    raw_imp = np.asarray(median_model.feature_importances_, dtype=np.float64)
    total = float(raw_imp.sum()) or 1.0
    importance = {f: float(v) / total for f, v in zip(features, raw_imp, strict=False)}

    caveats: list[str] = []
    if r2 is not None and r2 < 0.25:
        caveats.append(
            "Blocked cross-validation explains little of the biomass variation here "
            f"(R² = {r2:.2f}); treat per-cell values as indicative only."
        )
    if "vh_db" not in features:
        caveats.append("No radar predictor available — optical-only calibration.")
    if y.max() > C_BAND_SATURATION_MG_HA and "vh_db" in features:
        caveats.append(
            f"Part of this area exceeds the ~{C_BAND_SATURATION_MG_HA:.0f} Mg/ha C-band "
            "saturation point, where radar adds little information."
        )

    provenance = ModelProvenance(
        version=settings.model_version,
        calibration="gedi-local",
        algorithm="LightGBM gradient boosting, quantile objective (α = 0.05 / 0.50 / 0.95)",
        features=features,
        n_training=int(y.size),
        training_source=gedi.collection,
        cv_r2=r2,
        cv_rmse=rmse,
        cv_folds=folds,
        cv_scheme=scheme,
        feature_importance=importance,
        caveats=caveats,
    )
    return models, provenance


# ----------------------------------------------------------------------
# Regional-default model
# ----------------------------------------------------------------------


def _predict_regional(
    stack: dict[str, np.ndarray], reason: str
) -> tuple[np.ndarray, np.ndarray, np.ndarray, ModelProvenance]:
    settings = get_settings()
    has_sar = "vh_db" in stack and "ndmi" in stack
    has_opt = "canopy_cover" in stack and "ndmi" in stack

    if has_sar:
        vh = stack["vh_db"]
        moisture = stack["ndmi"]
        ln_agb = REGIONAL_SAR_A + REGIONAL_SAR_B * vh + REGIONAL_SAR_C * moisture
        agb = np.exp(np.clip(ln_agb, -2.0, 7.0))
        used = ["vh_db", "ndmi"]
        algorithm = "Log-linear C-band/optical regional model: ln(AGB) = A + B·σ°VH + C·NDMI"
        # Relative uncertainty widens sharply past C-band saturation.
        rel = np.where(
            agb <= C_BAND_SATURATION_MG_HA,
            0.55,
            0.55 + 0.35 * np.clip((agb - C_BAND_SATURATION_MG_HA) / 200.0, 0.0, 1.5),
        )
        saturation_note = (
            f"C-band backscatter saturates near {C_BAND_SATURATION_MG_HA:.0f} Mg/ha; "
            "values above that carry substantially wider bounds."
        )
    elif has_opt:
        cover = np.clip(stack["canopy_cover"], 0.0, 1.0)
        moisture = stack["ndmi"]
        ln_agb = REGIONAL_OPT_A + REGIONAL_OPT_B * cover + REGIONAL_OPT_C * moisture
        agb = np.exp(np.clip(ln_agb, -2.0, 7.0))
        used = ["canopy_cover", "ndmi"]
        algorithm = "Log-linear optical regional model: ln(AGB) = A + B·cover + C·NDMI"
        rel = np.full_like(agb, 0.70)
        saturation_note = (
            "Optical indices saturate in closed canopy; this estimate cannot "
            "distinguish dense stands from very dense stands."
        )
    else:
        raise insufficient_data(
            "Neither radar nor optical predictors are available for this area, so "
            "biomass cannot be estimated at all.",
            causes=[
                "no Sentinel-1 acquisition over this area",
                "no cloud-free Sentinel-2 observation in the window",
            ],
        )

    half = 1.645 * rel * agb / 1.645  # rel is already a 90% relative half-width
    p05 = np.clip(agb - half, 0.0, None)
    p95 = agb + half

    provenance = ModelProvenance(
        version=settings.model_version,
        calibration="regional-default",
        algorithm=algorithm,
        features=used,
        n_training=0,
        training_source="Published regional relationship (not calibrated on this site)",
        saturation_note=saturation_note,
        uncalibrated=True,
        caveats=[
            reason,
            "This is an uncalibrated regional estimate. It is suitable for "
            "prioritising survey effort, not for carbon accounting.",
        ],
    )
    return agb, p05, p95, provenance


# ----------------------------------------------------------------------
# Entry point
# ----------------------------------------------------------------------


def estimate_biomass(
    bundle: ObservationBundle, stack: dict[str, np.ndarray]
) -> BiomassResult:
    settings = get_settings()
    features = available_features(stack)
    if not features:
        raise insufficient_data(
            "No usable predictors could be derived for this area — neither optical "
            "nor radar observations were returned."
        )

    fitted = _fit_gedi_local(bundle, stack, features)

    if fitted is not None:
        models, provenance = fitted
        X, shape = stack_matrix(stack, features)
        finite_rows = np.isfinite(X).all(axis=1)
        X_safe = np.where(np.isfinite(X), X, 0.0)

        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            pred = {a: models[a].predict(X_safe) for a in QUANTILES}

        agb = np.where(finite_rows, pred[0.50], np.nan).reshape(shape)
        p05 = np.where(finite_rows, pred[0.05], np.nan).reshape(shape)
        p95 = np.where(finite_rows, pred[0.95], np.nan).reshape(shape)
    else:
        n_shots = 0 if bundle.gedi is None else len(bundle.gedi)
        reason = (
            f"Only {n_shots} usable GEDI footprints fall inside this area; "
            f"{settings.min_gedi_samples} are required to calibrate locally."
        )
        agb, p05, p95, provenance = _predict_regional(stack, reason)

    # Quantile models are fitted independently and can cross; enforce ordering.
    agb = np.clip(agb, 0.0, None)
    p05 = np.clip(np.minimum(p05, agb), 0.0, None)
    p95 = np.maximum(p95, agb)

    outside = ~bundle.mask
    for arr in (agb, p05, p95):
        arr[outside] = np.nan

    # A 90% interval spans 2 × 1.645 σ for a Gaussian; use that to express the
    # interval as an equivalent standard deviation for downstream scoring.
    agb_sd = (p95 - p05) / (2.0 * 1.645)

    inside = bundle.mask & np.isfinite(agb)
    if not inside.any():
        raise insufficient_data(
            "Biomass could not be estimated for any cell inside this area."
        )

    aoi_mean = float(np.mean(agb[inside]))
    effective_n = _effective_sample_size(inside)
    # Cell-level errors are strongly spatially correlated, so the area mean is
    # not sqrt(n) times tighter — it is sqrt(effective_n) times tighter.
    mean_sd = float(np.mean(agb_sd[inside])) / np.sqrt(max(effective_n, 1.0))
    aoi_p05 = max(aoi_mean - 1.645 * mean_sd, 0.0)
    aoi_p95 = aoi_mean + 1.645 * mean_sd

    cell_ha = bundle.cell_area_ha()
    total_stock = float(np.sum(agb[inside]) * cell_ha)

    return BiomassResult(
        agb=agb,
        agb_p05=p05,
        agb_p95=p95,
        agb_sd=agb_sd,
        model=provenance,
        aoi_mean=aoi_mean,
        aoi_p05=aoi_p05,
        aoi_p95=aoi_p95,
        total_stock_mg=total_stock,
        effective_n=effective_n,
    )


def _effective_sample_size(inside: np.ndarray) -> float:
    """Independent spatial units, counting one per CV-sized block."""
    rows, cols = np.nonzero(inside)
    if rows.size == 0:
        return 1.0
    blocks = _spatial_blocks(rows, cols)
    return float(np.unique(blocks).size)
