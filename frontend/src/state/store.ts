/**
 * Application state.
 *
 * The state machine is explicit because the interface has to distinguish
 * "nothing selected" from "audited but not analysed" from "analysed with
 * partial inputs" — and each of those shows a different thing.
 */

import { create } from 'zustand';

import type {
  AnalysisSummary,
  ApiError,
  AoiValidation,
  AuditResult,
  CellInspection,
  ChangeResult,
  FieldPlan,
  FieldSite,
  Geometry,
  Job,
} from '../lib/types';

export type AppState =
  | 'IDLE'
  | 'AOI_SELECTED'
  | 'AUDITING'
  | 'AUDIT_COMPLETE'
  | 'PARTIAL_DATA'
  | 'INSUFFICIENT_DATA'
  | 'ANALYZING'
  | 'ANALYSIS_COMPLETE'
  | 'ERROR';

export type DrawMode = 'idle' | 'drawing' | 'editing';

export type TabKey =
  | 'audit'
  | 'analysis'
  | 'confidence'
  | 'fieldplan'
  | 'change'
  | 'export';

const CURRENT_YEAR = new Date().getFullYear();

interface State {
  /* --- Area of interest --- */
  geometry: Geometry | null;
  aoi: AoiValidation | null;
  drawMode: DrawMode;
  aoiLabel: string | null;

  /* --- Workflow --- */
  state: AppState;
  error: ApiError | null;
  job: Job | null;
  drawerOpen: boolean;

  /* --- Results --- */
  audit: AuditResult | null;
  analysis: AnalysisSummary | null;
  fieldPlan: FieldPlan | null;
  change: ChangeResult | null;

  /* --- Epochs --- */
  year: number;
  compareYear: number;

  /* --- Map --- */
  activeLayers: string[];
  layerOpacity: number;
  showFieldSites: boolean;
  selectedCell: CellInspection | null;
  selectedSite: FieldSite | null;
  inspectMode: boolean;

  /* --- UI --- */
  tab: TabKey;
  layersOpen: boolean;
  panelOpen: boolean;
}

interface Actions {
  setGeometry: (geometry: Geometry | null, label?: string | null) => void;
  setAoi: (aoi: AoiValidation | null) => void;
  setDrawMode: (mode: DrawMode) => void;
  clearAoi: () => void;

  setState: (state: AppState) => void;
  setError: (error: ApiError | null) => void;
  setJob: (job: Job | null) => void;
  setDrawerOpen: (open: boolean) => void;

  setAudit: (audit: AuditResult | null) => void;
  setAnalysis: (analysis: AnalysisSummary | null) => void;
  setFieldPlan: (plan: FieldPlan | null) => void;
  setChange: (change: ChangeResult | null) => void;

  setYear: (year: number) => void;
  setCompareYear: (year: number) => void;

  toggleLayer: (key: string) => void;
  setActiveLayers: (keys: string[]) => void;
  setLayerOpacity: (opacity: number) => void;
  setShowFieldSites: (visible: boolean) => void;
  setSelectedCell: (cell: CellInspection | null) => void;
  setSelectedSite: (site: FieldSite | null) => void;
  setInspectMode: (on: boolean) => void;

  setTab: (tab: TabKey) => void;
  setLayersOpen: (open: boolean) => void;
  setPanelOpen: (open: boolean) => void;
}

/** Layers that replace each other rather than stacking. */
const BASE_IMAGERY = new Set(['truecolor', 'falsecolor']);

const initial: State = {
  geometry: null,
  aoi: null,
  drawMode: 'idle',
  aoiLabel: null,

  state: 'IDLE',
  error: null,
  job: null,
  drawerOpen: false,

  audit: null,
  analysis: null,
  fieldPlan: null,
  change: null,

  year: CURRENT_YEAR,
  compareYear: Math.max(CURRENT_YEAR - 4, 2019),

  activeLayers: [],
  layerOpacity: 0.9,
  showFieldSites: false,
  selectedCell: null,
  selectedSite: null,
  inspectMode: false,

  tab: 'audit',
  layersOpen: true,
  panelOpen: true,
};

export const useStore = create<State & Actions>((set, get) => ({
  ...initial,

  setGeometry: (geometry, label = null) =>
    set({
      geometry,
      aoiLabel: label,
      // A new area invalidates everything derived from the previous one.
      audit: null,
      analysis: null,
      fieldPlan: null,
      change: null,
      selectedCell: null,
      selectedSite: null,
      activeLayers: [],
      showFieldSites: false,
      error: null,
      job: null,
      state: geometry ? 'AOI_SELECTED' : 'IDLE',
      tab: 'audit',
    }),

  setAoi: (aoi) => set({ aoi }),
  setDrawMode: (drawMode) => set({ drawMode }),

  clearAoi: () => set({ ...initial, year: get().year, compareYear: get().compareYear }),

  setState: (state) => set({ state }),
  setError: (error) => set({ error, state: error ? 'ERROR' : get().state }),
  setJob: (job) => set({ job }),
  setDrawerOpen: (drawerOpen) => set({ drawerOpen }),

  setAudit: (audit) =>
    set({
      audit,
      state: !audit
        ? 'AOI_SELECTED'
        : audit.verdict === 'INSUFFICIENT_DATA'
          ? 'INSUFFICIENT_DATA'
          : audit.verdict === 'PARTIAL_DATA'
            ? 'PARTIAL_DATA'
            : 'AUDIT_COMPLETE',
    }),

  setAnalysis: (analysis) =>
    set({
      analysis,
      state: analysis ? 'ANALYSIS_COMPLETE' : get().state,
      // Show biomass by default the moment an analysis lands — the result
      // should be visible on the map without a further click.
      activeLayers: analysis && get().activeLayers.length === 0
        ? ['truecolor', 'agb']
        : get().activeLayers,
    }),

  setFieldPlan: (fieldPlan) => set({ fieldPlan }),
  setChange: (change) => set({ change }),

  setYear: (year) =>
    set({
      year,
      analysis: null,
      fieldPlan: null,
      change: null,
      selectedCell: null,
      selectedSite: null,
      showFieldSites: false,
      activeLayers: [],
      state: get().geometry ? 'AOI_SELECTED' : 'IDLE',
    }),

  setCompareYear: (compareYear) => set({ compareYear, change: null }),

  toggleLayer: (key) => {
    const active = get().activeLayers;
    if (active.includes(key)) {
      set({ activeLayers: active.filter((k) => k !== key) });
      return;
    }
    // Imagery composites are mutually exclusive: stacking two opaque RGB
    // rasters just hides one of them.
    const next = BASE_IMAGERY.has(key)
      ? active.filter((k) => !BASE_IMAGERY.has(k))
      : active;
    set({ activeLayers: [...next, key] });
  },

  setActiveLayers: (activeLayers) => set({ activeLayers }),
  setLayerOpacity: (layerOpacity) => set({ layerOpacity }),
  setShowFieldSites: (showFieldSites) => set({ showFieldSites }),
  setSelectedCell: (selectedCell) => set({ selectedCell }),
  setSelectedSite: (selectedSite) => set({ selectedSite }),
  setInspectMode: (inspectMode) => set({ inspectMode }),

  setTab: (tab) => set({ tab }),
  setLayersOpen: (layersOpen) => set({ layersOpen }),
  setPanelOpen: (panelOpen) => set({ panelOpen }),
}));

/** Human-readable label for the current workflow state. */
export const STATE_LABEL: Record<AppState, string> = {
  IDLE: 'Select a forest area',
  AOI_SELECTED: 'Area selected',
  AUDITING: 'Auditing',
  AUDIT_COMPLETE: 'Audit complete',
  PARTIAL_DATA: 'Partial data',
  INSUFFICIENT_DATA: 'Insufficient data',
  ANALYZING: 'Analysing forest',
  ANALYSIS_COMPLETE: 'Analysis complete',
  ERROR: 'Error',
};
