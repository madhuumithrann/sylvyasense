"""Runtime configuration.

Every setting is environment-driven so that the same image runs in a
credential-less sandbox and against a real Earth Engine service account
without code changes.
"""

from __future__ import annotations

import os
from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

ProviderName = Literal["earthengine", "sandbox", "auto"]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="SYLVASENSE_",
        env_file=(".env", "../.env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- Service ---
    app_name: str = "SylvaSense"
    version: str = "0.3.0"
    host: str = "127.0.0.1"
    port: int = 8000
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"

    # --- Data provider selection ---
    # "auto"        : use Earth Engine when credentials initialise, else sandbox
    # "earthengine" : require Earth Engine; fail loudly when unavailable
    # "sandbox"     : always use the synthetic forward model
    provider: ProviderName = "auto"

    # --- Earth Engine credentials ---
    # Path to a Google Cloud service-account JSON with the Earth Engine API
    # enabled, plus the Cloud project that service account belongs to.
    ee_service_account_file: str | None = None
    ee_service_account_json: str | None = None  # inline JSON, for container secrets
    ee_project: str | None = None
    ee_high_volume: bool = True

    # --- Analysis defaults ---
    analysis_scale_m: int = 30          # native working resolution
    max_aoi_km2: float = 2500.0         # guard against runaway EE requests
    min_aoi_km2: float = 0.05
    grid_max_cells: int = 4096          # cap on the internal analysis grid
    optical_cloud_limit: float = 60.0   # % scene cloud cover to reject a scene
    composite_months: int = 6           # look-back window for a composite

    # --- Model ---
    model_version: str = "sylvasense-agb-0.3"
    min_gedi_samples: int = 40          # below this we cannot calibrate locally

    # --- Jobs ---
    job_ttl_seconds: int = 3600
    max_concurrent_jobs: int = 4

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def ee_endpoint(self) -> str:
        if self.ee_high_volume:
            return "https://earthengine-highvolume.googleapis.com"
        return "https://earthengine.googleapis.com"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


def reset_settings_cache() -> None:
    """Test hook — drops the memoised settings object."""
    get_settings.cache_clear()


def running_under_pytest() -> bool:
    return "PYTEST_CURRENT_TEST" in os.environ
