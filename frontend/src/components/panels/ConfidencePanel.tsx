import { humanise, integer, latLon, num, pct, score } from '../../lib/format';
import { useStore } from '../../state/store';
import {
  EmptyState,
  Meter,
  Note,
  Provenance,
  Section,
  StatRow,
  StatusBadge,
} from '../ui';

const CLASS_COLOR: Record<string, string> = {
  HIGH_CONFIDENCE: 'var(--conf-high)',
  SURVEY_RECOMMENDED: 'var(--conf-survey)',
  INSUFFICIENT_DATA: 'var(--conf-insufficient)',
};

const CLASS_MEANING: Record<string, string> = {
  HIGH_CONFIDENCE: 'The estimate is well supported by the available evidence',
  SURVEY_RECOMMENDED: 'Evidence is thin — a ground measurement would materially help',
  INSUFFICIENT_DATA: 'Not enough evidence to stand behind a value here',
};

/**
 * Confidence, and — when a cell is picked on the map — exactly why that cell
 * scored the way it did. The reason shown is the component that actually
 * dominated the loss, computed by the backend, not a narrative written after
 * the fact.
 */
export function ConfidencePanel() {
  const analysis = useStore((s) => s.analysis);
  const cell = useStore((s) => s.selectedCell);
  const inspectMode = useStore((s) => s.inspectMode);
  const setInspectMode = useStore((s) => s.setInspectMode);
  const toggleLayer = useStore((s) => s.toggleLayer);
  const activeLayers = useStore((s) => s.activeLayers);
  const setSelectedCell = useStore((s) => s.setSelectedCell);

  if (!analysis) {
    return (
      <EmptyState title="No analysis yet">
        Confidence is produced alongside the biomass estimate. Run an analysis first.
      </EmptyState>
    );
  }

  const conf = analysis.confidence;
  const fractions = conf.class_fractions;
  const showing = activeLayers.includes('confidence_class');

  return (
    <>
      <Section
        title="Confidence across the area"
        action={
          <button
            className="btn btn--sm"
            onClick={() => toggleLayer('confidence_class')}
            data-testid="view-confidence"
          >
            {showing ? 'Hide on map' : 'View on map'}
          </button>
        }
      >
        <div className="conf-classes">
          {(
            [
              'HIGH_CONFIDENCE',
              'SURVEY_RECOMMENDED',
              'INSUFFICIENT_DATA',
            ] as const
          ).map((key) => (
            <div className="conf-class" key={key}>
              <div className="conf-class__head">
                <span
                  className="conf-class__swatch"
                  style={{ background: CLASS_COLOR[key] }}
                />
                <span className="conf-class__label">{humanise(key)}</span>
                <span className="conf-class__value mono">{score(fractions[key], 1)}</span>
              </div>
              <Meter
                value={fractions[key]}
                color={CLASS_COLOR[key]}
                label={`${humanise(key)}: ${score(fractions[key], 1)} of the area`}
              />
              <p className="conf-class__meaning">{CLASS_MEANING[key]}</p>
            </div>
          ))}
        </div>

        <div style={{ marginTop: 'var(--s3)' }}>
          <StatRow label="Mean confidence" value={score(conf.mean_score, 1)} />
          <StatRow label="High threshold" value={num(conf.thresholds.high, 2)} />
          <StatRow label="Survey threshold" value={num(conf.thresholds.survey, 2)} />
        </div>
      </Section>

      <Section title="How confidence is scored">
        <p className="hint" style={{ marginBottom: 'var(--s2)' }}>
          Four measured properties of the evidence, weighted as shown. It is not a
          restatement of the model interval alone.
        </p>
        {Object.entries(conf.weights).map(([key, weight]) => (
          <StatRow key={key} label={humanise(key)} value={score(weight, 0)} />
        ))}
      </Section>

      <Section
        title="Cell detail"
        action={
          <button
            className={`btn btn--sm ${inspectMode ? 'btn--primary' : ''}`}
            onClick={() => setInspectMode(!inspectMode)}
            aria-pressed={inspectMode}
            data-testid="confidence-inspect"
          >
            {inspectMode ? 'Inspecting' : 'Inspect a cell'}
          </button>
        }
      >
        {!cell && (
          <p className="hint">
            Switch on Inspect, then click anywhere inside the area to see what the
            model knows about that cell and why it scored as it did.
          </p>
        )}

        {cell && !cell.inside_aoi && (
          <Note tone="info">{cell.message ?? 'That point is outside the analysed area.'}</Note>
        )}

        {cell && cell.inside_aoi && cell.confidence && (
          <div className="cell-detail" data-testid="cell-detail">
            <div className="cell-detail__head">
              <StatusBadge status={cell.confidence.class} />
              <button
                className="btn btn--sm btn--ghost"
                onClick={() => setSelectedCell(null)}
                aria-label="Clear selection"
              >
                Clear
              </button>
            </div>

            <div className="cell-detail__score mono">
              {score(cell.confidence.score, 0)}
              <span>confidence</span>
            </div>

            <Note tone="warn" title="Limiting factor">
              {cell.confidence.limiting_factor}
            </Note>

            <div style={{ marginTop: 'var(--s3)' }}>
              <div className="eyebrow" style={{ marginBottom: 'var(--s2)' }}>
                Components
              </div>
              {Object.entries(cell.confidence.components).map(([key, value]) => (
                <div className="component-row" key={key}>
                  <span className="component-row__label">{humanise(key)}</span>
                  <Meter
                    value={value ?? 0}
                    color={
                      key === cell.confidence?.limiting_component
                        ? 'var(--warn)'
                        : 'var(--accent)'
                    }
                    label={`${humanise(key)}: ${score(value, 0)}`}
                  />
                  <span className="component-row__value mono">{score(value, 0)}</span>
                </div>
              ))}
            </div>

            <div style={{ marginTop: 'var(--s4)' }}>
              <div className="eyebrow" style={{ marginBottom: 'var(--s2)' }}>
                Prediction at this cell
              </div>
              <StatRow label="Location" value={latLon(cell.lat, cell.lon)} />
              <StatRow
                label="Cell size"
                value={`${num(cell.cell?.size_m, 0)} m`}
              />
              <StatRow
                label="Biomass"
                value={`${num(cell.biomass?.agb_mg_ha, 0)} Mg/ha`}
              />
              <StatRow
                label="90% interval"
                value={`${num(cell.biomass?.p05_mg_ha, 0)} – ${num(cell.biomass?.p95_mg_ha, 0)}`}
              />
              <StatRow
                label="Uncertainty (SD)"
                value={`± ${num(cell.biomass?.sd_mg_ha, 0)} Mg/ha`}
              />
              <StatRow label="Carbon" value={`${num(cell.carbon?.tc_ha, 1)} tC/ha`} />
              <StatRow label="Canopy cover" value={pct(cell.canopy?.cover_pct)} />
              <StatRow label="NDVI" value={num(cell.canopy?.ndvi, 3)} />
            </div>

            <div style={{ marginTop: 'var(--s4)' }}>
              <div className="eyebrow" style={{ marginBottom: 'var(--s2)' }}>
                Evidence behind it
              </div>
              <StatRow
                label="GEDI footprints nearby"
                value={integer(cell.evidence?.gedi_footprints_nearby)}
              />
              <StatRow
                label="Clear observations"
                value={pct(cell.evidence?.clear_observation_pct)}
              />
              <StatRow
                label="Optical scenes"
                value={integer(cell.evidence?.optical_scenes)}
              />
              <StatRow
                label="Radar scenes"
                value={
                  cell.evidence?.radar_available
                    ? integer(cell.evidence?.radar_scenes)
                    : 'None'
                }
              />
              <StatRow label="VV" value={`${num(cell.radar?.vv_db, 1)} dB`} />
              <StatRow label="VH" value={`${num(cell.radar?.vh_db, 1)} dB`} />
              <StatRow
                label="Elevation"
                value={`${num(cell.terrain?.elevation_m, 0)} m`}
              />
              <StatRow label="Slope" value={`${num(cell.terrain?.slope_deg, 1)}°`} />
            </div>

            {cell.model && (
              <div style={{ marginTop: 'var(--s3)' }}>
                <Provenance
                  lines={[
                    cell.model.calibration === 'gedi-local'
                      ? 'GEDI-calibrated LightGBM'
                      : 'Regional default — uncalibrated',
                    cell.model.version,
                    cell.model.cv_r2 !== null
                      ? `Blocked-CV R² ${num(cell.model.cv_r2, 2)}`
                      : null,
                  ]}
                />
              </div>
            )}
          </div>
        )}
      </Section>
    </>
  );
}
