import type { TabKey } from '../state/store';
import { useStore } from '../state/store';
import './TabBar.css';

interface TabDef {
  key: TabKey;
  label: string;
  /** Why the tab is unavailable, when it is. */
  requires?: 'aoi' | 'analysis';
}

const TABS: TabDef[] = [
  { key: 'audit', label: 'Audit', requires: 'aoi' },
  { key: 'analysis', label: 'Analysis', requires: 'analysis' },
  { key: 'confidence', label: 'Confidence', requires: 'analysis' },
  { key: 'fieldplan', label: 'Field Plan', requires: 'analysis' },
  { key: 'change', label: 'Change', requires: 'aoi' },
  { key: 'export', label: 'Export', requires: 'analysis' },
];

export function TabBar() {
  const tab = useStore((s) => s.tab);
  const setTab = useStore((s) => s.setTab);
  const setPanelOpen = useStore((s) => s.setPanelOpen);
  const panelOpen = useStore((s) => s.panelOpen);
  const geometry = useStore((s) => s.geometry);
  const analysis = useStore((s) => s.analysis);
  const state = useStore((s) => s.state);
  const aoi = useStore((s) => s.aoi);

  function available(def: TabDef): boolean {
    if (def.requires === 'analysis') return Boolean(analysis);
    if (def.requires === 'aoi') return Boolean(geometry);
    return true;
  }

  function select(key: TabKey) {
    setTab(key);
    if (!panelOpen) setPanelOpen(true);
  }

  return (
    <nav className="tabbar" role="tablist" aria-label="Workspace sections">
      <div className="tabbar__tabs">
        {TABS.map((def) => {
          const enabled = available(def);
          return (
            <button
              key={def.key}
              role="tab"
              aria-selected={tab === def.key}
              aria-controls="side-panel"
              className={`tabbar__tab ${tab === def.key ? 'is-active' : ''}`}
              disabled={!enabled}
              onClick={() => select(def.key)}
              data-testid={`tab-${def.key}`}
              title={
                enabled
                  ? undefined
                  : def.requires === 'analysis'
                    ? 'Run an analysis first'
                    : 'Select an area first'
              }
            >
              {def.label}
            </button>
          );
        })}
      </div>

      <div className="tabbar__status">
        {aoi && (
          <span className="tabbar__meta mono" title="Area of interest identifier">
            AOI {aoi.aoi_id}
          </span>
        )}
        <span className={`tabbar__state tabbar__state--${stateTone(state)}`}>
          <span className="status-dot" />
          {label(state)}
        </span>
      </div>
    </nav>
  );
}

function stateTone(state: string): string {
  if (state === 'ERROR' || state === 'INSUFFICIENT_DATA') return 'bad';
  if (state === 'PARTIAL_DATA') return 'warn';
  if (state === 'ANALYZING' || state === 'AUDITING') return 'busy';
  if (state === 'ANALYSIS_COMPLETE' || state === 'AUDIT_COMPLETE') return 'ok';
  return 'idle';
}

function label(state: string): string {
  return state.replace(/_/g, ' ');
}
