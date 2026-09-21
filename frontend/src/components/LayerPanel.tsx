import { useMemo, useState } from 'react';

import { BASEMAPS } from '../lib/basemap';
import type { LayerSpec, SystemLayers } from '../lib/types';
import { useStore } from '../state/store';
import { RampKey } from './ui';
import './LayerPanel.css';

interface Props {
  catalogue: SystemLayers | undefined;
}

/** Groups are ordered so the most-used sit at the top of the panel. */
const GROUP_ORDER = ['Optical', 'Radar', 'Forest', 'Quality', 'Terrain', 'Change'];

export function LayerPanel({ catalogue }: Props) {
  const analysis = useStore((s) => s.analysis);
  const change = useStore((s) => s.change);
  const activeLayers = useStore((s) => s.activeLayers);
  const layerOpacity = useStore((s) => s.layerOpacity);
  const layersOpen = useStore((s) => s.layersOpen);
  const showFieldSites = useStore((s) => s.showFieldSites);
  const fieldPlan = useStore((s) => s.fieldPlan);

  const basemap = useStore((s) => s.basemap);
  const setBasemap = useStore((s) => s.setBasemap);
  const toggleLayer = useStore((s) => s.toggleLayer);
  const setLayerOpacity = useStore((s) => s.setLayerOpacity);
  const setLayersOpen = useStore((s) => s.setLayersOpen);
  const setShowFieldSites = useStore((s) => s.setShowFieldSites);

  const [collapsed, setCollapsed] = useState<Record<string, boolean>>({
    Terrain: true,
    Change: true,
  });

  const groups = useMemo(() => {
    const all = catalogue?.catalogue.groups ?? [];
    return [...all].sort(
      (a, b) => GROUP_ORDER.indexOf(a.name) - GROUP_ORDER.indexOf(b.name),
    );
  }, [catalogue]);

  const legends = catalogue?.legends ?? {};
  const disabled = !analysis;

  return (
    <aside className="layer-panel panel" aria-label="Map layers">
      <header className="layer-panel__head">
        <button
          className="layer-panel__toggle"
          onClick={() => setLayersOpen(!layersOpen)}
          aria-expanded={layersOpen}
          data-testid="layers-toggle"
        >
          <span className="section-title">Layers</span>
          <span className="layer-panel__count">
            {activeLayers.length > 0 && (
              <span className="layer-panel__badge">{activeLayers.length}</span>
            )}
            <Chevron open={layersOpen} />
          </span>
        </button>
      </header>

      {layersOpen && (
        <div className="layer-panel__body" data-testid="layer-list">
          <div className="layer-group">
            <div className="layer-group__head layer-group__head--static">
              <span className="eyebrow">Basemap</span>
            </div>
            <div className="layer-group__items">
              {BASEMAPS.map((option) => (
                <label
                  className="layer-row"
                  key={option.id}
                  title={option.description}
                >
                  <input
                    type="radio"
                    name="basemap"
                    checked={basemap === option.id}
                    onChange={() => setBasemap(option.id)}
                    data-testid={`basemap-${option.id}`}
                  />
                  <span className="layer-row__main">
                    <span className="layer-row__label">{option.label}</span>
                    <span className="layer-row__source">{option.description}</span>
                  </span>
                </label>
              ))}
            </div>
          </div>

          {disabled && (
            <p className="layer-panel__locked hint">
              Run an analysis to switch on data layers.
            </p>
          )}

          {groups.map((group) => {
            const isChange = group.name === 'Change';
            const groupDisabled = disabled || (isChange && !change);
            const isCollapsed = collapsed[group.name] ?? false;

            return (
              <div className="layer-group" key={group.name}>
                <button
                  className="layer-group__head"
                  onClick={() =>
                    setCollapsed((prev) => ({
                      ...prev,
                      [group.name]: !isCollapsed,
                    }))
                  }
                  aria-expanded={!isCollapsed}
                >
                  <span className="eyebrow">{group.name}</span>
                  <Chevron open={!isCollapsed} small />
                </button>

                {!isCollapsed && (
                  <div className="layer-group__items">
                    {group.layers.map((layer) => (
                      <LayerRow
                        key={layer.key}
                        layer={layer}
                        active={activeLayers.includes(layer.key)}
                        disabled={groupDisabled}
                        legend={layer.ramp ? legends[layer.ramp] : undefined}
                        onToggle={() => toggleLayer(layer.key)}
                      />
                    ))}
                    {isChange && !change && (
                      <p className="layer-group__hint hint">
                        Run a comparison on the Change tab to enable these.
                      </p>
                    )}
                  </div>
                )}
              </div>
            );
          })}

          {/* Field sites are markers, not a raster, so they live apart. */}
          <div className="layer-group">
            <div className="layer-group__head layer-group__head--static">
              <span className="eyebrow">Field</span>
            </div>
            <div className="layer-group__items">
              <label
                className={`layer-row ${!fieldPlan ? 'is-disabled' : ''}`}
                title={
                  fieldPlan
                    ? 'Show the recommended survey points on the map'
                    : 'Run an analysis to generate a field plan'
                }
              >
                <input
                  type="checkbox"
                  checked={showFieldSites}
                  disabled={!fieldPlan}
                  onChange={(event) => setShowFieldSites(event.target.checked)}
                  data-testid="layer-field-sites"
                />
                <span className="layer-row__main">
                  <span className="layer-row__label">Survey points</span>
                  <span className="layer-row__source">
                    {fieldPlan ? `${fieldPlan.count} sites` : 'Not generated'}
                  </span>
                </span>
              </label>
            </div>
          </div>

          <div className="layer-panel__opacity">
            <label className="eyebrow" htmlFor="layer-opacity">
              Layer opacity
            </label>
            <div className="layer-panel__opacity-row">
              <input
                id="layer-opacity"
                type="range"
                min={0.15}
                max={1}
                step={0.05}
                value={layerOpacity}
                disabled={disabled}
                onChange={(event) => setLayerOpacity(Number(event.target.value))}
                data-testid="layer-opacity"
              />
              <span className="mono layer-panel__opacity-value">
                {Math.round(layerOpacity * 100)}%
              </span>
            </div>
          </div>
        </div>
      )}
    </aside>
  );
}

function LayerRow({
  layer,
  active,
  disabled,
  legend,
  onToggle,
}: {
  layer: LayerSpec;
  active: boolean;
  disabled: boolean;
  legend: SystemLayers['legends'][string] | undefined;
  onToggle: () => void;
}) {
  return (
    <div className={`layer-row-wrap ${active ? 'is-active' : ''}`}>
      <label
        className={`layer-row ${disabled ? 'is-disabled' : ''}`}
        title={`${layer.description} — ${layer.source}`}
      >
        <input
          type="checkbox"
          checked={active}
          disabled={disabled}
          onChange={onToggle}
          data-testid={`layer-${layer.key}`}
        />
        <span className="layer-row__main">
          <span className="layer-row__label">{layer.label}</span>
          <span className="layer-row__source">{layer.source}</span>
        </span>
      </label>

      {active && legend && (
        <div className="layer-row__legend">
          {legend.categorical ? (
            <ul className="legend-cats">
              {legend.categories?.map((category) => (
                <li key={category.code}>
                  <span
                    className="legend-cats__swatch"
                    style={{ background: category.color }}
                  />
                  {category.label}
                </li>
              ))}
            </ul>
          ) : (
            legend.stops && (
              <RampKey
                stops={legend.stops}
                min={legend.vmin ?? 0}
                max={legend.vmax ?? 1}
                unit={legend.unit}
              />
            )
          )}
        </div>
      )}
    </div>
  );
}

function Chevron({ open, small = false }: { open: boolean; small?: boolean }) {
  const size = small ? 10 : 12;
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 12 12"
      fill="none"
      aria-hidden="true"
      style={{
        transform: open ? 'rotate(180deg)' : 'rotate(0deg)',
        transition: 'transform var(--t-base) var(--ease)',
      }}
    >
      <path
        d="m3 4.5 3 3 3-3"
        stroke="currentColor"
        strokeWidth="1.4"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}
