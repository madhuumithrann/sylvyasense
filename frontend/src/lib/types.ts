/* API response types — mirrors the FastAPI contract in backend/app/api. */

export type DataMode = 'LIVE_EARTH_ENGINE' | 'SANDBOX_SIMULATION' | 'UNAVAILABLE';

export type SourceStatus = 'AVAILABLE' | 'PARTIAL' | 'UNAVAILABLE' | 'NOT_CONFIGURED';

export type Verdict = 'READY' | 'PARTIAL_DATA' | 'INSUFFICIENT_DATA';

export type ConfidenceClass =
  | 'HIGH_CONFIDENCE'
  | 'SURVEY_RECOMMENDED'
  | 'INSUFFICIENT_DATA';

export type ChangeVerdict =
  | 'SIGNIFICANT_CHANGE'
  | 'NO_SIGNIFICANT_CHANGE'
  | 'INSUFFICIENT_DATA';

export type JobStatus = 'QUEUED' | 'RUNNING' | 'COMPLETE' | 'FAILED';

export type StepState = 'PENDING' | 'ACTIVE' | 'DONE' | 'SKIPPED' | 'FAILED';

/** The error contract. Every failure the UI can receive has this shape. */
export interface ApiError {
  code: string;
  title: string;
  detail: string;
  causes: string[];
  next_step: string | null;
  retryable: boolean;
  technical: string | null;
}

export interface Geometry {
  type: 'Polygon' | 'MultiPolygon';
  coordinates: number[][][] | number[][][][];
}

export interface ProviderStatus {
  active: string;
  mode: DataMode;
  ready: boolean;
  simulated: boolean;
  indicator: string;
  headline: string;
  detail: Record<string, unknown> & {
    label?: string;
    warning?: string;
    next_step?: string;
    project?: string | null;
    collections?: Record<string, string>;
    forward_models?: Record<string, string>;
  };
  earth_engine: {
    ready: boolean;
    reason: string;
    configured: boolean;
    setup_doc: string;
    next_step: string | null;
  };
  fallback_reason: string | null;
}

export interface SystemStatus {
  app: string;
  version: string;
  server_time: string;
  provider: ProviderStatus;
  limits: {
    max_aoi_km2: number;
    min_aoi_km2: number;
    grid_max_cells: number;
    min_gedi_samples: number;
  };
  model_version: string;
  available_years: number[];
}

export interface LayerSpec {
  key: string;
  label: string;
  group: string;
  kind: 'continuous' | 'categorical' | 'rgb';
  ramp: string | null;
  description: string;
  source: string;
  requires: 'analysis' | 'change';
  default_opacity: number;
}

export interface LayerCatalogue {
  groups: { name: string; layers: LayerSpec[] }[];
}

export interface RampLegend {
  key: string;
  label: string;
  unit?: string;
  vmin?: number;
  vmax?: number;
  stops?: string[];
  description?: string;
  categorical?: boolean;
  categories?: { code: number; color: string; label: string }[];
}

export interface SystemLayers {
  catalogue: LayerCatalogue;
  legends: Record<string, RampLegend>;
  tile_size: number;
}

export interface Place {
  name: string;
  country: string;
  biome: string;
  lon: number;
  lat: number;
  span_deg: number;
  bounds: [number, number, number, number];
  demo: boolean;
  note: string;
  geometry?: Geometry;
}

export interface AoiValidation {
  aoi_id: string;
  area_km2: number;
  area_ha: number;
  perimeter_km: number;
  centroid: { lon: number; lat: number };
  bounds: [number, number, number, number];
  measurement: string;
  analysed_years: number[];
}

export interface SourceAvailability {
  key: string;
  label: string;
  status: SourceStatus;
  scene_count: number;
  first_date: string | null;
  last_date: string | null;
  detail: string;
  metrics: Record<string, unknown>;
}

export interface AuditResult {
  aoi_id: string;
  area_km2: number;
  area_ha: number;
  perimeter_km: number;
  centroid: { lon: number; lat: number };
  bounds: [number, number, number, number];
  forest_cover_pct: number | null;
  cloud_cover_pct: number | null;
  sources: SourceAvailability[];
  mode: DataMode;
  window: { start: string; end: string };
  verdict: Verdict;
  verdict_detail: string;
  generated_at: string;
  year: number;
  provider: ProviderStatus;
  analysed_years: number[];
}

export interface JobStep {
  key: string;
  label: string;
  state: StepState;
  note: string;
  started_at: string | null;
  finished_at: string | null;
}

export interface Job {
  job_id: string;
  kind: string;
  status: JobStatus;
  steps: JobStep[];
  steps_completed: number;
  steps_total: number;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  error: ApiError | null;
  result: Record<string, unknown> | null;
  context: Record<string, unknown>;
}

export interface ModelProvenance {
  version: string;
  calibration: 'gedi-local' | 'regional-default';
  algorithm: string;
  features: string[];
  n_training: number;
  training_source: string;
  cv_r2: number | null;
  cv_rmse: number | null;
  cv_folds: number | null;
  cv_scheme: string | null;
  feature_importance: Record<string, number>;
  saturation_note: string | null;
  caveats: string[];
  uncalibrated: boolean;
}

export interface Provenance {
  mode: DataMode;
  simulated: boolean;
  window: { start: string; end: string };
  grid: { rows: number; cols: number; cell_size_m: number; cell_area_ha: number };
  optical: {
    collection: string;
    scenes: number;
    first_date: string;
    last_date: string;
    cloud_cover_pct: number;
    resolution_m: number;
  } | null;
  radar: {
    collection: string;
    scenes: number;
    first_date: string;
    last_date: string;
    orbit: string;
    resolution_m: number;
  } | null;
  gedi: {
    collection: string;
    footprints: number;
    first_date: string | null;
    last_date: string | null;
  } | null;
  terrain: { collection: string } | null;
  landcover: { collection: string; year: number } | null;
  model: ModelProvenance;
  created_at: string;
}

export interface AnalysisSummary {
  aoi_id: string;
  year: number;
  area_km2: number;
  area_ha: number;
  mode: DataMode;
  simulated: boolean;
  canopy: { cover_pct: number; method: string };
  biomass: {
    mean_mg_ha: number;
    p05_mg_ha: number;
    p95_mg_ha: number;
    total_stock_mg: number;
    effective_n: number;
    model: ModelProvenance;
  };
  carbon: {
    mean_tc_ha: number;
    p05_tc_ha: number;
    p95_tc_ha: number;
    total_tc: number;
  };
  co2e: {
    mean_tco2e_ha: number;
    p05_tco2e_ha: number;
    p95_tco2e_ha: number;
    total_tco2e: number;
  };
  belowground: { mean_tc_ha: number; root_to_shoot: number; note: string };
  constants: {
    carbon_fraction: number;
    carbon_fraction_source: string;
    co2e_per_carbon: number;
    co2e_source: string;
  };
  confidence: {
    mean_score: number;
    class_fractions: Record<ConfidenceClass, number>;
    weights: Record<string, number>;
    thresholds: { high: number; survey: number };
  };
  field_plan: { count: number; total_expected_reduction_pct: number };
  provenance: Provenance;
  created_at: string;
  audit: AuditResult;
  geometry: Geometry;
  bounds: [number, number, number, number];
  layers: LayerCatalogue;
  analysed_years: number[];
}

export interface FieldSite {
  index: number;
  label: string;
  lon: number;
  lat: number;
  priority: 'HIGH' | 'MEDIUM' | 'LOW';
  priority_score: number;
  agb_pred_mg_ha: number;
  agb_sd_mg_ha: number;
  agb_p05_mg_ha: number;
  agb_p95_mg_ha: number;
  confidence: number;
  reason: string;
  expected_variance_reduction_pct: number;
  elevation_m: number | null;
  slope_deg: number | null;
  access_note: string;
}

export interface FieldPlan {
  sites: FieldSite[];
  count: number;
  requested: number;
  method: string;
  min_separation_m: number;
  correlation_range_m: number;
  total_expected_reduction_pct: number;
  geojson: { type: 'FeatureCollection'; features: unknown[] };
  mode: DataMode;
  simulated: boolean;
}

export interface CellInspection {
  inside_aoi: boolean;
  message?: string;
  lon: number;
  lat: number;
  cell?: { row: number; col: number; size_m: number };
  biomass?: {
    agb_mg_ha: number | null;
    p05_mg_ha: number | null;
    p95_mg_ha: number | null;
    sd_mg_ha: number | null;
  };
  carbon?: { tc_ha: number | null };
  canopy?: { cover_pct: number | null; ndvi: number | null };
  radar?: { vv_db: number | null; vh_db: number | null };
  terrain?: { elevation_m: number | null; slope_deg: number | null };
  confidence?: {
    score: number | null;
    class: ConfidenceClass;
    components: Record<string, number | null>;
    weights: Record<string, number>;
    limiting_factor: string;
    limiting_component: string | null;
  };
  evidence?: {
    gedi_footprints_nearby: number | null;
    clear_observation_pct: number | null;
    radar_available: boolean;
    optical_scenes: number;
    radar_scenes: number;
  };
  model?: ModelProvenance;
  mode?: DataMode;
  simulated?: boolean;
}

export interface ChangeResult {
  year_from: number;
  year_to: number;
  biomass: {
    from_mg_ha: number;
    to_mg_ha: number;
    delta_mg_ha: number;
    delta_p05_mg_ha: number;
    delta_p95_mg_ha: number;
    delta_pct: number | null;
  };
  carbon: {
    from_tc_ha: number;
    to_tc_ha: number;
    delta_tc_ha: number;
    delta_tco2e_ha: number;
  };
  statistics: {
    z_score: number;
    p_value: number;
    z_critical: number;
    significant: boolean;
    test: string;
  };
  areas: {
    significant_loss_ha: number;
    significant_gain_ha: number;
    stable_ha: number;
  };
  total_stock_delta_mg: number;
  verdict: ChangeVerdict;
  verdict_detail: string;
  evidence: {
    cells_compared: number;
    cell_area_ha: number;
    significant_cells: number;
    materiality_floor_mg_ha: number;
    epochs: Record<string, Record<string, unknown>>;
  };
  aoi_id: string;
  mode: DataMode | null;
  simulated: boolean | null;
}

export interface PipelineSteps {
  analysis: { key: string; label: string }[];
  change: { key: string; label: string }[];
  confidence_components: { key: string; label: string; weight: number }[];
}
