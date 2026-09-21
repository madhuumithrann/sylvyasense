"""The analysis pipeline.

Runs the ordered steps that turn an AOI into a biomass, carbon, confidence and
field-plan product. Each step reports its own start and completion through a
callback, so the UI's progress drawer reflects real backend state rather than a
timer. A step that cannot run is marked SKIPPED with the reason — it is never
silently marked done.
"""

from __future__ import annotations

import datetime as dt
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

import numpy as np

from app.core.config import get_settings
from app.core.errors import insufficient_data
from app.providers.base import AuditResult, DataMode, ObservationBundle, year_window
from app.providers.registry import active_provider
from app.science.biomass import BiomassResult, estimate_biomass
from app.science.carbon import CarbonResult, biomass_to_carbon
from app.science.confidence import ConfidenceResult, compute_confidence
from app.science.fieldplan import FieldPlan, plan_survey
from app.science.geo import AOI
from app.science.indices import compute_index_stack

log = logging.getLogger("sylvasense.pipeline")


class StepState(str, Enum):
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    DONE = "DONE"
    SKIPPED = "SKIPPED"
    FAILED = "FAILED"


#: Ordered pipeline steps. Keys are stable; labels are shown to the user.
STEPS: tuple[tuple[str, str], ...] = (
    ("validate_aoi", "AOI validated"),
    ("check_availability", "Data availability checked"),
    ("load_optical", "Sentinel-2 loaded"),
    ("load_radar", "Sentinel-1 loaded"),
    ("process_gedi", "GEDI footprints processed"),
    ("biomass_model", "Biomass model"),
    ("uncertainty", "Uncertainty"),
    ("confidence_map", "Confidence map"),
    ("field_plan", "Field plan"),
)

StepReporter = Callable[[str, StepState, str], None]


@dataclass
class AnalysisResult:
    """A completed analysis for one AOI and one year."""

    aoi: AOI
    year: int
    window: tuple[str, str]
    bundle: ObservationBundle
    stack: dict[str, np.ndarray]
    audit: AuditResult
    biomass: BiomassResult
    carbon: CarbonResult
    confidence: ConfidenceResult
    field_plan: FieldPlan
    mode: DataMode
    canopy_cover_pct: float
    created_at: str = field(
        default_factory=lambda: dt.datetime.now(dt.UTC).isoformat(timespec="seconds")
    )

    @property
    def key(self) -> str:
        return f"{self.aoi.aoi_id}:{self.year}"

    def provenance(self) -> dict[str, Any]:
        """Where every headline number came from."""
        o, r, g = self.bundle.optical, self.bundle.radar, self.bundle.gedi
        return {
            "mode": self.mode.value,
            "simulated": self.mode == DataMode.SANDBOX_SIMULATION,
            "window": {"start": self.window[0], "end": self.window[1]},
            "grid": {
                "rows": self.bundle.shape[0],
                "cols": self.bundle.shape[1],
                "cell_size_m": round(self.bundle.cell_size_m, 1),
                "cell_area_ha": round(self.bundle.cell_area_ha(), 3),
            },
            "optical": None
            if o is None
            else {
                "collection": o.collection,
                "scenes": o.scene_count,
                "first_date": o.first_date,
                "last_date": o.last_date,
                "cloud_cover_pct": round(o.cloud_cover_pct, 2),
                "resolution_m": o.resolution_m,
            },
            "radar": None
            if r is None
            else {
                "collection": r.collection,
                "scenes": r.scene_count,
                "first_date": r.first_date,
                "last_date": r.last_date,
                "orbit": r.orbit,
                "resolution_m": r.resolution_m,
            },
            "gedi": None
            if g is None
            else {
                "collection": g.collection,
                "footprints": len(g),
                "first_date": g.first_date,
                "last_date": g.last_date,
            },
            "terrain": None
            if self.bundle.terrain is None
            else {"collection": self.bundle.terrain.collection},
            "landcover": None
            if self.bundle.landcover is None
            else {
                "collection": self.bundle.landcover.collection,
                "year": self.bundle.landcover.year,
            },
            "model": self.biomass.model.as_dict(),
            "created_at": self.created_at,
        }

    def summary(self) -> dict[str, Any]:
        b, c = self.biomass, self.carbon
        return {
            "aoi_id": self.aoi.aoi_id,
            "year": self.year,
            "area_km2": round(self.aoi.area_km2, 4),
            "area_ha": round(self.aoi.area_ha, 2),
            "mode": self.mode.value,
            "simulated": self.mode == DataMode.SANDBOX_SIMULATION,
            "canopy": {
                "cover_pct": round(self.canopy_cover_pct, 2),
                "method": "Fractional cover from scaled NDVI (Carlson & Ripley 1997)",
            },
            "biomass": b.as_dict(),
            **c.as_dict(),
            "confidence": self.confidence.as_dict(),
            "field_plan": {
                "count": len(self.field_plan.sites),
                "total_expected_reduction_pct": round(
                    self.field_plan.total_expected_reduction_pct, 2
                ),
            },
            "provenance": self.provenance(),
            "created_at": self.created_at,
        }


def _noop_reporter(step: str, state: StepState, note: str) -> None:  # pragma: no cover
    return None


def run_analysis(
    aoi: AOI,
    year: int,
    report: StepReporter | None = None,
    target_cells: int = 2500,
) -> AnalysisResult:
    """Execute the full pipeline for one AOI and year."""
    report = report or _noop_reporter
    settings = get_settings()
    provider = active_provider()
    window_start, window_end = year_window(year)

    # --- 1. AOI --------------------------------------------------------
    report("validate_aoi", StepState.ACTIVE, "")
    report(
        "validate_aoi",
        StepState.DONE,
        f"{aoi.area_km2:,.2f} km² ({aoi.area_ha:,.0f} ha), geodesic on WGS84",
    )

    # --- 2. Availability ------------------------------------------------
    report("check_availability", StepState.ACTIVE, "")
    audit = provider.audit(aoi, window_start, window_end)
    if audit.verdict == "INSUFFICIENT_DATA":
        report("check_availability", StepState.FAILED, audit.verdict_detail)
        raise insufficient_data(audit.verdict_detail)
    report(
        "check_availability",
        StepState.DONE,
        f"{audit.verdict.replace('_', ' ').title()} — {audit.verdict_detail}",
    )

    # --- 3-5. Observation pull -----------------------------------------
    report("load_optical", StepState.ACTIVE, "")
    bundle = provider.observe(aoi, window_start, window_end, target_cells)

    if bundle.optical is None:
        report("load_optical", StepState.FAILED, "No optical composite returned")
        raise insufficient_data(
            "No usable optical composite could be built for this area and window."
        )
    report(
        "load_optical",
        StepState.DONE,
        f"{bundle.optical.scene_count} scenes, "
        f"{bundle.optical.cloud_cover_pct:.1f}% mean cloud, "
        f"{bundle.optical.first_date} to {bundle.optical.last_date}",
    )

    report("load_radar", StepState.ACTIVE, "")
    if bundle.radar is None:
        report(
            "load_radar",
            StepState.SKIPPED,
            "No dual-polarisation acquisition over this area — "
            "biomass will rely on optical predictors alone",
        )
    else:
        report(
            "load_radar",
            StepState.DONE,
            f"{bundle.radar.scene_count} acquisitions ({bundle.radar.orbit})",
        )

    report("process_gedi", StepState.ACTIVE, "")
    n_shots = 0 if bundle.gedi is None else len(bundle.gedi)
    if n_shots == 0:
        report(
            "process_gedi",
            StepState.SKIPPED,
            "No GEDI footprints inside this area — falling back to the "
            "uncalibrated regional model",
        )
    elif n_shots < settings.min_gedi_samples:
        report(
            "process_gedi",
            StepState.SKIPPED,
            f"Only {n_shots} footprints, below the {settings.min_gedi_samples}-shot "
            "calibration minimum — falling back to the regional model",
        )
    else:
        report("process_gedi", StepState.DONE, f"{n_shots} quality-filtered footprints")

    # --- 6-7. Biomass and uncertainty -----------------------------------
    report("biomass_model", StepState.ACTIVE, "")
    stack = compute_index_stack(bundle)
    biomass = estimate_biomass(bundle, stack)
    model = biomass.model
    if model.calibration == "gedi-local":
        skill = (
            f", blocked-CV R² = {model.cv_r2:.2f}, RMSE = {model.cv_rmse:.0f} Mg/ha"
            if model.cv_r2 is not None
            else ""
        )
        note = f"{model.calibration} on {model.n_training} footprints{skill}"
    else:
        note = "regional-default — UNCALIBRATED for this site"
    report("biomass_model", StepState.DONE, note)

    report("uncertainty", StepState.ACTIVE, "")
    carbon = biomass_to_carbon(
        biomass.aoi_mean,
        biomass.aoi_p05,
        biomass.aoi_p95,
        biomass.total_stock_mg,
        biomass.agb,
    )
    report(
        "uncertainty",
        StepState.DONE,
        f"90% interval {biomass.aoi_p05:.0f}–{biomass.aoi_p95:.0f} Mg/ha "
        f"over {biomass.effective_n:.0f} independent spatial blocks",
    )

    # --- 8. Confidence ---------------------------------------------------
    report("confidence_map", StepState.ACTIVE, "")
    confidence = compute_confidence(
        bundle, biomass.agb, biomass.agb_p05, biomass.agb_p95, model.uncalibrated
    )
    high = confidence.class_fractions["HIGH_CONFIDENCE"] * 100.0
    survey = confidence.class_fractions["SURVEY_RECOMMENDED"] * 100.0
    report(
        "confidence_map",
        StepState.DONE,
        f"{high:.0f}% high confidence, {survey:.0f}% survey recommended",
    )

    # --- 9. Field plan ----------------------------------------------------
    report("field_plan", StepState.ACTIVE, "")
    plan = plan_survey(
        bundle,
        biomass.agb,
        biomass.agb_sd,
        biomass.agb_p05,
        biomass.agb_p95,
        confidence,
        n_sites=12,
    )
    if not plan.sites:
        report("field_plan", StepState.SKIPPED, "No cell had a usable uncertainty estimate")
    else:
        report(
            "field_plan",
            StepState.DONE,
            f"{len(plan.sites)} sites, {plan.total_expected_reduction_pct:.1f}% of "
            "total variance addressed",
        )

    cover = stack.get("canopy_cover")
    inside = bundle.mask & np.isfinite(cover) if cover is not None else None
    canopy_pct = (
        float(np.mean(cover[inside]) * 100.0)
        if inside is not None and inside.any()
        else 0.0
    )

    return AnalysisResult(
        aoi=aoi,
        year=year,
        window=(window_start, window_end),
        bundle=bundle,
        stack=stack,
        audit=audit,
        biomass=biomass,
        carbon=carbon,
        confidence=confidence,
        field_plan=plan,
        mode=bundle.mode,
        canopy_cover_pct=canopy_pct,
    )


def step_labels() -> list[dict[str, str]]:
    return [{"key": k, "label": label} for k, label in STEPS]
