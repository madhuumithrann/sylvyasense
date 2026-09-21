"""Geodesic measurement and AOI validation."""

from __future__ import annotations

import math

import pytest

from app.core.errors import SylvaSenseError
from app.science.geo import (
    analysis_grid,
    geodesic_area_km2,
    geodesic_distance_m,
    inside_mask,
    parse_aoi,
)


def test_equatorial_square_area_matches_expectation(amazon_geometry):
    """0.18 deg square at the equator is ~20 km a side, so ~400 km2."""
    aoi = parse_aoi(amazon_geometry)
    assert aoi.area_km2 == pytest.approx(398.3, rel=0.01)
    assert aoi.area_ha == pytest.approx(aoi.area_km2 * 100.0)


def test_area_is_geodesic_not_planar():
    """A degree square shrinks with latitude. A planar area would not."""
    def square(lat: float) -> float:
        return geodesic_area_km2(
            parse_aoi(
                {
                    "type": "Polygon",
                    "coordinates": [
                        [[0, lat], [1, lat], [1, lat + 1], [0, lat + 1], [0, lat]]
                    ],
                }
            ).geometry
        )

    equator = square(0.0)
    high = square(60.0)
    # cos(60.5 deg) ~ 0.49, so the high-latitude cell is roughly half the area.
    assert high < equator * 0.6
    assert high == pytest.approx(equator * math.cos(math.radians(60.5)), rel=0.05)


def test_self_intersecting_polygon_is_repaired_or_rejected():
    bowtie = {
        "type": "Polygon",
        "coordinates": [[[0, 0], [1, 1], [1, 0], [0, 1], [0, 0]]],
    }
    # Shapely repairs a bowtie into a valid multipolygon; either way we must
    # never end up with an invalid geometry downstream.
    try:
        aoi = parse_aoi(bowtie)
    except SylvaSenseError as exc:
        assert exc.code == "INVALID_AOI"
    else:
        assert aoi.geometry.is_valid


def test_non_polygon_is_rejected():
    with pytest.raises(SylvaSenseError) as excinfo:
        parse_aoi({"type": "Point", "coordinates": [0, 0]})
    assert excinfo.value.code == "INVALID_AOI"
    assert excinfo.value.next_step


def test_out_of_range_coordinates_rejected():
    with pytest.raises(SylvaSenseError):
        parse_aoi(
            {
                "type": "Polygon",
                "coordinates": [[[0, 0], [400, 0], [400, 1], [0, 1], [0, 0]]],
            }
        )


def test_feature_and_featurecollection_are_unwrapped(amazon_geometry):
    direct = parse_aoi(amazon_geometry)
    feature = parse_aoi({"type": "Feature", "geometry": amazon_geometry, "properties": {}})
    collection = parse_aoi(
        {
            "type": "FeatureCollection",
            "features": [{"type": "Feature", "geometry": amazon_geometry}],
        }
    )
    assert direct.aoi_id == feature.aoi_id == collection.aoi_id


def test_fingerprint_is_stable_and_shape_sensitive(amazon_geometry):
    a = parse_aoi(amazon_geometry).aoi_id
    b = parse_aoi(amazon_geometry).aoi_id
    shifted = parse_aoi(
        {
            "type": "Polygon",
            "coordinates": [
                [[c[0] + 0.5, c[1]] for c in amazon_geometry["coordinates"][0]]
            ],
        }
    ).aoi_id
    assert a == b
    assert a != shifted


def test_grid_respects_cell_cap(amazon_geometry):
    aoi = parse_aoi(amazon_geometry)
    lons, lats, cell = analysis_grid(aoi, target_cells=100_000, max_cells=1024)
    assert lons.size * lats.size <= 1024
    assert cell > 0
    mask = inside_mask(aoi, lons, lats)
    assert mask.shape == (lats.size, lons.size)
    assert mask.any()


def test_grid_latitudes_descend(amazon_geometry):
    """Image convention: row 0 is the northern edge."""
    _, lats, _ = analysis_grid(parse_aoi(amazon_geometry), 2500, 4096)
    assert lats[0] > lats[-1]


def test_geodesic_distance_matches_known_separation():
    # One degree of latitude is ~111 km.
    assert geodesic_distance_m(0, 0, 0, 1) == pytest.approx(110_574, rel=0.01)
