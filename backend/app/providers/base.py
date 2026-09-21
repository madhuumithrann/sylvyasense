"""The data-provider contract.

Everything downstream of this module — the biomass model, uncertainty,
confidence scoring, the field planner, change detection — operates on the
structures defined here and has no knowledge of where the pixels came from.

That is what makes the sandbox honest: it substitutes only the *pixel source*,
never the science. When an Earth Engine credential is supplied, the identical
downstream code runs on real Sentinel/GEDI observations.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Protocol

import numpy as np

from app.science.geo import AOI


class DataMode(str, Enum):
    """How the numbers on screen were obtained. Rendered verbatim in the UI."""

    LIVE_EARTH_ENGINE = "LIVE_EARTH_ENGINE"
    SANDBOX_SIMULATION = "SANDBOX_SIMULATION"
    UNAVAILABLE = "UNAVAILABLE"


class SourceStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    PARTIAL = "PARTIAL"
    UNAVAILABLE = "UNAVAILABLE"
    NOT_CONFIGURED = "NOT_CONFIGURED"


@dataclass
class SourceAvailability:
    """Availability of one input mission over the AOI and time window."""

    key: str                      # "sentinel2" | "sentinel1" | "gedi" | "dem" | "worldcover"
    label: str                    # "Sentinel-2 L2A"
    status: SourceStatus
    scene_count: int = 0
    first_date: str | None = None
    last_date: str | None = None
    detail: str = ""
    metrics: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "label": self.label,
            "status": self.status.value,
            "scene_count": self.scene_count,
            "first_date": self.first_date,
            "last_date": self.last_date,
            "detail": self.detail,
            "metrics": self.metrics,
        }


@dataclass
class AuditResult:
    """Answer to 'can this area be analysed, and with what?'"""

    aoi_id: str
    area_km2: float
    area_ha: float
    perimeter_km: float
    centroid: tuple[float, float]
    bounds: list[float]
    forest_cover_pct: float | None
    cloud_cover_pct: float | None
    sources: list[SourceAvailability]
    mode: DataMode
    window_start: str
    window_end: str
    verdict: str                  # READY | PARTIAL_DATA | INSUFFICIENT_DATA
    verdict_detail: str
    generated_at: str = field(
        default_factory=lambda: dt.datetime.now(dt.UTC).isoformat(timespec="seconds")
    )

    def as_dict(self) -> dict[str, Any]:
        return {
            "aoi_id": self.aoi_id,
            "area_km2": round(self.area_km2, 4),
            "area_ha": round(self.area_ha, 2),
            "perimeter_km": round(self.perimeter_km, 3),
            "centroid": {"lon": self.centroid[0], "lat": self.centroid[1]},
            "bounds": self.bounds,
            "forest_cover_pct": self.forest_cover_pct,
            "cloud_cover_pct": self.cloud_cover_pct,
            "sources": [s.as_dict() for s in self.sources],
            "mode": self.mode.value,
            "window": {"start": self.window_start, "end": self.window_end},
            "verdict": self.verdict,
            "verdict_detail": self.verdict_detail,
            "generated_at": self.generated_at,
        }


@dataclass
class OpticalObservation:
    """Cloud-masked surface-reflectance composite, reflectance in [0, 1]."""

    bands: dict[str, np.ndarray]      # "B2".."B12" keyed, each (n_lat, n_lon)
    scene_count: int
    cloud_cover_pct: float
    valid_fraction: np.ndarray        # per-cell share of clear observations
    first_date: str
    last_date: str
    collection: str
    resolution_m: int


@dataclass
class RadarObservation:
    """Terrain-corrected backscatter in dB."""

    vv_db: np.ndarray
    vh_db: np.ndarray
    scene_count: int
    first_date: str
    last_date: str
    collection: str
    orbit: str
    resolution_m: int


@dataclass
class GediSamples:
    """GEDI L4A aboveground biomass density footprints inside the AOI."""

    lon: np.ndarray
    lat: np.ndarray
    agbd: np.ndarray                  # Mg/ha
    agbd_se: np.ndarray               # Mg/ha, per-shot standard error
    rh98: np.ndarray                  # m, relative height 98
    quality_flag: np.ndarray
    collection: str
    first_date: str | None
    last_date: str | None

    def __len__(self) -> int:
        return int(self.agbd.size)


@dataclass
class TerrainObservation:
    elevation_m: np.ndarray
    slope_deg: np.ndarray
    collection: str
    resolution_m: int


@dataclass
class LandcoverObservation:
    """ESA WorldCover class codes plus the derived tree-cover mask."""

    classes: np.ndarray               # WorldCover codes (10, 20, 30, ...)
    tree_mask: np.ndarray             # bool, class 10 "Tree cover"
    collection: str
    year: int
    resolution_m: int


@dataclass
class ObservationBundle:
    """Everything the science stack needs for one AOI and one time window."""

    aoi: AOI
    lons: np.ndarray
    lats: np.ndarray
    mask: np.ndarray                  # inside-AOI mask, (n_lat, n_lon)
    cell_size_m: float
    window_start: str
    window_end: str
    mode: DataMode
    optical: OpticalObservation | None = None
    radar: RadarObservation | None = None
    gedi: GediSamples | None = None
    terrain: TerrainObservation | None = None
    landcover: LandcoverObservation | None = None

    @property
    def shape(self) -> tuple[int, int]:
        return (int(self.lats.size), int(self.lons.size))

    def cell_area_ha(self) -> float:
        return (self.cell_size_m**2) / 10_000.0


class DataProvider(Protocol):
    """Implemented by EarthEngineProvider and SandboxProvider."""

    name: str
    mode: DataMode

    def is_ready(self) -> tuple[bool, str]:
        """(ready, reason). `reason` explains the failure when not ready."""
        ...

    def describe(self) -> dict[str, Any]:
        """Provenance block shown in the UI data-status panel."""
        ...

    def audit(self, aoi: AOI, window_start: str, window_end: str) -> AuditResult:
        """Cheap availability check — no heavy pixel work."""
        ...

    def observe(
        self, aoi: AOI, window_start: str, window_end: str, target_cells: int
    ) -> ObservationBundle:
        """Full observation pull for an analysis run."""
        ...


def window_for(end: dt.date | None = None, months: int = 6) -> tuple[str, str]:
    """A look-back window ending today (or `end`), as ISO dates."""
    end_date = end or dt.date.today()
    start_date = end_date - dt.timedelta(days=int(months * 30.44))
    return start_date.isoformat(), end_date.isoformat()


def year_window(year: int) -> tuple[str, str]:
    """Peak-growing-season-agnostic full-year window, clamped to today."""
    start = dt.date(year, 1, 1)
    end = min(dt.date(year, 12, 31), dt.date.today())
    return start.isoformat(), end.isoformat()
