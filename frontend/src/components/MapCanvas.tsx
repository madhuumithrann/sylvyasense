import { useCallback, useEffect, useRef, useState } from 'react';
import maplibregl, {
  type GeoJSONSource,
  type LngLatBoundsLike,
  type Map as MapLibreMap,
  type MapMouseEvent,
  type RasterLayerSpecification,
} from 'maplibre-gl';
import 'maplibre-gl/dist/maplibre-gl.css';

import { api, changeTileUrl, tileUrl } from '../lib/api';
import { ANALYSIS_LAYER_ANCHOR, buildStyle } from '../lib/basemap';
import { PolygonDrawer } from '../lib/draw';
import { COLORS, PRIORITY_COLOR } from '../lib/mapTheme';
import type { FieldSite } from '../lib/types';
import { useStore } from '../state/store';
import { MapControls } from './MapControls';
import './MapCanvas.css';

const EMPTY: GeoJSON.FeatureCollection = { type: 'FeatureCollection', features: [] };

const SRC_AOI = 'aoi';
const SRC_INSPECT = 'inspect';
const LYR_INSPECT = 'inspect-ring';

/** Consecutive basemap tile errors before falling back to bundled vectors. */
const BASEMAP_FAILURE_LIMIT = 4;

export function MapCanvas() {
  const containerRef = useRef<HTMLDivElement>(null);
  const mapRef = useRef<MapLibreMap | null>(null);
  const drawerRef = useRef<PolygonDrawer | null>(null);
  const markersRef = useRef<maplibregl.Marker[]>([]);
  const analysisLayersRef = useRef<string[]>([]);
  const basemapFailuresRef = useRef(0);

  const [ready, setReady] = useState(false);
  const [basemapOffline, setBasemapOffline] = useState(false);
  const [cursor, setCursor] = useState<{ lon: number; lat: number } | null>(null);

  const geometry = useStore((s) => s.geometry);
  const aoi = useStore((s) => s.aoi);
  const analysis = useStore((s) => s.analysis);
  const change = useStore((s) => s.change);
  const activeLayers = useStore((s) => s.activeLayers);
  const layerOpacity = useStore((s) => s.layerOpacity);
  const fieldPlan = useStore((s) => s.fieldPlan);
  const showFieldSites = useStore((s) => s.showFieldSites);
  const inspectMode = useStore((s) => s.inspectMode);
  const year = useStore((s) => s.year);
  const compareYear = useStore((s) => s.compareYear);
  const selectedCell = useStore((s) => s.selectedCell);

  const setGeometry = useStore((s) => s.setGeometry);
  const setDrawMode = useStore((s) => s.setDrawMode);
  const setSelectedCell = useStore((s) => s.setSelectedCell);
  const setSelectedSite = useStore((s) => s.setSelectedSite);
  const setTab = useStore((s) => s.setTab);

  // ---------------------------------------------------------------- map init

  useEffect(() => {
    if (!containerRef.current || mapRef.current) return;

    const map = new maplibregl.Map({
      container: containerRef.current,
      style: buildStyle(),
      center: [-60.0, -3.0],
      zoom: 2.4,
      minZoom: 1,
      maxZoom: 17,
      attributionControl: false,
      dragRotate: false,
      pitchWithRotate: false,
      fadeDuration: 180,
      // Keeps the canvas readable when the OS is set to a light theme.
      localIdeographFontFamily: false,
    });
    mapRef.current = map;
    // Exposed for end-to-end tests, which assert on real rendered layers
    // rather than on React state.
    (window as unknown as { __sylvasenseMap?: MapLibreMap }).__sylvasenseMap = map;

    map.addControl(
      new maplibregl.AttributionControl({ compact: true }),
      'bottom-right',
    );
    map.addControl(
      new maplibregl.ScaleControl({ maxWidth: 110, unit: 'metric' }),
      'bottom-left',
    );

    // A basemap host that is blocked or down must not leave a blank map. The
    // bundled vectors are already underneath, so the failing raster layer is
    // simply hidden — never a setStyle, which would destroy every source and
    // layer this component adds at runtime.
    const onError = (event: { error?: { status?: number }; sourceId?: string }) => {
      if (event.sourceId !== 'basemap') return;
      basemapFailuresRef.current += 1;
      if (basemapFailuresRef.current !== BASEMAP_FAILURE_LIMIT) return;
      setBasemapOffline(true);
      if (map.getLayer('basemap')) {
        map.setLayoutProperty('basemap', 'visibility', 'none');
      }
    };
    map.on('error', onError as never);
    map.on('error', (event: { error?: Error; sourceId?: string }) => {
      if (event.sourceId === 'basemap') return;
      // eslint-disable-next-line no-console
      console.error('[maplibre]', event.sourceId ?? 'style', event.error?.message);
    });

    map.on('mousemove', (event: MapMouseEvent) => {
      setCursor({ lon: event.lngLat.lng, lat: event.lngLat.lat });
    });
    map.on('mouseout', () => setCursor(null));

    map.on('load', () => {
      installAoiLayers(map);
      drawerRef.current = new PolygonDrawer(map, {
        onChange: (next) => setGeometry(next),
        onModeChange: (mode) => setDrawMode(mode),
      });
      installInspectLayer(map);
      setReady(true);
    });

    return () => {
      drawerRef.current?.destroy();
      drawerRef.current = null;
      markersRef.current.forEach((m) => m.remove());
      markersRef.current = [];
      map.remove();
      mapRef.current = null;
    };
    // Mount once; everything else is synced by the effects below.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // --------------------------------------------------------------- AOI sync

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready) return;
    const source = map.getSource(SRC_AOI) as GeoJSONSource | undefined;
    if (!source) return;

    if (!geometry) {
      source.setData(EMPTY);
      return;
    }
    source.setData({
      type: 'Feature',
      geometry: geometry as never,
      properties: {},
    } as never);
  }, [geometry, ready]);

  // Frame a newly selected area.
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready || !aoi) return;
    const [west, south, east, north] = aoi.bounds;
    map.fitBounds(
      [
        [west, south],
        [east, north],
      ] as LngLatBoundsLike,
      { padding: { top: 90, bottom: 110, left: 300, right: 420 }, duration: 900 },
    );
  }, [aoi?.aoi_id, ready]); // eslint-disable-line react-hooks/exhaustive-deps

  // Reflect externally-set geometry (demo area, search) into the drawer.
  useEffect(() => {
    if (!ready) return;
    const drawer = drawerRef.current;
    if (!drawer) return;
    if (!geometry) {
      if (drawer.getMode() !== 'drawing') drawer.clear();
      return;
    }
    if (drawer.getMode() === 'idle') drawer.loadPolygon(geometry);
  }, [geometry, ready]);

  // ------------------------------------------------------- analysis rasters

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready) return;

    // Remove the previous set; tiles are cheap to re-request and this keeps
    // ordering deterministic.
    for (const id of analysisLayersRef.current) {
      if (map.getLayer(id)) map.removeLayer(id);
      if (map.getSource(id)) map.removeSource(id);
    }
    analysisLayersRef.current = [];

    if (!analysis) return;

    const anchor = map.getLayer(ANALYSIS_LAYER_ANCHOR)
      ? ANALYSIS_LAYER_ANCHOR
      : undefined;

    for (const key of activeLayers) {
      const isChangeLayer = ['agb_change', 'carbon_change', 'change_class'].includes(
        key,
      );
      if (isChangeLayer && !change) continue;

      const id = `analysis-${key}`;
      const url = isChangeLayer
        ? changeTileUrl(analysis.aoi_id, compareYear, year, key, 1)
        : tileUrl(analysis.aoi_id, year, key, 1);

      // Continuous fields are smoothed between analysis cells; class rasters
      // must stay crisp, because interpolating between class codes would
      // invent classes that were never predicted.
      const categorical =
        key === 'confidence_class' || key === 'change_class' || key === 'worldcover';

      map.addSource(id, {
        type: 'raster',
        tiles: [url],
        tileSize: 256,
        minzoom: 0,
        maxzoom: 22,
      });
      map.addLayer(
        {
          id,
          type: 'raster',
          source: id,
          paint: {
            'raster-opacity': layerOpacity,
            'raster-fade-duration': 200,
            'raster-resampling': categorical ? 'nearest' : 'linear',
          },
        } as RasterLayerSpecification,
        anchor,
      );
      analysisLayersRef.current.push(id);
    }
  }, [analysis, activeLayers, year, compareYear, change, ready]); // eslint-disable-line react-hooks/exhaustive-deps

  // Opacity changes must not rebuild the tile sources.
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready) return;
    for (const id of analysisLayersRef.current) {
      if (map.getLayer(id)) {
        map.setPaintProperty(id, 'raster-opacity', layerOpacity);
      }
    }
  }, [layerOpacity, ready]);

  // ------------------------------------------------------- field site markers

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready) return;

    markersRef.current.forEach((m) => m.remove());
    markersRef.current = [];

    if (!showFieldSites || !fieldPlan) return;

    for (const site of fieldPlan.sites) {
      const element = document.createElement('button');
      element.type = 'button';
      element.className = `site-marker site-marker--${site.priority.toLowerCase()}`;
      element.textContent = site.label;
      element.setAttribute(
        'aria-label',
        `Field site ${site.label}, ${site.priority.toLowerCase()} priority`,
      );
      element.style.setProperty('--site-color', PRIORITY_COLOR[site.priority]);
      element.addEventListener('click', (event) => {
        event.stopPropagation();
        setSelectedSite(site);
        setTab('fieldplan');
      });

      const marker = new maplibregl.Marker({ element, anchor: 'center' })
        .setLngLat([site.lon, site.lat])
        .addTo(map);
      markersRef.current.push(marker);
    }
  }, [fieldPlan, showFieldSites, ready, setSelectedSite, setTab]);

  // ------------------------------------------------------------ inspect click

  const handleInspect = useCallback(
    async (event: MapMouseEvent) => {
      const current = useStore.getState();
      if (!current.inspectMode || !current.analysis) return;
      if (current.drawMode === 'drawing') return;

      try {
        const cell = await api.inspect(
          current.analysis.aoi_id,
          current.year,
          event.lngLat.lng,
          event.lngLat.lat,
        );
        setSelectedCell(cell);
        if (cell.inside_aoi) setTab('confidence');
      } catch {
        // Inspection is a convenience; a failure must not break the map.
        setSelectedCell(null);
      }
    },
    [setSelectedCell, setTab],
  );

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready) return;
    map.on('click', handleInspect);
    return () => {
      map.off('click', handleInspect);
    };
  }, [handleInspect, ready]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready) return;
    const canvas = map.getCanvas();
    if (inspectMode) canvas.classList.add('map-canvas--inspect');
    else canvas.classList.remove('map-canvas--inspect');
  }, [inspectMode, ready]);

  // Marker for the inspected cell.
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready) return;
    const source = map.getSource(SRC_INSPECT) as GeoJSONSource | undefined;
    if (!source) return;

    if (!selectedCell || !selectedCell.inside_aoi) {
      source.setData(EMPTY);
      return;
    }
    source.setData({
      type: 'Feature',
      geometry: {
        type: 'Point',
        coordinates: [selectedCell.lon, selectedCell.lat],
      },
      properties: {},
    } as never);
  }, [selectedCell, ready]);

  // ------------------------------------------------------------------ actions

  const startDraw = useCallback(() => {
    setSelectedCell(null);
    drawerRef.current?.start();
  }, [setSelectedCell]);

  const cancelDraw = useCallback(() => drawerRef.current?.cancel(), []);
  const finishDraw = useCallback(() => drawerRef.current?.finish(), []);
  const clearDraw = useCallback(() => {
    drawerRef.current?.clear();
    useStore.getState().clearAoi();
  }, []);

  return (
    <div className="map-shell">
      <div ref={containerRef} className="map-canvas" data-testid="map-canvas" />
      <MapControls
        map={mapRef.current}
        cursor={cursor}
        basemapOffline={basemapOffline}
        onDraw={startDraw}
        onCancelDraw={cancelDraw}
        onFinishDraw={finishDraw}
        onClear={clearDraw}
      />
    </div>
  );
}

// ---------------------------------------------------------------- layer setup

function installAoiLayers(map: MapLibreMap): void {
  if (map.getSource(SRC_AOI)) return;
  map.addSource(SRC_AOI, { type: 'geojson', data: EMPTY });

  map.addLayer({
    id: ANALYSIS_LAYER_ANCHOR,
    type: 'fill',
    source: SRC_AOI,
    paint: { 'fill-color': COLORS.aoiFill, 'fill-opacity': 1 },
  });

  // A dark halo under the bright stroke keeps the boundary legible over both
  // bright imagery and dark background.
  map.addLayer({
    id: 'aoi-line-halo',
    type: 'line',
    source: SRC_AOI,
    layout: { 'line-cap': 'round', 'line-join': 'round' },
    paint: { 'line-color': COLORS.aoiLineHalo, 'line-width': 5 },
  });

  map.addLayer({
    id: 'aoi-line',
    type: 'line',
    source: SRC_AOI,
    layout: { 'line-cap': 'round', 'line-join': 'round' },
    paint: { 'line-color': COLORS.aoiLine, 'line-width': 2 },
  });
}

function installInspectLayer(map: MapLibreMap): void {
  if (map.getSource(SRC_INSPECT)) return;
  map.addSource(SRC_INSPECT, { type: 'geojson', data: EMPTY });
  map.addLayer({
    id: LYR_INSPECT,
    type: 'circle',
    source: SRC_INSPECT,
    paint: {
      'circle-radius': 9,
      'circle-color': 'rgba(0,0,0,0)',
      'circle-stroke-color': COLORS.inspectRing,
      'circle-stroke-width': 2.5,
    },
  });
}

export type { FieldSite };
