"""Provider selection.

`SYLVASENSE_PROVIDER` decides which data path is active:

    earthengine  require Earth Engine; refuse to run without it
    sandbox      always run the forward model
    auto         use Earth Engine when it initialises, otherwise the sandbox

In `auto` the fallback is never silent: the active mode is reported on every
status call, every audit, every analysis result and every export.
"""

from __future__ import annotations

import logging
import threading
from typing import Any

from app.core.config import Settings, get_settings
from app.core.errors import earth_engine_not_configured
from app.providers.base import DataMode, DataProvider
from app.providers.earthengine import EarthEngineProvider
from app.providers.sandbox import SandboxProvider

log = logging.getLogger("sylvasense.providers")

_lock = threading.Lock()
_cached: dict[str, Any] = {}


def _build(settings: Settings) -> dict[str, Any]:
    ee_provider = EarthEngineProvider(settings)
    sandbox = SandboxProvider(settings)
    ee_ready, ee_reason = ee_provider.is_ready()

    if settings.provider == "sandbox":
        active: DataProvider = sandbox
        fallback_reason = "SYLVASENSE_PROVIDER=sandbox — forward model requested explicitly"
    elif settings.provider == "earthengine":
        if not ee_ready:
            raise earth_engine_not_configured(ee_reason)
        active = ee_provider
        fallback_reason = None
    else:  # auto
        if ee_ready:
            active = ee_provider
            fallback_reason = None
        else:
            active = sandbox
            fallback_reason = ee_reason
            log.warning(
                "Earth Engine unavailable (%s) — falling back to the sandbox forward "
                "model. Results are simulated and labelled as such.",
                ee_reason,
            )

    return {
        "active": active,
        "earthengine": ee_provider,
        "sandbox": sandbox,
        "ee_ready": ee_ready,
        "ee_reason": ee_reason,
        "fallback_reason": fallback_reason,
    }


def _state() -> dict[str, Any]:
    global _cached
    if _cached:
        return _cached
    with _lock:
        if not _cached:
            _cached = _build(get_settings())
    return _cached


def reset() -> None:
    """Test hook — forces provider re-selection on the next call."""
    global _cached
    with _lock:
        _cached = {}


def active_provider() -> DataProvider:
    return _state()["active"]


def provider_status() -> dict[str, Any]:
    """The payload behind the UI's data-status indicator."""
    st = _state()
    active: DataProvider = st["active"]
    described = active.describe()
    simulated = active.mode == DataMode.SANDBOX_SIMULATION

    return {
        "active": active.name,
        "mode": active.mode.value,
        "ready": True,
        "simulated": simulated,
        "indicator": "SANDBOX SIMULATION" if simulated else "LIVE EARTH ENGINE",
        "headline": (
            "Simulated scene — not a satellite observation"
            if simulated
            else "Live Earth Engine observations"
        ),
        "detail": described,
        "earth_engine": {
            "ready": st["ee_ready"],
            "reason": st["ee_reason"],
            "configured": bool(
                get_settings().ee_service_account_file
                or get_settings().ee_service_account_json
            ),
            "setup_doc": "docs/EARTH_ENGINE_SETUP.md",
            "next_step": (
                None
                if st["ee_ready"]
                else (
                    "Set SYLVASENSE_EE_SERVICE_ACCOUNT_FILE and SYLVASENSE_EE_PROJECT, "
                    "then restart the backend. See docs/EARTH_ENGINE_SETUP.md."
                )
            ),
        },
        "fallback_reason": st["fallback_reason"],
    }
