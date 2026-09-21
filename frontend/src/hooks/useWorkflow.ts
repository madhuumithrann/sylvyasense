/**
 * Workflow actions.
 *
 * Each action drives a real backend call and moves the explicit state machine.
 * Job progress is polled and mirrored into the store exactly as the backend
 * reports it — the UI never advances a step the backend has not finished.
 */

import { useCallback, useRef } from 'react';

import { SylvaSenseError, api } from '../lib/api';
import type { ApiError, Job } from '../lib/types';
import { useStore } from '../state/store';

const POLL_INTERVAL_MS = 400;
const POLL_TIMEOUT_MS = 240_000;

function toApiError(error: unknown): ApiError {
  if (error instanceof SylvaSenseError) return error.api;
  return {
    code: 'UNEXPECTED_ERROR',
    title: 'SOMETHING WENT WRONG',
    detail: 'An unexpected problem stopped this step.',
    causes: [],
    next_step: 'Retry. If it keeps happening, reload the page.',
    retryable: true,
    technical: String(error),
  };
}

export function useWorkflow() {
  // Guards against a stale poll loop writing over a newer run.
  const runToken = useRef(0);

  const pollJob = useCallback(async (jobId: string, token: number): Promise<Job> => {
    const deadline = Date.now() + POLL_TIMEOUT_MS;
    for (;;) {
      const job = await api.job(jobId);
      if (token === runToken.current) useStore.getState().setJob(job);
      if (job.status === 'COMPLETE' || job.status === 'FAILED') return job;
      if (Date.now() > deadline) {
        throw new SylvaSenseError(
          {
            code: 'ANALYSIS_TIMED_OUT',
            title: 'THE ANALYSIS TOOK TOO LONG',
            detail:
              'The backend did not finish this analysis within the time the page waits for it.',
            causes: [
              'a very large area of interest',
              'a slow or rate-limited Earth Engine request',
            ],
            next_step: 'Try a smaller area, then run the analysis again.',
            retryable: true,
            technical: `job ${jobId}`,
          },
          504,
        );
      }
      await new Promise((resolve) => setTimeout(resolve, POLL_INTERVAL_MS));
    }
  }, []);

  /** Validate the drawn geometry and record its measured properties. */
  const validate = useCallback(async () => {
    const { geometry, setAoi, setError } = useStore.getState();
    if (!geometry) return null;
    try {
      const aoi = await api.validateAoi(geometry);
      setAoi(aoi);
      setError(null);
      return aoi;
    } catch (error) {
      setAoi(null);
      setError(toApiError(error));
      return null;
    }
  }, []);

  /** Check what data exists for this area before spending an analysis on it. */
  const runAudit = useCallback(async () => {
    const store = useStore.getState();
    const { geometry, year } = store;
    if (!geometry) return;

    store.setError(null);
    store.setState('AUDITING');
    try {
      const audit = await api.audit(geometry, year);
      useStore.getState().setAudit(audit);
      useStore.getState().setTab('audit');
    } catch (error) {
      useStore.getState().setError(toApiError(error));
    }
  }, []);

  /** Run the full analysis pipeline as a polled backend job. */
  const runAnalysis = useCallback(async () => {
    const store = useStore.getState();
    const { geometry, year } = store;
    if (!geometry) return;

    const token = ++runToken.current;
    store.setError(null);
    store.setJob(null);
    store.setState('ANALYZING');
    store.setDrawerOpen(true);

    try {
      const started = await api.startAnalysis(geometry, year);
      if (token !== runToken.current) return;
      useStore.getState().setJob(started);

      const finished =
        started.status === 'COMPLETE' ? started : await pollJob(started.job_id, token);
      if (token !== runToken.current) return;

      if (finished.status === 'FAILED' || !finished.result) {
        useStore
          .getState()
          .setError(finished.error ?? toApiError('analysis job failed'));
        return;
      }

      const aoiId = String(finished.result.aoi_id);
      const [summary, plan] = await Promise.all([
        api.analysis(aoiId, year),
        api.fieldPlan(aoiId, year),
      ]);
      if (token !== runToken.current) return;

      const next = useStore.getState();
      next.setAnalysis(summary);
      next.setFieldPlan(plan);
      next.setTab('analysis');
      // Leave the drawer up briefly so the completed step list is readable.
      setTimeout(() => {
        if (token === runToken.current) useStore.getState().setDrawerOpen(false);
      }, 1100);
    } catch (error) {
      if (token !== runToken.current) return;
      useStore.getState().setError(toApiError(error));
    }
  }, [pollJob]);

  /** Compare two epochs; each missing epoch is analysed as part of the job. */
  const runChange = useCallback(async () => {
    const store = useStore.getState();
    const { geometry, year, compareYear } = store;
    if (!geometry || year === compareYear) return;

    const token = ++runToken.current;
    store.setError(null);
    store.setJob(null);
    store.setDrawerOpen(true);

    try {
      const started = await api.startChange(geometry, compareYear, year);
      if (token !== runToken.current) return;
      useStore.getState().setJob(started);

      const finished = await pollJob(started.job_id, token);
      if (token !== runToken.current) return;

      if (finished.status === 'FAILED' || !finished.result) {
        useStore.getState().setError(finished.error ?? toApiError('change job failed'));
        return;
      }

      const aoiId = String(finished.result.aoi_id);
      const change = await api.change(aoiId, compareYear, year);
      if (token !== runToken.current) return;

      const next = useStore.getState();
      next.setChange(change);
      next.setTab('change');

      // A change run also produces (or reuses) the current epoch's analysis;
      // pull it in so the rest of the interface is populated too.
      if (!next.analysis) {
        const [summary, plan] = await Promise.all([
          api.analysis(aoiId, year),
          api.fieldPlan(aoiId, year),
        ]);
        if (token !== runToken.current) return;
        useStore.getState().setAnalysis(summary);
        useStore.getState().setFieldPlan(plan);
      }

      setTimeout(() => {
        if (token === runToken.current) useStore.getState().setDrawerOpen(false);
      }, 1100);
    } catch (error) {
      if (token !== runToken.current) return;
      useStore.getState().setError(toApiError(error));
    }
  }, [pollJob]);

  return { validate, runAudit, runAnalysis, runChange };
}
