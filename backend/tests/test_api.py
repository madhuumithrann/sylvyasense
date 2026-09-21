"""API contract and the full analysis workflow over HTTP."""

from __future__ import annotations

import io
import json
import time

import pytest


def _wait_for_job(client, job_id: str, timeout: float = 120.0) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        payload = client.get(f"/api/v1/jobs/{job_id}").json()
        if payload["status"] in ("COMPLETE", "FAILED"):
            return payload
        time.sleep(0.15)
    raise AssertionError(f"job {job_id} did not finish within {timeout}s")


@pytest.fixture
def analysed(client, amazon_geometry):
    started = client.post(
        "/api/v1/analysis", json={"geometry": amazon_geometry, "year": 2026}
    )
    assert started.status_code == 202
    job = _wait_for_job(client, started.json()["job_id"])
    assert job["status"] == "COMPLETE", job.get("error")
    return job["result"]


# --- System -------------------------------------------------------------


def test_health_reports_data_mode(client):
    body = client.get("/health").json()
    assert body["status"] == "ok"
    assert body["data_mode"] in ("LIVE_EARTH_ENGINE", "SANDBOX_SIMULATION")
    assert isinstance(body["simulated"], bool)


def test_status_exposes_provider_and_remediation(client):
    body = client.get("/api/v1/system/status").json()
    provider = body["provider"]
    assert provider["indicator"] in ("LIVE EARTH ENGINE", "SANDBOX SIMULATION")
    ee = provider["earth_engine"]
    assert "ready" in ee
    if not ee["ready"]:
        # A missing credential must always come with the exact next step.
        assert ee["next_step"]
        assert "EARTH_ENGINE_SETUP" in ee["setup_doc"]
    assert body["limits"]["max_aoi_km2"] > 0


def test_layer_catalogue_matches_legends(client):
    body = client.get("/api/v1/system/layers").json()
    legends = body["legends"]
    for group in body["catalogue"]["groups"]:
        for layer in group["layers"]:
            if layer["ramp"]:
                assert layer["ramp"] in legends, layer["key"]


def test_steps_endpoint_lists_pipeline(client):
    body = client.get("/api/v1/system/steps").json()
    keys = [s["key"] for s in body["analysis"]]
    assert "biomass_model" in keys and "confidence_map" in keys
    assert sum(c["weight"] for c in body["confidence_components"]) == pytest.approx(1.0)


# --- Places ---------------------------------------------------------------


def test_place_search_and_demo_areas(client):
    results = client.get("/api/v1/places", params={"q": "amazon"}).json()["results"]
    assert results and all("lon" in r and "lat" in r for r in results)

    demos = client.get("/api/v1/places/demo").json()["results"]
    assert len(demos) >= 4
    for demo in demos:
        assert demo["geometry"]["type"] == "Polygon"


def test_demo_area_is_analysable(client):
    demo = client.get("/api/v1/places/demo").json()["results"][0]
    validated = client.post("/api/v1/aoi/validate", json={"geometry": demo["geometry"]})
    assert validated.status_code == 200
    assert validated.json()["area_km2"] > 0


# --- AOI validation --------------------------------------------------------


def test_validate_returns_geodesic_measurements(client, amazon_geometry):
    body = client.post("/api/v1/aoi/validate", json={"geometry": amazon_geometry}).json()
    assert body["area_km2"] == pytest.approx(398.3, rel=0.01)
    assert body["perimeter_km"] > 0
    assert "Geodesic" in body["measurement"]
    assert len(body["bounds"]) == 4


def test_oversized_aoi_is_refused_with_guidance(client):
    huge = {
        "type": "Polygon",
        "coordinates": [[[0, 0], [5, 0], [5, 5], [0, 5], [0, 0]]],
    }
    response = client.post("/api/v1/aoi/validate", json={"geometry": huge})
    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "AOI_TOO_LARGE"
    assert error["next_step"]
    assert error["title"].isupper()


def test_invalid_geometry_returns_readable_error(client):
    response = client.post(
        "/api/v1/aoi/validate", json={"geometry": {"type": "Point", "coordinates": [0, 0]}}
    )
    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "INVALID_AOI"
    assert error["causes"]
    # Never leak a raw traceback to the user.
    assert "Traceback" not in json.dumps(error)


def test_malformed_request_is_translated(client):
    response = client.post("/api/v1/analysis", json={"geometry": {}, "year": 1800})
    assert response.status_code == 422
    assert response.json()["error"]["code"] in ("INVALID_REQUEST", "INVALID_AOI")


# --- Audit -------------------------------------------------------------------


def test_audit_reports_every_source(client, amazon_geometry):
    body = client.post(
        "/api/v1/audit", json={"geometry": amazon_geometry, "year": 2026}
    ).json()
    assert body["verdict"] in ("READY", "PARTIAL_DATA", "INSUFFICIENT_DATA")
    keys = {s["key"] for s in body["sources"]}
    assert {"sentinel2", "sentinel1", "gedi", "dem", "worldcover"} <= keys
    assert body["area_km2"] > 0
    assert body["forest_cover_pct"] is not None


def test_audit_of_boreal_site_flags_gedi_gap(client, boreal_geometry):
    body = client.post(
        "/api/v1/audit", json={"geometry": boreal_geometry, "year": 2026}
    ).json()
    gedi = next(s for s in body["sources"] if s["key"] == "gedi")
    assert gedi["status"] in ("UNAVAILABLE", "PARTIAL")
    assert body["verdict"] in ("PARTIAL_DATA", "INSUFFICIENT_DATA")


# --- Analysis workflow ---------------------------------------------------------


def test_analysis_job_reports_real_steps(client, amazon_geometry):
    started = client.post(
        "/api/v1/analysis", json={"geometry": amazon_geometry, "year": 2026}
    ).json()
    assert started["status"] in ("QUEUED", "RUNNING")
    assert started["steps_total"] == len(started["steps"])

    job = _wait_for_job(client, started["job_id"])
    assert job["status"] == "COMPLETE"
    assert job["steps_completed"] == job["steps_total"]
    states = {s["state"] for s in job["steps"]}
    assert states <= {"DONE", "SKIPPED"}
    # Every finished step must carry a note explaining what actually happened.
    assert all(s["note"] for s in job["steps"])


def test_analysis_summary_is_complete(client, analysed):
    body = client.get(
        f"/api/v1/analysis/{analysed['aoi_id']}/{analysed['year']}"
    ).json()
    assert body["canopy"]["cover_pct"] > 0
    assert body["biomass"]["mean_mg_ha"] > 0
    assert body["biomass"]["p05_mg_ha"] <= body["biomass"]["mean_mg_ha"]
    assert body["biomass"]["p95_mg_ha"] >= body["biomass"]["mean_mg_ha"]
    assert body["carbon"]["mean_tc_ha"] > 0
    assert body["co2e"]["mean_tco2e_ha"] > body["carbon"]["mean_tc_ha"]
    assert body["confidence"]["mean_score"] >= 0
    assert body["geometry"]["type"] in ("Polygon", "MultiPolygon")


def test_every_headline_number_has_provenance(client, analysed):
    prov = client.get(
        f"/api/v1/analysis/{analysed['aoi_id']}/{analysed['year']}"
    ).json()["provenance"]
    assert prov["mode"]
    assert prov["window"]["start"] and prov["window"]["end"]
    assert prov["optical"]["collection"]
    assert prov["optical"]["scenes"] > 0
    assert prov["model"]["version"]
    assert prov["model"]["calibration"] in ("gedi-local", "regional-default")
    assert prov["grid"]["cell_size_m"] > 0


def test_second_run_is_served_from_cache(client, amazon_geometry, analysed):
    again = client.post(
        "/api/v1/analysis", json={"geometry": amazon_geometry, "year": 2026}
    ).json()
    assert again["status"] == "COMPLETE"
    assert again["result"]["cached"] is True


def test_result_missing_before_analysis(client):
    response = client.get("/api/v1/analysis/deadbeefdeadbeef/2026")
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "ANALYSIS_REQUIRED"


# --- Inspection -------------------------------------------------------------------


def test_inspect_returns_full_confidence_detail(client, analysed, amazon_geometry):
    lon, lat = -59.91, -2.91
    body = client.get(
        f"/api/v1/analysis/{analysed['aoi_id']}/{analysed['year']}/inspect",
        params={"lon": lon, "lat": lat},
    ).json()
    assert body["inside_aoi"] is True
    assert body["biomass"]["agb_mg_ha"] is not None
    assert body["confidence"]["class"] in (
        "HIGH_CONFIDENCE",
        "SURVEY_RECOMMENDED",
        "INSUFFICIENT_DATA",
    )
    assert body["confidence"]["limiting_factor"]
    assert set(body["confidence"]["components"]) == {
        "model_precision",
        "gedi_support",
        "optical_quality",
        "radar_support",
    }
    assert body["evidence"]["optical_scenes"] > 0


def test_inspect_outside_aoi_says_so(client, analysed):
    body = client.get(
        f"/api/v1/analysis/{analysed['aoi_id']}/{analysed['year']}/inspect",
        params={"lon": 10.0, "lat": 40.0},
    ).json()
    assert body["inside_aoi"] is False
    assert body["message"]


def test_fieldplan_endpoint_returns_numbered_sites(client, analysed):
    body = client.get(
        f"/api/v1/analysis/{analysed['aoi_id']}/{analysed['year']}/fieldplan"
    ).json()
    assert body["count"] > 0
    assert body["geojson"]["type"] == "FeatureCollection"
    labels = [f["properties"]["label"] for f in body["geojson"]["features"]]
    assert labels == [f"{i:02d}" for i in range(1, len(labels) + 1)]


# --- Tiles ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "layer",
    ["truecolor", "falsecolor", "ndvi", "vv", "vh", "agb", "carbon",
     "confidence", "confidence_class", "canopy_cover", "gedi_density",
     "cloud", "elevation", "slope", "worldcover"],
)
def test_every_layer_renders_a_png(client, analysed, layer):
    from PIL import Image

    url = f"/api/v1/tiles/{analysed['aoi_id']}/{analysed['year']}/{layer}/11/683/1040.png"
    response = client.get(url)
    assert response.status_code == 200
    assert response.headers["content-type"] == "image/png"
    image = Image.open(io.BytesIO(response.content))
    assert image.size == (256, 256)
    assert image.mode == "RGBA"


def test_tile_over_the_aoi_is_not_blank(client, analysed):
    import numpy as np
    from PIL import Image

    url = f"/api/v1/tiles/{analysed['aoi_id']}/{analysed['year']}/agb/11/683/1040.png"
    pixels = np.array(Image.open(io.BytesIO(client.get(url).content)))
    assert (pixels[..., 3] > 0).sum() > 1000


def test_tile_away_from_the_aoi_is_transparent(client, analysed):
    import numpy as np
    from PIL import Image

    url = f"/api/v1/tiles/{analysed['aoi_id']}/{analysed['year']}/agb/11/100/1040.png"
    pixels = np.array(Image.open(io.BytesIO(client.get(url).content)))
    assert (pixels[..., 3] > 0).sum() == 0


def test_unknown_layer_is_rejected(client, analysed):
    response = client.get(
        f"/api/v1/tiles/{analysed['aoi_id']}/{analysed['year']}/nope/11/683/1040.png"
    )
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND"


# --- Change --------------------------------------------------------------------------


@pytest.fixture
def changed(client, amazon_geometry, analysed):
    started = client.post(
        "/api/v1/change",
        json={"geometry": amazon_geometry, "year_from": 2022, "year_to": 2026},
    )
    assert started.status_code == 202
    job = _wait_for_job(client, started.json()["job_id"], timeout=180)
    assert job["status"] == "COMPLETE", job.get("error")
    return job["result"]


def test_change_job_and_summary(client, changed):
    body = client.get(
        f"/api/v1/change/{changed['aoi_id']}/{changed['year_from']}/{changed['year_to']}"
    ).json()
    assert body["verdict"] in (
        "SIGNIFICANT_CHANGE",
        "NO_SIGNIFICANT_CHANGE",
        "INSUFFICIENT_DATA",
    )
    assert "z_score" in body["statistics"]
    assert body["statistics"]["z_critical"] == pytest.approx(1.96, abs=0.01)
    assert body["biomass"]["from_mg_ha"] > 0
    assert body["verdict_detail"]
    assert body["evidence"]["cells_compared"] > 0


def test_change_tiles_render(client, changed):
    for layer in ("agb_change", "carbon_change", "change_class"):
        url = (
            f"/api/v1/tiles/change/{changed['aoi_id']}/{changed['year_from']}"
            f"/{changed['year_to']}/{layer}/11/683/1040.png"
        )
        response = client.get(url)
        assert response.status_code == 200, layer
        assert response.headers["content-type"] == "image/png"


def test_change_before_running_is_refused(client, analysed):
    response = client.get(f"/api/v1/change/{analysed['aoi_id']}/2019/2020")
    assert response.status_code == 409


# --- Exports ----------------------------------------------------------------------------


def test_analysis_geojson_download(client, analysed):
    response = client.get(
        f"/api/v1/export/{analysed['aoi_id']}/{analysed['year']}/analysis.geojson"
    )
    assert response.status_code == 200
    assert "attachment" in response.headers["content-disposition"]
    payload = response.json()
    assert payload["type"] == "FeatureCollection"
    kinds = {f["properties"]["feature_type"] for f in payload["features"]}
    assert {"aoi", "analysis_cell", "field_site"} <= kinds
    assert payload["metadata"]["provenance"]["model"]["version"]


def test_geojson_is_valid_json_without_nan(client, analysed):
    response = client.get(
        f"/api/v1/export/{analysed['aoi_id']}/{analysed['year']}/analysis.geojson"
    )
    # json.loads rejects bare NaN, so this asserts strict JSON compliance.
    json.loads(response.content.decode("utf-8"), parse_constant=_reject)


def _reject(value):  # pragma: no cover - only runs on malformed output
    raise AssertionError(f"non-standard JSON constant in export: {value}")


def test_csv_download_has_provenance_header(client, analysed):
    response = client.get(
        f"/api/v1/export/{analysed['aoi_id']}/{analysed['year']}/analysis.csv"
    )
    assert response.status_code == 200
    text = response.text
    assert text.startswith("#")
    assert "Data mode:" in text
    assert "agb_mg_ha" in text
    assert text.count("\n") > 10


def test_fieldplan_downloads(client, analysed):
    gj = client.get(
        f"/api/v1/export/{analysed['aoi_id']}/{analysed['year']}/fieldplan.geojson"
    )
    assert gj.status_code == 200
    assert gj.json()["type"] == "FeatureCollection"

    csv_response = client.get(
        f"/api/v1/export/{analysed['aoi_id']}/{analysed['year']}/fieldplan.csv"
    )
    assert csv_response.status_code == 200
    assert "priority" in csv_response.text


def test_dossier_is_a_real_pdf(client, analysed):
    response = client.get(
        f"/api/v1/export/{analysed['aoi_id']}/{analysed['year']}/dossier.pdf"
    )
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/pdf"
    assert response.content.startswith(b"%PDF")
    assert len(response.content) > 5000


def test_change_geojson_export(client, changed):
    response = client.get(
        f"/api/v1/export/{changed['aoi_id']}/{changed['year_from']}"
        f"/{changed['year_to']}/change.geojson"
    )
    assert response.status_code == 200
    payload = response.json()
    kinds = {f["properties"]["feature_type"] for f in payload["features"]}
    assert "change_cell" in kinds


def test_simulated_exports_carry_the_warning(client, analysed):
    status = client.get("/api/v1/system/status").json()
    if not status["provider"]["simulated"]:
        pytest.skip("running against live Earth Engine")

    gj = client.get(
        f"/api/v1/export/{analysed['aoi_id']}/{analysed['year']}/analysis.geojson"
    ).json()
    assert "SANDBOX SIMULATION" in gj["metadata"]["warning"]

    csv_text = client.get(
        f"/api/v1/export/{analysed['aoi_id']}/{analysed['year']}/analysis.csv"
    ).text
    assert "SANDBOX SIMULATION" in csv_text
