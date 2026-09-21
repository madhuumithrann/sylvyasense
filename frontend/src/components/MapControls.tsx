import { useEffect, useState } from 'react';
import type { Map as MapLibreMap } from 'maplibre-gl';

import { latLon } from '../lib/format';
import { useStore } from '../state/store';

interface Props {
  map: MapLibreMap | null;
  cursor: { lon: number; lat: number } | null;
  basemapOffline: boolean;
  onDraw: () => void;
  onCancelDraw: () => void;
  onFinishDraw: () => void;
  onClear: () => void;
}

export function MapControls({
  map,
  cursor,
  basemapOffline,
  onDraw,
  onCancelDraw,
  onFinishDraw,
  onClear,
}: Props) {
  const drawMode = useStore((s) => s.drawMode);
  const geometry = useStore((s) => s.geometry);
  const analysis = useStore((s) => s.analysis);
  const inspectMode = useStore((s) => s.inspectMode);
  const setInspectMode = useStore((s) => s.setInspectMode);

  const [zoom, setZoom] = useState(2.4);

  useEffect(() => {
    if (!map) return;
    const update = () => setZoom(map.getZoom());
    map.on('zoom', update);
    update();
    return () => {
      map.off('zoom', update);
    };
  }, [map]);

  return (
    <>
      {/* --- Drawing toolbar ------------------------------------------- */}
      <div className="map-toolbar panel" role="toolbar" aria-label="Map tools">
        {drawMode === 'drawing' ? (
          <>
            <span className="map-toolbar__hint">
              Click to add corners · click the first corner or press Enter to close
            </span>
            <button className="btn btn--sm" onClick={onFinishDraw}>
              Close shape
            </button>
            <button className="btn btn--sm btn--ghost" onClick={onCancelDraw}>
              Cancel
            </button>
          </>
        ) : (
          <>
            <button
              className="btn btn--sm"
              onClick={onDraw}
              data-testid="draw-aoi"
              title="Draw an area of interest (Esc to cancel)"
            >
              <PolygonIcon />
              {geometry ? 'Redraw area' : 'Draw area'}
            </button>
            <button
              className={`btn btn--sm ${inspectMode ? 'btn--active' : ''}`}
              onClick={() => setInspectMode(!inspectMode)}
              disabled={!analysis}
              data-testid="inspect-toggle"
              aria-pressed={inspectMode}
              title={
                analysis
                  ? 'Click the map to inspect a cell'
                  : 'Run an analysis first'
              }
            >
              <CrosshairIcon />
              Inspect
            </button>
            {geometry && (
              <button
                className="btn btn--sm btn--ghost btn--danger"
                onClick={onClear}
                data-testid="clear-aoi"
                title="Remove the area of interest"
              >
                Clear
              </button>
            )}
          </>
        )}
      </div>

      {/* --- Zoom ------------------------------------------------------- */}
      <div className="map-zoom panel" role="group" aria-label="Zoom">
        <button
          className="map-zoom__btn"
          onClick={() => map?.zoomIn({ duration: 240 })}
          aria-label="Zoom in"
        >
          +
        </button>
        <div className="map-zoom__level mono" aria-live="off">
          z{zoom.toFixed(1)}
        </div>
        <button
          className="map-zoom__btn"
          onClick={() => map?.zoomOut({ duration: 240 })}
          aria-label="Zoom out"
        >
          −
        </button>
      </div>

      {/* --- Readout ---------------------------------------------------- */}
      <div className="map-readout">
        {basemapOffline && (
          <span
            className="pill pill--warn"
            title="The basemap tile host could not be reached. Bundled Natural Earth vectors are shown instead; all SylvaSense analysis layers are unaffected."
          >
            <span className="pill__dot" />
            Basemap offline
          </span>
        )}
        {cursor && (
          <span className="map-readout__coords mono">
            {latLon(cursor.lat, cursor.lon)}
          </span>
        )}
      </div>
    </>
  );
}

function PolygonIcon() {
  return (
    <svg width="13" height="13" viewBox="0 0 16 16" fill="none" aria-hidden="true">
      <path
        d="M8 1.6 14.4 6.2 12 13.9H4L1.6 6.2 8 1.6Z"
        stroke="currentColor"
        strokeWidth="1.3"
        strokeLinejoin="round"
      />
    </svg>
  );
}

function CrosshairIcon() {
  return (
    <svg width="13" height="13" viewBox="0 0 16 16" fill="none" aria-hidden="true">
      <circle cx="8" cy="8" r="4" stroke="currentColor" strokeWidth="1.3" />
      <path
        d="M8 1v2.2M8 12.8V15M1 8h2.2M12.8 8H15"
        stroke="currentColor"
        strokeWidth="1.3"
        strokeLinecap="round"
      />
    </svg>
  );
}
