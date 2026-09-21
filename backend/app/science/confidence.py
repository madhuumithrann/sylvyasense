"""Per-cell confidence in the biomass estimate.

Confidence is *not* a restatement of the model interval. It combines four
measurable properties of the evidence behind each cell:

    model precision   how tight the 90% prediction interval is, relative to the
                      predicted value
    GEDI support      how many calibration footprints fall near the cell
    optical quality   the share of clear Sentinel-2 observations at that cell
    radar support     whether dual-pol backscatter was available

Each component is bounded 0-1 and reported separately, so the reason a cell
scores badly is always visible and always traceable to a measured quantity.
Nothing here is narrated after the fact — the explanation is generated from the
component that actually dominated the loss.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any

import numpy as np

from app.providers.base import ObservationBundle

#: Radius, in analysis cells, over which GEDI support is counted.
GEDI_SUPPORT_RADIUS_CELLS = 2
#: Footprint count within that radius that counts as full support. GEDI tracks
#: are ~600 m apart, so genuinely well-supported cells sit on or beside a track.
GEDI_SATURATION_COUNT = 30.0

#: Relative 90% interval half-width that counts as fully precise / useless.
PRECISION_BEST_REL_WIDTH = 0.15
PRECISION_WORST_REL_WIDTH = 0.70

#: Slope beyond which SAR geometry (foreshortening, layover, shadow) starts to
#: degrade the backscatter measurement, and where it is unusable.
SAR_SLOPE_DEGRADE_DEG = 15.0
SAR_SLOPE_UNUSABLE_DEG = 45.0

HIGH_CONFIDENCE_THRESHOLD = 0.70
SURVEY_THRESHOLD = 0.40

WEIGHTS = {
    "model_precision": 0.46,
    "gedi_support": 0.24,
    "optical_quality": 0.18,
    "radar_support": 0.12,
}


class ConfidenceClass(str, Enum):
    HIGH = "HIGH_CONFIDENCE"
    SURVEY = "SURVEY_RECOMMENDED"
    INSUFFICIENT = "INSUFFICIENT_DATA"


@dataclass
class ConfidenceResult:
    score: np.ndarray                      # 0-1 per cell
    classes: np.ndarray                    # int codes: 2 high, 1 survey, 0 insufficient
    components: dict[str, np.ndarray]
    dominant_limit: np.ndarray             # int index into COMPONENT_ORDER
    class_fractions: dict[str, float]
    mean_score: float

    def as_dict(self) -> dict[str, Any]:
        return {
            "mean_score": round(self.mean_score, 4),
            "class_fractions": {k: round(v, 4) for k, v in self.class_fractions.items()},
            "weights": WEIGHTS,
            "thresholds": {
                "high": HIGH_CONFIDENCE_THRESHOLD,
                "survey": SURVEY_THRESHOLD,
            },
        }


COMPONENT_ORDER = ("model_precision", "gedi_support", "optical_quality", "radar_support")

CLASS_CODE = {
    ConfidenceClass.INSUFFICIENT: 0,
    ConfidenceClass.SURVEY: 1,
    ConfidenceClass.HIGH: 2,
}

#: Plain-language reason per limiting component. Selected by which component
#: actually scored lowest for that cell — never written to fit a narrative.
LIMIT_REASON = {
    "model_precision": (
        "Wide model prediction interval — the predictors do not constrain biomass "
        "tightly at this location"
    ),
    "gedi_support": "Sparse GEDI observations near this cell",
    "optical_quality": "Few clear optical observations — persistent cloud",
    "radar_support": (
        "Radar support is weak here — either no dual-polarisation acquisition, or "
        "terrain too steep for reliable backscatter geometry"
    ),
}


def _gedi_support(bundle: ObservationBundle) -> np.ndarray:
    """Count GEDI footprints near each cell, normalised to 0-1."""
    n_lat, n_lon = bundle.shape
    counts = np.zeros((n_lat, n_lon), dtype=np.float64)
    gedi = bundle.gedi
    if gedi is None or len(gedi) == 0:
        return counts

    col = np.clip(np.searchsorted(bundle.lons, gedi.lon) - 1, 0, n_lon - 1)
    row = np.clip(np.searchsorted(-bundle.lats, -gedi.lat) - 1, 0, n_lat - 1)
    np.add.at(counts, (row, col), 1.0)

    # Box-sum over the support radius via a cumulative-sum integral image.
    r = GEDI_SUPPORT_RADIUS_CELLS
    padded = np.pad(counts, r + 1, mode="constant")
    integral = padded.cumsum(axis=0).cumsum(axis=1)
    size = 2 * r + 1
    local = (
        integral[size:, size:]
        - integral[:-size, size:]
        - integral[size:, :-size]
        + integral[:-size, :-size]
    )
    local = local[:n_lat, :n_lon]
    return np.clip(local / GEDI_SATURATION_COUNT, 0.0, 1.0)


def compute_confidence(
    bundle: ObservationBundle,
    agb: np.ndarray,
    agb_p05: np.ndarray,
    agb_p95: np.ndarray,
    uncalibrated: bool,
) -> ConfidenceResult:
    shape = bundle.shape
    inside = bundle.mask

    # --- model precision: relative 90% interval half-width ---------------
    half_width = (agb_p95 - agb_p05) / 2.0
    denom = np.maximum(np.abs(agb), 10.0)  # floor keeps low-biomass cells sane
    rel_width = np.where(np.isfinite(half_width), half_width / denom, np.nan)
    # Linear between the two published-interval anchors above.
    span = PRECISION_WORST_REL_WIDTH - PRECISION_BEST_REL_WIDTH
    model_precision = np.clip(
        1.0 - (rel_width - PRECISION_BEST_REL_WIDTH) / span, 0.0, 1.0
    )
    model_precision = np.nan_to_num(model_precision, nan=0.0)
    if uncalibrated:
        # A regional model that was never fitted here cannot claim precision.
        model_precision *= 0.45

    # --- GEDI support -----------------------------------------------------
    gedi_support = _gedi_support(bundle)

    # --- optical quality --------------------------------------------------
    if bundle.optical is not None:
        optical_quality = np.clip(
            np.nan_to_num(bundle.optical.valid_fraction, nan=0.0), 0.0, 1.0
        )
    else:
        optical_quality = np.zeros(shape)

    # --- radar support ----------------------------------------------------
    # Availability alone is not quality: on steep ground, foreshortening and
    # layover corrupt the backscatter that the biomass model relies on.
    if bundle.radar is not None:
        radar_ok = np.isfinite(bundle.radar.vv_db) & np.isfinite(bundle.radar.vh_db)
        radar_support = radar_ok.astype(np.float64)
        if bundle.terrain is not None:
            slope = np.nan_to_num(bundle.terrain.slope_deg, nan=0.0)
            geometry_penalty = np.clip(
                (slope - SAR_SLOPE_DEGRADE_DEG)
                / (SAR_SLOPE_UNUSABLE_DEG - SAR_SLOPE_DEGRADE_DEG),
                0.0,
                1.0,
            )
            radar_support *= 1.0 - geometry_penalty
    else:
        radar_support = np.zeros(shape)

    components = {
        "model_precision": model_precision,
        "gedi_support": gedi_support,
        "optical_quality": optical_quality,
        "radar_support": radar_support,
    }

    score = np.zeros(shape, dtype=np.float64)
    for key, weight in WEIGHTS.items():
        score += weight * components[key]
    score = np.clip(score, 0.0, 1.0)

    # A cell with no biomass prediction has no confidence to report.
    no_prediction = ~np.isfinite(agb)
    score[no_prediction] = 0.0
    score[~inside] = np.nan

    classes = np.full(shape, CLASS_CODE[ConfidenceClass.INSUFFICIENT], dtype=np.int16)
    classes[score >= SURVEY_THRESHOLD] = CLASS_CODE[ConfidenceClass.SURVEY]
    classes[score >= HIGH_CONFIDENCE_THRESHOLD] = CLASS_CODE[ConfidenceClass.HIGH]
    classes[~inside] = -1

    # Which component actually cost this cell the most weighted score?
    deficits = np.stack(
        [WEIGHTS[k] * (1.0 - components[k]) for k in COMPONENT_ORDER], axis=0
    )
    dominant_limit = np.argmax(deficits, axis=0).astype(np.int16)
    dominant_limit[~inside] = -1

    valid = inside & np.isfinite(score)
    total = max(int(valid.sum()), 1)
    class_fractions = {
        ConfidenceClass.HIGH.value: float(
            np.sum(classes[valid] == CLASS_CODE[ConfidenceClass.HIGH]) / total
        ),
        ConfidenceClass.SURVEY.value: float(
            np.sum(classes[valid] == CLASS_CODE[ConfidenceClass.SURVEY]) / total
        ),
        ConfidenceClass.INSUFFICIENT.value: float(
            np.sum(classes[valid] == CLASS_CODE[ConfidenceClass.INSUFFICIENT]) / total
        ),
    }

    return ConfidenceResult(
        score=score,
        classes=classes,
        components=components,
        dominant_limit=dominant_limit,
        class_fractions=class_fractions,
        mean_score=float(np.nanmean(score[valid])) if valid.any() else 0.0,
    )


def class_label(code: int) -> str:
    for cls, value in CLASS_CODE.items():
        if value == code:
            return cls.value
    return ConfidenceClass.INSUFFICIENT.value


def limit_reason(index: int) -> str:
    if 0 <= index < len(COMPONENT_ORDER):
        return LIMIT_REASON[COMPONENT_ORDER[index]]
    return "Outside the area of interest"
