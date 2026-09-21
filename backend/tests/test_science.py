"""The scientific core: indices, biomass, carbon, confidence, planning, change."""

from __future__ import annotations

import numpy as np
import pytest

from app.analysis.pipeline import run_analysis
from app.core.errors import SylvaSenseError
from app.providers.base import window_for
from app.providers.sandbox import SandboxProvider
from app.science.biomass import estimate_biomass
from app.science.carbon import (
    CARBON_FRACTION,
    CO2E_PER_CARBON,
    biomass_to_carbon,
)
from app.science.change import detect_change
from app.science.confidence import (
    COMPONENT_ORDER,
    HIGH_CONFIDENCE_THRESHOLD,
    SURVEY_THRESHOLD,
    compute_confidence,
)
from app.science.geo import geodesic_distance_m, parse_aoi
from app.science.indices import compute_index_stack, fractional_cover, ndvi


@pytest.fixture(scope="module")
def amazon_analysis():
    aoi = parse_aoi(
        {
            "type": "Polygon",
            "coordinates": [
                [[-60.0, -3.0], [-59.82, -3.0], [-59.82, -2.82], [-60.0, -2.82], [-60.0, -3.0]]
            ],
        }
    )
    return run_analysis(aoi, 2026)


# --- Indices -----------------------------------------------------------


def test_ndvi_bounds_and_direction():
    nir = np.array([0.32, 0.10, 0.05])
    red = np.array([0.03, 0.10, 0.20])
    values = ndvi(nir, red)
    assert values[0] > 0.7          # dense canopy
    assert values[1] == pytest.approx(0.0)
    assert values[2] < 0.0          # bare/water
    assert np.all(values >= -1.0) and np.all(values <= 1.0)


def test_ndvi_handles_zero_denominator_without_warning():
    out = ndvi(np.array([0.0]), np.array([0.0]))
    assert np.isnan(out[0])


def test_fractional_cover_is_clamped_and_monotonic():
    values = fractional_cover(np.array([-0.5, 0.12, 0.5, 0.9, 1.5]))
    assert values[0] == 0.0
    assert values[1] == pytest.approx(0.0)
    assert values[-1] == pytest.approx(1.0)
    assert np.all(np.diff(values) >= -1e-12)


def test_index_stack_has_optical_and_radar_predictors(amazon_analysis):
    stack = amazon_analysis.stack
    for key in ("ndvi", "evi", "ndmi", "canopy_cover", "vv_db", "vh_db", "rvi"):
        assert key in stack


def test_sandbox_radar_matches_published_forest_backscatter(amazon_analysis):
    """Dense tropical canopy sits near VV -9 dB and VH -16 dB at C-band."""
    bundle = amazon_analysis.bundle
    vv = float(np.nanmean(bundle.radar.vv_db[bundle.mask]))
    vh = float(np.nanmean(bundle.radar.vh_db[bundle.mask]))
    assert -12.0 < vv < -6.0
    assert -19.0 < vh < -13.0
    assert vh < vv          # cross-pol is always weaker than co-pol


# --- Biomass -------------------------------------------------------------


def test_biomass_interval_ordering_and_positivity(amazon_analysis):
    r = amazon_analysis.biomass
    inside = amazon_analysis.bundle.mask & np.isfinite(r.agb)
    assert np.all(r.agb[inside] >= 0)
    assert np.all(r.agb_p05[inside] <= r.agb[inside] + 1e-9)
    assert np.all(r.agb_p95[inside] >= r.agb[inside] - 1e-9)
    assert r.aoi_p05 <= r.aoi_mean <= r.aoi_p95


def test_tropical_biomass_is_physically_plausible(amazon_analysis):
    assert 80.0 < amazon_analysis.biomass.aoi_mean < 450.0


def test_local_calibration_reports_blocked_cv(amazon_analysis):
    model = amazon_analysis.biomass.model
    assert model.calibration == "gedi-local"
    assert model.n_training >= 40
    assert model.uncalibrated is False
    assert "spatial blocks" in (model.cv_scheme or "")
    assert model.cv_rmse is not None and model.cv_rmse > 0


def test_area_mean_interval_uses_effective_sample_size(amazon_analysis):
    """The area mean must not be tightened as if every cell were independent."""
    r = amazon_analysis.biomass
    inside = amazon_analysis.bundle.mask & np.isfinite(r.agb)
    n_cells = int(inside.sum())
    assert r.effective_n < n_cells      # blocks, not cells
    assert r.effective_n >= 1


def test_beyond_gedi_latitude_falls_back_and_is_flagged(boreal_geometry):
    aoi = parse_aoi(boreal_geometry)
    start, end = window_for(months=6)
    bundle = SandboxProvider().observe(aoi, start, end, 1024)
    assert bundle.gedi is None or len(bundle.gedi) == 0

    result = estimate_biomass(bundle, compute_index_stack(bundle))
    model = result.model
    assert model.calibration == "regional-default"
    assert model.uncalibrated is True
    assert model.n_training == 0
    assert model.cv_r2 is None
    assert any("GEDI" in c for c in model.caveats)


def test_biomass_refuses_when_no_predictors_exist(amazon_analysis):
    with pytest.raises(SylvaSenseError) as excinfo:
        estimate_biomass(amazon_analysis.bundle, {})
    assert excinfo.value.code == "INSUFFICIENT_DATA"


# --- Carbon ----------------------------------------------------------------


def test_carbon_conversion_uses_ipcc_constants():
    result = biomass_to_carbon(200.0, 150.0, 250.0, 20_000.0, np.array([[200.0]]))
    assert result.carbon_mean == pytest.approx(200.0 * CARBON_FRACTION)
    assert result.co2e_mean == pytest.approx(200.0 * CARBON_FRACTION * CO2E_PER_CARBON)
    assert result.total_carbon_t == pytest.approx(20_000.0 * CARBON_FRACTION)
    # 1 Mg/ha AGB -> 0.47 tC/ha -> 1.72 tCO2e/ha
    assert CO2E_PER_CARBON == pytest.approx(3.6641, rel=1e-4)


def test_carbon_interval_inherits_biomass_interval():
    result = biomass_to_carbon(200.0, 150.0, 250.0, 1.0, np.array([[200.0]]))
    assert result.carbon_p05 < result.carbon_mean < result.carbon_p95
    assert result.carbon_p05 == pytest.approx(150.0 * CARBON_FRACTION)


def test_belowground_is_reported_separately():
    result = biomass_to_carbon(200.0, 150.0, 250.0, 1.0, np.array([[200.0]]))
    assert result.belowground_carbon_mean > 0
    assert result.belowground_carbon_mean < result.carbon_mean
    assert "excluded" in result.as_dict()["belowground"]["note"]


# --- Confidence -------------------------------------------------------------


def test_confidence_components_are_bounded(amazon_analysis):
    conf = amazon_analysis.confidence
    for key in COMPONENT_ORDER:
        values = conf.components[key]
        assert np.nanmin(values) >= -1e-9
        assert np.nanmax(values) <= 1.0 + 1e-9


def test_confidence_classes_follow_thresholds(amazon_analysis):
    conf = amazon_analysis.confidence
    inside = amazon_analysis.bundle.mask
    high = conf.classes[inside] == 2
    assert np.all(conf.score[inside][high] >= HIGH_CONFIDENCE_THRESHOLD - 1e-9)
    low = conf.classes[inside] == 0
    assert np.all(conf.score[inside][low] < SURVEY_THRESHOLD + 1e-9)
    assert sum(conf.class_fractions.values()) == pytest.approx(1.0, abs=1e-6)


def test_uncalibrated_model_lowers_confidence(amazon_analysis):
    """The same evidence must score lower when the model was never fitted here."""
    b = amazon_analysis.bundle
    bio = amazon_analysis.biomass
    calibrated = compute_confidence(b, bio.agb, bio.agb_p05, bio.agb_p95, False)
    uncalibrated = compute_confidence(b, bio.agb, bio.agb_p05, bio.agb_p95, True)
    assert uncalibrated.mean_score < calibrated.mean_score


def test_limiting_factor_names_a_real_component(amazon_analysis):
    conf = amazon_analysis.confidence
    inside = amazon_analysis.bundle.mask
    limits = conf.dominant_limit[inside]
    assert limits.min() >= 0
    assert limits.max() < len(COMPONENT_ORDER)


# --- Field plan ---------------------------------------------------------------


def test_field_plan_respects_minimum_separation(amazon_analysis):
    plan = amazon_analysis.field_plan
    assert len(plan.sites) > 0
    for i, a in enumerate(plan.sites):
        for b in plan.sites[i + 1 :]:
            assert geodesic_distance_m(a.lon, a.lat, b.lon, b.lat) >= (
                plan.min_separation_m - 1.0
            )


def test_field_sites_carry_computed_expected_value(amazon_analysis):
    plan = amazon_analysis.field_plan
    assert all(s.expected_variance_reduction_pct >= 0 for s in plan.sites)
    assert plan.total_expected_reduction_pct == pytest.approx(
        sum(s.expected_variance_reduction_pct for s in plan.sites), rel=1e-6
    )
    # Sites resolve a share of total variance, never more than all of it.
    assert plan.total_expected_reduction_pct <= 100.0 + 1e-6


def test_field_sites_are_inside_the_aoi(amazon_analysis):
    from shapely.geometry import Point

    geom = amazon_analysis.aoi.geometry
    for site in amazon_analysis.field_plan.sites:
        assert geom.buffer(1e-6).contains(Point(site.lon, site.lat))


def test_field_sites_are_numbered_and_prioritised(amazon_analysis):
    sites = amazon_analysis.field_plan.sites
    assert [s.index for s in sites] == list(range(1, len(sites) + 1))
    assert all(s.priority in ("HIGH", "MEDIUM", "LOW") for s in sites)
    assert all(s.reason for s in sites)
    assert all(s.access_note for s in sites)


# --- Change ---------------------------------------------------------------------


def test_identical_epochs_show_no_change(amazon_analysis):
    change = detect_change(
        amazon_analysis.bundle,
        amazon_analysis.biomass,
        amazon_analysis.bundle,
        amazon_analysis.biomass,
        2026,
        2026,
    )
    assert change.agb_delta == pytest.approx(0.0, abs=1e-9)
    assert change.verdict == "NO_SIGNIFICANT_CHANGE"
    assert change.loss_area_ha == 0.0
    assert change.gain_area_ha == 0.0


def test_active_frontier_reports_significant_loss():
    """A high-disturbance sandbox site must clear the significance bar."""
    aoi = parse_aoi(
        {
            "type": "Polygon",
            "coordinates": [
                [[101.8, -0.6], [101.94, -0.6], [101.94, -0.46], [101.8, -0.46], [101.8, -0.6]]
            ],
        }
    )
    old = run_analysis(aoi, 2022)
    new = run_analysis(aoi, 2026)
    change = detect_change(old.bundle, old.biomass, new.bundle, new.biomass, 2022, 2026)
    assert change.verdict == "SIGNIFICANT_CHANGE"
    assert change.agb_delta < 0
    assert abs(change.z_score) > 1.96
    assert change.p_value < 0.05
    assert change.loss_area_ha > 0


def test_change_carbon_tracks_biomass_delta():
    aoi = parse_aoi(
        {
            "type": "Polygon",
            "coordinates": [
                [[101.8, -0.6], [101.94, -0.6], [101.94, -0.46], [101.8, -0.46], [101.8, -0.6]]
            ],
        }
    )
    old = run_analysis(aoi, 2022)
    new = run_analysis(aoi, 2026)
    change = detect_change(old.bundle, old.biomass, new.bundle, new.biomass, 2022, 2026)
    assert change.carbon_delta == pytest.approx(change.agb_delta * CARBON_FRACTION)
    assert change.co2e_delta == pytest.approx(
        change.carbon_delta * CO2E_PER_CARBON
    )


def test_uncalibrated_epoch_blocks_a_change_verdict(boreal_geometry):
    aoi = parse_aoi(boreal_geometry)
    old = run_analysis(aoi, 2022)
    new = run_analysis(aoi, 2026)
    change = detect_change(old.bundle, old.biomass, new.bundle, new.biomass, 2022, 2026)
    assert change.verdict == "INSUFFICIENT_DATA"
    assert "uncalibrated" in change.verdict_detail.lower()


def test_change_requires_matching_grids(amazon_analysis):
    aoi = parse_aoi(
        {
            "type": "Polygon",
            "coordinates": [
                [[-60.0, -3.0], [-59.9, -3.0], [-59.9, -2.9], [-60.0, -2.9], [-60.0, -3.0]]
            ],
        }
    )
    other = run_analysis(aoi, 2026, target_cells=256)
    if other.bundle.shape != amazon_analysis.bundle.shape:
        with pytest.raises(ValueError):
            detect_change(
                amazon_analysis.bundle,
                amazon_analysis.biomass,
                other.bundle,
                other.biomass,
                2025,
                2026,
            )
