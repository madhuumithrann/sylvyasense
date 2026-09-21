import { compact, date, integer, num, pct, score } from '../../lib/format';
import { useStore } from '../../state/store';
import { EmptyState, Metric, Note, Provenance, Section, StatRow } from '../ui';

/**
 * The result. Every headline figure carries the sensor, model and date behind
 * it, because a number without provenance is not a scientific claim.
 */
export function AnalysisPanel() {
  const analysis = useStore((s) => s.analysis);
  const setTab = useStore((s) => s.setTab);

  if (!analysis) {
    return (
      <EmptyState
        title="No analysis yet"
        action={
          <button className="btn btn--primary" onClick={() => setTab('audit')}>
            Go to audit
          </button>
        }
      >
        Run an analysis from the Audit tab to produce canopy, biomass, carbon and
        uncertainty for this area.
      </EmptyState>
    );
  }

  const { biomass, carbon, co2e, canopy, provenance } = analysis;
  const model = biomass.model;
  const optical = provenance.optical;
  const radar = provenance.radar;
  const gedi = provenance.gedi;

  return (
    <>
      {analysis.simulated && (
        <Note tone="sim" title="Sandbox simulation">
          These figures were produced by SylvaSense's forward model, not measured by
          a satellite. They exercise the pipeline; they do not describe a real
          forest. Configure an Earth Engine service account for real observations.
        </Note>
      )}

      <Section title="Headline">
        <div className="metric-grid">
          <Metric
            label="Canopy"
            value={num(canopy.cover_pct, 1)}
            unit="%"
            testId="metric-canopy"
            provenance={
              <Provenance
                lines={[
                  optical ? shortCollection(optical.collection) : null,
                  optical ? `${date(optical.last_date)}` : null,
                  optical ? `Cloud ${pct(optical.cloud_cover_pct)}` : null,
                ]}
              />
            }
          />
          <Metric
            label="Aboveground biomass"
            value={num(biomass.mean_mg_ha, 0)}
            unit="Mg/ha"
            range={`${num(biomass.p05_mg_ha, 0)} – ${num(biomass.p95_mg_ha, 0)} (90%)`}
            tone="accent"
            testId="metric-agb"
            provenance={
              <Provenance
                lines={[
                  model.calibration === 'gedi-local'
                    ? 'GEDI-calibrated LightGBM'
                    : 'Regional default — uncalibrated',
                  model.version,
                  model.n_training > 0
                    ? `n = ${integer(model.n_training)} GEDI footprints`
                    : 'No local calibration data',
                ]}
              />
            }
          />
          <Metric
            label="Carbon"
            value={num(carbon.mean_tc_ha, 1)}
            unit="tC/ha"
            range={`${num(carbon.p05_tc_ha, 1)} – ${num(carbon.p95_tc_ha, 1)}`}
            testId="metric-carbon"
            provenance={
              <Provenance
                lines={[
                  `Carbon fraction ${analysis.constants.carbon_fraction}`,
                  analysis.constants.carbon_fraction_source,
                ]}
              />
            }
          />
          <Metric
            label="CO₂ equivalent"
            value={num(co2e.mean_tco2e_ha, 1)}
            unit="tCO₂e/ha"
            range={`${num(co2e.p05_tco2e_ha, 1)} – ${num(co2e.p95_tco2e_ha, 1)}`}
            testId="metric-co2e"
            provenance={<Provenance lines={[analysis.constants.co2e_source]} />}
          />
        </div>
      </Section>

      <Section title="Stock over the area">
        <StatRow label="Area" value={`${integer(analysis.area_ha)} ha`} />
        <StatRow label="Total biomass" value={compact(biomass.total_stock_mg, 'Mg')} />
        <StatRow label="Total carbon" value={compact(carbon.total_tc, 'tC')} />
        <StatRow label="Total CO₂e" value={compact(co2e.total_tco2e, 'tCO₂e')} />
        <StatRow
          label="Belowground (inferred)"
          value={`${num(analysis.belowground.mean_tc_ha, 1)} tC/ha`}
          title={analysis.belowground.note}
        />
        <p className="hint" style={{ marginTop: 'var(--s2)' }}>
          {analysis.belowground.note}
        </p>
      </Section>

      <Section title="Model">
        <StatRow label="Version" value={model.version} />
        <StatRow label="Calibration" value={model.calibration} />
        <StatRow label="Algorithm" value={model.algorithm} />
        <StatRow label="Training samples" value={integer(model.n_training)} />
        {model.cv_r2 !== null ? (
          <>
            <StatRow label="Cross-validated R²" value={num(model.cv_r2, 2)} />
            <StatRow label="Cross-validated RMSE" value={`${num(model.cv_rmse, 1)} Mg/ha`} />
            <StatRow label="Validation" value={model.cv_scheme ?? '—'} />
          </>
        ) : (
          <StatRow label="Cross-validated skill" value="Not fitted for this site" />
        )}
        <StatRow
          label="Effective sample size"
          value={num(biomass.effective_n, 0)}
          title="Independent spatial blocks behind the area mean. Neighbouring cells do not carry independent errors, so the area interval is not tightened as if they did."
        />

        {model.uncalibrated && (
          <div style={{ marginTop: 'var(--s3)' }}>
            <Note tone="warn" title="Uncalibrated estimate">
              This area had too few GEDI reference footprints to fit a local model, so
              a published regional relationship was used. Suitable for prioritising
              survey effort, not for carbon accounting.
            </Note>
          </div>
        )}

        {model.saturation_note && (
          <div style={{ marginTop: 'var(--s2)' }}>
            <Note tone="info" title="Saturation">
              {model.saturation_note}
            </Note>
          </div>
        )}

        {model.caveats.length > 0 && (
          <div style={{ marginTop: 'var(--s2)' }}>
            <Note tone="warn" title="Caveats recorded by the model">
              <ul>
                {model.caveats.map((caveat) => (
                  <li key={caveat}>{caveat}</li>
                ))}
              </ul>
            </Note>
          </div>
        )}
      </Section>

      {Object.keys(model.feature_importance).length > 0 && (
        <Section title="Predictor importance">
          <div className="importance">
            {Object.entries(model.feature_importance)
              .slice(0, 8)
              .map(([feature, value]) => (
                <div className="importance__row" key={feature}>
                  <span className="importance__label mono">{feature}</span>
                  <span className="importance__bar">
                    <span
                      className="importance__fill"
                      style={{ width: `${Math.min(value * 100 * 4, 100)}%` }}
                    />
                  </span>
                  <span className="importance__value mono">{score(value, 1)}</span>
                </div>
              ))}
          </div>
        </Section>
      )}

      <Section title="Inputs">
        <StatRow label="Mode" value={provenance.mode.replace(/_/g, ' ')} />
        <StatRow
          label="Window"
          value={`${date(provenance.window.start)} → ${date(provenance.window.end)}`}
        />
        <StatRow
          label="Grid"
          value={`${provenance.grid.rows} × ${provenance.grid.cols} @ ${num(provenance.grid.cell_size_m, 0)} m`}
        />
        {optical && (
          <>
            <StatRow label="Optical" value={shortCollection(optical.collection)} />
            <StatRow
              label="Optical scenes"
              value={`${optical.scenes} · ${date(optical.first_date)} → ${date(optical.last_date)}`}
            />
          </>
        )}
        {radar ? (
          <>
            <StatRow label="Radar" value={shortCollection(radar.collection)} />
            <StatRow label="Radar scenes" value={`${radar.scenes} · ${radar.orbit}`} />
          </>
        ) : (
          <StatRow label="Radar" value="Not available for this area" />
        )}
        {gedi ? (
          <StatRow
            label="Biomass reference"
            value={`${integer(gedi.footprints)} GEDI footprints`}
          />
        ) : (
          <StatRow label="Biomass reference" value="No GEDI coverage" />
        )}
        <StatRow label="Analysis created" value={date(provenance.created_at)} />
      </Section>
    </>
  );
}

/** "COPERNICUS/S2_SR_HARMONIZED" reads better as its last segment in a row. */
function shortCollection(id: string): string {
  const parts = id.split('/');
  return parts[parts.length - 1] ?? id;
}
