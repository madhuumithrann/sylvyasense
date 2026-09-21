import { distance, integer, latLon, num, pct, score } from '../../lib/format';
import { exportUrl } from '../../lib/api';
import type { FieldSite } from '../../lib/types';
import { useStore } from '../../state/store';
import { EmptyState, Meter, Note, Section, StatRow } from '../ui';

const PRIORITY_COLOR: Record<string, string> = {
  HIGH: 'var(--danger)',
  MEDIUM: 'var(--warn)',
  LOW: 'var(--info)',
};

/**
 * Where a field crew should actually go, and what each visit buys. The
 * "expected value" is a computed share of the area's total biomass variance,
 * not an adjective.
 */
export function FieldPlanPanel() {
  const analysis = useStore((s) => s.analysis);
  const plan = useStore((s) => s.fieldPlan);
  const selected = useStore((s) => s.selectedSite);
  const setSelected = useStore((s) => s.setSelectedSite);
  const showSites = useStore((s) => s.showFieldSites);
  const setShowSites = useStore((s) => s.setShowFieldSites);
  const year = useStore((s) => s.year);

  if (!analysis || !plan) {
    return (
      <EmptyState title="No field plan yet">
        A survey plan is generated alongside the analysis, from the cells where a
        ground measurement would reduce the most uncertainty.
      </EmptyState>
    );
  }

  if (plan.count === 0) {
    return (
      <Note tone="warn" title="No sites could be placed">
        No cell in this area had a usable uncertainty estimate, so no survey site
        could be recommended.
      </Note>
    );
  }

  return (
    <>
      <Section
        title="Plan"
        action={
          <button
            className={`btn btn--sm ${showSites ? 'btn--primary' : ''}`}
            onClick={() => setShowSites(!showSites)}
            aria-pressed={showSites}
            data-testid="toggle-field-sites"
          >
            {showSites ? 'On map' : 'Show on map'}
          </button>
        }
      >
        <StatRow label="Sites" value={`${plan.count} of ${plan.requested} requested`} />
        <StatRow label="Minimum separation" value={distance(plan.min_separation_m)} />
        <StatRow
          label="Correlation range"
          value={distance(plan.correlation_range_m)}
          title="A ground plot informs its surroundings out to roughly this distance."
        />
        <StatRow
          label="Variance addressed"
          value={pct(plan.total_expected_reduction_pct)}
          title="Share of the area's total biomass variance that lies inside the sites' correlation neighbourhoods."
        />
        <p className="hint" style={{ marginTop: 'var(--s2)' }}>{plan.method}.</p>
      </Section>

      <Section title="Sites">
        <ul className="site-list">
          {plan.sites.map((site) => (
            <li key={site.index}>
              <button
                className={`site-item ${selected?.index === site.index ? 'is-active' : ''}`}
                onClick={() => setSelected(selected?.index === site.index ? null : site)}
                data-testid={`site-${site.label}`}
              >
                <span
                  className="site-item__badge mono"
                  style={{ borderColor: PRIORITY_COLOR[site.priority], color: PRIORITY_COLOR[site.priority] }}
                >
                  {site.label}
                </span>
                <span className="site-item__main">
                  <span className="site-item__coords mono">
                    {latLon(site.lat, site.lon)}
                  </span>
                  <span className="site-item__meta">
                    {num(site.agb_pred_mg_ha, 0)} ± {num(site.agb_sd_mg_ha, 0)} Mg/ha
                  </span>
                </span>
                <span
                  className="site-item__priority"
                  style={{ color: PRIORITY_COLOR[site.priority] }}
                >
                  {site.priority}
                </span>
              </button>
            </li>
          ))}
        </ul>
      </Section>

      {selected && <SiteDetail site={selected} />}

      <Section title="Download">
        <div className="download-list">
          <DownloadRow
            label="Field plan (GeoJSON)"
            desc="Numbered waypoints with priority, prediction and reason"
            href={exportUrl.fieldPlanGeoJson(analysis.aoi_id, year)}
            testId="download-fieldplan-geojson"
          />
          <DownloadRow
            label="Field plan (CSV)"
            desc="Same sites as a spreadsheet for a handheld GPS"
            href={exportUrl.fieldPlanCsv(analysis.aoi_id, year)}
            testId="download-fieldplan-csv"
          />
        </div>
      </Section>
    </>
  );
}

function SiteDetail({ site }: { site: FieldSite }) {
  return (
    <Section title={`Field site ${site.label}`}>
      <div className="site-detail" data-testid="site-detail">
        <div className="site-detail__priority" style={{ color: PRIORITY_COLOR[site.priority] }}>
          {site.priority} PRIORITY
        </div>

        <StatRow label="Latitude" value={num(site.lat, 6)} />
        <StatRow label="Longitude" value={num(site.lon, 6)} />
        <StatRow label="Predicted biomass" value={`${num(site.agb_pred_mg_ha, 0)} Mg/ha`} />
        <StatRow
          label="90% interval"
          value={`${num(site.agb_p05_mg_ha, 0)} – ${num(site.agb_p95_mg_ha, 0)}`}
        />
        <StatRow label="Uncertainty (SD)" value={`± ${num(site.agb_sd_mg_ha, 0)} Mg/ha`} />
        <StatRow label="Confidence here" value={score(site.confidence, 0)} />
        <StatRow label="Elevation" value={`${num(site.elevation_m, 0)} m`} />
        <StatRow label="Slope" value={`${num(site.slope_deg, 1)}°`} />

        <div style={{ marginTop: 'var(--s3)' }}>
          <Note tone="warn" title="Why this site">
            {site.reason}
          </Note>
        </div>

        <div style={{ marginTop: 'var(--s2)' }}>
          <div className="eyebrow" style={{ marginBottom: 'var(--s1)' }}>
            Expected value of a visit
          </div>
          <div className="site-detail__value mono">
            {pct(site.expected_variance_reduction_pct, 2)}
          </div>
          <Meter
            value={site.expected_variance_reduction_pct}
            max={5}
            color={PRIORITY_COLOR[site.priority]}
            label={`Resolves ${site.expected_variance_reduction_pct.toFixed(2)}% of total variance`}
          />
          <p className="hint" style={{ marginTop: 'var(--s1)' }}>
            Share of the area's total biomass variance inside this site's
            correlation neighbourhood.
          </p>
        </div>

        <div style={{ marginTop: 'var(--s3)' }}>
          <Note tone="info" title="Access">
            {site.access_note}
          </Note>
        </div>
      </div>
    </Section>
  );
}

export function DownloadRow({
  label,
  desc,
  href,
  testId,
}: {
  label: string;
  desc: string;
  href: string;
  testId?: string;
}) {
  return (
    <div className="download-item">
      <span className="download-item__main">
        <span className="download-item__label">{label}</span>
        <span className="download-item__desc">{desc}</span>
      </span>
      <a className="btn btn--sm" href={href} download data-testid={testId}>
        Download
      </a>
    </div>
  );
}

export { integer };
