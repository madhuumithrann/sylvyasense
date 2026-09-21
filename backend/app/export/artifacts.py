"""Downloadable artifacts: GeoJSON, CSV and the PDF audit dossier.

Everything exported carries its provenance. A file that leaves SylvaSense must
be able to answer, on its own, which sensor and which model produced each
number — including, unmissably, whether the run was a sandbox simulation.
"""

from __future__ import annotations

import csv
import datetime as dt
import io
import json
from collections.abc import Iterable
from typing import Any

import numpy as np

from app.analysis.pipeline import AnalysisResult
from app.providers.base import DataMode
from app.science.carbon import CARBON_FRACTION, CO2E_PER_CARBON
from app.science.change import ChangeResult
from app.science.confidence import class_label, limit_reason

SIMULATION_WARNING = (
    "SANDBOX SIMULATION — these values were produced by a forward model, not "
    "measured by a satellite. They must not be used for carbon accounting, "
    "reporting or any operational decision."
)


def _mode_banner(mode: DataMode) -> str | None:
    return SIMULATION_WARNING if mode == DataMode.SANDBOX_SIMULATION else None


def _cell_polygon(
    lon: float, lat: float, dlon: float, dlat: float
) -> list[list[list[float]]]:
    hw, hh = dlon / 2.0, dlat / 2.0
    return [
        [
            [lon - hw, lat - hh],
            [lon + hw, lat - hh],
            [lon + hw, lat + hh],
            [lon - hw, lat + hh],
            [lon - hw, lat - hh],
        ]
    ]


def _grid_steps(result: AnalysisResult) -> tuple[float, float]:
    lons, lats = result.bundle.lons, result.bundle.lats
    dlon = float(abs(lons[1] - lons[0])) if lons.size > 1 else 0.001
    dlat = float(abs(lats[1] - lats[0])) if lats.size > 1 else 0.001
    return dlon, dlat


def _iter_cells(result: AnalysisResult) -> Iterable[dict[str, Any]]:
    b = result.bundle
    agb, p05, p95 = result.biomass.agb, result.biomass.agb_p05, result.biomass.agb_p95
    sd = result.biomass.agb_sd
    conf = result.confidence.score
    classes = result.confidence.classes
    limits = result.confidence.dominant_limit
    cover = result.stack.get("canopy_cover")
    ndvi = result.stack.get("ndvi")

    rows, cols = np.nonzero(b.mask & np.isfinite(agb))
    for r, c in zip(rows, cols, strict=False):
        yield {
            "lon": float(b.lons[c]),
            "lat": float(b.lats[r]),
            "agb_mg_ha": float(agb[r, c]),
            "agb_p05_mg_ha": float(p05[r, c]),
            "agb_p95_mg_ha": float(p95[r, c]),
            "agb_sd_mg_ha": float(sd[r, c]),
            "carbon_tc_ha": float(agb[r, c] * CARBON_FRACTION),
            "co2e_tco2e_ha": float(agb[r, c] * CARBON_FRACTION * CO2E_PER_CARBON),
            "canopy_cover_pct": (
                float(cover[r, c] * 100.0) if cover is not None else None
            ),
            "ndvi": float(ndvi[r, c]) if ndvi is not None else None,
            "confidence": float(conf[r, c]),
            "confidence_class": class_label(int(classes[r, c])),
            "limiting_factor": limit_reason(int(limits[r, c])),
        }


# ----------------------------------------------------------------------
# GeoJSON
# ----------------------------------------------------------------------


def analysis_geojson(result: AnalysisResult, include_cells: bool = True) -> dict[str, Any]:
    dlon, dlat = _grid_steps(result)
    summary = result.summary()

    features: list[dict[str, Any]] = [
        {
            "type": "Feature",
            "geometry": result.aoi.geojson(),
            "properties": {
                "feature_type": "aoi",
                "aoi_id": result.aoi.aoi_id,
                "year": result.year,
                "area_km2": round(result.aoi.area_km2, 4),
                "area_ha": round(result.aoi.area_ha, 2),
                "canopy_cover_pct": summary["canopy"]["cover_pct"],
                "agb_mean_mg_ha": summary["biomass"]["mean_mg_ha"],
                "agb_p05_mg_ha": summary["biomass"]["p05_mg_ha"],
                "agb_p95_mg_ha": summary["biomass"]["p95_mg_ha"],
                "carbon_mean_tc_ha": summary["carbon"]["mean_tc_ha"],
                "co2e_mean_tco2e_ha": summary["co2e"]["mean_tco2e_ha"],
                "total_carbon_tc": summary["carbon"]["total_tc"],
                "total_co2e_t": summary["co2e"]["total_tco2e"],
                "mean_confidence": summary["confidence"]["mean_score"],
                "data_mode": result.mode.value,
                "simulated": result.mode == DataMode.SANDBOX_SIMULATION,
            },
        }
    ]

    if include_cells:
        for cell in _iter_cells(result):
            features.append(
                {
                    "type": "Feature",
                    "geometry": {
                        "type": "Polygon",
                        "coordinates": _cell_polygon(cell["lon"], cell["lat"], dlon, dlat),
                    },
                    "properties": {"feature_type": "analysis_cell", **cell},
                }
            )

    for site in result.field_plan.sites:
        feature = site.as_geojson_feature()
        feature["properties"]["feature_type"] = "field_site"
        features.append(feature)

    return {
        "type": "FeatureCollection",
        "name": f"sylvasense_{result.aoi.aoi_id}_{result.year}",
        "crs": {
            "type": "name",
            "properties": {"name": "urn:ogc:def:crs:OGC:1.3:CRS84"},
        },
        "metadata": {
            "generator": "SylvaSense",
            "generated_at": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
            "warning": _mode_banner(result.mode),
            "provenance": result.provenance(),
        },
        "features": features,
    }


def fieldplan_geojson(result: AnalysisResult) -> dict[str, Any]:
    payload = result.field_plan.as_geojson()
    payload["name"] = f"sylvasense_fieldplan_{result.aoi.aoi_id}_{result.year}"
    payload["crs"] = {
        "type": "name",
        "properties": {"name": "urn:ogc:def:crs:OGC:1.3:CRS84"},
    }
    payload["metadata"] = {
        "generator": "SylvaSense",
        "generated_at": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
        "method": result.field_plan.method,
        "min_separation_m": round(result.field_plan.min_separation_m, 1),
        "warning": _mode_banner(result.mode),
        "provenance": result.provenance(),
    }
    return payload


def change_geojson(result: AnalysisResult, change: ChangeResult) -> dict[str, Any]:
    dlon, dlat = _grid_steps(result)
    b = result.bundle
    features: list[dict[str, Any]] = [
        {
            "type": "Feature",
            "geometry": result.aoi.geojson(),
            "properties": {
                "feature_type": "aoi_change_summary",
                "aoi_id": result.aoi.aoi_id,
                **{
                    k: v
                    for k, v in change.as_dict().items()
                    if k not in ("evidence",)
                },
            },
        }
    ]
    rows, cols = np.nonzero(b.mask & np.isfinite(change.delta_grid))
    for r, c in zip(rows, cols, strict=False):
        code = int(change.class_grid[r, c])
        features.append(
            {
                "type": "Feature",
                "geometry": {
                    "type": "Polygon",
                    "coordinates": _cell_polygon(
                        float(b.lons[c]), float(b.lats[r]), dlon, dlat
                    ),
                },
                "properties": {
                    "feature_type": "change_cell",
                    "lon": float(b.lons[c]),
                    "lat": float(b.lats[r]),
                    "delta_agb_mg_ha": round(float(change.delta_grid[r, c]), 2),
                    "delta_carbon_tc_ha": round(
                        float(change.delta_grid[r, c]) * CARBON_FRACTION, 2
                    ),
                    "z_score": (
                        round(float(change.z_grid[r, c]), 3)
                        if np.isfinite(change.z_grid[r, c])
                        else None
                    ),
                    "change_class": {1: "SIGNIFICANT_LOSS", 2: "SIGNIFICANT_GAIN"}.get(
                        code, "NO_SIGNIFICANT_CHANGE"
                    ),
                },
            }
        )

    return {
        "type": "FeatureCollection",
        "name": (
            f"sylvasense_change_{result.aoi.aoi_id}_"
            f"{change.year_from}_{change.year_to}"
        ),
        "crs": {"type": "name", "properties": {"name": "urn:ogc:def:crs:OGC:1.3:CRS84"}},
        "metadata": {
            "generator": "SylvaSense",
            "generated_at": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
            "warning": _mode_banner(result.mode),
            "evidence": change.evidence,
        },
        "features": features,
    }


# ----------------------------------------------------------------------
# CSV
# ----------------------------------------------------------------------


CSV_COLUMNS = [
    "lon",
    "lat",
    "agb_mg_ha",
    "agb_p05_mg_ha",
    "agb_p95_mg_ha",
    "agb_sd_mg_ha",
    "carbon_tc_ha",
    "co2e_tco2e_ha",
    "canopy_cover_pct",
    "ndvi",
    "confidence",
    "confidence_class",
    "limiting_factor",
]


def analysis_csv(result: AnalysisResult) -> str:
    buf = io.StringIO()
    banner = _mode_banner(result.mode)
    if banner:
        buf.write(f"# {banner}\n")
    prov = result.provenance()
    buf.write(f"# SylvaSense analysis — AOI {result.aoi.aoi_id}, year {result.year}\n")
    buf.write(f"# Data mode: {result.mode.value}\n")
    buf.write(
        f"# Model: {prov['model']['version']} "
        f"({prov['model']['calibration']}, n={prov['model']['n_training']})\n"
    )
    buf.write(f"# Generated: {dt.datetime.now(dt.UTC).isoformat(timespec='seconds')}\n")
    buf.write(f"# Cell size: {prov['grid']['cell_size_m']} m ({prov['grid']['cell_area_ha']} ha)\n")

    writer = csv.DictWriter(buf, fieldnames=CSV_COLUMNS, extrasaction="ignore")
    writer.writeheader()
    for cell in _iter_cells(result):
        writer.writerow(
            {
                k: (round(v, 6) if isinstance(v, float) else v)
                for k, v in cell.items()
                if k in CSV_COLUMNS
            }
        )
    return buf.getvalue()


def fieldplan_csv(result: AnalysisResult) -> str:
    buf = io.StringIO()
    banner = _mode_banner(result.mode)
    if banner:
        buf.write(f"# {banner}\n")
    buf.write(f"# SylvaSense field plan — AOI {result.aoi.aoi_id}, year {result.year}\n")
    buf.write(f"# Method: {result.field_plan.method}\n")
    buf.write(f"# Minimum separation: {result.field_plan.min_separation_m:.0f} m\n")

    sites = [s.as_dict() for s in result.field_plan.sites]
    if not sites:
        buf.write("# No sites could be placed for this area.\n")
        return buf.getvalue()

    writer = csv.DictWriter(buf, fieldnames=list(sites[0].keys()))
    writer.writeheader()
    writer.writerows(sites)
    return buf.getvalue()


def to_json_bytes(payload: dict[str, Any]) -> bytes:
    return json.dumps(payload, indent=2, allow_nan=False, default=_json_default).encode(
        "utf-8"
    )


def _json_default(obj: Any) -> Any:
    if isinstance(obj, np.integer):
        return int(obj)
    if isinstance(obj, np.floating):
        value = float(obj)
        return None if not np.isfinite(value) else value
    if isinstance(obj, np.ndarray):
        return obj.tolist()
    if isinstance(obj, np.bool_):
        return bool(obj)
    raise TypeError(f"Not JSON serialisable: {type(obj)!r}")
