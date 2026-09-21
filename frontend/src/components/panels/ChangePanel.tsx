import { useWorkflow } from '../../hooks/useWorkflow';
import { compact, humanise, integer, num, pValue, signed } from '../../lib/format';
import type { SystemStatus } from '../../lib/types';
import { useStore } from '../../state/store';
import { EmptyState, Note, Section, StatRow, StatusBadge } from '../ui';

/**
 * Two epochs, and whether the difference between them is real.
 *
 * A difference is only called a change when it clears both the statistical
 * test and a materiality floor — and when neither epoch relied on the
 * uncalibrated fallback, because a change measured against an uncalibrated
 * estimate is not interpretable.
 */
export function ChangePanel({ status }: { status: SystemStatus | undefined }) {
  const geometry = useStore((s) => s.geometry);
  const change = useStore((s) => s.change);
  const year = useStore((s) => s.year);
  const compareYear = useStore((s) => s.compareYear);
  const setCompareYear = useStore((s) => s.setCompareYear);
  const job = useStore((s) => s.job);
  const toggleLayer = useStore((s) => s.toggleLayer);
  const activeLayers = useStore((s) => s.activeLayers);
  const { runChange } = useWorkflow();

  const years = (status?.available_years ?? []).filter((y) => y !== year);
  const running = job?.kind === 'change' && (job.status === 'RUNNING' || job.status === 'QUEUED');

  if (!geometry) {
    return (
      <EmptyState title="Select a forest area">
        Choose an area first, then compare two epochs to see whether biomass has
        genuinely moved.
      </EmptyState>
    );
  }

  return (
    <>
      <Section title="Epochs">
        <div className="timeline" data-testid="time-slider">
          <div className="timeline__labels mono">
            <span>{compareYear}</span>
            <span className="timeline__arrow">→</span>
            <span>{year}</span>
          </div>
          <input
            type="range"
            min={Math.min(...(years.length ? years : [compareYear]))}
            max={Math.max(...(years.length ? years : [compareYear]))}
            step={1}
            value={compareYear}
            onChange={(event) => setCompareYear(Number(event.target.value))}
            aria-label="Baseline year"
            data-testid="compare-year-slider"
          />
          <div className="timeline__ticks">
            {years.map((option) => (
              <button
                key={option}
                className={`year-chip year-chip--sm ${option === compareYear ? 'is-active' : ''}`}
                onClick={() => setCompareYear(option)}
                data-testid={`compare-year-${option}`}
              >
                {option}
              </button>
            ))}
          </div>
        </div>
        <p className="hint" style={{ marginTop: 'var(--s2)' }}>
          Baseline {compareYear} compared against the current epoch {year}. Both
          epochs are analysed with the same model and the same grid.
        </p>
      </Section>

      <div className="panel-actions">
        <button
          className="btn btn--primary btn--lg btn--block"
          onClick={() => void runChange()}
          disabled={running || compareYear === year}
          data-testid="run-change"
        >
          {running ? 'Comparing…' : change ? 'Re-run comparison' : 'Run comparison'}
        </button>
        {running && <div className="indeterminate" />}
      </div>

      {change && (
        <>
          <Section
            title="Verdict"
            action={
              <button
                className="btn btn--sm"
                onClick={() => toggleLayer('change_class')}
                data-testid="view-change"
              >
                {activeLayers.includes('change_class') ? 'Hide on map' : 'View on map'}
              </button>
            }
          >
            <div className="verdict" data-testid="change-verdict">
              <StatusBadge status={change.verdict} label={humanise(change.verdict)} />
              <p className="verdict__detail">{change.verdict_detail}</p>
            </div>
          </Section>

          <Section title="Biomass">
            <div className="compare-row">
              <div className="compare-cell">
                <div className="eyebrow">{change.year_from}</div>
                <div className="compare-cell__value mono">
                  {num(change.biomass.from_mg_ha, 1)}
                </div>
                <div className="compare-cell__unit">Mg/ha</div>
              </div>
              <div className="compare-arrow" aria-hidden="true">→</div>
              <div className="compare-cell">
                <div className="eyebrow">{change.year_to}</div>
                <div className="compare-cell__value mono">
                  {num(change.biomass.to_mg_ha, 1)}
                </div>
                <div className="compare-cell__unit">Mg/ha</div>
              </div>
              <div
                className={`compare-delta ${change.biomass.delta_mg_ha < 0 ? 'is-loss' : 'is-gain'}`}
              >
                <div className="eyebrow">Change</div>
                <div className="compare-cell__value mono">
                  {signed(change.biomass.delta_mg_ha, 1)}
                </div>
                <div className="compare-cell__unit">
                  {change.biomass.delta_pct !== null
                    ? `${signed(change.biomass.delta_pct, 1)}%`
                    : 'Mg/ha'}
                </div>
              </div>
            </div>
            <StatRow
              label="95% interval on the change"
              value={`${signed(change.biomass.delta_p05_mg_ha, 1)} to ${signed(change.biomass.delta_p95_mg_ha, 1)} Mg/ha`}
            />
          </Section>

          <Section title="Carbon">
            <StatRow
              label={`Carbon ${change.year_from}`}
              value={`${num(change.carbon.from_tc_ha, 1)} tC/ha`}
            />
            <StatRow
              label={`Carbon ${change.year_to}`}
              value={`${num(change.carbon.to_tc_ha, 1)} tC/ha`}
            />
            <StatRow
              label="Change"
              value={`${signed(change.carbon.delta_tc_ha, 1)} tC/ha`}
            />
            <StatRow
              label="CO₂e change"
              value={`${signed(change.carbon.delta_tco2e_ha, 1)} tCO₂e/ha`}
            />
            <StatRow
              label="Total stock change"
              value={compact(change.total_stock_delta_mg, 'Mg')}
            />
          </Section>

          <Section title="Evidence">
            <StatRow label="Test" value={change.statistics.test} />
            <StatRow label="z" value={num(change.statistics.z_score, 2)} />
            <StatRow label="p" value={pValue(change.statistics.p_value)} />
            <StatRow
              label="Critical |z|"
              value={num(change.statistics.z_critical, 2)}
            />
            <StatRow
              label="Significant"
              value={change.statistics.significant ? 'Yes' : 'No'}
            />
            <StatRow
              label="Materiality floor"
              value={`${num(change.evidence.materiality_floor_mg_ha, 0)} Mg/ha`}
              title="Changes smaller than this are not reported even when statistically detectable."
            />
            <StatRow label="Cells compared" value={integer(change.evidence.cells_compared)} />
          </Section>

          <Section title="Area affected">
            <StatRow
              label="Significant loss"
              value={`${integer(change.areas.significant_loss_ha)} ha`}
            />
            <StatRow
              label="Significant gain"
              value={`${integer(change.areas.significant_gain_ha)} ha`}
            />
            <StatRow label="Stable" value={`${integer(change.areas.stable_ha)} ha`} />
            {change.verdict === 'NO_SIGNIFICANT_CHANGE' &&
              change.areas.significant_loss_ha > 0 && (
                <div style={{ marginTop: 'var(--s3)' }}>
                  <Note tone="info" title="Cell-level loss without an area-level verdict">
                    {integer(change.areas.significant_loss_ha)} ha of individual cells
                    show significant loss, but the area mean has not moved beyond its
                    combined uncertainty. Both statements are true: scattered loss can
                    be real while the whole-area figure stays within noise.
                  </Note>
                </div>
              )}
          </Section>

          {change.verdict === 'INSUFFICIENT_DATA' && (
            <Note tone="danger" title="Not interpretable">
              {change.verdict_detail}
            </Note>
          )}
        </>
      )}
    </>
  );
}
