/**
 * Typed API client.
 *
 * Every non-2xx response is converted into an ApiError carrying the backend's
 * user-readable error contract, so components render the same explanation the
 * backend authored instead of inventing their own.
 */

import type {
  AnalysisSummary,
  ApiError,
  AoiValidation,
  AuditResult,
  CellInspection,
  ChangeResult,
  FieldPlan,
  Geometry,
  Job,
  PipelineSteps,
  Place,
  SystemLayers,
  SystemStatus,
} from './types';

export class SylvaSenseError extends Error {
  readonly api: ApiError;
  readonly status: number;

  constructor(api: ApiError, status: number) {
    super(api.title);
    this.name = 'SylvaSenseError';
    this.api = api;
    this.status = status;
  }
}

const NETWORK_ERROR: ApiError = {
  code: 'BACKEND_UNREACHABLE',
  title: 'CANNOT REACH THE SYLVASENSE BACKEND',
  detail:
    'The analysis service did not respond. Nothing on this page can be computed until it is running.',
  causes: [
    'the backend process is not running',
    'it is listening on a different port',
    'a network or proxy problem between browser and backend',
  ],
  next_step: 'Start the backend with `python run.py` in backend/, then retry.',
  retryable: true,
  technical: null,
};

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(path, {
      ...init,
      headers: {
        Accept: 'application/json',
        ...(init?.body ? { 'Content-Type': 'application/json' } : {}),
        ...init?.headers,
      },
    });
  } catch (cause) {
    throw new SylvaSenseError(
      { ...NETWORK_ERROR, technical: String(cause) },
      0,
    );
  }

  if (!response.ok) {
    let api: ApiError;
    try {
      const body = (await response.json()) as { error?: ApiError };
      api = body.error ?? {
        code: 'UNEXPECTED_RESPONSE',
        title: 'UNEXPECTED RESPONSE FROM THE BACKEND',
        detail: `The backend replied with status ${response.status}.`,
        causes: ['a version mismatch between page and backend'],
        next_step: 'Reload the page. If it persists, restart the backend.',
        retryable: true,
        technical: null,
      };
    } catch {
      api = {
        code: 'UNREADABLE_RESPONSE',
        title: 'THE BACKEND REPLY COULD NOT BE READ',
        detail: `Status ${response.status} with a body that was not JSON.`,
        causes: ['a proxy returned an error page instead of the API'],
        next_step: 'Check that the dev proxy points at the backend, then reload.',
        retryable: true,
        technical: null,
      };
    }
    throw new SylvaSenseError(api, response.status);
  }

  return (await response.json()) as T;
}

const post = <T>(path: string, body: unknown) =>
  request<T>(path, { method: 'POST', body: JSON.stringify(body) });

export const api = {
  status: () => request<SystemStatus>('/api/v1/system/status'),
  layers: () => request<SystemLayers>('/api/v1/system/layers'),
  steps: () => request<PipelineSteps>('/api/v1/system/steps'),

  searchPlaces: (q: string) =>
    request<{ query: string; results: Place[] }>(
      `/api/v1/places?q=${encodeURIComponent(q)}&limit=8`,
    ),
  demoPlaces: () => request<{ results: Place[] }>('/api/v1/places/demo'),

  validateAoi: (geometry: Geometry) =>
    post<AoiValidation>('/api/v1/aoi/validate', { geometry }),

  audit: (geometry: Geometry, year: number) =>
    post<AuditResult>('/api/v1/audit', { geometry, year }),

  startAnalysis: (geometry: Geometry, year: number) =>
    post<Job>('/api/v1/analysis', { geometry, year }),

  startChange: (geometry: Geometry, yearFrom: number, yearTo: number) =>
    post<Job>('/api/v1/change', {
      geometry,
      year_from: yearFrom,
      year_to: yearTo,
    }),

  job: (jobId: string) => request<Job>(`/api/v1/jobs/${jobId}`),

  analysis: (aoiId: string, year: number) =>
    request<AnalysisSummary>(`/api/v1/analysis/${aoiId}/${year}`),

  fieldPlan: (aoiId: string, year: number) =>
    request<FieldPlan>(`/api/v1/analysis/${aoiId}/${year}/fieldplan`),

  inspect: (aoiId: string, year: number, lon: number, lat: number) =>
    request<CellInspection>(
      `/api/v1/analysis/${aoiId}/${year}/inspect?lon=${lon}&lat=${lat}`,
    ),

  change: (aoiId: string, yearFrom: number, yearTo: number) =>
    request<ChangeResult>(`/api/v1/change/${aoiId}/${yearFrom}/${yearTo}`),
};

/** XYZ template for an analysis layer, consumed directly by MapLibre. */
export function tileUrl(
  aoiId: string,
  year: number,
  layer: string,
  opacity = 0.9,
): string {
  const origin = window.location.origin;
  return `${origin}/api/v1/tiles/${aoiId}/${year}/${layer}/{z}/{x}/{y}.png?opacity=${opacity}`;
}

export function changeTileUrl(
  aoiId: string,
  yearFrom: number,
  yearTo: number,
  layer: string,
  opacity = 0.9,
): string {
  const origin = window.location.origin;
  return `${origin}/api/v1/tiles/change/${aoiId}/${yearFrom}/${yearTo}/${layer}/{z}/{x}/{y}.png?opacity=${opacity}`;
}

export const exportUrl = {
  analysisGeoJson: (aoiId: string, year: number) =>
    `/api/v1/export/${aoiId}/${year}/analysis.geojson`,
  analysisCsv: (aoiId: string, year: number) =>
    `/api/v1/export/${aoiId}/${year}/analysis.csv`,
  fieldPlanGeoJson: (aoiId: string, year: number) =>
    `/api/v1/export/${aoiId}/${year}/fieldplan.geojson`,
  fieldPlanCsv: (aoiId: string, year: number) =>
    `/api/v1/export/${aoiId}/${year}/fieldplan.csv`,
  dossier: (aoiId: string, year: number, changeFrom?: number) =>
    `/api/v1/export/${aoiId}/${year}/dossier.pdf` +
    (changeFrom ? `?change_from=${changeFrom}` : ''),
  changeGeoJson: (aoiId: string, yearFrom: number, yearTo: number) =>
    `/api/v1/export/${aoiId}/${yearFrom}/${yearTo}/change.geojson`,
};
