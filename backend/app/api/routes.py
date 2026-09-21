"""HTTP API.

Route contract notes:

* Every error reaching a client is a SylvaSenseError payload — a stable code, a
  plain-language title, causes and a next step. The exception handler in
  app.main guarantees this even for unexpected failures.
* Analysis and change runs are asynchronous jobs. Progress is reported as
  completed steps out of total steps, which is a fact; there is no synthetic
  percentage anywhere in this file.
* Tiles are rendered on demand from arrays already in memory, so toggling a
  layer costs no recomputation.
"""

from __future__ import annotations

import datetime as dt
import logging
from typing import Any

import numpy as np
from fastapi import APIRouter, Query, Response

from app.analysis.gazetteer import demo_places
from app.analysis.gazetteer import search as search_places
from app.analysis.pipeline import (
    STEPS,
    AnalysisResult,
    StepState,
    run_analysis,
    step_labels,
)
from app.analysis.store import STORE
from app.api import layers as layer_catalogue
from app.api.schemas import AnalysisRequest, AuditRequest, ChangeRequest, GeometryRequest
from app.core.config import get_settings
from app.core.errors import (
    analysis_required,
    aoi_too_large,
    aoi_too_small,
    not_found,
)
from app.export.artifacts import (
    analysis_csv,
    analysis_geojson,
    change_geojson,
    fieldplan_csv,
    fieldplan_geojson,
    to_json_bytes,
)
from app.export.dossier import build_dossier
from app.jobs.manager import MANAGER, Job
from app.providers.base import DataMode, year_window
from app.providers.registry import provider_status
from app.render import tiles as tile_render
from app.render.colormaps import CATEGORY_RAMPS, RAMPS, legends
from app.science.carbon import CARBON_FRACTION
from app.science.change import detect_change
from app.science.confidence import (
    COMPONENT_ORDER,
    WEIGHTS,
    class_label,
    limit_reason,
)
from app.science.geo import AOI, geodesic_perimeter_km, parse_aoi

log = logging.getLogger("sylvasense.api")

router = APIRouter(prefix="/api/v1")

CHANGE_STEPS: list[tuple[str, str]] = [
    ("epoch_from", "Baseline epoch analysed"),
    ("epoch_to", "Comparison epoch analysed"),
    ("difference", "Difference computed"),
    ("significance", "Significance tested"),
]


# ----------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------


def _validated_aoi(geometry: dict[str, Any]) -> AOI:
    settings = get_settings()
    aoi = parse_aoi(geometry)
    if aoi.area_km2 > settings.max_aoi_km2:
        raise aoi_too_large(aoi.area_km2, settings.max_aoi_km2)
    if aoi.area_km2 < settings.min_aoi_km2:
        raise aoi_too_small(aoi.area_km2, settings.min_aoi_km2)
    STORE.remember_aoi(aoi)
    return aoi


def _require_result(aoi_id: str, year: int) -> AnalysisResult:
    result = STORE.get(aoi_id, year)
    if result is None:
        raise analysis_required(f"the {year} analysis")
    return result


def _cell_at(result: AnalysisResult, lon: float, lat: float) -> tuple[int, int]:
    b = result.bundle
    col = int(np.clip(np.abs(b.lons - lon).argmin(), 0, b.lons.size - 1))
    row = int(np.clip(np.abs(b.lats - lat).argmin(), 0, b.lats.size - 1))
    return row, col


def _f(value: Any) -> float | None:
    """Float that is JSON-safe (NaN and infinities become null)."""
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if np.isfinite(out) else None


# ----------------------------------------------------------------------
# System
# ----------------------------------------------------------------------


@router.get("/system/status")
def system_status() -> dict[str, Any]:
    settings = get_settings()
    return {
        "app": settings.app_name,
        "version": settings.version,
        "server_time": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
        "provider": provider_status(),
        "limits": {
            "max_aoi_km2": settings.max_aoi_km2,
            "min_aoi_km2": settings.min_aoi_km2,
            "grid_max_cells": settings.grid_max_cells,
            "min_gedi_samples": settings.min_gedi_samples,
        },
        "model_version": settings.model_version,
        "jobs": MANAGER.stats(),
        "store": STORE.stats(),
        "available_years": list(range(2019, dt.date.today().year + 1)),
    }


@router.get("/system/layers")
def system_layers() -> dict[str, Any]:
    return {
        "catalogue": layer_catalogue.catalogue(available_change=True),
        "legends": legends(),
        "tile_size": tile_render.TILE_SIZE,
    }


@router.get("/system/steps")
def system_steps() -> dict[str, Any]:
    return {
        "analysis": step_labels(),
        "change": [{"key": k, "label": label} for k, label in CHANGE_STEPS],
        "confidence_components": [
            {"key": k, "label": k.replace("_", " ").title(), "weight": WEIGHTS[k]}
            for k in COMPONENT_ORDER
        ],
    }


# ----------------------------------------------------------------------
# Places
# ----------------------------------------------------------------------


@router.get("/places")
def places(q: str = Query(default="", max_length=120), limit: int = Query(8, ge=1, le=25)):
    return {"query": q, "results": [p.as_dict() for p in search_places(q, limit)]}


@router.get("/places/demo")
def places_demo() -> dict[str, Any]:
    return {
        "results": [
            {**p.as_dict(), "geometry": p.aoi_geometry()} for p in demo_places()
        ]
    }


# ----------------------------------------------------------------------
# AOI and audit
# ----------------------------------------------------------------------


@router.post("/aoi/validate")
def validate_aoi(payload: GeometryRequest) -> dict[str, Any]:
    aoi = _validated_aoi(payload.geometry)
    lon, lat = aoi.centroid()
    return {
        "aoi_id": aoi.aoi_id,
        "area_km2": round(aoi.area_km2, 4),
        "area_ha": round(aoi.area_ha, 2),
        "perimeter_km": round(geodesic_perimeter_km(aoi.geometry), 3),
        "centroid": {"lon": lon, "lat": lat},
        "bounds": aoi.bounds.as_list(),
        "measurement": "Geodesic on the WGS84 ellipsoid (pyproj.Geod)",
        "analysed_years": STORE.years_for(aoi.aoi_id),
    }


@router.post("/audit")
def audit(payload: AuditRequest) -> dict[str, Any]:
    from app.providers.registry import active_provider

    aoi = _validated_aoi(payload.geometry)
    start, end = year_window(payload.year)
    result = active_provider().audit(aoi, start, end)
    return {
        **result.as_dict(),
        "year": payload.year,
        "provider": provider_status(),
        "analysed_years": STORE.years_for(aoi.aoi_id),
    }


# ----------------------------------------------------------------------
# Analysis jobs
# ----------------------------------------------------------------------


@router.post("/analysis", status_code=202)
def start_analysis(payload: AnalysisRequest) -> dict[str, Any]:
    aoi = _validated_aoi(payload.geometry)

    existing = STORE.get(aoi.aoi_id, payload.year)
    job = MANAGER.create(
        "analysis",
        list(STEPS),
        aoi_id=aoi.aoi_id,
        year=payload.year,
        area_km2=round(aoi.area_km2, 3),
    )

    if existing is not None:
        # Cached: report every step done with its recorded note rather than
        # pretending to recompute.
        for key, _label in STEPS:
            job.report(key, StepState.DONE, "Reused from the cached analysis")
        job.status = job.status.__class__.COMPLETE
        job.result_ref = {
            "aoi_id": aoi.aoi_id,
            "year": payload.year,
            "cached": True,
        }
        job.finished_at = dt.datetime.now(dt.UTC).isoformat(timespec="seconds")
        return job.as_dict()

    def work(j: Job) -> dict[str, Any]:
        result = run_analysis(
            aoi,
            payload.year,
            report=lambda key, state, note: j.report(key, state, note),
            target_cells=payload.target_cells,
        )
        STORE.put(result)
        return {"aoi_id": aoi.aoi_id, "year": payload.year, "cached": False}

    MANAGER.submit(job, work)
    return job.as_dict()


@router.post("/change", status_code=202)
def start_change(payload: ChangeRequest) -> dict[str, Any]:
    aoi = _validated_aoi(payload.geometry)
    job = MANAGER.create(
        "change",
        CHANGE_STEPS,
        aoi_id=aoi.aoi_id,
        year_from=payload.year_from,
        year_to=payload.year_to,
    )

    def work(j: Job) -> dict[str, Any]:
        def epoch(year: int, step_key: str) -> AnalysisResult:
            j.report(step_key, StepState.ACTIVE, f"Analysing {year}")
            cached = STORE.get(aoi.aoi_id, year)
            if cached is not None:
                j.report(step_key, StepState.DONE, f"{year} reused from cache")
                return cached
            res = run_analysis(aoi, year, target_cells=payload.target_cells)
            STORE.put(res)
            j.report(
                step_key,
                StepState.DONE,
                f"{year}: {res.biomass.aoi_mean:.1f} Mg/ha "
                f"({res.biomass.model.calibration})",
            )
            return res

        res_from = epoch(payload.year_from, "epoch_from")
        res_to = epoch(payload.year_to, "epoch_to")

        j.report("difference", StepState.ACTIVE, "")
        change = detect_change(
            res_from.bundle,
            res_from.biomass,
            res_to.bundle,
            res_to.biomass,
            payload.year_from,
            payload.year_to,
        )
        j.report(
            "difference",
            StepState.DONE,
            f"Δ {change.agb_delta:+.1f} Mg/ha across "
            f"{change.evidence['cells_compared']:,} cells",
        )

        j.report("significance", StepState.ACTIVE, "")
        STORE.put_change(aoi.aoi_id, payload.year_from, payload.year_to, change)
        j.report(
            "significance",
            StepState.DONE,
            f"{change.verdict.replace('_', ' ').title()} "
            f"(z = {change.z_score:.2f}, p = {change.p_value:.4f})",
        )
        return {
            "aoi_id": aoi.aoi_id,
            "year_from": payload.year_from,
            "year_to": payload.year_to,
        }

    MANAGER.submit(job, work)
    return job.as_dict()


@router.get("/jobs/{job_id}")
def job_status(job_id: str) -> dict[str, Any]:
    job = MANAGER.get(job_id)
    if job is None:
        raise not_found("job", job_id)
    return job.as_dict()


# ----------------------------------------------------------------------
# Results
# ----------------------------------------------------------------------


@router.get("/analysis/{aoi_id}/{year}")
def analysis_summary(aoi_id: str, year: int) -> dict[str, Any]:
    result = _require_result(aoi_id, year)
    return {
        **result.summary(),
        "audit": result.audit.as_dict(),
        "geometry": result.aoi.geojson(),
        "bounds": result.aoi.bounds.as_list(),
        "layers": layer_catalogue.catalogue(available_change=False),
        "analysed_years": STORE.years_for(aoi_id),
    }


@router.get("/analysis/{aoi_id}/{year}/fieldplan")
def analysis_fieldplan(aoi_id: str, year: int) -> dict[str, Any]:
    result = _require_result(aoi_id, year)
    return {
        **result.field_plan.as_dict(),
        "geojson": result.field_plan.as_geojson(),
        "mode": result.mode.value,
        "simulated": result.mode == DataMode.SANDBOX_SIMULATION,
    }


@router.get("/analysis/{aoi_id}/{year}/inspect")
def inspect_cell(
    aoi_id: str,
    year: int,
    lon: float = Query(..., ge=-180, le=180),
    lat: float = Query(..., ge=-90, le=90),
) -> dict[str, Any]:
    """Everything known about one cell — the confidence-detail panel."""
    result = _require_result(aoi_id, year)
    row, col = _cell_at(result, lon, lat)
    b = result.bundle

    if not bool(b.mask[row, col]):
        return {
            "inside_aoi": False,
            "message": "This point is outside the analysed area.",
            "lon": lon,
            "lat": lat,
        }

    conf = result.confidence
    components = {
        key: _f(conf.components[key][row, col]) for key in COMPONENT_ORDER
    }
    limit_index = int(conf.dominant_limit[row, col])
    gedi_grid = layer_catalogue._gedi_density_grid(result)

    return {
        "inside_aoi": True,
        "lon": float(b.lons[col]),
        "lat": float(b.lats[row]),
        "requested": {"lon": lon, "lat": lat},
        "cell": {"row": row, "col": col, "size_m": round(b.cell_size_m, 1)},
        "biomass": {
            "agb_mg_ha": _f(result.biomass.agb[row, col]),
            "p05_mg_ha": _f(result.biomass.agb_p05[row, col]),
            "p95_mg_ha": _f(result.biomass.agb_p95[row, col]),
            "sd_mg_ha": _f(result.biomass.agb_sd[row, col]),
        },
        "carbon": {
            "tc_ha": _f(result.biomass.agb[row, col] * CARBON_FRACTION),
        },
        "canopy": {
            "cover_pct": _f(
                result.stack["canopy_cover"][row, col] * 100.0
                if "canopy_cover" in result.stack
                else None
            ),
            "ndvi": _f(result.stack.get("ndvi", np.full(b.shape, np.nan))[row, col]),
        },
        "radar": {
            "vv_db": _f(b.radar.vv_db[row, col]) if b.radar else None,
            "vh_db": _f(b.radar.vh_db[row, col]) if b.radar else None,
        },
        "terrain": {
            "elevation_m": _f(b.terrain.elevation_m[row, col]) if b.terrain else None,
            "slope_deg": _f(b.terrain.slope_deg[row, col]) if b.terrain else None,
        },
        "confidence": {
            "score": _f(conf.score[row, col]),
            "class": class_label(int(conf.classes[row, col])),
            "components": components,
            "weights": WEIGHTS,
            "limiting_factor": limit_reason(limit_index),
            "limiting_component": (
                COMPONENT_ORDER[limit_index]
                if 0 <= limit_index < len(COMPONENT_ORDER)
                else None
            ),
        },
        "evidence": {
            "gedi_footprints_nearby": _f(gedi_grid[row, col]),
            "clear_observation_pct": _f(
                b.optical.valid_fraction[row, col] * 100.0 if b.optical else None
            ),
            "radar_available": bool(b.radar is not None),
            "optical_scenes": b.optical.scene_count if b.optical else 0,
            "radar_scenes": b.radar.scene_count if b.radar else 0,
        },
        "model": result.biomass.model.as_dict(),
        "mode": result.mode.value,
        "simulated": result.mode == DataMode.SANDBOX_SIMULATION,
    }


@router.get("/change/{aoi_id}/{year_from}/{year_to}")
def change_summary(aoi_id: str, year_from: int, year_to: int) -> dict[str, Any]:
    change = STORE.get_change(aoi_id, year_from, year_to)
    if change is None:
        raise analysis_required(f"the {year_from} to {year_to} comparison")
    result = STORE.get(aoi_id, year_to)
    return {
        **change.as_dict(),
        "aoi_id": aoi_id,
        "mode": result.mode.value if result else None,
        "simulated": (result.mode == DataMode.SANDBOX_SIMULATION) if result else None,
    }


# ----------------------------------------------------------------------
# Tiles
# ----------------------------------------------------------------------


_PNG_HEADERS = {"Cache-Control": "public, max-age=600"}


def _png(data: bytes) -> Response:
    return Response(content=data, media_type="image/png", headers=_PNG_HEADERS)


@router.get("/tiles/{aoi_id}/{year}/{layer}/{z}/{x}/{y}.png")
def analysis_tile(
    aoi_id: str,
    year: int,
    layer: str,
    z: int,
    x: int,
    y: int,
    opacity: float = Query(0.85, ge=0.0, le=1.0),
) -> Response:
    spec = layer_catalogue.LAYER_INDEX.get(layer)
    if spec is None:
        raise not_found("layer", layer)

    result = STORE.get(aoi_id, year)
    if result is None:
        return _png(tile_render.blank_tile())
    if not tile_render.tile_intersects(z, x, y, result.aoi.bounds.as_list()):
        return _png(tile_render.blank_tile())

    b = result.bundle

    if spec.kind == "rgb":
        bands = layer_catalogue.RGB_RESOLVERS[layer]
        if b.optical is None:
            return _png(tile_render.blank_tile())
        arrays = [layer_catalogue.masked(result, b.optical.bands[band]) for band in bands]
        vmax = 0.45 if layer == "falsecolor" else 0.30
        return _png(
            tile_render.render_rgb(
                arrays[0], arrays[1], arrays[2], b.lons, b.lats, z, x, y,
                vmax=vmax, opacity=opacity,
            )
        )

    grid = layer_catalogue.masked(result, layer_catalogue.GRID_RESOLVERS[layer](result))
    if grid is None:
        return _png(tile_render.blank_tile())

    if spec.kind == "categorical":
        ramp = CATEGORY_RAMPS[spec.ramp or layer]
        return _png(
            tile_render.render_categorical(grid, b.lons, b.lats, z, x, y, ramp, opacity)
        )

    ramp = RAMPS[spec.ramp or layer]
    return _png(
        tile_render.render_continuous(grid, b.lons, b.lats, z, x, y, ramp, opacity)
    )


@router.get("/tiles/change/{aoi_id}/{year_from}/{year_to}/{layer}/{z}/{x}/{y}.png")
def change_tile(
    aoi_id: str,
    year_from: int,
    year_to: int,
    layer: str,
    z: int,
    x: int,
    y: int,
    opacity: float = Query(0.85, ge=0.0, le=1.0),
) -> Response:
    change = STORE.get_change(aoi_id, year_from, year_to)
    result = STORE.get(aoi_id, year_to)
    if change is None or result is None:
        return _png(tile_render.blank_tile())
    if not tile_render.tile_intersects(z, x, y, result.aoi.bounds.as_list()):
        return _png(tile_render.blank_tile())

    b = result.bundle
    if layer == "agb_change":
        grid = layer_catalogue.masked(result, change.delta_grid)
        return _png(
            tile_render.render_continuous(
                grid, b.lons, b.lats, z, x, y, RAMPS["agb_change"], opacity
            )
        )
    if layer == "carbon_change":
        grid = layer_catalogue.masked(result, change.delta_grid * CARBON_FRACTION)
        return _png(
            tile_render.render_continuous(
                grid, b.lons, b.lats, z, x, y, RAMPS["carbon_change"], opacity
            )
        )
    if layer == "change_class":
        grid = layer_catalogue.masked(result, change.class_grid.astype(np.float64))
        return _png(
            tile_render.render_categorical(
                grid, b.lons, b.lats, z, x, y, CATEGORY_RAMPS["change_class"], opacity
            )
        )
    raise not_found("change layer", layer)


# ----------------------------------------------------------------------
# Exports
# ----------------------------------------------------------------------


def _attachment(data: bytes, filename: str, media_type: str) -> Response:
    return Response(
        content=data,
        media_type=media_type,
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Cache-Control": "no-store",
        },
    )


@router.get("/export/{aoi_id}/{year}/analysis.geojson")
def export_analysis_geojson(
    aoi_id: str, year: int, cells: bool = Query(True)
) -> Response:
    result = _require_result(aoi_id, year)
    payload = to_json_bytes(analysis_geojson(result, include_cells=cells))
    return _attachment(
        payload, f"sylvasense_{aoi_id}_{year}_analysis.geojson", "application/geo+json"
    )


@router.get("/export/{aoi_id}/{year}/analysis.csv")
def export_analysis_csv(aoi_id: str, year: int) -> Response:
    result = _require_result(aoi_id, year)
    return _attachment(
        analysis_csv(result).encode("utf-8"),
        f"sylvasense_{aoi_id}_{year}_cells.csv",
        "text/csv",
    )


@router.get("/export/{aoi_id}/{year}/fieldplan.geojson")
def export_fieldplan_geojson(aoi_id: str, year: int) -> Response:
    result = _require_result(aoi_id, year)
    return _attachment(
        to_json_bytes(fieldplan_geojson(result)),
        f"sylvasense_{aoi_id}_{year}_fieldplan.geojson",
        "application/geo+json",
    )


@router.get("/export/{aoi_id}/{year}/fieldplan.csv")
def export_fieldplan_csv(aoi_id: str, year: int) -> Response:
    result = _require_result(aoi_id, year)
    return _attachment(
        fieldplan_csv(result).encode("utf-8"),
        f"sylvasense_{aoi_id}_{year}_fieldplan.csv",
        "text/csv",
    )


@router.get("/export/{aoi_id}/{year}/dossier.pdf")
def export_dossier(
    aoi_id: str,
    year: int,
    change_from: int | None = Query(default=None),
) -> Response:
    result = _require_result(aoi_id, year)
    change = (
        STORE.get_change(aoi_id, change_from, year) if change_from is not None else None
    )
    return _attachment(
        build_dossier(result, change),
        f"sylvasense_{aoi_id}_{year}_dossier.pdf",
        "application/pdf",
    )


@router.get("/export/{aoi_id}/{year_from}/{year_to}/change.geojson")
def export_change_geojson(aoi_id: str, year_from: int, year_to: int) -> Response:
    change = STORE.get_change(aoi_id, year_from, year_to)
    result = STORE.get(aoi_id, year_to)
    if change is None or result is None:
        raise analysis_required(f"the {year_from} to {year_to} comparison")
    return _attachment(
        to_json_bytes(change_geojson(result, change)),
        f"sylvasense_{aoi_id}_{year_from}_{year_to}_change.geojson",
        "application/geo+json",
    )
