"""Field survey planner.

Picks ground-measurement locations that buy the most uncertainty reduction per
visit. Two things decide where a crew should go:

PRIORITY
    Cells where the model is least sure in absolute terms. Measuring a cell the
    model already predicts tightly teaches nothing, and measuring a cell whose
    predicted biomass is near zero reduces little total stock uncertainty. The
    priority surface is therefore the per-cell standard deviation weighted by
    how much of the AOI's total variance that cell carries, discounted by
    confidence.

SPATIAL BALANCE
    Uncertainty is spatially autocorrelated, so the top-N most uncertain cells
    are usually neighbours and a plan built from them measures one patch five
    times. Sites are selected greedily under a minimum-separation constraint —
    a maximin design — so the plan spreads across the AOI.

The "expected value" reported for each site is computed, not asserted: it is
the share of the AOI's total biomass variance that lies inside that site's
correlation neighbourhood, which is the variance a measurement there would
plausibly resolve.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np

from app.providers.base import ObservationBundle
from app.science.confidence import ConfidenceResult, limit_reason
from app.science.geo import geodesic_distance_m

#: A ground plot informs its surroundings out to roughly the correlation range
#: of the biomass field. 500 m is a conservative working value for C-band /
#: optical derived AGB maps.
CORRELATION_RANGE_M = 500.0

PRIORITY_HIGH_QUANTILE = 0.80
PRIORITY_MEDIUM_QUANTILE = 0.50

#: Terrain thresholds for the access note shown to the field crew.
STEEP_SLOPE_DEG = 25.0
VERY_STEEP_SLOPE_DEG = 35.0


@dataclass
class FieldSite:
    index: int
    lon: float
    lat: float
    priority: str
    priority_score: float
    agb_pred_mg_ha: float
    agb_sd_mg_ha: float
    agb_p05_mg_ha: float
    agb_p95_mg_ha: float
    confidence: float
    reason: str
    expected_variance_reduction_pct: float
    elevation_m: float | None
    slope_deg: float | None
    access_note: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "index": self.index,
            "label": f"{self.index:02d}",
            "lon": round(self.lon, 6),
            "lat": round(self.lat, 6),
            "priority": self.priority,
            "priority_score": round(self.priority_score, 4),
            "agb_pred_mg_ha": round(self.agb_pred_mg_ha, 1),
            "agb_sd_mg_ha": round(self.agb_sd_mg_ha, 1),
            "agb_p05_mg_ha": round(self.agb_p05_mg_ha, 1),
            "agb_p95_mg_ha": round(self.agb_p95_mg_ha, 1),
            "confidence": round(self.confidence, 3),
            "reason": self.reason,
            "expected_variance_reduction_pct": round(
                self.expected_variance_reduction_pct, 2
            ),
            "elevation_m": None if self.elevation_m is None else round(self.elevation_m, 1),
            "slope_deg": None if self.slope_deg is None else round(self.slope_deg, 1),
            "access_note": self.access_note,
        }

    def as_geojson_feature(self) -> dict[str, Any]:
        props = self.as_dict()
        return {
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [self.lon, self.lat]},
            "properties": props,
        }


@dataclass
class FieldPlan:
    sites: list[FieldSite]
    method: str
    min_separation_m: float
    correlation_range_m: float
    total_expected_reduction_pct: float
    requested: int

    def as_dict(self) -> dict[str, Any]:
        return {
            "sites": [s.as_dict() for s in self.sites],
            "count": len(self.sites),
            "requested": self.requested,
            "method": self.method,
            "min_separation_m": round(self.min_separation_m, 1),
            "correlation_range_m": self.correlation_range_m,
            "total_expected_reduction_pct": round(self.total_expected_reduction_pct, 2),
        }

    def as_geojson(self) -> dict[str, Any]:
        return {
            "type": "FeatureCollection",
            "features": [s.as_geojson_feature() for s in self.sites],
        }


def _access_note(slope: float | None, elevation: float | None) -> str:
    if slope is None:
        return "Terrain not characterised for this site."
    if slope >= VERY_STEEP_SLOPE_DEG:
        return (
            f"Very steep ({slope:.0f}°) — expect roped access or a long approach on foot."
        )
    if slope >= STEEP_SLOPE_DEG:
        return f"Steep ({slope:.0f}°) — plan extra time for the approach."
    if elevation is not None and elevation > 2000:
        return f"Moderate terrain at {elevation:.0f} m — altitude may slow the crew."
    return f"Moderate terrain ({slope:.0f}°) — normal walk-in access expected."


def plan_survey(
    bundle: ObservationBundle,
    agb: np.ndarray,
    agb_sd: np.ndarray,
    agb_p05: np.ndarray,
    agb_p95: np.ndarray,
    confidence: ConfidenceResult,
    n_sites: int = 12,
) -> FieldPlan:
    inside = bundle.mask & np.isfinite(agb) & np.isfinite(agb_sd)
    if not inside.any():
        return FieldPlan(
            sites=[],
            method="uncertainty-weighted maximin sampling",
            min_separation_m=0.0,
            correlation_range_m=CORRELATION_RANGE_M,
            total_expected_reduction_pct=0.0,
            requested=n_sites,
        )

    variance = np.where(inside, np.square(agb_sd), 0.0)
    total_variance = float(variance.sum())

    conf = np.nan_to_num(confidence.score, nan=0.0)
    # Priority: absolute uncertainty, discounted by how confident we already are.
    priority = np.where(inside, agb_sd * (1.0 - 0.65 * conf), -np.inf)

    # Minimum separation: spread n_sites over the AOI, but never closer than the
    # correlation range, or two sites would resolve the same neighbourhood.
    aoi_area_m2 = bundle.aoi.area_km2 * 1e6
    spacing = float(np.sqrt(aoi_area_m2 / max(n_sites, 1)))
    min_sep = max(0.60 * spacing, CORRELATION_RANGE_M)

    order = np.argsort(priority, axis=None)[::-1]
    rows, cols = np.unravel_index(order, priority.shape)

    chosen: list[tuple[int, int]] = []
    chosen_lonlat: list[tuple[float, float]] = []
    for r, c in zip(rows, cols):
        if len(chosen) >= n_sites:
            break
        if not np.isfinite(priority[r, c]) or priority[r, c] == -np.inf:
            break
        lon = float(bundle.lons[c])
        lat = float(bundle.lats[r])
        if any(
            geodesic_distance_m(lon, lat, plon, plat) < min_sep
            for plon, plat in chosen_lonlat
        ):
            continue
        chosen.append((int(r), int(c)))
        chosen_lonlat.append((lon, lat))

    # If separation was too strict to place the full complement, relax it once
    # rather than silently returning a short plan.
    if len(chosen) < n_sites and min_sep > CORRELATION_RANGE_M:
        relaxed = max(CORRELATION_RANGE_M, min_sep * 0.5)
        for r, c in zip(rows, cols):
            if len(chosen) >= n_sites:
                break
            if (int(r), int(c)) in chosen:
                continue
            if not np.isfinite(priority[r, c]) or priority[r, c] == -np.inf:
                break
            lon, lat = float(bundle.lons[c]), float(bundle.lats[r])
            if any(
                geodesic_distance_m(lon, lat, plon, plat) < relaxed
                for plon, plat in chosen_lonlat
            ):
                continue
            chosen.append((int(r), int(c)))
            chosen_lonlat.append((lon, lat))
        min_sep = relaxed

    if not chosen:
        return FieldPlan(
            sites=[],
            method="uncertainty-weighted maximin sampling",
            min_separation_m=min_sep,
            correlation_range_m=CORRELATION_RANGE_M,
            total_expected_reduction_pct=0.0,
            requested=n_sites,
        )

    scores = np.array([priority[r, c] for r, c in chosen], dtype=np.float64)
    score_max = float(scores.max()) or 1.0
    high_cut = float(np.quantile(scores, PRIORITY_HIGH_QUANTILE))
    med_cut = float(np.quantile(scores, PRIORITY_MEDIUM_QUANTILE))

    radius_cells = max(int(round(CORRELATION_RANGE_M / max(bundle.cell_size_m, 1.0))), 1)
    n_lat, n_lon = bundle.shape

    sites: list[FieldSite] = []
    claimed = np.zeros(bundle.shape, dtype=bool)
    for i, (r, c) in enumerate(chosen, start=1):
        r0, r1 = max(r - radius_cells, 0), min(r + radius_cells + 1, n_lat)
        c0, c1 = max(c - radius_cells, 0), min(c + radius_cells + 1, n_lon)
        window = np.zeros(bundle.shape, dtype=bool)
        window[r0:r1, c0:c1] = True
        # Only count variance not already claimed by an earlier site.
        newly = window & inside & ~claimed
        resolved = float(variance[newly].sum())
        claimed |= newly
        reduction_pct = 100.0 * resolved / total_variance if total_variance > 0 else 0.0

        score = float(priority[r, c])
        if score >= high_cut:
            priority_label = "HIGH"
        elif score >= med_cut:
            priority_label = "MEDIUM"
        else:
            priority_label = "LOW"

        elevation = (
            float(bundle.terrain.elevation_m[r, c])
            if bundle.terrain is not None and np.isfinite(bundle.terrain.elevation_m[r, c])
            else None
        )
        slope = (
            float(bundle.terrain.slope_deg[r, c])
            if bundle.terrain is not None and np.isfinite(bundle.terrain.slope_deg[r, c])
            else None
        )

        limit_idx = int(confidence.dominant_limit[r, c])
        reason = limit_reason(limit_idx)

        sites.append(
            FieldSite(
                index=i,
                lon=float(bundle.lons[c]),
                lat=float(bundle.lats[r]),
                priority=priority_label,
                priority_score=score / score_max,
                agb_pred_mg_ha=float(agb[r, c]),
                agb_sd_mg_ha=float(agb_sd[r, c]),
                agb_p05_mg_ha=float(agb_p05[r, c]),
                agb_p95_mg_ha=float(agb_p95[r, c]),
                confidence=float(conf[r, c]),
                reason=reason,
                expected_variance_reduction_pct=reduction_pct,
                elevation_m=elevation,
                slope_deg=slope,
                access_note=_access_note(slope, elevation),
            )
        )

    return FieldPlan(
        sites=sites,
        method=(
            "Uncertainty-weighted maximin sampling: cells ranked by predicted "
            "standard deviation discounted by confidence, then thinned to a "
            "minimum separation so sites do not resolve the same neighbourhood"
        ),
        min_separation_m=min_sep,
        correlation_range_m=CORRELATION_RANGE_M,
        total_expected_reduction_pct=sum(
            s.expected_variance_reduction_pct for s in sites
        ),
        requested=n_sites,
    )
