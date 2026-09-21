"""In-memory result store.

Analysis results are large (several float grids each) and expensive to compute,
so they are cached by AOI fingerprint and year. The fingerprint is derived from
the geometry itself, which means redrawing the same polygon reuses the cached
result and a browser refresh loses nothing.

Entries expire on a TTL and the store is bounded, so a long-running server
cannot grow without limit.
"""

from __future__ import annotations

import threading
import time
from collections import OrderedDict
from typing import Any

from app.analysis.pipeline import AnalysisResult
from app.core.config import get_settings
from app.science.geo import AOI

_MAX_RESULTS = 24
_MAX_AOIS = 256


class ResultStore:
    def __init__(self) -> None:
        self._results: OrderedDict[str, tuple[float, AnalysisResult]] = OrderedDict()
        self._aois: OrderedDict[str, tuple[float, AOI]] = OrderedDict()
        self._changes: OrderedDict[str, tuple[float, Any]] = OrderedDict()
        self._lock = threading.RLock()

    # --- AOIs -----------------------------------------------------------

    def remember_aoi(self, aoi: AOI) -> None:
        with self._lock:
            self._aois[aoi.aoi_id] = (time.time(), aoi)
            self._aois.move_to_end(aoi.aoi_id)
            while len(self._aois) > _MAX_AOIS:
                self._aois.popitem(last=False)

    def get_aoi(self, aoi_id: str) -> AOI | None:
        with self._lock:
            entry = self._aois.get(aoi_id)
            if entry is None:
                return None
            self._aois.move_to_end(aoi_id)
            return entry[1]

    # --- Analyses --------------------------------------------------------

    def put(self, result: AnalysisResult) -> None:
        with self._lock:
            self.remember_aoi(result.aoi)
            self._results[result.key] = (time.time(), result)
            self._results.move_to_end(result.key)
            self._evict()

    def get(self, aoi_id: str, year: int) -> AnalysisResult | None:
        key = f"{aoi_id}:{year}"
        with self._lock:
            entry = self._results.get(key)
            if entry is None:
                return None
            created, result = entry
            if time.time() - created > get_settings().job_ttl_seconds:
                self._results.pop(key, None)
                return None
            self._results.move_to_end(key)
            return result

    def years_for(self, aoi_id: str) -> list[int]:
        with self._lock:
            return sorted(
                int(k.split(":")[1])
                for k in self._results
                if k.startswith(f"{aoi_id}:")
            )

    # --- Change results ---------------------------------------------------

    def put_change(self, aoi_id: str, year_from: int, year_to: int, result: Any) -> None:
        with self._lock:
            self._changes[f"{aoi_id}:{year_from}:{year_to}"] = (time.time(), result)
            while len(self._changes) > _MAX_RESULTS:
                self._changes.popitem(last=False)

    def get_change(self, aoi_id: str, year_from: int, year_to: int) -> Any | None:
        with self._lock:
            entry = self._changes.get(f"{aoi_id}:{year_from}:{year_to}")
            if entry is None:
                return None
            created, result = entry
            if time.time() - created > get_settings().job_ttl_seconds:
                self._changes.pop(f"{aoi_id}:{year_from}:{year_to}", None)
                return None
            return result

    # --- Housekeeping -----------------------------------------------------

    def _evict(self) -> None:
        ttl = get_settings().job_ttl_seconds
        now = time.time()
        stale = [k for k, (t, _) in self._results.items() if now - t > ttl]
        for key in stale:
            self._results.pop(key, None)
        while len(self._results) > _MAX_RESULTS:
            self._results.popitem(last=False)

    def stats(self) -> dict[str, int]:
        with self._lock:
            return {
                "analyses": len(self._results),
                "aois": len(self._aois),
                "changes": len(self._changes),
            }

    def clear(self) -> None:
        with self._lock:
            self._results.clear()
            self._aois.clear()
            self._changes.clear()


STORE = ResultStore()
