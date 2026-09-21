import type { JobStep } from '../lib/types';
import { useStore } from '../state/store';
import './AnalysisDrawer.css';

/**
 * Live pipeline progress.
 *
 * The step list mirrors backend state exactly: a step is only ticked when the
 * backend reports it done, and a step it skipped says so with the reason.
 * Progress is expressed as completed steps out of total steps — a real count —
 * with an indeterminate bar for the step currently running, because the
 * backend cannot report fractional progress within a step and inventing one
 * would be a lie.
 */
export function AnalysisDrawer() {
  const job = useStore((s) => s.job);
  const open = useStore((s) => s.drawerOpen);
  const setOpen = useStore((s) => s.setDrawerOpen);

  if (!open || !job) return null;

  const running = job.status === 'RUNNING' || job.status === 'QUEUED';
  const heading = job.kind === 'change' ? 'Comparing epochs' : 'Analysing forest';

  return (
    <aside className="drawer panel" role="status" aria-live="polite" data-testid="analysis-drawer">
      <header className="drawer__head">
        <div className="drawer__title">
          <span className="eyebrow">SylvaSense analysis</span>
          <span className="drawer__heading">
            {job.status === 'COMPLETE'
              ? 'Analysis complete'
              : job.status === 'FAILED'
                ? 'Analysis stopped'
                : heading}
          </span>
        </div>
        <button
          className="btn btn--sm btn--ghost"
          onClick={() => setOpen(false)}
          aria-label="Hide progress"
        >
          ✕
        </button>
      </header>

      <div className="drawer__progress">
        <div className="drawer__counter mono">
          {job.steps_completed} / {job.steps_total} steps
        </div>
        {running && <div className="indeterminate" />}
      </div>

      <ol className="drawer__steps">
        {job.steps.map((step) => (
          <Step key={step.key} step={step} />
        ))}
      </ol>

      {job.status === 'FAILED' && job.error && (
        <div className="note note--danger drawer__error">
          <div className="note__title">{job.error.title}</div>
          <div className="note__body">{job.error.detail}</div>
        </div>
      )}
    </aside>
  );
}

function Step({ step }: { step: JobStep }) {
  return (
    <li className={`drawer-step drawer-step--${step.state.toLowerCase()}`}>
      <span className="drawer-step__marker" aria-hidden="true">
        {step.state === 'DONE' && <CheckIcon />}
        {step.state === 'SKIPPED' && <SkipIcon />}
        {step.state === 'FAILED' && <CrossIcon />}
        {step.state === 'ACTIVE' && <span className="drawer-step__spinner" />}
        {step.state === 'PENDING' && <span className="drawer-step__dot" />}
      </span>
      <span className="drawer-step__main">
        <span className="drawer-step__label">{step.label}</span>
        {step.note && <span className="drawer-step__note">{step.note}</span>}
      </span>
    </li>
  );
}

function CheckIcon() {
  return (
    <svg width="11" height="11" viewBox="0 0 12 12" fill="none">
      <path
        d="m2.5 6.2 2.3 2.3 4.7-5"
        stroke="currentColor"
        strokeWidth="1.7"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

function SkipIcon() {
  return (
    <svg width="11" height="11" viewBox="0 0 12 12" fill="none">
      <path d="M2.6 6h6.8" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" />
    </svg>
  );
}

function CrossIcon() {
  return (
    <svg width="11" height="11" viewBox="0 0 12 12" fill="none">
      <path
        d="m3.2 3.2 5.6 5.6M8.8 3.2 3.2 8.8"
        stroke="currentColor"
        strokeWidth="1.7"
        strokeLinecap="round"
      />
    </svg>
  );
}
