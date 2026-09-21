import { useEffect, useRef } from 'react';

import type { SystemStatus } from '../lib/types';
import { StatRow } from './ui';
import './DataStatusPopover.css';

interface Props {
  status: SystemStatus;
  onClose: () => void;
}

/**
 * Where the numbers come from.
 *
 * This is the one place a judge, auditor or user can check whether they are
 * looking at satellite observations or a forward model — so it states that
 * first, and when Earth Engine is absent it gives the exact command to fix it
 * rather than a vague "not configured".
 */
export function DataStatusPopover({ status, onClose }: Props) {
  const ref = useRef<HTMLDivElement>(null);
  const provider = status.provider;
  const ee = provider.earth_engine;
  const detail = provider.detail;

  useEffect(() => {
    const onDown = (event: MouseEvent) => {
      if (!ref.current?.contains(event.target as Node)) onClose();
    };
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onClose();
    };
    document.addEventListener('mousedown', onDown);
    document.addEventListener('keydown', onKey);
    return () => {
      document.removeEventListener('mousedown', onDown);
      document.removeEventListener('keydown', onKey);
    };
  }, [onClose]);

  const collections = (detail.collections ?? {}) as Record<string, string>;
  const forwardModels = (detail.forward_models ?? {}) as Record<string, string>;

  return (
    <div className="data-status panel" ref={ref} role="dialog" aria-label="Data status">
      <div className="data-status__head">
        <span className={`pill ${provider.simulated ? 'pill--sim' : 'pill--live'}`}>
          <span className="pill__dot" />
          {provider.indicator}
        </span>
        <button className="btn btn--sm btn--ghost" onClick={onClose} aria-label="Close">
          ✕
        </button>
      </div>

      <p className="data-status__headline">{provider.headline}</p>

      {provider.simulated && (
        <div className="note note--sim">
          <div className="note__title">Not an observation</div>
          <div className="note__body">
            {String(detail.warning ?? '')}
            {ee.next_step && (
              <p className="data-status__next">
                <strong>To use real data:</strong> {ee.next_step}
              </p>
            )}
          </div>
        </div>
      )}

      <div className="data-status__block">
        <div className="eyebrow">Earth Engine</div>
        <StatRow label="Credential" value={ee.ready ? 'Working' : 'Not available'} />
        <StatRow label="Configured" value={ee.configured ? 'Yes' : 'No'} />
        {detail.project ? <StatRow label="Project" value={String(detail.project)} /> : null}
        {!ee.ready && ee.reason && (
          <div className="data-status__reason mono">{ee.reason}</div>
        )}
      </div>

      {Object.keys(collections).length > 0 && (
        <div className="data-status__block">
          <div className="eyebrow">Collections</div>
          {Object.entries(collections).map(([role, id]) => (
            <StatRow key={role} label={role.replace(/_/g, ' ')} value={id} />
          ))}
        </div>
      )}

      {Object.keys(forwardModels).length > 0 && (
        <div className="data-status__block">
          <div className="eyebrow">Forward models in use</div>
          {Object.entries(forwardModels).map(([role, id]) => (
            <StatRow key={role} label={role.replace(/_/g, ' ')} value={id} />
          ))}
        </div>
      )}

      <div className="data-status__block">
        <div className="eyebrow">Service</div>
        <StatRow label="Version" value={status.version} />
        <StatRow label="Model" value={status.model_version} />
        <StatRow label="Max area" value={`${status.limits.max_aoi_km2.toLocaleString()} km²`} />
        <StatRow
          label="GEDI minimum"
          value={`${status.limits.min_gedi_samples} footprints`}
          title="Below this, the model cannot be calibrated locally and falls back to the regional default."
        />
      </div>
    </div>
  );
}
