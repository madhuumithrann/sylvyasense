import { useQuery } from '@tanstack/react-query';

import { useWorkflow } from '../../hooks/useWorkflow';
import { api } from '../../lib/api';
import { area, date, integer, num, pct } from '../../lib/format';
import type { SystemStatus } from '../../lib/types';
import { useStore } from '../../state/store';
import { EmptyState, Meter, Note, Section, StatRow, StatusBadge } from '../ui';

/**
 * Step one of the workflow: what is this area, and is there enough data to
 * analyse it? The audit runs before any expensive modelling, so a user never
 * spends a run on an area that cannot produce a defensible result.
 */
export function AuditPanel({ status }: { status: SystemStatus | undefined }) {
  const geometry = useStore((s) => s.geometry);
  const aoi = useStore((s) => s.aoi);
  const audit = useStore((s) => s.audit);
  const analysis = useStore((s) => s.analysis);
  const state = useStore((s) => s.state);
  const year = useStore((s) => s.year);
  const setYear = useStore((s) => s.setYear);
  const setGeometry = useStore((s) => s.setGeometry);

  const { runAudit, runAnalysis } = useWorkflow();
  const demo = useQuery({ queryKey: ['demo-places'], queryFn: api.demoPlaces });

  const years = status?.available_years ?? [];
  const busy = state === 'AUDITING';
  const analysing = state === 'ANALYZING';

  if (!geometry) {
    return (
      <>
        <EmptyState title="Select a forest area">
          Draw a polygon on the map, search for a forest region, or pick one of the
          demo areas below. SylvaSense measures the area geodesically and checks
          what satellite data exists before running anything.
        </EmptyState>

        <Section title="Demo areas">
          <div className="demo-list">
            {(demo.data?.results ?? []).map((place) => (
              <button
                key={place.name}
                className="demo-item"
                onClick={() => place.geometry && setGeometry(place.geometry, place.name)}
                data-testid={`demo-${place.name.replace(/\W+/g, '-').toLowerCase()}`}
              >
                <span className="demo-item__name">{place.name}</span>
                <span className="demo-item__meta">
                  {place.country} · {place.biome}
                </span>
                {place.note && <span className="demo-item__note">{place.note}</span>}
              </button>
            ))}
          </div>
        </Section>
      </>
    );
  }

  return (
    <>
      <Section title="Area of interest">
        {aoi ? (
          <>
            <StatRow label="Area" value={area(aoi.area_km2)} />
            <StatRow label="Hectares" value={`${integer(aoi.area_ha)} ha`} />
            <StatRow label="Perimeter" value={`${num(aoi.perimeter_km, 2)} km`} />
            <StatRow
              label="Centroid"
              value={`${num(aoi.centroid.lat, 4)}, ${num(aoi.centroid.lon, 4)}`}
            />
            <StatRow label="Identifier" value={aoi.aoi_id} />
            <p className="hint" style={{ marginTop: 'var(--s2)' }}>
              {aoi.measurement}
            </p>
          </>
        ) : (
          <p className="hint">Measuring the drawn area…</p>
        )}
      </Section>

      <Section title="Epoch">
        <div className="year-picker" role="group" aria-label="Analysis year">
          {years.map((option) => (
            <button
              key={option}
              className={`year-chip ${option === year ? 'is-active' : ''}`}
              onClick={() => setYear(option)}
              data-testid={`year-${option}`}
            >
              {option}
            </button>
          ))}
        </div>
      </Section>

      {!audit && (
        <div className="panel-actions">
          <button
            className="btn btn--primary btn--lg btn--block"
            onClick={() => void runAudit()}
            disabled={busy || !aoi}
            data-testid="run-audit"
          >
            {busy ? 'Checking data availability…' : 'Run audit'}
          </button>
          {busy && <div className="indeterminate" />}
          <p className="hint">
            Checks which missions actually observed this area in {year}, before any
            modelling is attempted.
          </p>
        </div>
      )}

      {audit && (
        <>
          <Section title="Data availability">
            <div className="verdict">
              <StatusBadge status={audit.verdict} />
              <p className="verdict__detail">{audit.verdict_detail}</p>
            </div>

            <div className="source-list">
              {audit.sources.map((source) => (
                <div className="source" key={source.key}>
                  <div className="source__head">
                    <span className="source__label">{source.label}</span>
                    <StatusBadge status={source.status} />
                  </div>
                  <p className="source__detail">{source.detail}</p>
                  {(source.first_date || source.last_date) && (
                    <p className="source__dates mono">
                      {date(source.first_date)} → {date(source.last_date)}
                    </p>
                  )}
                </div>
              ))}
            </div>
          </Section>

          <Section title="Cover and cloud">
            {audit.forest_cover_pct !== null && (
              <>
                <StatRow label="Tree cover" value={pct(audit.forest_cover_pct)} />
                <Meter
                  value={audit.forest_cover_pct}
                  max={100}
                  label={`${audit.forest_cover_pct.toFixed(1)}% tree cover`}
                />
              </>
            )}
            {audit.cloud_cover_pct !== null && (
              <div style={{ marginTop: 'var(--s3)' }}>
                <StatRow label="Mean scene cloud" value={pct(audit.cloud_cover_pct)} />
                <Meter
                  value={audit.cloud_cover_pct}
                  max={100}
                  color="var(--info)"
                  label={`${audit.cloud_cover_pct.toFixed(1)}% cloud`}
                />
              </div>
            )}
            <StatRow
              label="Window"
              value={`${date(audit.window.start)} → ${date(audit.window.end)}`}
            />
          </Section>

          {audit.verdict === 'INSUFFICIENT_DATA' ? (
            <Note tone="danger" title="Analysis cannot run here">
              {audit.verdict_detail} Try a different area or another year.
            </Note>
          ) : (
            <div className="panel-actions">
              {audit.verdict === 'PARTIAL_DATA' && (
                <Note tone="warn" title="Reduced support">
                  {audit.verdict_detail}
                </Note>
              )}
              <button
                className="btn btn--primary btn--lg btn--block"
                onClick={() => void runAnalysis()}
                disabled={analysing}
                data-testid="run-analysis"
              >
                {analysing
                  ? 'Analysing…'
                  : analysis
                    ? 'Re-run analysis'
                    : 'Run analysis'}
              </button>
              <button
                className="btn btn--block"
                onClick={() => void runAudit()}
                disabled={busy || analysing}
              >
                Re-check availability
              </button>
            </div>
          )}
        </>
      )}
    </>
  );
}
