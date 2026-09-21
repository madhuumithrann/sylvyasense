"""Geospatial primitives.

All areas and distances are computed geodesically on the WGS84 ellipsoid via
pyproj.Geod — never with a planar approximation of lat/lon degrees, which is
wrong by tens of percent away from the equator.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Any

import numpy as np
from pyproj import Geod
from shapely.geometry import MultiPolygon, Polygon, mapping, shape
from shapely.geometry.base import BaseGeometry
from shapely.validation import explain_validity

from app.core.errors import invalid_aoi

GEOD = Geod(ellps="WGS84")

# IUCN/FAO-style working constant: 1 hectare = 0.01 km²
KM2_PER_HA = 0.01


@dataclass(frozen=True)
class Bounds:
    west: float
    south: float
    east: float
    north: float

    def as_list(self) -> list[float]:
        return [self.west, self.south, self.east, self.north]

    @property
    def center(self) -> tuple[float, float]:
        return ((self.west + self.east) / 2.0, (self.south + self.north) / 2.0)

    def width_m(self) -> float:
        _, _, d = GEOD.inv(self.west, self.center[1], self.east, self.center[1])
        return float(d)

    def height_m(self) -> float:
        _, _, d = GEOD.inv(self.center[0], self.south, self.center[0], self.north)
        return float(d)


@dataclass(frozen=True)
class AOI:
    """A validated area of interest."""

    geometry: BaseGeometry
    area_km2: float
    bounds: Bounds
    aoi_id: str

    @property
    def area_ha(self) -> float:
        return self.area_km2 / KM2_PER_HA

    def geojson(self) -> dict[str, Any]:
        return mapping(self.geometry)

    def centroid(self) -> tuple[float, float]:
        c = self.geometry.centroid
        return (float(c.x), float(c.y))


def geodesic_area_km2(geometry: BaseGeometry) -> float:
    """Ellipsoidal area in km², holes subtracted, multipart aware."""

    def polygon_area(poly: Polygon) -> float:
        area, _ = GEOD.geometry_area_perimeter(poly)
        return abs(area)

    if isinstance(geometry, Polygon):
        total = polygon_area(geometry)
    elif isinstance(geometry, MultiPolygon):
        total = sum(polygon_area(p) for p in geometry.geoms)
    else:
        raise invalid_aoi("Only polygons and multipolygons can be analysed.")
    return total / 1_000_000.0


def geodesic_perimeter_km(geometry: BaseGeometry) -> float:
    _, perim = GEOD.geometry_area_perimeter(geometry)
    return abs(perim) / 1000.0


def geodesic_distance_m(lon1: float, lat1: float, lon2: float, lat2: float) -> float:
    _, _, dist = GEOD.inv(lon1, lat1, lon2, lat2)
    return float(dist)


def _coords_in_range(geometry: BaseGeometry) -> bool:
    for lon, lat in _iter_coords(geometry):
        if not (-180.0 <= lon <= 180.0 and -90.0 <= lat <= 90.0):
            return False
    return True


def _iter_coords(geometry: BaseGeometry) -> Iterable[tuple[float, float]]:
    if isinstance(geometry, Polygon):
        yield from ((float(x), float(y)) for x, y in geometry.exterior.coords)
        for ring in geometry.interiors:
            yield from ((float(x), float(y)) for x, y in ring.coords)
    elif isinstance(geometry, MultiPolygon):
        for poly in geometry.geoms:
            yield from _iter_coords(poly)


def aoi_fingerprint(geometry: BaseGeometry) -> str:
    """Stable identity for a geometry — identical shapes reuse cached analysis."""
    normalised = json.dumps(
        _round_geojson(mapping(geometry), 6), sort_keys=True, separators=(",", ":")
    )
    return hashlib.sha256(normalised.encode("utf-8")).hexdigest()[:16]


def _round_geojson(obj: Any, ndigits: int) -> Any:
    if isinstance(obj, dict):
        return {k: _round_geojson(v, ndigits) for k, v in obj.items()}
    if isinstance(obj, list | tuple):
        return [_round_geojson(v, ndigits) for v in obj]
    if isinstance(obj, float):
        return round(obj, ndigits)
    return obj


def parse_aoi(geojson_geometry: dict[str, Any]) -> AOI:
    """Validate an incoming GeoJSON geometry and derive its measured properties."""
    if not isinstance(geojson_geometry, dict) or "type" not in geojson_geometry:
        raise invalid_aoi("The area of interest was not sent as a GeoJSON geometry.")

    gtype = geojson_geometry.get("type")
    if gtype == "Feature":
        geojson_geometry = geojson_geometry.get("geometry") or {}
        gtype = geojson_geometry.get("type")
    if gtype == "FeatureCollection":
        feats = geojson_geometry.get("features") or []
        if not feats:
            raise invalid_aoi("The area of interest contains no shapes.")
        geojson_geometry = feats[0].get("geometry") or {}
        gtype = geojson_geometry.get("type")

    if gtype not in ("Polygon", "MultiPolygon"):
        raise invalid_aoi(
            f"A {gtype or 'shape'} cannot be analysed — draw a closed area instead."
        )

    try:
        geometry = shape(geojson_geometry)
    except Exception as exc:  # malformed coordinate structure
        raise invalid_aoi(
            "The polygon coordinates could not be read.", technical=str(exc)
        ) from exc

    if geometry.is_empty:
        raise invalid_aoi("The drawn area is empty.")
    if not _coords_in_range(geometry):
        raise invalid_aoi(
            "Some corners of the area fall outside valid longitude/latitude ranges."
        )
    if not geometry.is_valid:
        reason = explain_validity(geometry)
        repaired = geometry.buffer(0)
        if repaired.is_empty or not repaired.is_valid:
            raise invalid_aoi(
                "The polygon crosses itself and could not be repaired.", technical=reason
            )
        geometry = repaired

    if isinstance(geometry, Polygon) and len(geometry.exterior.coords) < 4:
        raise invalid_aoi("A polygon needs at least three distinct corners.")

    area_km2 = geodesic_area_km2(geometry)
    if area_km2 <= 0:
        raise invalid_aoi("The drawn area has no measurable extent.")

    minx, miny, maxx, maxy = geometry.bounds
    return AOI(
        geometry=geometry,
        area_km2=area_km2,
        bounds=Bounds(float(minx), float(miny), float(maxx), float(maxy)),
        aoi_id=aoi_fingerprint(geometry),
    )


def analysis_grid(
    aoi: AOI, target_cells: int, max_cells: int
) -> tuple[np.ndarray, np.ndarray, float]:
    """Build a regular lon/lat sampling grid covering the AOI bounding box.

    Returns (lons, lats, cell_size_m). The grid is sized so that the number of
    cells lands near `target_cells` while never exceeding `max_cells`, keeping
    a single analysis bounded regardless of AOI size.
    """
    b = aoi.bounds
    width_m = max(b.width_m(), 1.0)
    height_m = max(b.height_m(), 1.0)
    aspect = width_m / height_m

    cells = min(target_cells, max_cells)
    n_x = max(int(round(math.sqrt(cells * aspect))), 4)
    n_y = max(int(round(cells / n_x)), 4)
    while n_x * n_y > max_cells:
        n_x = max(n_x - 1, 4)
        n_y = max(n_y - 1, 4)
        if n_x == 4 and n_y == 4:
            break

    lons = np.linspace(b.west, b.east, n_x)
    lats = np.linspace(b.north, b.south, n_y)  # north-up, image convention
    cell_size_m = float(np.mean([width_m / max(n_x - 1, 1), height_m / max(n_y - 1, 1)]))
    return lons, lats, cell_size_m


def inside_mask(aoi: AOI, lons: np.ndarray, lats: np.ndarray) -> np.ndarray:
    """Boolean mask (n_lat, n_lon) marking grid centres inside the AOI polygon."""
    from shapely import contains_xy  # shapely >= 2.0 vectorised predicate

    lon_grid, lat_grid = np.meshgrid(lons, lats)
    mask = contains_xy(aoi.geometry, lon_grid.ravel(), lat_grid.ravel())
    return np.asarray(mask, dtype=bool).reshape(lon_grid.shape)


def bounds_of(coords: Sequence[tuple[float, float]]) -> Bounds:
    xs = [c[0] for c in coords]
    ys = [c[1] for c in coords]
    return Bounds(min(xs), min(ys), max(xs), max(ys))


def bbox_polygon(bounds: Bounds) -> Polygon:
    return Polygon(
        [
            (bounds.west, bounds.south),
            (bounds.east, bounds.south),
            (bounds.east, bounds.north),
            (bounds.west, bounds.north),
        ]
    )


def tile_bounds(z: int, x: int, y: int) -> Bounds:
    """Web-Mercator XYZ tile to WGS84 bounds."""
    n = 2.0**z

    def lon(tx: float) -> float:
        return tx / n * 360.0 - 180.0

    def lat(ty: float) -> float:
        return math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * ty / n))))

    return Bounds(lon(x), lat(y + 1), lon(x + 1), lat(y))
