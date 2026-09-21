import { useStore } from '../state/store';
import { useWorkflow } from '../hooks/useWorkflow';
import './ErrorSheet.css';
import { useState } from 'react';

/**
 * The error experience.
 *
 * Renders the backend's error contract verbatim: a plain-language title, what
 * it means, the likely causes and the concrete next step. The raw technical
 * detail is available behind a disclosure for whoever needs it, and never
 * shown by default.
 */
export function ErrorSheet() {
  const error = useStore((s) => s.error);
  const setError = useStore((s) => s.setError);
  const state = useStore((s) => s.state);
  const [showDetails, setShowDetails] = useState(false);
  const { runAnalysis, runAudit } = useWorkflow();

  if (!error) return null;

  function dismiss() {
    setShowDetails(false);
    setError(null);
    useStore.getState().setState(useStore.getState().analysis ? 'ANALYSIS_COMPLETE' : 'AOI_SELECTED');
  }

  function retry() {
    setShowDetails(false);
    setError(null);
    if (state === 'AUDITING' || !useStore.getState().audit) void runAudit();
    else void runAnalysis();
  }

  return (
    <div className="error-scrim" role="alertdialog" aria-labelledby="error-title">
      <div className="error-sheet panel" data-testid="error-sheet">
        <div className="error-sheet__icon" aria-hidden="true">
          <svg width="20" height="20" viewBox="0 0 20 20" fill="none">
            <path
              d="M10 6.2v4.6M10 13.6v.2"
              stroke="currentColor"
              strokeWidth="1.8"
              strokeLinecap="round"
            />
            <circle cx="10" cy="10" r="7.6" stroke="currentColor" strokeWidth="1.5" />
          </svg>
        </div>

        <h2 id="error-title" className="error-sheet__title">
          {error.title}
        </h2>
        <p className="error-sheet__detail">{error.detail}</p>

        {error.causes.length > 0 && (
          <div className="error-sheet__causes">
            <div className="eyebrow">Possible reasons</div>
            <ul>
              {error.causes.map((cause) => (
                <li key={cause}>{cause}</li>
              ))}
            </ul>
          </div>
        )}

        {error.next_step && (
          <div className="note note--info error-sheet__next">
            <div className="note__title">What to do</div>
            <div className="note__body">{error.next_step}</div>
          </div>
        )}

        <div className="error-sheet__actions">
          {error.retryable && (
            <button className="btn btn--primary" onClick={retry} data-testid="error-retry">
              Retry
            </button>
          )}
          <button className="btn" onClick={dismiss} data-testid="error-dismiss">
            Dismiss
          </button>
          {error.technical && (
            <button
              className="btn btn--ghost"
              onClick={() => setShowDetails((v) => !v)}
              aria-expanded={showDetails}
            >
              {showDetails ? 'Hide details' : 'View details'}
            </button>
          )}
        </div>

        {showDetails && error.technical && (
          <pre className="error-sheet__technical mono">
            {error.code}
            {'\n\n'}
            {error.technical}
          </pre>
        )}
      </div>
    </div>
  );
}
