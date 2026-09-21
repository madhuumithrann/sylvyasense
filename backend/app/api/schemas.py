"""Request models."""

from __future__ import annotations

import datetime as dt
from typing import Any

from pydantic import BaseModel, Field, field_validator


def _default_year() -> int:
    return dt.date.today().year


class GeometryRequest(BaseModel):
    geometry: dict[str, Any] = Field(
        ..., description="GeoJSON Polygon, MultiPolygon, Feature or FeatureCollection"
    )


class AuditRequest(GeometryRequest):
    year: int = Field(default_factory=_default_year, ge=2015, le=2100)


class AnalysisRequest(GeometryRequest):
    year: int = Field(default_factory=_default_year, ge=2015, le=2100)
    target_cells: int = Field(default=2500, ge=256, le=4096)


class ChangeRequest(GeometryRequest):
    year_from: int = Field(..., ge=2015, le=2100)
    year_to: int = Field(..., ge=2015, le=2100)
    target_cells: int = Field(default=2500, ge=256, le=4096)

    @field_validator("year_to")
    @classmethod
    def _distinct_years(cls, value: int, info: Any) -> int:
        year_from = info.data.get("year_from")
        if year_from is not None and value == year_from:
            raise ValueError("year_to must differ from year_from")
        return value
