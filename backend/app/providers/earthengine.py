"""Earth Engine data provider — the real observation path.

Collections used:

  Sentinel-2 L2A   COPERNICUS/S2_SR_HARMONIZED       10-20 m optical SR
  Cloud masking    GOOGLE/CLOUD_SCORE_PLUS/V1/S2_HARMONIZED
  Sentinel-1 GRD   COPERNICUS/S1_GRD                 10 m C-band SAR, dB
  GEDI L4A         LARSE/GEDI/GEDI04_A_002_MONTHLY   25 m AGBD footprints
  GEDI L2A         LARSE/GEDI/GEDI02_A_002_MONTHLY   relative heights
  Terrain          COPERNICUS/DEM/GLO30              30 m DEM
  Land cover       ESA/WorldCover/v200               10 m, 2021 epoch

Pixels are pulled with ee.data.computePixels against an explicit EPSG:4326
grid, so the array the science stack receives is aligned cell-for-cell with the
grid produced by app.science.geo.analysis_grid.

Nothing in this module invents a value. Every failure path raises a
SylvaSenseError that names the missing dependency and the next step.
"""

from __future__ import annotations

import datetime as dt
import json
import logging
import os
import threading
from typing import Any

import numpy as np

from app.core.config import Settings, get_settings
from app.core.errors import (
    SylvaSenseError,
    earth_engine_not_configured,
    earth_engine_unavailable,
)
from app.providers.base import (
    AOI,
    AuditResult,
    DataMode,
    GediSamples,
    LandcoverObservation,
    ObservationBundle,
    OpticalObservation,
    RadarObservation,
    SourceAvailability,
    SourceStatus,
    TerrainObservation,
)
from app.science.geo import (
    analysis_grid,
    geodesic_perimeter_km,
    inside_mask,
)

log = logging.getLogger("sylvasense.ee")

S2_COLLECTION = "COPERNICUS/S2_SR_HARMONIZED"
CS_PLUS_COLLECTION = "GOOGLE/CLOUD_SCORE_PLUS/V1/S2_HARMONIZED"
S1_COLLECTION = "COPERNICUS/S1_GRD"
GEDI_L4A_COLLECTION = "LARSE/GEDI/GEDI04_A_002_MONTHLY"
GEDI_L2A_COLLECTION = "LARSE/GEDI/GEDI02_A_002_MONTHLY"
DEM_COLLECTION = "COPERNICUS/DEM/GLO30"
WORLDCOVER_COLLECTION = "ESA/WorldCover/v200"

# Optical bands carried through to the model, with their native resolutions.
S2_BANDS = ["B2", "B3", "B4", "B5", "B6", "B7", "B8", "B8A", "B11", "B12"]

# Cloud Score+ keeps a pixel when cs_cdf is at or above this threshold.
CS_PLUS_CLEAR_THRESHOLD = 0.60

# GEDI does not observe above this latitude (ISS inclination).
GEDI_LAT_LIMIT = 51.6

EE_SCOPES = [
    "https://www.googleapis.com/auth/earthengine",
    "https://www.googleapis.com/auth/devstorage.full_control",
]


class EarthEngineProvider:
    """Real satellite observations through Google Earth Engine."""

    name = "earthengine"
    mode = DataMode.LIVE_EARTH_ENGINE

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self._initialised = False
        self._init_error: str | None = None
        self._lock = threading.Lock()
        self._account_email: str | None = None
        self._project: str | None = None

    # ------------------------------------------------------------------
    # Initialisation / readiness
    # ------------------------------------------------------------------

    def _credentials_payload(self) -> dict[str, Any] | None:
        inline = self.settings.ee_service_account_json
        if inline:
            try:
                return json.loads(inline)
            except json.JSONDecodeError as exc:
                raise earth_engine_not_configured(
                    f"SYLVASENSE_EE_SERVICE_ACCOUNT_JSON is not valid JSON: {exc}"
                ) from exc

        path = self.settings.ee_service_account_file
        if not path:
            return None
        if not os.path.isfile(path):
            raise earth_engine_not_configured(
                f"Service-account key not found at {path}"
            )
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)

    def _initialise(self) -> None:
        """Initialise the EE client once. Raises SylvaSenseError on failure."""
        if self._initialised:
            return
        with self._lock:
            if self._initialised:
                return
            try:
                import ee  # noqa: PLC0415 — heavy import, deferred on purpose
                from google.oauth2 import service_account  # noqa: PLC0415
            except ImportError as exc:
                raise earth_engine_not_configured(
                    f"earthengine-api is not installed: {exc}"
                ) from exc

            payload = self._credentials_payload()
            project = self.settings.ee_project or (payload or {}).get("project_id")

            try:
                if payload is not None:
                    creds = service_account.Credentials.from_service_account_info(
                        payload, scopes=EE_SCOPES
                    )
                    self._account_email = payload.get("client_email")
                    ee.Initialize(
                        credentials=creds,
                        project=project,
                        opt_url=self.settings.ee_endpoint,
                    )
                else:
                    # Fall back to application-default credentials (a developer
                    # who has run `earthengine authenticate` locally).
                    ee.Initialize(project=project, opt_url=self.settings.ee_endpoint)
                    self._account_email = "application-default-credentials"

                # Force a round trip so a bad credential fails here, not mid-analysis.
                ee.Number(1).getInfo()
            except SylvaSenseError:
                raise
            except Exception as exc:
                self._init_error = f"{type(exc).__name__}: {exc}"
                raise earth_engine_not_configured(self._init_error) from exc

            self._project = project
            self._initialised = True
            log.info("Earth Engine initialised (project=%s)", project)

    def is_ready(self) -> tuple[bool, str]:
        try:
            self._initialise()
        except SylvaSenseError as exc:
            return False, exc.technical or exc.detail
        except Exception as exc:  # defensive
            return False, f"{type(exc).__name__}: {exc}"
        return True, "Earth Engine initialised"

    def describe(self) -> dict[str, Any]:
        ready, reason = self.is_ready()
        return {
            "provider": self.name,
            "mode": self.mode.value,
            "ready": ready,
            "reason": reason,
            "label": "Live Earth Engine",
            "project": self._project,
            "service_account": self._account_email,
            "endpoint": self.settings.ee_endpoint,
            "collections": {
                "optical": S2_COLLECTION,
                "cloud_mask": CS_PLUS_COLLECTION,
                "radar": S1_COLLECTION,
                "biomass_reference": GEDI_L4A_COLLECTION,
                "height_reference": GEDI_L2A_COLLECTION,
                "terrain": DEM_COLLECTION,
                "landcover": WORLDCOVER_COLLECTION,
            },
            "setup_doc": "docs/EARTH_ENGINE_SETUP.md",
        }

    # ------------------------------------------------------------------
    # Earth Engine helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _ee_geometry(aoi: AOI):
        import ee

        return ee.Geometry(aoi.geojson(), geodesic=False)

    def _optical_collection(self, region, start: str, end: str):
        import ee

        base = (
            ee.ImageCollection(S2_COLLECTION)
            .filterBounds(region)
            .filterDate(start, end)
            .filter(
                ee.Filter.lt(
                    "CLOUDY_PIXEL_PERCENTAGE", self.settings.optical_cloud_limit
                )
            )
        )
        cs = ee.ImageCollection(CS_PLUS_COLLECTION).filterBounds(region).filterDate(start, end)
        linked = base.linkCollection(cs, ["cs_cdf"])

        def mask_scene(img):
            clear = img.select("cs_cdf").gte(CS_PLUS_CLEAR_THRESHOLD)
            sr = img.select(S2_BANDS).divide(10_000).updateMask(clear)
            return sr.copyProperties(img, ["system:time_start", "CLOUDY_PIXEL_PERCENTAGE"])

        return linked.map(mask_scene), base

    def _radar_collection(self, region, start: str, end: str):
        import ee

        return (
            ee.ImageCollection(S1_COLLECTION)
            .filterBounds(region)
            .filterDate(start, end)
            .filter(ee.Filter.eq("instrumentMode", "IW"))
            .filter(ee.Filter.listContains("transmitterReceiverPolarisation", "VV"))
            .filter(ee.Filter.listContains("transmitterReceiverPolarisation", "VH"))
            .select(["VV", "VH"])
        )

    def _gedi_collection(self, region, start: str, end: str):
        import ee

        l4a = (
            ee.ImageCollection(GEDI_L4A_COLLECTION)
            .filterBounds(region)
            .filterDate(start, end)
        )

        def quality_mask(img):
            good = img.select("l4_quality_flag").eq(1).And(img.select("degrade_flag").eq(0))
            return img.updateMask(good)

        return l4a.map(quality_mask)

    @staticmethod
    def _grid_spec(lons: np.ndarray, lats: np.ndarray) -> dict[str, Any]:
        """EPSG:4326 pixel grid whose pixel centres are exactly lons x lats."""
        n_x, n_y = int(lons.size), int(lats.size)
        scale_x = float(lons[1] - lons[0]) if n_x > 1 else 1e-4
        scale_y = float(lats[1] - lats[0]) if n_y > 1 else -1e-4  # lats descend
        return {
            "dimensions": {"width": n_x, "height": n_y},
            "affineTransform": {
                "scaleX": scale_x,
                "shearX": 0.0,
                "translateX": float(lons[0]) - scale_x / 2.0,
                "shearY": 0.0,
                "scaleY": scale_y,
                "translateY": float(lats[0]) - scale_y / 2.0,
            },
            "crsCode": "EPSG:4326",
        }

    def _compute_pixels(self, image, grid: dict[str, Any], bands: list[str]) -> dict[str, np.ndarray]:
        """Pull a band stack as float arrays aligned to `grid`."""
        import ee

        try:
            raw = ee.data.computePixels(
                {
                    "expression": image.select(bands).toFloat(),
                    "fileFormat": "NUMPY_NDARRAY",
                    "grid": grid,
                }
            )
        except Exception as exc:
            raise earth_engine_unavailable(f"computePixels failed: {exc}") from exc

        out: dict[str, np.ndarray] = {}
        for band in bands:
            arr = np.asarray(raw[band], dtype=np.float64)
            # EE writes masked pixels as 0 in NUMPY_NDARRAY; recover them via a
            # companion mask band so genuinely-zero values are not confused with
            # no-data. See _compute_pixels_masked.
            out[band] = arr
        return out

    def _compute_pixels_masked(
        self, image, grid: dict[str, Any], bands: list[str]
    ) -> tuple[dict[str, np.ndarray], np.ndarray]:
        """Like _compute_pixels but returns a genuine validity mask.

        A constant band is unmasked alongside the data, so cells where EE had no
        observation come back as False rather than silently as zero.
        """
        import ee

        valid_band = "__valid__"
        stacked = image.select(bands).addBands(
            ee.Image.constant(1).rename(valid_band).updateMask(image.select(bands[0]).mask())
        )
        pulled = self._compute_pixels(stacked, grid, [*bands, valid_band])
        valid = pulled.pop(valid_band) > 0.5
        for band in bands:
            pulled[band] = np.where(valid, pulled[band], np.nan)
        return pulled, valid

    # ------------------------------------------------------------------
    # Audit
    # ------------------------------------------------------------------

    def audit(self, aoi: AOI, window_start: str, window_end: str) -> AuditResult:
        self._initialise()
        import ee

        region = self._ee_geometry(aoi)
        sources: list[SourceAvailability] = []

        # --- Sentinel-2 -------------------------------------------------
        cloud_pct: float | None = None
        try:
            _, raw_s2 = self._optical_collection(region, window_start, window_end)
            s2_info = raw_s2.aggregate_array("system:time_start").getInfo() or []
            s2_clouds = raw_s2.aggregate_array("CLOUDY_PIXEL_PERCENTAGE").getInfo() or []
            n_s2 = len(s2_info)
            if s2_clouds:
                cloud_pct = float(np.mean(s2_clouds))
            sources.append(
                SourceAvailability(
                    key="sentinel2",
                    label="Sentinel-2 L2A",
                    status=SourceStatus.AVAILABLE if n_s2 >= 3 else (
                        SourceStatus.PARTIAL if n_s2 > 0 else SourceStatus.UNAVAILABLE
                    ),
                    scene_count=n_s2,
                    first_date=_ms_to_date(min(s2_info)) if s2_info else None,
                    last_date=_ms_to_date(max(s2_info)) if s2_info else None,
                    detail=(
                        f"{n_s2} scenes under {self.settings.optical_cloud_limit:.0f}% cloud"
                        if n_s2
                        else "No scene under the cloud limit in this window"
                    ),
                    metrics={"mean_scene_cloud_pct": cloud_pct},
                )
            )
        except Exception as exc:
            sources.append(_source_error("sentinel2", "Sentinel-2 L2A", exc))

        # --- Sentinel-1 -------------------------------------------------
        try:
            s1 = self._radar_collection(region, window_start, window_end)
            s1_times = s1.aggregate_array("system:time_start").getInfo() or []
            orbits = s1.aggregate_array("orbitProperties_pass").getInfo() or []
            n_s1 = len(s1_times)
            sources.append(
                SourceAvailability(
                    key="sentinel1",
                    label="Sentinel-1 GRD (IW, VV+VH)",
                    status=SourceStatus.AVAILABLE if n_s1 >= 3 else (
                        SourceStatus.PARTIAL if n_s1 > 0 else SourceStatus.UNAVAILABLE
                    ),
                    scene_count=n_s1,
                    first_date=_ms_to_date(min(s1_times)) if s1_times else None,
                    last_date=_ms_to_date(max(s1_times)) if s1_times else None,
                    detail=(
                        f"{n_s1} dual-pol acquisitions"
                        if n_s1
                        else "No VV+VH acquisition over this area"
                    ),
                    metrics={"orbit_passes": sorted(set(orbits))},
                )
            )
        except Exception as exc:
            sources.append(_source_error("sentinel1", "Sentinel-1 GRD", exc))

        # --- GEDI -------------------------------------------------------
        try:
            lat_ok = abs(aoi.centroid()[1]) <= GEDI_LAT_LIMIT
            if not lat_ok:
                sources.append(
                    SourceAvailability(
                        key="gedi",
                        label="GEDI L4A biomass",
                        status=SourceStatus.UNAVAILABLE,
                        detail=(
                            f"Outside the GEDI footprint — the mission does not observe "
                            f"beyond {GEDI_LAT_LIMIT}° latitude"
                        ),
                    )
                )
            else:
                gedi = self._gedi_collection(region, "2019-04-18", window_end)
                shot_count = (
                    gedi.select("agbd")
                    .count()
                    .rename("shots")
                    .reduceRegion(
                        reducer=ee.Reducer.sum(),
                        geometry=region,
                        scale=25,
                        maxPixels=1e9,
                        bestEffort=True,
                    )
                    .getInfo()
                    or {}
                )
                n_shots = int(shot_count.get("shots") or 0)
                enough = n_shots >= self.settings.min_gedi_samples
                sources.append(
                    SourceAvailability(
                        key="gedi",
                        label="GEDI L4A biomass",
                        status=SourceStatus.AVAILABLE if enough else (
                            SourceStatus.PARTIAL if n_shots > 0 else SourceStatus.UNAVAILABLE
                        ),
                        scene_count=n_shots,
                        detail=(
                            f"{n_shots} quality-filtered footprints — "
                            + (
                                "enough to calibrate locally"
                                if enough
                                else f"below the {self.settings.min_gedi_samples}-shot "
                                "calibration minimum"
                            )
                        ),
                        metrics={"shots": n_shots, "min_required": self.settings.min_gedi_samples},
                    )
                )
        except Exception as exc:
            sources.append(_source_error("gedi", "GEDI L4A biomass", exc))

        # --- Terrain ----------------------------------------------------
        try:
            dem_stats = (
                ee.ImageCollection(DEM_COLLECTION)
                .select("DEM")
                .mosaic()
                .reduceRegion(
                    reducer=ee.Reducer.minMax().combine(ee.Reducer.mean(), sharedInputs=True),
                    geometry=region,
                    scale=30,
                    maxPixels=1e9,
                    bestEffort=True,
                )
                .getInfo()
                or {}
            )
            has_dem = dem_stats.get("DEM_mean") is not None
            sources.append(
                SourceAvailability(
                    key="dem",
                    label="Copernicus DEM GLO-30",
                    status=SourceStatus.AVAILABLE if has_dem else SourceStatus.UNAVAILABLE,
                    detail=(
                        f"{dem_stats.get('DEM_min', 0):.0f}–{dem_stats.get('DEM_max', 0):.0f} m elevation"
                        if has_dem
                        else "No DEM coverage"
                    ),
                    metrics=dem_stats,
                )
            )
        except Exception as exc:
            sources.append(_source_error("dem", "Copernicus DEM GLO-30", exc))

        # --- Land cover / forest fraction -------------------------------
        forest_pct: float | None = None
        try:
            wc = ee.ImageCollection(WORLDCOVER_COLLECTION).first().select("Map")
            tree = wc.eq(10).rename("tree")
            frac = tree.reduceRegion(
                reducer=ee.Reducer.mean(),
                geometry=region,
                scale=20,
                maxPixels=1e9,
                bestEffort=True,
            ).getInfo() or {}
            if frac.get("tree") is not None:
                forest_pct = float(frac["tree"]) * 100.0
            sources.append(
                SourceAvailability(
                    key="worldcover",
                    label="ESA WorldCover v200 (2021)",
                    status=SourceStatus.AVAILABLE if forest_pct is not None else SourceStatus.UNAVAILABLE,
                    detail=(
                        f"{forest_pct:.1f}% tree cover"
                        if forest_pct is not None
                        else "No land-cover coverage"
                    ),
                    metrics={"tree_cover_pct": forest_pct},
                )
            )
        except Exception as exc:
            sources.append(_source_error("worldcover", "ESA WorldCover v200", exc))

        verdict, verdict_detail = _verdict_from_sources(sources)

        return AuditResult(
            aoi_id=aoi.aoi_id,
            area_km2=aoi.area_km2,
            area_ha=aoi.area_ha,
            perimeter_km=geodesic_perimeter_km(aoi.geometry),
            centroid=aoi.centroid(),
            bounds=aoi.bounds.as_list(),
            forest_cover_pct=None if forest_pct is None else round(forest_pct, 2),
            cloud_cover_pct=None if cloud_pct is None else round(cloud_pct, 2),
            sources=sources,
            mode=self.mode,
            window_start=window_start,
            window_end=window_end,
            verdict=verdict,
            verdict_detail=verdict_detail,
        )

    # ------------------------------------------------------------------
    # Observation
    # ------------------------------------------------------------------

    def observe(
        self, aoi: AOI, window_start: str, window_end: str, target_cells: int
    ) -> ObservationBundle:
        self._initialise()
        import ee

        region = self._ee_geometry(aoi)
        lons, lats, cell_size_m = analysis_grid(
            aoi, target_cells, self.settings.grid_max_cells
        )
        mask = inside_mask(aoi, lons, lats)
        grid = self._grid_spec(lons, lats)

        bundle = ObservationBundle(
            aoi=aoi,
            lons=lons,
            lats=lats,
            mask=mask,
            cell_size_m=cell_size_m,
            window_start=window_start,
            window_end=window_end,
            mode=self.mode,
        )

        # --- Optical ----------------------------------------------------
        masked_coll, raw_coll = self._optical_collection(region, window_start, window_end)
        times = raw_coll.aggregate_array("system:time_start").getInfo() or []
        if not times:
            raise earth_engine_unavailable(
                f"No Sentinel-2 scene under {self.settings.optical_cloud_limit:.0f}% cloud "
                f"between {window_start} and {window_end}."
            )
        clouds = raw_coll.aggregate_array("CLOUDY_PIXEL_PERCENTAGE").getInfo() or [0.0]
        composite = masked_coll.median()
        # Per-cell count of clear observations -> valid fraction.
        clear_count = masked_coll.select("B8").count().rename("n_clear")
        bands, valid = self._compute_pixels_masked(composite, grid, S2_BANDS)
        counts = self._compute_pixels(clear_count, grid, ["n_clear"])["n_clear"]
        valid_fraction = np.clip(counts / max(len(times), 1), 0.0, 1.0)
        valid_fraction = np.where(valid, valid_fraction, 0.0)

        bundle.optical = OpticalObservation(
            bands=bands,
            scene_count=len(times),
            cloud_cover_pct=float(np.mean(clouds)),
            valid_fraction=valid_fraction,
            first_date=_ms_to_date(min(times)),
            last_date=_ms_to_date(max(times)),
            collection=S2_COLLECTION,
            resolution_m=10,
        )

        # --- Radar ------------------------------------------------------
        try:
            s1 = self._radar_collection(region, window_start, window_end)
            s1_times = s1.aggregate_array("system:time_start").getInfo() or []
            if s1_times:
                s1_composite = s1.median()
                sar, _ = self._compute_pixels_masked(s1_composite, grid, ["VV", "VH"])
                orbits = s1.aggregate_array("orbitProperties_pass").getInfo() or []
                bundle.radar = RadarObservation(
                    vv_db=sar["VV"],
                    vh_db=sar["VH"],
                    scene_count=len(s1_times),
                    first_date=_ms_to_date(min(s1_times)),
                    last_date=_ms_to_date(max(s1_times)),
                    collection=S1_COLLECTION,
                    orbit="/".join(sorted(set(orbits))) or "unknown",
                    resolution_m=10,
                )
        except SylvaSenseError:
            raise
        except Exception as exc:
            log.warning("Sentinel-1 unavailable for %s: %s", aoi.aoi_id, exc)

        # --- GEDI footprints -------------------------------------------
        try:
            bundle.gedi = self._sample_gedi(region, aoi, window_end)
        except SylvaSenseError:
            raise
        except Exception as exc:
            log.warning("GEDI sampling failed for %s: %s", aoi.aoi_id, exc)

        # --- Terrain ----------------------------------------------------
        try:
            dem_img = ee.ImageCollection(DEM_COLLECTION).select("DEM").mosaic()
            slope = ee.Terrain.slope(dem_img.setDefaultProjection("EPSG:3857", None, 30))
            terrain = self._compute_pixels(
                dem_img.rename("elevation").addBands(slope.rename("slope")),
                grid,
                ["elevation", "slope"],
            )
            bundle.terrain = TerrainObservation(
                elevation_m=terrain["elevation"],
                slope_deg=terrain["slope"],
                collection=DEM_COLLECTION,
                resolution_m=30,
            )
        except Exception as exc:
            log.warning("DEM unavailable for %s: %s", aoi.aoi_id, exc)

        # --- Land cover -------------------------------------------------
        try:
            wc = ee.ImageCollection(WORLDCOVER_COLLECTION).first().select("Map")
            lc = self._compute_pixels(wc.rename("lc"), grid, ["lc"])["lc"]
            bundle.landcover = LandcoverObservation(
                classes=lc,
                tree_mask=np.isclose(lc, 10.0),
                collection=WORLDCOVER_COLLECTION,
                year=2021,
                resolution_m=10,
            )
        except Exception as exc:
            log.warning("WorldCover unavailable for %s: %s", aoi.aoi_id, exc)

        return bundle

    def _sample_gedi(self, region, aoi: AOI, window_end: str) -> GediSamples | None:
        import ee

        if abs(aoi.centroid()[1]) > GEDI_LAT_LIMIT:
            return None

        l4a = self._gedi_collection(region, "2019-04-18", window_end)
        stack = l4a.select(["agbd", "agbd_se"]).mosaic()
        try:
            rh = (
                ee.ImageCollection(GEDI_L2A_COLLECTION)
                .filterBounds(region)
                .filterDate("2019-04-18", window_end)
                .map(lambda img: img.updateMask(img.select("quality_flag").eq(1)))
                .select("rh98")
                .mosaic()
            )
            stack = stack.addBands(rh)
            band_names = ["agbd", "agbd_se", "rh98"]
        except Exception:
            band_names = ["agbd", "agbd_se"]

        fc = stack.sample(
            region=region,
            scale=25,
            projection="EPSG:4326",
            geometries=True,
            dropNulls=True,
            numPixels=5000,
            seed=17,
        )
        info = fc.getInfo() or {}
        feats = info.get("features") or []
        if not feats:
            return None

        lon, lat, agbd, se, rh98 = [], [], [], [], []
        for f in feats:
            props = f.get("properties") or {}
            coords = ((f.get("geometry") or {}).get("coordinates")) or None
            if coords is None or props.get("agbd") is None:
                continue
            lon.append(float(coords[0]))
            lat.append(float(coords[1]))
            agbd.append(float(props["agbd"]))
            se.append(float(props.get("agbd_se") or np.nan))
            rh98.append(float(props.get("rh98") or np.nan))

        if not agbd:
            return None

        return GediSamples(
            lon=np.array(lon),
            lat=np.array(lat),
            agbd=np.array(agbd),
            agbd_se=np.array(se),
            rh98=np.array(rh98),
            quality_flag=np.ones(len(agbd), dtype=int),
            collection=GEDI_L4A_COLLECTION,
            first_date="2019-04-18",
            last_date=window_end,
        )

    # ------------------------------------------------------------------
    # Basemap imagery tiles (proxied through the backend; no key in browser)
    # ------------------------------------------------------------------

    def imagery_tile_template(self, window_start: str, window_end: str) -> str | None:
        """XYZ template for a true-colour Sentinel-2 mosaic, or None."""
        self._initialise()
        import ee

        try:
            coll, _ = self._optical_collection(
                ee.Geometry.Rectangle([-180, -85, 180, 85], geodesic=False),
                window_start,
                window_end,
            )
            img = coll.median().select(["B4", "B3", "B2"])
            mapid = img.getMapId({"min": 0.02, "max": 0.30, "gamma": 1.25})
            return mapid["tile_fetcher"].url_format
        except Exception as exc:
            log.warning("Could not build imagery tile template: %s", exc)
            return None


# ----------------------------------------------------------------------
# Module helpers
# ----------------------------------------------------------------------


def _ms_to_date(ms: float | int | None) -> str | None:
    if ms is None:
        return None
    return dt.datetime.fromtimestamp(float(ms) / 1000.0, tz=dt.timezone.utc).date().isoformat()


def _source_error(key: str, label: str, exc: Exception) -> SourceAvailability:
    return SourceAvailability(
        key=key,
        label=label,
        status=SourceStatus.UNAVAILABLE,
        detail=f"Could not be queried: {type(exc).__name__}",
        metrics={"error": str(exc)[:300]},
    )


def _verdict_from_sources(sources: list[SourceAvailability]) -> tuple[str, str]:
    by_key = {s.key: s for s in sources}
    optical = by_key.get("sentinel2")

    if optical is None or optical.status == SourceStatus.UNAVAILABLE:
        return (
            "INSUFFICIENT_DATA",
            "No usable optical imagery for this area in the selected window. "
            "Analysis cannot run without it.",
        )

    degraded = [
        s.label
        for s in sources
        if s.key in ("sentinel1", "gedi") and s.status != SourceStatus.AVAILABLE
    ]
    if optical.status == SourceStatus.PARTIAL or degraded:
        missing = ", ".join(degraded) if degraded else "a thin optical stack"
        return (
            "PARTIAL_DATA",
            f"Analysis can run, but with reduced support: {missing}. "
            "Expect wider uncertainty bounds.",
        )
    return ("READY", "All primary inputs are available for this area and window.")
