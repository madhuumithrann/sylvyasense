"""Deterministic coherent-noise fields.

Multi-octave value noise with quintic interpolation — the same construction
used for procedural terrain. Given an identical seed and grid, the output is
bit-for-bit reproducible, which is what makes sandbox analyses stable across
reloads and comparable across years.
"""

from __future__ import annotations

import numpy as np


def _hash_lattice(ix: np.ndarray, iy: np.ndarray, seed: int) -> np.ndarray:
    """Integer lattice -> pseudo-random values in [0, 1), via integer hashing."""
    mask = np.int64(0x7FFFFFFFFFFFFFFF)
    # Fold the seed in Python-int space first: numpy int64 would overflow on the
    # 64-bit odd multiplier before the mask is applied.
    seed_term = np.int64((int(seed) * 1_442_695_040_888_963_407) & 0x7FFFFFFFFFFFFFFF)
    h = (ix.astype(np.int64) * np.int64(374_761_393)) + (
        iy.astype(np.int64) * np.int64(668_265_263)
    )
    h = (h + seed_term) & mask
    h = ((h ^ (h >> 13)) * np.int64(1_274_126_177)) & mask
    h = h ^ (h >> 16)
    return (h & np.int64(0xFFFFFF)).astype(np.float64) / float(0xFFFFFF)


def _quintic(t: np.ndarray) -> np.ndarray:
    """6t^5 - 15t^4 + 10t^3 — C2-continuous ease curve (Perlin's improved fade)."""
    return t * t * t * (t * (t * 6.0 - 15.0) + 10.0)


def value_noise(x: np.ndarray, y: np.ndarray, seed: int) -> np.ndarray:
    """Smooth value noise in [0, 1] sampled at continuous coordinates."""
    x0 = np.floor(x).astype(np.int64)
    y0 = np.floor(y).astype(np.int64)
    fx = _quintic(x - x0)
    fy = _quintic(y - y0)

    v00 = _hash_lattice(x0, y0, seed)
    v10 = _hash_lattice(x0 + 1, y0, seed)
    v01 = _hash_lattice(x0, y0 + 1, seed)
    v11 = _hash_lattice(x0 + 1, y0 + 1, seed)

    top = v00 + (v10 - v00) * fx
    bottom = v01 + (v11 - v01) * fx
    return top + (bottom - top) * fy


def fbm(
    x: np.ndarray,
    y: np.ndarray,
    seed: int,
    octaves: int = 5,
    lacunarity: float = 2.0,
    gain: float = 0.5,
) -> np.ndarray:
    """Fractional Brownian motion — summed octaves, normalised to [0, 1]."""
    total = np.zeros_like(x, dtype=np.float64)
    amplitude = 1.0
    frequency = 1.0
    norm = 0.0
    for o in range(octaves):
        total += amplitude * value_noise(x * frequency, y * frequency, seed + o * 7919)
        norm += amplitude
        amplitude *= gain
        frequency *= lacunarity
    return total / max(norm, 1e-9)


def ridged(x: np.ndarray, y: np.ndarray, seed: int, octaves: int = 4) -> np.ndarray:
    """Ridged multifractal — produces drainage-like ridges and valleys."""
    total = np.zeros_like(x, dtype=np.float64)
    amplitude = 1.0
    frequency = 1.0
    norm = 0.0
    for o in range(octaves):
        n = value_noise(x * frequency, y * frequency, seed + o * 6151)
        total += amplitude * (1.0 - np.abs(2.0 * n - 1.0))
        norm += amplitude
        amplitude *= 0.5
        frequency *= 2.0
    return total / max(norm, 1e-9)


def normalise(a: np.ndarray) -> np.ndarray:
    """Rescale a finite array to [0, 1]; constant input maps to 0.5."""
    finite = np.isfinite(a)
    if not finite.any():
        return np.full_like(a, 0.5, dtype=np.float64)
    lo = float(np.nanmin(a[finite]))
    hi = float(np.nanmax(a[finite]))
    if hi - lo < 1e-12:
        return np.full_like(a, 0.5, dtype=np.float64)
    return (a - lo) / (hi - lo)
