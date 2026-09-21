import type { SystemStatus } from '../lib/types';
import { useAoiSync } from '../hooks/useAoiSync';
import { useStore } from '../state/store';
import { AnalysisPanel } from './panels/AnalysisPanel';
import { AuditPanel } from './panels/AuditPanel';
import { ChangePanel } from './panels/ChangePanel';
import { ConfidencePanel } from './panels/ConfidencePanel';
import { ExportPanel } from './panels/ExportPanel';
import { FieldPlanPanel } from './panels/FieldPlanPanel';
import './SidePanel.css';
import './panels/panels.css';

const TITLES: Record<string, string> = {
  audit: 'Forest audit',
  analysis: 'Forest analysis',
  confidence: 'Confidence',
  fieldplan: 'Field survey plan',
  change: 'Temporal change',
  export: 'Export',
};

export function SidePanel({ status }: { status: SystemStatus | undefined }) {
  // Measuring the drawn area is a side effect of the geometry changing.
  useAoiSync();

  const tab = useStore((s) => s.tab);
  const aoiLabel = useStore((s) => s.aoiLabel);
  const simulated = status?.provider.simulated ?? false;

  return (
    <section
      id="side-panel"
      className="side-panel panel"
      role="tabpanel"
      aria-label={TITLES[tab]}
      data-testid="side-panel"
    >
      <header className="side-panel__head">
        <div className="side-panel__title">
          <h2>{TITLES[tab]}</h2>
          {aoiLabel && <span className="side-panel__aoi truncate">{aoiLabel}</span>}
        </div>
        {simulated && (
          <span className="pill pill--sim" title="These figures come from a forward model, not a satellite">
            <span className="pill__dot" />
            Sandbox
          </span>
        )}
      </header>

      <div className="side-panel__body" data-testid={`panel-${tab}`}>
        {tab === 'audit' && <AuditPanel status={status} />}
        {tab === 'analysis' && <AnalysisPanel />}
        {tab === 'confidence' && <ConfidencePanel />}
        {tab === 'fieldplan' && <FieldPlanPanel />}
        {tab === 'change' && <ChangePanel status={status} />}
        {tab === 'export' && <ExportPanel />}
      </div>
    </section>
  );
}
