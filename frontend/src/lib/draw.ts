/**
 * Polygon draw and edit for MapLibre.
 *
 * Written rather than pulled in so the interaction and the styling match the
 * rest of the product: a rubber band that follows the cursor, a first vertex
 * that highlights when closing is possible, draggable vertices in edit mode,
 * and keyboard affordances (Enter to close, Escape to cancel, Backspace to
 * undo the last vertex).
 */

import type { GeoJSONSource, Map as MapLibreMap, MapMouseEvent } from 'maplibre-gl';

import { COLORS } from './mapTheme';
import type { Geometry } from './types';

export type DrawMode = 'idle' | 'drawing' | 'editing';

interface Handlers {
  onChange: (geometry: Geometry | null) => void;
  onModeChange: (mode: DrawMode) => void;
}

type Position = [number, number];

const SRC_FILL = 'draw-fill';
const SRC_LINE = 'draw-line';
const SRC_VERTEX = 'draw-vertex';

const LYR_FILL = 'draw-fill-layer';
const LYR_LINE = 'draw-line-layer';
const LYR_VERTEX = 'draw-vertex-layer';
const LYR_VERTEX_HIT = 'draw-vertex-hit';

const EMPTY: GeoJSON.FeatureCollection = { type: 'FeatureCollection', features: [] };

/** Pixel radius within which a click counts as "on the first vertex". */
const CLOSE_TOLERANCE_PX = 14;

export class PolygonDrawer {
  private map: MapLibreMap;
  private handlers: Handlers;
  private mode: DrawMode = 'idle';
  private points: Position[] = [];
  private cursor: Position | null = null;
  private dragIndex: number | null = null;
  private hoverFirst = false;
  private destroyed = false;

  constructor(map: MapLibreMap, handlers: Handlers) {
    this.map = map;
    this.handlers = handlers;
    this.install();
  }

  // --- Setup ------------------------------------------------------------

  private install(): void {
    const map = this.map;

    map.addSource(SRC_FILL, { type: 'geojson', data: EMPTY });
    map.addSource(SRC_LINE, { type: 'geojson', data: EMPTY });
    map.addSource(SRC_VERTEX, { type: 'geojson', data: EMPTY });

    map.addLayer({
      id: LYR_FILL,
      type: 'fill',
      source: SRC_FILL,
      paint: { 'fill-color': COLORS.draftFill, 'fill-opacity': 1 },
    });

    map.addLayer({
      id: LYR_LINE,
      type: 'line',
      source: SRC_LINE,
      layout: { 'line-cap': 'round', 'line-join': 'round' },
      paint: {
        'line-color': COLORS.draftLine,
        'line-width': 2,
        'line-dasharray': [2.5, 1.5],
      },
    });

    // A wider transparent target so vertices are easy to grab.
    map.addLayer({
      id: LYR_VERTEX_HIT,
      type: 'circle',
      source: SRC_VERTEX,
      paint: { 'circle-radius': 13, 'circle-color': 'rgba(0,0,0,0)' },
    });

    map.addLayer({
      id: LYR_VERTEX,
      type: 'circle',
      source: SRC_VERTEX,
      paint: {
        'circle-radius': ['case', ['get', 'isFirst'], 6.5, 5],
        'circle-color': [
          'case',
          ['get', 'active'],
          COLORS.vertexActive,
          COLORS.vertex,
        ],
        'circle-stroke-color': COLORS.vertexStroke,
        'circle-stroke-width': 2,
      },
    });

    map.on('click', this.onClick);
    map.on('mousemove', this.onMouseMove);
    map.on('dblclick', this.onDoubleClick);
    map.on('mousedown', LYR_VERTEX_HIT, this.onVertexDown);
    window.addEventListener('keydown', this.onKeyDown);
  }

  destroy(): void {
    if (this.destroyed) return;
    this.destroyed = true;
    const map = this.map;
    map.off('click', this.onClick);
    map.off('mousemove', this.onMouseMove);
    map.off('dblclick', this.onDoubleClick);
    map.off('mousedown', LYR_VERTEX_HIT, this.onVertexDown);
    window.removeEventListener('keydown', this.onKeyDown);

    for (const id of [LYR_VERTEX, LYR_VERTEX_HIT, LYR_LINE, LYR_FILL]) {
      if (map.getLayer(id)) map.removeLayer(id);
    }
    for (const id of [SRC_VERTEX, SRC_LINE, SRC_FILL]) {
      if (map.getSource(id)) map.removeSource(id);
    }
  }

  // --- Public API --------------------------------------------------------

  getMode(): DrawMode {
    return this.mode;
  }

  start(): void {
    this.points = [];
    this.cursor = null;
    this.setMode('drawing');
    this.map.getCanvas().style.cursor = 'crosshair';
    this.map.doubleClickZoom.disable();
    this.render();
    this.handlers.onChange(null);
  }

  cancel(): void {
    this.points = [];
    this.cursor = null;
    this.setMode('idle');
    this.resetCursor();
    this.render();
  }

  clear(): void {
    this.points = [];
    this.cursor = null;
    this.setMode('idle');
    this.resetCursor();
    this.render();
    this.handlers.onChange(null);
  }

  /** Enter edit mode on an existing polygon (from a demo area or a search). */
  loadPolygon(geometry: Geometry | null): void {
    if (!geometry || geometry.type !== 'Polygon') {
      this.points = [];
      this.setMode('idle');
      this.render();
      return;
    }
    const ring = (geometry.coordinates as number[][][])[0] ?? [];
    // Drop the closing coordinate; it is re-added on export.
    const open = ring.slice(0, Math.max(ring.length - 1, 0));
    this.points = open.map((c) => [c[0], c[1]] as Position);
    this.cursor = null;
    this.setMode('editing');
    this.resetCursor();
    this.render();
  }

  finish(): boolean {
    if (this.points.length < 3) return false;
    this.cursor = null;
    this.setMode('editing');
    this.resetCursor();
    this.map.doubleClickZoom.enable();
    this.render();
    this.handlers.onChange(this.toGeometry());
    return true;
  }

  undoVertex(): void {
    if (this.mode !== 'drawing' || this.points.length === 0) return;
    this.points.pop();
    this.render();
  }

  // --- Interaction --------------------------------------------------------

  private onClick = (event: MapMouseEvent): void => {
    if (this.mode !== 'drawing') return;

    const point: Position = [event.lngLat.lng, event.lngLat.lat];

    if (this.points.length >= 3 && this.isNearFirst(event)) {
      this.finish();
      return;
    }

    // Ignore a click that lands exactly on the previous vertex.
    const last = this.points[this.points.length - 1];
    if (last && this.pixelDistance(last, point) < 4) return;

    this.points.push(point);
    this.render();
  };

  private onMouseMove = (event: MapMouseEvent): void => {
    if (this.mode === 'drawing') {
      this.cursor = [event.lngLat.lng, event.lngLat.lat];
      const near = this.points.length >= 3 && this.isNearFirst(event);
      if (near !== this.hoverFirst) {
        this.hoverFirst = near;
        this.map.getCanvas().style.cursor = near ? 'pointer' : 'crosshair';
      }
      this.render();
      return;
    }

    if (this.dragIndex !== null) {
      this.points[this.dragIndex] = [event.lngLat.lng, event.lngLat.lat];
      this.render();
    }
  };

  private onDoubleClick = (event: MapMouseEvent): void => {
    if (this.mode !== 'drawing') return;
    event.preventDefault();
    this.finish();
  };

  private onVertexDown = (event: MapMouseEvent & { features?: GeoJSON.Feature[] }): void => {
    if (this.mode !== 'editing') return;
    const feature = event.features?.[0];
    if (!feature) return;
    const index = (feature.properties as { index?: number } | null)?.index;
    if (index === undefined) return;

    event.preventDefault();
    this.dragIndex = index;
    this.map.dragPan.disable();
    this.map.getCanvas().style.cursor = 'grabbing';
    this.map.once('mouseup', this.onVertexUp);
  };

  private onVertexUp = (): void => {
    if (this.dragIndex === null) return;
    this.dragIndex = null;
    this.map.dragPan.enable();
    this.resetCursor();
    this.render();
    this.handlers.onChange(this.toGeometry());
  };

  private onKeyDown = (event: KeyboardEvent): void => {
    const target = event.target as HTMLElement | null;
    if (target && /^(INPUT|TEXTAREA|SELECT)$/.test(target.tagName)) return;

    if (event.key === 'Escape' && this.mode === 'drawing') {
      event.preventDefault();
      this.cancel();
    } else if (event.key === 'Enter' && this.mode === 'drawing') {
      event.preventDefault();
      this.finish();
    } else if (
      (event.key === 'Backspace' || event.key === 'Delete') &&
      this.mode === 'drawing'
    ) {
      event.preventDefault();
      this.undoVertex();
    }
  };

  // --- Geometry ------------------------------------------------------------

  private toGeometry(): Geometry | null {
    if (this.points.length < 3) return null;
    const ring = [...this.points, this.points[0]];
    return { type: 'Polygon', coordinates: [ring] };
  }

  private isNearFirst(event: MapMouseEvent): boolean {
    const first = this.points[0];
    if (!first) return false;
    const projected = this.map.project(first);
    const dx = projected.x - event.point.x;
    const dy = projected.y - event.point.y;
    return Math.hypot(dx, dy) <= CLOSE_TOLERANCE_PX;
  }

  private pixelDistance(a: Position, b: Position): number {
    const pa = this.map.project(a);
    const pb = this.map.project(b);
    return Math.hypot(pa.x - pb.x, pa.y - pb.y);
  }

  private setMode(mode: DrawMode): void {
    if (this.mode === mode) return;
    this.mode = mode;
    this.handlers.onModeChange(mode);
  }

  private resetCursor(): void {
    this.hoverFirst = false;
    this.map.getCanvas().style.cursor = '';
  }

  // --- Rendering -------------------------------------------------------------

  private render(): void {
    if (this.destroyed) return;
    const fill = this.map.getSource(SRC_FILL) as GeoJSONSource | undefined;
    const line = this.map.getSource(SRC_LINE) as GeoJSONSource | undefined;
    const vertex = this.map.getSource(SRC_VERTEX) as GeoJSONSource | undefined;
    if (!fill || !line || !vertex) return;

    if (this.mode === 'idle' || this.points.length === 0) {
      fill.setData(EMPTY);
      line.setData(EMPTY);
      vertex.setData(EMPTY);
      return;
    }

    // The rubber band includes the live cursor while drawing.
    const path: Position[] =
      this.mode === 'drawing' && this.cursor
        ? [...this.points, this.cursor]
        : [...this.points, this.points[0]];

    line.setData({
      type: 'Feature',
      geometry: { type: 'LineString', coordinates: path },
      properties: {},
    } as never);

    if (path.length >= 4) {
      fill.setData({
        type: 'Feature',
        geometry: { type: 'Polygon', coordinates: [[...path, path[0]]] },
        properties: {},
      } as never);
    } else {
      fill.setData(EMPTY);
    }

    vertex.setData({
      type: 'FeatureCollection',
      features: this.points.map((position, index) => ({
        type: 'Feature',
        geometry: { type: 'Point', coordinates: position },
        properties: {
          index,
          isFirst: index === 0,
          // Highlight the first vertex when clicking it would close the ring.
          active:
            (index === 0 && this.hoverFirst) || index === this.dragIndex,
        },
      })),
    } as never);
  }
}
