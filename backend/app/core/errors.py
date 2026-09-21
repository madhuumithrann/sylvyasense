"""User-facing error contract.

The spec is explicit: a user must never see "500 Internal Server Error".
Every failure that can reach the UI is modelled as a `SylvaSenseError` with
a stable machine code, a human title, a plain-language explanation, a list of
likely causes and a concrete next step. The frontend renders these directly.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class SylvaSenseError(Exception):
    """An error that is safe and useful to show to a non-technical user."""

    code: str
    title: str
    detail: str
    causes: list[str] = field(default_factory=list)
    next_step: str | None = None
    status_code: int = 400
    retryable: bool = True
    technical: str | None = None

    def __post_init__(self) -> None:
        super().__init__(f"{self.code}: {self.title}")

    def to_payload(self) -> dict[str, Any]:
        return {
            "error": {
                "code": self.code,
                "title": self.title,
                "detail": self.detail,
                "causes": self.causes,
                "next_step": self.next_step,
                "retryable": self.retryable,
                "technical": self.technical,
            }
        }


# --------------------------------------------------------------------------
# Concrete errors
# --------------------------------------------------------------------------


def invalid_aoi(detail: str, technical: str | None = None) -> SylvaSenseError:
    return SylvaSenseError(
        code="INVALID_AOI",
        title="AREA OF INTEREST IS NOT VALID",
        detail=detail,
        causes=[
            "the polygon crosses itself",
            "fewer than three distinct corners were drawn",
            "coordinates fall outside the valid lat/lon range",
        ],
        next_step="Redraw the area as a simple, non-crossing polygon.",
        status_code=422,
        technical=technical,
    )


def aoi_too_large(area_km2: float, limit_km2: float) -> SylvaSenseError:
    return SylvaSenseError(
        code="AOI_TOO_LARGE",
        title="AREA OF INTEREST IS TOO LARGE",
        detail=(
            f"This area covers {area_km2:,.0f} km². "
            f"SylvaSense analyses up to {limit_km2:,.0f} km² in a single run so that "
            "results stay at full resolution."
        ),
        causes=["the drawn polygon spans a whole region rather than a forest stand"],
        next_step=f"Draw a smaller area (under {limit_km2:,.0f} km²) or split it into tiles.",
        status_code=422,
        retryable=False,
    )


def aoi_too_small(area_km2: float, limit_km2: float) -> SylvaSenseError:
    return SylvaSenseError(
        code="AOI_TOO_SMALL",
        title="AREA OF INTEREST IS TOO SMALL",
        detail=(
            f"This area covers {area_km2:.3f} km², which is smaller than a single "
            f"reliable analysis cell. The minimum is {limit_km2:.2f} km²."
        ),
        causes=["the polygon was drawn as a very small sliver"],
        next_step=f"Draw an area of at least {limit_km2:.2f} km².",
        status_code=422,
        retryable=False,
    )


def earth_engine_not_configured(reason: str | None = None) -> SylvaSenseError:
    return SylvaSenseError(
        code="EARTH_ENGINE_NOT_CONFIGURED",
        title="EARTH ENGINE IS NOT CONFIGURED",
        detail=(
            "SylvaSense reads Sentinel-2, Sentinel-1, GEDI and Copernicus DEM through "
            "Google Earth Engine. No working Earth Engine credential is present, so no "
            "satellite observation can be retrieved for this area."
        ),
        causes=[
            "no service-account key has been supplied",
            "the service account is not registered for Earth Engine",
            "the Earth Engine API is not enabled on the Cloud project",
        ],
        next_step=(
            "Set SYLVASENSE_EE_SERVICE_ACCOUNT_FILE to a service-account JSON key and "
            "SYLVASENSE_EE_PROJECT to its Cloud project, then restart the backend. "
            "See docs/EARTH_ENGINE_SETUP.md for the four commands required."
        ),
        status_code=503,
        retryable=False,
        technical=reason,
    )


def earth_engine_unavailable(reason: str) -> SylvaSenseError:
    return SylvaSenseError(
        code="EARTH_ENGINE_DATA_UNAVAILABLE",
        title="EARTH ENGINE DATA UNAVAILABLE",
        detail=(
            "Satellite imagery could not be retrieved for this area from Earth Engine."
        ),
        causes=[
            "no valid scenes intersect this area in the selected window",
            "an Earth Engine authentication problem",
            "the Earth Engine request quota was exhausted",
            "the area of interest is invalid for this collection",
        ],
        next_step="Try another area or a wider date window, then retry.",
        status_code=502,
        retryable=True,
        technical=reason,
    )


def insufficient_data(detail: str, causes: list[str] | None = None) -> SylvaSenseError:
    return SylvaSenseError(
        code="INSUFFICIENT_DATA",
        title="NOT ENOUGH USABLE DATA",
        detail=detail,
        causes=causes
        or [
            "persistent cloud cover over the whole window",
            "no radar acquisitions over this area",
            "the area falls outside the mission footprint",
        ],
        next_step="Widen the date window, or choose an area with clearer acquisitions.",
        status_code=422,
        retryable=True,
    )


def analysis_required(what: str = "analysis") -> SylvaSenseError:
    return SylvaSenseError(
        code="ANALYSIS_REQUIRED",
        title="RUN AN ANALYSIS FIRST",
        detail=f"No completed analysis is available for this area, so {what} cannot be produced.",
        causes=["the analysis has not been run", "the previous result has expired"],
        next_step="Select the area and press RUN ANALYSIS.",
        status_code=409,
        retryable=False,
    )


def not_found(what: str, ident: str) -> SylvaSenseError:
    return SylvaSenseError(
        code="NOT_FOUND",
        title=f"{what.upper()} NOT FOUND",
        detail=f"No {what} exists with identifier {ident}. It may have expired.",
        causes=["the result expired", "the backend restarted"],
        next_step="Re-run the analysis to produce a fresh result.",
        status_code=404,
        retryable=False,
    )


def internal(reason: str) -> SylvaSenseError:
    return SylvaSenseError(
        code="INTERNAL_ERROR",
        title="SOMETHING WENT WRONG INSIDE SYLVASENSE",
        detail=(
            "The analysis stopped because of an unexpected internal problem. "
            "This is a defect in SylvaSense, not in your area of interest."
        ),
        causes=["an unhandled condition in the analysis pipeline"],
        next_step="Retry the analysis. If it keeps failing, report the technical detail below.",
        status_code=500,
        retryable=True,
        technical=reason,
    )
