from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# Tests exercise the pipeline deterministically through the forward model.
os.environ.setdefault("SYLVASENSE_PROVIDER", "sandbox")

from app.analysis.store import STORE  # noqa: E402
from app.core.config import reset_settings_cache  # noqa: E402
from app.providers import registry  # noqa: E402


@pytest.fixture(autouse=True)
def _clean_state():
    reset_settings_cache()
    registry.reset()
    STORE.clear()
    yield
    STORE.clear()


#: ~400 km2 over the central Amazon.
AMAZON = {
    "type": "Polygon",
    "coordinates": [
        [[-60.0, -3.0], [-59.82, -3.0], [-59.82, -2.82], [-60.0, -2.82], [-60.0, -3.0]]
    ],
}

#: ~500 km2 in Finnish Lapland — beyond the GEDI latitude limit.
BOREAL = {
    "type": "Polygon",
    "coordinates": [
        [[25.0, 62.0], [25.3, 62.0], [25.3, 62.15], [25.0, 62.15], [25.0, 62.0]]
    ],
}


@pytest.fixture
def amazon_geometry() -> dict:
    return AMAZON


@pytest.fixture
def boreal_geometry() -> dict:
    return BOREAL


@pytest.fixture
def client():
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as test_client:
        yield test_client
