"""Raster tile rendering.

Analysis grids live in EPSG:4326 over the AOI bounding box. Web maps request
Web-Mercator XYZ tiles. This module resamples a grid into a 256x256 RGBA tile
for any requested z/x/y, painting with the same ramp definition the legend is
generated from, and leaving everything outside the AOI fully transparent.

Rendering happens on the fly from arrays already in memory, so a layer toggle
costs no recomputation and no raster download.
"""

from __future__ import annotations

import io
import math
from typing import Any

import numpy as np
from PIL import Image

from app.render.colormaps import CATEGORY_RAMPS, RAMPS, CategoryRamp, Ramp

TILE_SIZE = 256


def _tile_lonlat(z: int, x: int, y: int, size: int = TILE_SIZE) -> tuple[np.ndarray, np.ndarray]:
    """Longitude and latitude of each pixel centre in an XYZ tile."""
    n = 2.0**z
    px = (np.arange(size) + 0.5) / size
    tx = x + px
    ty = y + px
    lons = tx / n * 360.0 - 180.0
    lat_rad = np.arctan(np.sinh(np.pi * (1.0 - 2.0 * ty / n)))
    lats = np.degrees(lat_rad)
    return lons, lats


def _sample_grid(
    grid: np.ndarray,
    grid_lons: np.ndarray,
    grid_lats: np.ndarray,
    tile_lons: np.ndarray,
    tile_lats: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    """Nearest-neighbour resample of `grid` onto the tile raster.

    Returns (values, in_extent). Pixels outside the grid's own extent are
    flagged so they can be made transparent rather than clamped to an edge
    value, which would smear the AOI edge across the whole tile.
    """
    lon_min, lon_max = float(grid_lons.min()), float(grid_lons.max())
    lat_min, lat_max = float(grid_lats.min()), float(grid_lats.max())

    # Half a cell of tolerance so edge cells are not clipped away.
    dlon = (
        float(np.mean(np.diff(grid_lons))) if grid_lons.size > 1 else 1e-4
    )
    dlat = (
        float(np.mean(np.abs(np.diff(grid_lats)))) if grid_lats.size > 1 else 1e-4
    )
    lon_ok = (tile_lons >= lon_min - dlon / 2) & (tile_lons <= lon_max + dlon / 2)
    lat_ok = (tile_lats >= lat_min - dlat / 2) & (tile_lats <= lat_max + dlat / 2)
    in_extent = lat_ok[:, None] & lon_ok[None, :]

    col = np.clip(
        np.searchsorted(grid_lons, tile_lons) - 0, 0, grid_lons.size - 1
    )
    # searchsorted gives the insertion point; step back when the left
    # neighbour is closer, so this is a true nearest-neighbour lookup.
    left = np.clip(col - 1, 0, grid_lons.size - 1)
    take_left = np.abs(grid_lons[left] - tile_lons) <= np.abs(grid_lons[col] - tile_lons)
    col = np.where(take_left, left, col)

    desc = -grid_lats  # grid latitudes descend; searchsorted needs ascending
    row = np.clip(np.searchsorted(desc, -tile_lats), 0, grid_lats.size - 1)
    up = np.clip(row - 1, 0, grid_lats.size - 1)
    take_up = np.abs(grid_lats[up] - tile_lats) <= np.abs(grid_lats[row] - tile_lats)
    row = np.where(take_up, up, row)

    values = grid[np.ix_(row, col)]
    return values, in_extent


def _encode(rgba: np.ndarray) -> bytes:
    img = Image.fromarray(rgba, mode="RGBA")
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


def blank_tile() -> bytes:
    return _encode(np.zeros((TILE_SIZE, TILE_SIZE, 4), dtype=np.uint8))


def render_continuous(
    grid: np.ndarray,
    grid_lons: np.ndarray,
    grid_lats: np.ndarray,
    z: int,
    x: int,
    y: int,
    ramp: Ramp,
    opacity: float = 1.0,
    vmin: float | None = None,
    vmax: float | None = None,
) -> bytes:
    tile_lons, tile_lats = _tile_lonlat(z, x, y)
    values, in_extent = _sample_grid(grid, grid_lons, grid_lats, tile_lons, tile_lats)

    lo = ramp.vmin if vmin is None else vmin
    hi = ramp.vmax if vmax is None else vmax
    span = (hi - lo) or 1.0
    normalised = np.clip((values - lo) / span, 0.0, 1.0)

    lut = ramp.lut(256)
    idx = np.nan_to_num(normalised * 255.0, nan=0.0).astype(np.uint16)
    rgb = lut[np.clip(idx, 0, 255)]

    rgba = np.zeros((TILE_SIZE, TILE_SIZE, 4), dtype=np.uint8)
    rgba[..., :3] = rgb
    visible = in_extent & np.isfinite(values)
    rgba[..., 3] = (visible * int(np.clip(opacity, 0.0, 1.0) * 255)).astype(np.uint8)
    return _encode(rgba)


def render_categorical(
    grid: np.ndarray,
    grid_lons: np.ndarray,
    grid_lats: np.ndarray,
    z: int,
    x: int,
    y: int,
    ramp: CategoryRamp,
    opacity: float = 1.0,
) -> bytes:
    tile_lons, tile_lats = _tile_lonlat(z, x, y)
    values, in_extent = _sample_grid(grid, grid_lons, grid_lats, tile_lons, tile_lats)

    rgba = np.zeros((TILE_SIZE, TILE_SIZE, 4), dtype=np.uint8)
    alpha = int(np.clip(opacity, 0.0, 1.0) * 255)
    codes = np.nan_to_num(values, nan=-999).astype(np.int32)

    for code, colour, _label in ramp.categories:
        hit = in_extent & (codes == code)
        if not hit.any():
            continue
        r, g, b = _hex(colour)
        rgba[hit, 0] = r
        rgba[hit, 1] = g
        rgba[hit, 2] = b
        rgba[hit, 3] = alpha
    return _encode(rgba)


def _hex(value: str) -> tuple[int, int, int]:
    value = value.lstrip("#")
    return (int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16))


def render_rgb(
    red: np.ndarray,
    green: np.ndarray,
    blue: np.ndarray,
    grid_lons: np.ndarray,
    grid_lats: np.ndarray,
    z: int,
    x: int,
    y: int,
    vmin: float = 0.02,
    vmax: float = 0.30,
    gamma: float = 1.25,
    opacity: float = 1.0,
) -> bytes:
    """True/false-colour composite from three reflectance bands."""
    tile_lons, tile_lats = _tile_lonlat(z, x, y)
    rgba = np.zeros((TILE_SIZE, TILE_SIZE, 4), dtype=np.uint8)

    finite = None
    for channel, band in enumerate((red, green, blue)):
        values, in_extent = _sample_grid(band, grid_lons, grid_lats, tile_lons, tile_lats)
        scaled = np.clip((values - vmin) / ((vmax - vmin) or 1.0), 0.0, 1.0)
        stretched = np.power(np.nan_to_num(scaled, nan=0.0), 1.0 / max(gamma, 1e-6))
        rgba[..., channel] = (stretched * 255).astype(np.uint8)
        ok = in_extent & np.isfinite(values)
        finite = ok if finite is None else (finite & ok)

    rgba[..., 3] = ((finite if finite is not None else False) * int(opacity * 255)).astype(
        np.uint8
    )
    return _encode(rgba)


def tile_intersects(
    z: int, x: int, y: int, bounds: list[float]
) -> bool:
    """Cheap rejection test so out-of-area tiles cost nothing to serve."""
    n = 2.0**z
    west = x / n * 360.0 - 180.0
    east = (x + 1) / n * 360.0 - 180.0
    north = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * y / n))))
    south = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * (y + 1) / n))))
    return not (
        east < bounds[0] or west > bounds[2] or north < bounds[1] or south > bounds[3]
    )


def ramp_for(layer: str) -> Ramp | CategoryRamp | None:
    return RAMPS.get(layer) or CATEGORY_RAMPS.get(layer)


def describe_layers() -> dict[str, Any]:
    return {
        "continuous": [r.legend() for r in RAMPS.values()],
        "categorical": [r.legend() for r in CATEGORY_RAMPS.values()],
        "tile_size": TILE_SIZE,
    }
