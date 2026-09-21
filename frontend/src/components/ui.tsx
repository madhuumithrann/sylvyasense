/** Small presentational primitives shared across the analysis panels. */

import type { ReactNode } from 'react';

import './ui.css';

/* ---------------------------------------------------------------- Metric */

interface MetricProps {
  label: string;
  value: ReactNode;
  unit?: string;
  range?: string;
  provenance?: ReactNode;
  tone?: 'default' | 'accent' | 'warn' | 'danger';
  testId?: string;
}

/** A headline number with its unit, interval and provenance attached. */
export function Metric({
  label,
  value,
  unit,
  range,
  provenance,
  tone = 'default',
  testId,
}: MetricProps) {
  return (
    <div className={`metric metric--${tone}`} data-testid={testId}>
      <div className="metric__label eyebrow">{label}</div>
      <div className="metric__value mono">
        {value}
        {unit && <span className="metric__unit">{unit}</span>}
      </div>
      {range && <div className="metric__range mono">{range}</div>}
      {provenance && <div className="metric__prov">{provenance}</div>}
    </div>
  );
}

/* ------------------------------------------------------------------- Row */

export function StatRow({
  label,
  value,
  title,
  mono = true,
}: {
  label: string;
  value: ReactNode;
  title?: string;
  mono?: boolean;
}) {
  return (
    <div className="stat-row" title={title}>
      <span className="stat-row__label">{label}</span>
      <span className={`stat-row__value ${mono ? 'mono' : ''}`}>{value}</span>
    </div>
  );
}

/* --------------------------------------------------------------- Section */

export function Section({
  title,
  action,
  children,
  dense = false,
}: {
  title: string;
  action?: ReactNode;
  children: ReactNode;
  dense?: boolean;
}) {
  return (
    <section className={`section ${dense ? 'section--dense' : ''}`}>
      <header className="section__head">
        <h3 className="section-title">{title}</h3>
        {action}
      </header>
      <div className="section__body">{children}</div>
    </section>
  );
}

/* ----------------------------------------------------------------- Notes */

export function Note({
  tone = 'info',
  title,
  children,
}: {
  tone?: 'info' | 'warn' | 'danger' | 'sim';
  title?: string;
  children: ReactNode;
}) {
  return (
    <div className={`note note--${tone}`}>
      {title && <div className="note__title">{title}</div>}
      <div className="note__body">{children}</div>
    </div>
  );
}

/* ----------------------------------------------------------- Empty state */

export function EmptyState({
  title,
  children,
  action,
}: {
  title: string;
  children?: ReactNode;
  action?: ReactNode;
}) {
  return (
    <div className="empty">
      <div className="empty__title">{title}</div>
      {children && <p className="empty__body">{children}</p>}
      {action && <div className="empty__action">{action}</div>}
    </div>
  );
}

/* ---------------------------------------------------------------- Status */

const STATUS_TONE: Record<string, string> = {
  AVAILABLE: 'ok',
  PARTIAL: 'warn',
  UNAVAILABLE: 'bad',
  NOT_CONFIGURED: 'bad',
  READY: 'ok',
  PARTIAL_DATA: 'warn',
  INSUFFICIENT_DATA: 'bad',
  HIGH_CONFIDENCE: 'ok',
  SURVEY_RECOMMENDED: 'warn',
  SIGNIFICANT_CHANGE: 'warn',
  NO_SIGNIFICANT_CHANGE: 'ok',
};

export function StatusDot({ status }: { status: string }) {
  return (
    <span
      className={`status-dot status-dot--${STATUS_TONE[status] ?? 'muted'}`}
      aria-hidden="true"
    />
  );
}

export function StatusBadge({ status, label }: { status: string; label?: string }) {
  return (
    <span className={`status-badge status-badge--${STATUS_TONE[status] ?? 'muted'}`}>
      <StatusDot status={status} />
      {label ?? status.replace(/_/g, ' ')}
    </span>
  );
}

/* ------------------------------------------------------------------- Bar */

/** A proportion bar. Only ever fed a real measured fraction. */
export function Meter({
  value,
  max = 1,
  color,
  label,
}: {
  value: number;
  max?: number;
  color?: string;
  label?: string;
}) {
  const pct = Math.max(0, Math.min(1, max === 0 ? 0 : value / max)) * 100;
  return (
    <div
      className="meter"
      role="img"
      aria-label={label ?? `${pct.toFixed(0)} percent`}
      title={label}
    >
      <div
        className="meter__fill"
        style={{ width: `${pct}%`, background: color ?? 'var(--accent)' }}
      />
    </div>
  );
}

/* -------------------------------------------------------------- Ramp key */

export function RampKey({
  stops,
  min,
  max,
  unit,
}: {
  stops: string[];
  min: number;
  max: number;
  unit?: string;
}) {
  return (
    <div className="ramp-key">
      <div
        className="ramp-key__bar"
        style={{ background: `linear-gradient(90deg, ${stops.join(', ')})` }}
      />
      <div className="ramp-key__scale mono">
        <span>{min}</span>
        {unit && <span className="ramp-key__unit">{unit}</span>}
        <span>{max}</span>
      </div>
    </div>
  );
}

/* --------------------------------------------------------- Provenance tag */

export function Provenance({ lines }: { lines: (string | null | undefined)[] }) {
  const visible = lines.filter(Boolean) as string[];
  if (visible.length === 0) return null;
  return (
    <div className="provenance">
      {visible.map((line, index) => (
        <span key={index} className="provenance__line">
          {line}
        </span>
      ))}
    </div>
  );
}
