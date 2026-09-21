"""Temporal change detection.

A difference between two biomass maps is only news if it is larger than the
uncertainty on both of them. This module never reports a change without a
significance test behind it.

Per cell:

    delta   = AGB(t2) - AGB(t1)
    sigma   = sqrt(sd(t1)^2 + sd(t2)^2)        errors treated as independent
    z       = delta / sigma
    verdict = significant when |z| > z_crit (95% two-sided)

At AOI level the same test is applied to the area means, with the standard
error of each mean derived from the effective sample size rather than the raw
cell count, because neighbouring cells do not carry independent errors.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
from scipy import stats

from app.providers.base import ObservationBundle
from app.science.biomass import BiomassResult
from app.science.carbon import CARBON_FRACTION, CO2E_PER_CARBON

Z_CRIT = 1.959963985  # two-sided 95%

#: Per-cell classification codes, used by the change raster tiles.
CHANGE_NO_DATA = -1
CHANGE_STABLE = 0
CHANGE_LOSS = 1
CHANGE_GAIN = 2

#: A cell must move at least this much before it is worth calling a change,
#: even when the statistics allow it. Guards against declaring a 1 Mg/ha shift
#: meaningful just because both intervals happened to be narrow.
MIN_MATERIAL_DELTA_MG_HA = 5.0


@dataclass
class ChangeResult:
    year_from: int
    year_to: int
    delta_grid: np.ndarray
    z_grid: np.ndarray
    class_grid: np.ndarray

    agb_from: float
    agb_to: float
    agb_delta: float
    agb_delta_p05: float
    agb_delta_p95: float

    carbon_from: float
    carbon_to: float
    carbon_delta: float
    co2e_delta: float

    z_score: float
    p_value: float
    verdict: str
    verdict_detail: str

    loss_area_ha: float
    gain_area_ha: float
    stable_area_ha: float
    total_stock_delta_mg: float

    evidence: dict[str, Any]

    def as_dict(self) -> dict[str, Any]:
        return {
            "year_from": self.year_from,
            "year_to": self.year_to,
            "biomass": {
                "from_mg_ha": round(self.agb_from, 2),
                "to_mg_ha": round(self.agb_to, 2),
                "delta_mg_ha": round(self.agb_delta, 2),
                "delta_p05_mg_ha": round(self.agb_delta_p05, 2),
                "delta_p95_mg_ha": round(self.agb_delta_p95, 2),
                "delta_pct": (
                    round(100.0 * self.agb_delta / self.agb_from, 2)
                    if self.agb_from > 1e-6
                    else None
                ),
            },
            "carbon": {
                "from_tc_ha": round(self.carbon_from, 2),
                "to_tc_ha": round(self.carbon_to, 2),
                "delta_tc_ha": round(self.carbon_delta, 2),
                "delta_tco2e_ha": round(self.co2e_delta, 2),
            },
            "statistics": {
                "z_score": round(self.z_score, 3),
                "p_value": round(self.p_value, 5),
                "z_critical": round(Z_CRIT, 3),
                "significant": bool(abs(self.z_score) > Z_CRIT),
                "test": "Two-sided z-test on the difference of two area means",
            },
            "areas": {
                "significant_loss_ha": round(self.loss_area_ha, 1),
                "significant_gain_ha": round(self.gain_area_ha, 1),
                "stable_ha": round(self.stable_area_ha, 1),
            },
            "total_stock_delta_mg": round(self.total_stock_delta_mg, 1),
            "verdict": self.verdict,
            "verdict_detail": self.verdict_detail,
            "evidence": self.evidence,
        }


def detect_change(
    bundle_from: ObservationBundle,
    result_from: BiomassResult,
    bundle_to: ObservationBundle,
    result_to: BiomassResult,
    year_from: int,
    year_to: int,
) -> ChangeResult:
    if bundle_from.shape != bundle_to.shape:
        raise ValueError(
            "Change detection needs both epochs on the same analysis grid; "
            f"got {bundle_from.shape} and {bundle_to.shape}."
        )

    inside = (
        bundle_from.mask
        & bundle_to.mask
        & np.isfinite(result_from.agb)
        & np.isfinite(result_to.agb)
    )

    delta = np.where(inside, result_to.agb - result_from.agb, np.nan)
    sigma = np.sqrt(
        np.square(np.nan_to_num(result_from.agb_sd))
        + np.square(np.nan_to_num(result_to.agb_sd))
    )
    with np.errstate(divide="ignore", invalid="ignore"):
        z_grid = np.where(inside & (sigma > 1e-9), delta / sigma, np.nan)

    classes = np.full(bundle_from.shape, CHANGE_NO_DATA, dtype=np.int16)
    significant = np.isfinite(z_grid) & (np.abs(z_grid) > Z_CRIT)
    material = np.isfinite(delta) & (np.abs(delta) >= MIN_MATERIAL_DELTA_MG_HA)
    classes[inside] = CHANGE_STABLE
    classes[inside & significant & material & (delta < 0)] = CHANGE_LOSS
    classes[inside & significant & material & (delta > 0)] = CHANGE_GAIN

    cell_ha = bundle_from.cell_area_ha()
    loss_ha = float(np.sum(classes == CHANGE_LOSS) * cell_ha)
    gain_ha = float(np.sum(classes == CHANGE_GAIN) * cell_ha)
    stable_ha = float(np.sum(classes == CHANGE_STABLE) * cell_ha)

    # --- AOI-level test ------------------------------------------------
    agb_from = result_from.aoi_mean
    agb_to = result_to.aoi_mean
    agb_delta = agb_to - agb_from

    se_from = (result_from.aoi_p95 - result_from.aoi_p05) / (2.0 * Z_CRIT)
    se_to = (result_to.aoi_p95 - result_to.aoi_p05) / (2.0 * Z_CRIT)
    se_delta = float(np.sqrt(se_from**2 + se_to**2))

    if se_delta > 1e-9:
        z_score = agb_delta / se_delta
        p_value = float(2.0 * (1.0 - stats.norm.cdf(abs(z_score))))
    else:
        z_score = 0.0
        p_value = 1.0

    delta_p05 = agb_delta - Z_CRIT * se_delta
    delta_p95 = agb_delta + Z_CRIT * se_delta

    uncalibrated = result_from.model.uncalibrated or result_to.model.uncalibrated
    if uncalibrated:
        verdict = "INSUFFICIENT_DATA"
        verdict_detail = (
            "At least one epoch could only be estimated with the uncalibrated "
            "regional model. A change measured between an uncalibrated estimate "
            "and anything else is not interpretable."
        )
    elif abs(z_score) > Z_CRIT and abs(agb_delta) >= MIN_MATERIAL_DELTA_MG_HA:
        direction = "loss" if agb_delta < 0 else "gain"
        verdict = "SIGNIFICANT_CHANGE"
        verdict_detail = (
            f"Mean aboveground biomass shows a {direction} of "
            f"{abs(agb_delta):.1f} Mg/ha between {year_from} and {year_to} "
            f"(z = {z_score:.2f}, p = {p_value:.4f}). The change exceeds the "
            "combined uncertainty of both epochs."
        )
    else:
        verdict = "NO_SIGNIFICANT_CHANGE"
        if abs(agb_delta) < MIN_MATERIAL_DELTA_MG_HA:
            verdict_detail = (
                f"Mean biomass moved by only {abs(agb_delta):.1f} Mg/ha, below the "
                f"{MIN_MATERIAL_DELTA_MG_HA:.0f} Mg/ha materiality floor."
            )
        else:
            verdict_detail = (
                f"The {abs(agb_delta):.1f} Mg/ha difference is within the combined "
                f"uncertainty of both epochs (z = {z_score:.2f}, p = {p_value:.3f}), "
                "so it cannot be distinguished from noise."
            )

    carbon_from = agb_from * CARBON_FRACTION
    carbon_to = agb_to * CARBON_FRACTION
    carbon_delta = carbon_to - carbon_from

    total_delta = float(
        np.nansum(np.where(inside, delta, 0.0)) * cell_ha
    )

    evidence = {
        "cells_compared": int(inside.sum()),
        "cell_area_ha": round(cell_ha, 3),
        "significant_cells": int(np.sum(significant & inside)),
        "materiality_floor_mg_ha": MIN_MATERIAL_DELTA_MG_HA,
        "epochs": {
            str(year_from): {
                "window": [bundle_from.window_start, bundle_from.window_end],
                "mode": bundle_from.mode.value,
                "calibration": result_from.model.calibration,
                "n_training": result_from.model.n_training,
                "optical_scenes": (
                    bundle_from.optical.scene_count if bundle_from.optical else 0
                ),
                "radar_scenes": (
                    bundle_from.radar.scene_count if bundle_from.radar else 0
                ),
                "se_mg_ha": round(se_from, 3),
            },
            str(year_to): {
                "window": [bundle_to.window_start, bundle_to.window_end],
                "mode": bundle_to.mode.value,
                "calibration": result_to.model.calibration,
                "n_training": result_to.model.n_training,
                "optical_scenes": (
                    bundle_to.optical.scene_count if bundle_to.optical else 0
                ),
                "radar_scenes": bundle_to.radar.scene_count if bundle_to.radar else 0,
                "se_mg_ha": round(se_to, 3),
            },
        },
    }

    return ChangeResult(
        year_from=year_from,
        year_to=year_to,
        delta_grid=delta,
        z_grid=z_grid,
        class_grid=classes,
        agb_from=agb_from,
        agb_to=agb_to,
        agb_delta=agb_delta,
        agb_delta_p05=delta_p05,
        agb_delta_p95=delta_p95,
        carbon_from=carbon_from,
        carbon_to=carbon_to,
        carbon_delta=carbon_delta,
        co2e_delta=carbon_delta * CO2E_PER_CARBON,
        z_score=z_score,
        p_value=p_value,
        verdict=verdict,
        verdict_detail=verdict_detail,
        loss_area_ha=loss_ha,
        gain_area_ha=gain_ha,
        stable_area_ha=stable_ha,
        total_stock_delta_mg=total_delta,
        evidence=evidence,
    )
