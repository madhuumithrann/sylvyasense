/**
 * Basemap construction.
 *
 * SylvaSense must render a usable map in three situations:
 *
 *   ONLINE    a raster basemap from a tile provider. Several keyless options
 *             are offered because providers change their terms: CARTO, for
 *             one, moved its public basemaps behind an API key and now serves
 *             "API KEY REQUIRED" watermarks rather than failing outright — a
 *             failure no amount of error handling can detect, because the
 *             tiles load successfully.
 *   OFFLINE   no external tile host is reachable. Bundled Natural Earth
 *             vectors and a graticule are drawn instead, entirely from data
 *             shipped with the app.
 *   DELIBERATE a user who wants no basemap at all, so the analysis layers sit
 *             on a plain cartographic backdrop.
 *
 * The switcher exists because the right answer differs per deployment and per
 * network, and because a basemap that silently degrades is worse than one the
 * user can change.
 */

import type { StyleSpecification } from 'maplibre-gl';
import { feature } from 'topojson-client';
import landTopo from 'world-atlas/land-110m.json';
import countriesTopo from 'world-atlas/countries-110m.json';

import { COLORS } from './mapTheme';

export interface BasemapOption {
  id: string;
  label: string;
  description: string;
  /** null means: draw only the bundled vectors. */
  url: string | null;
  attribution: string;
  maxzoom: number;
}

/**
 * Keyless raster basemaps.
 *
 * Satellite imagery is the default: this is an Earth-observation product, and
 * seeing the actual canopy underneath an analysis layer is more useful than
 * seeing road names.
 */
export const BASEMAPS: BasemapOption[] = [
  {
    id: 'satellite',
    label: 'Satellite',
    description: 'Esri World Imagery — see the canopy under the analysis',
    url: 'https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',
    attribution: 'Esri, Maxar, Earthstar Geographics',
    maxzoom: 19,
  },
  {
    id: 'dark',
    label: 'Dark canvas',
    description: 'Esri Dark Gray Canvas — quiet backdrop, analysis stands out',
    url: 'https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Dark_Gray_Base/MapServer/tile/{z}/{y}/{x}',
    attribution: 'Esri, HERE, Garmin, © OpenStreetMap contributors',
    maxzoom: 16,
  },
  {
    id: 'terrain',
    label: 'Terrain',
    description: 'Esri World Terrain — relief and landform context',
    url: 'https://server.arcgisonline.com/ArcGIS/rest/services/World_Terrain_Base/MapServer/tile/{z}/{y}/{x}',
    attribution: 'Esri, USGS, NOAA',
    maxzoom: 13,
  },
  {
    id: 'streets',
    label: 'Streets',
    description: 'OpenStreetMap — place names and access routes',
    url: 'https://tile.openstreetmap.org/{z}/{x}/{y}.png',
    attribution: '© OpenStreetMap contributors',
    maxzoom: 19,
  },
  {
    id: 'none',
    label: 'None',
    description: 'Bundled Natural Earth vectors only — works with no network',
    url: null,
    attribution: 'Natural Earth',
    maxzoom: 22,
  },
];

/** A deployment can override the default with VITE_BASEMAP_URL. */
const ENV_URL = import.meta.env.VITE_BASEMAP_URL as string | undefined;
const ENV_ATTRIBUTION = import.meta.env.VITE_BASEMAP_ATTRIBUTION as string | undefined;

if (ENV_URL) {
  BASEMAPS.unshift({
    id: 'custom',
    label: 'Custom',
    description: 'From VITE_BASEMAP_URL',
    url: ENV_URL,
    attribution: ENV_ATTRIBUTION ?? 'Custom tile source',
    maxzoom: 22,
  });
}

export const DEFAULT_BASEMAP = BASEMAPS[0].id;

export function basemapById(id: string): BasemapOption {
  return BASEMAPS.find((b) => b.id === id) ?? BASEMAPS[0];
}

export const BASEMAP_SOURCE_ID = 'basemap';
export const BASEMAP_LAYER_ID = 'basemap';

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
export function buildStyle(basemapId: string = DEFAULT_BASEMAP): StyleSpecification {
  const sources: StyleSpecification['sources'] = {
    'ne-land': { type: 'geojson', data: landGeoJson() as never },
    'ne-countries': { type: 'geojson', data: countriesGeoJson() as never },
    graticule: { type: 'geojson', data: graticule(10) as never },
  };

  const layers = offlineLayers();

  const basemap = basemapById(basemapId);
  if (basemap.url) {
    sources[BASEMAP_SOURCE_ID] = {
      type: 'raster',
      tiles: [basemap.url],
      tileSize: 256,
      maxzoom: basemap.maxzoom,
      attribution: basemap.attribution,
    };
    // Raster sits above the bundled vectors so the vectors act as a backdrop
    // for tiles that have not loaded yet, rather than disappearing.
    layers.push({
      id: BASEMAP_LAYER_ID,
      type: 'raster',
      source: BASEMAP_SOURCE_ID,
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
