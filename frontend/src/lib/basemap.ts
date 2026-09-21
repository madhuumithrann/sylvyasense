/**
 * Basemap construction.
 *
 * SylvaSense must render a usable map in two very different situations:
 *
 *   ONLINE   a raster basemap from a tile provider (configurable; the default
 *            needs no API key). Best context for interpreting imagery.
 *   OFFLINE  no external tile host is reachable — a restricted network, an
 *            air-gapped deployment, or a provider outage. A bundled Natural
 *            Earth vector basemap plus a graticule is drawn instead, entirely
 *            from data shipped with the app.
 *
 * The fallback is automatic and announced in the UI, never silent: a map that
 * quietly shows nothing is worse than one that says why.
 */

import type { StyleSpecification } from 'maplibre-gl';
import { feature } from 'topojson-client';
import landTopo from 'world-atlas/land-110m.json';
import countriesTopo from 'world-atlas/countries-110m.json';

import { COLORS } from './mapTheme';

/** Raster basemap tiles. Overridable so a deployment can use its own. */
export const RASTER_BASEMAP_URL =
  import.meta.env.VITE_BASEMAP_URL ??
  'https://basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png';

export const RASTER_BASEMAP_ATTRIBUTION =
  import.meta.env.VITE_BASEMAP_ATTRIBUTION ??
  '© OpenStreetMap contributors © CARTO';

function landGeoJson(): GeoJSON.FeatureCollection {
  // topojson-client's types are loose; the shape is a FeatureCollection.
  const collection = feature(
    landTopo as never,
    (landTopo as never as { objects: { land: unknown } }).objects.land as never,
  ) as unknown as GeoJSON.FeatureCollection;
  return collection;
}

function countriesGeoJson(): GeoJSON.FeatureCollection {
  const collection = feature(
    countriesTopo as never,
    (countriesTopo as never as { objects: { countries: unknown } }).objects
      .countries as never,
  ) as unknown as GeoJSON.FeatureCollection;
  return collection;
}

/** Meridians and parallels, so the offline map still conveys scale and place. */
function graticule(stepDeg: number): GeoJSON.FeatureCollection {
  const features: GeoJSON.Feature[] = [];

  for (let lon = -180; lon <= 180; lon += stepDeg) {
    const line: [number, number][] = [];
    for (let lat = -85; lat <= 85; lat += 5) line.push([lon, lat]);
    features.push({
      type: 'Feature',
      geometry: { type: 'LineString', coordinates: line },
      properties: { kind: 'meridian', value: lon },
    });
  }
  for (let lat = -80; lat <= 80; lat += stepDeg) {
    const line: [number, number][] = [];
    for (let lon = -180; lon <= 180; lon += 5) line.push([lon, lat]);
    features.push({
      type: 'Feature',
      geometry: { type: 'LineString', coordinates: line },
      properties: { kind: 'parallel', value: lat },
    });
  }

  return { type: 'FeatureCollection', features };
}

/** Layers drawn from bundled data — always present, under any raster tiles. */
function offlineLayers(): StyleSpecification['layers'] {
  return [
    {
      id: 'bg',
      type: 'background',
      paint: { 'background-color': COLORS.water },
    },
    {
      id: 'land',
      type: 'fill',
      source: 'ne-land',
      paint: { 'fill-color': COLORS.land, 'fill-opacity': 1 },
    },
    {
      id: 'country-line',
      type: 'line',
      source: 'ne-countries',
      paint: {
        'line-color': COLORS.border,
        'line-width': ['interpolate', ['linear'], ['zoom'], 1, 0.4, 8, 1.1],
        'line-opacity': 0.75,
      },
    },
    {
      id: 'graticule',
      type: 'line',
      source: 'graticule',
      paint: {
        'line-color': COLORS.graticule,
        'line-width': 0.5,
        'line-opacity': ['interpolate', ['linear'], ['zoom'], 1, 0.35, 10, 0.16],
      },
    },
  ];
}

/**
 * One style, built once and never swapped.
 *
 * The bundled vector layers are always present and the raster basemap sits on
 * top of them. When the tile host is unreachable the raster simply paints
 * nothing and the vectors show through — so a basemap outage costs a bit of
 * detail, never the whole map, and never the app's own layers (a setStyle call
 * would destroy every source and layer added at runtime).
 */
export function buildStyle(useRaster = true): StyleSpecification {
  const sources: StyleSpecification['sources'] = {
    'ne-land': { type: 'geojson', data: landGeoJson() as never },
    'ne-countries': { type: 'geojson', data: countriesGeoJson() as never },
    graticule: { type: 'geojson', data: graticule(10) as never },
  };

  const layers = offlineLayers();

  if (useRaster) {
    sources.basemap = {
      type: 'raster',
      tiles: [RASTER_BASEMAP_URL],
      tileSize: 256,
      maxzoom: 19,
      attribution: RASTER_BASEMAP_ATTRIBUTION,
    };
    // Raster sits above the bundled vectors so the vectors act as a backdrop
    // for tiles that have not loaded yet, rather than disappearing.
    layers.push({
      id: 'basemap',
      type: 'raster',
      source: 'basemap',
      paint: { 'raster-opacity': 1, 'raster-fade-duration': 220 },
    });
  }

  // No `glyphs` key at all: MapLibre validates it as a string when present,
  // and an explicit `undefined` fails validation and stops the style loading.
  // SylvaSense draws no symbol text on the map — field-site numbers are HTML
  // markers — so no glyph endpoint is needed.
  return {
    version: 8,
    name: 'SylvaSense',
    sources,
    layers,
  } as StyleSpecification;
}

/** Where analysis rasters are inserted — above the basemap, below AOI vectors. */
export const ANALYSIS_LAYER_ANCHOR = 'aoi-fill';
