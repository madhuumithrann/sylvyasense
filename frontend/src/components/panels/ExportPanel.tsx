import { exportUrl } from '../../lib/api';
import { date, integer } from '../../lib/format';
import { useStore } from '../../state/store';
import { EmptyState, Note, Section, StatRow } from '../ui';
import { DownloadRow } from './FieldPlanPanel';

/**
 * Everything that leaves SylvaSense carries its provenance, including — in the
 * first line of every file and on the first page of the dossier — whether the
 * run was a sandbox simulation.
 */
export function ExportPanel() {
  const analysis = useStore((s) => s.analysis);
  const change = useStore((s) => s.change);
  const year = useStore((s) => s.year);
  const compareYear = useStore((s) => s.compareYear);

  if (!analysis) {
    return (
      <EmptyState title="Nothing to export yet">
        Run an analysis and its results become downloadable here as GeoJSON, CSV and
        a PDF audit dossier.
      </EmptyState>
    );
  }

  const aoiId = analysis.aoi_id;

  return (
    <>
      {analysis.simulated && (
        <Note tone="sim" title="Exports are labelled">
          This run is a sandbox simulation. Every file below states that in its
          metadata, and the dossier carries it on the first page, so a downloaded
          artifact cannot be mistaken for an observation.
        </Note>
      )}

      <Section title="Analysis">
        <div className="download-list">
          <DownloadRow
            label="Audit dossier (PDF)"
            desc="Self-contained record: inputs, model, skill, confidence, field plan, caveats and citations"
            href={exportUrl.dossier(aoiId, year, change ? compareYear : undefined)}
            testId="download-dossier"
          />
          <DownloadRow
            label="Analysis (GeoJSON)"
            desc="AOI, per-cell polygons with biomass, carbon and confidence, and survey sites"
            href={exportUrl.analysisGeoJson(aoiId, year)}
            testId="download-geojson"
          />
          <DownloadRow
            label="Analysis cells (CSV)"
            desc="Per-cell table with a provenance header"
            href={exportUrl.analysisCsv(aoiId, year)}
            testId="download-csv"
          />
        </div>
      </Section>

      <Section title="Field plan">
        <div className="download-list">
          <DownloadRow
            label="Field plan (GeoJSON)"
            desc="Numbered waypoints with priority and reason"
            href={exportUrl.fieldPlanGeoJson(aoiId, year)}
            testId="download-fieldplan-geojson-export"
          />
          <DownloadRow
            label="Field plan (CSV)"
            desc="Waypoints for a handheld GPS"
            href={exportUrl.fieldPlanCsv(aoiId, year)}
            testId="download-fieldplan-csv-export"
          />
        </div>
      </Section>

      {change && (
        <Section title="Change">
          <div className="download-list">
            <DownloadRow
              label={`Change ${compareYear} → ${year} (GeoJSON)`}
              desc="Per-cell delta, z-score and significance class"
              href={exportUrl.changeGeoJson(aoiId, compareYear, year)}
              testId="download-change-geojson"
            />
          </div>
        </Section>
      )}

      <Section title="What is in these files">
        <StatRow label="AOI" value={aoiId} />
        <StatRow label="Epoch" value={String(year)} />
        <StatRow label="Data mode" value={analysis.provenance.mode.replace(/_/g, ' ')} />
        <StatRow label="Model" value={analysis.provenance.model.version} />
        <StatRow label="Calibration" value={analysis.provenance.model.calibration} />
        <StatRow
          label="Analysis cells"
          value={integer(
            analysis.provenance.grid.rows * analysis.provenance.grid.cols,
          )}
        />
        <StatRow label="Created" value={date(analysis.created_at)} />
        <StatRow label="Coordinate system" value="WGS84 (CRS84)" />
      </Section>
    </>
  );
}
