import { useEffect, useRef, useState } from 'react';
import { useQuery } from '@tanstack/react-query';

import { api } from '../lib/api';
import type { Place, SystemStatus } from '../lib/types';
import { useStore } from '../state/store';
import { DataStatusPopover } from './DataStatusPopover';
import './TopBar.css';

interface Props {
  status: SystemStatus | undefined;
  isLoading: boolean;
  error: unknown;
}

export function TopBar({ status, isLoading, error }: Props) {
  const [query, setQuery] = useState('');
  const [open, setOpen] = useState(false);
  const [statusOpen, setStatusOpen] = useState(false);
  const [highlight, setHighlight] = useState(0);
  const boxRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  const setGeometry = useStore((s) => s.setGeometry);
  const panelOpen = useStore((s) => s.panelOpen);
  const setPanelOpen = useStore((s) => s.setPanelOpen);

  const trimmed = query.trim();

  const search = useQuery({
    queryKey: ['places', trimmed],
    queryFn: () => api.searchPlaces(trimmed),
    enabled: trimmed.length >= 2,
  });

  const demo = useQuery({ queryKey: ['demo-places'], queryFn: api.demoPlaces });

  const results: Place[] =
    trimmed.length >= 2 ? (search.data?.results ?? []) : (demo.data?.results ?? []);

  useEffect(() => setHighlight(0), [trimmed]);

  // Dismiss the suggestion list on an outside click.
  useEffect(() => {
    if (!open) return;
    const onDown = (event: MouseEvent) => {
      if (!boxRef.current?.contains(event.target as Node)) setOpen(false);
    };
    document.addEventListener('mousedown', onDown);
    return () => document.removeEventListener('mousedown', onDown);
  }, [open]);

  // Cmd/Ctrl-K focuses search, the convention users already know.
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 'k') {
        event.preventDefault();
        inputRef.current?.focus();
        setOpen(true);
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, []);

  function choose(place: Place) {
    const geometry =
      place.geometry ??
      squareAround(place.lon, place.lat, Math.min(place.span_deg, 0.18));
    setGeometry(geometry, place.name);
    setQuery('');
    setOpen(false);
    inputRef.current?.blur();
  }

  function onKeyDown(event: React.KeyboardEvent<HTMLInputElement>) {
    if (!open || results.length === 0) return;
    if (event.key === 'ArrowDown') {
      event.preventDefault();
      setHighlight((h) => (h + 1) % results.length);
    } else if (event.key === 'ArrowUp') {
      event.preventDefault();
      setHighlight((h) => (h - 1 + results.length) % results.length);
    } else if (event.key === 'Enter') {
      event.preventDefault();
      const place = results[highlight];
      if (place) choose(place);
    } else if (event.key === 'Escape') {
      setOpen(false);
    }
  }

  const simulated = status?.provider.simulated ?? false;
  const indicator = status?.provider.indicator ?? (isLoading ? 'Connecting' : 'Offline');

  return (
    <header className="topbar">
      <div className="topbar__brand">
        <LeafMark />
        <div className="topbar__wordmark">
          <span className="topbar__name">SylvaSense</span>
          <span className="topbar__tagline">Forest carbon intelligence</span>
        </div>
      </div>

      <div className="topbar__search" ref={boxRef}>
        <SearchIcon />
        <input
          ref={inputRef}
          type="search"
          className="topbar__input"
          placeholder="Search a forest region…"
          aria-label="Search a forest region"
          value={query}
          onChange={(event) => {
            setQuery(event.target.value);
            setOpen(true);
          }}
          onFocus={() => setOpen(true)}
          onKeyDown={onKeyDown}
          data-testid="search-input"
        />
        <kbd className="topbar__kbd mono">⌘K</kbd>

        {open && results.length > 0 && (
          <ul className="search-results panel" role="listbox" data-testid="search-results">
            {trimmed.length < 2 && (
              <li className="search-results__head eyebrow">Demo areas — ready to analyse</li>
            )}
            {results.map((place, index) => (
              <li key={`${place.name}-${place.lon}`}>
                <button
                  type="button"
                  role="option"
                  aria-selected={index === highlight}
                  className={`search-result ${index === highlight ? 'is-active' : ''}`}
                  onMouseEnter={() => setHighlight(index)}
                  onClick={() => choose(place)}
                >
                  <span className="search-result__main">
                    <span className="search-result__name">{place.name}</span>
                    <span className="search-result__meta">
                      {place.country} · {place.biome}
                    </span>
                  </span>
                  {place.demo && <span className="search-result__tag">Demo</span>}
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>

      <div className="topbar__right">
        <button
          type="button"
          className={`pill ${simulated ? 'pill--sim' : status ? 'pill--live' : 'pill--danger'}`}
          onClick={() => setStatusOpen((v) => !v)}
          aria-expanded={statusOpen}
          data-testid="data-status"
          title="Where the numbers on screen come from"
        >
          <span className={`pill__dot ${isLoading ? 'pill__dot--pulse' : ''}`} />
          {error ? 'Backend offline' : indicator}
        </button>

        {status && (
          <span className="topbar__model mono" title="Active biomass model version">
            {status.model_version}
          </span>
        )}

        <button
          type="button"
          className="btn btn--sm btn--ghost topbar__toggle"
          onClick={() => setPanelOpen(!panelOpen)}
          aria-pressed={panelOpen}
          title={panelOpen ? 'Hide the analysis panel' : 'Show the analysis panel'}
        >
          {panelOpen ? 'Hide panel' : 'Show panel'}
        </button>

        {statusOpen && status && (
          <DataStatusPopover status={status} onClose={() => setStatusOpen(false)} />
        )}
      </div>
    </header>
  );
}

/** A square AOI around a point, used when a place has no bundled geometry. */
function squareAround(lon: number, lat: number, sizeDeg: number) {
  const half = sizeDeg / 2;
  return {
    type: 'Polygon' as const,
    coordinates: [
      [
        [lon - half, lat - half],
        [lon + half, lat - half],
        [lon + half, lat + half],
        [lon - half, lat + half],
        [lon - half, lat - half],
      ],
    ],
  };
}

function LeafMark() {
  return (
    <svg width="24" height="24" viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <path
        d="M12 21.5c-5 0-8.2-3.4-8.2-8 0-5.6 4.6-9.8 8.2-11 3.6 1.2 8.2 5.4 8.2 11 0 4.6-3.2 8-8.2 8Z"
        stroke="var(--accent)"
        strokeWidth="1.4"
        strokeLinejoin="round"
      />
      <path
        d="M12 21V6.5M12 12.5 8.4 9M12 15.8l3.6-3.5"
        stroke="var(--accent)"
        strokeWidth="1.4"
        strokeLinecap="round"
      />
    </svg>
  );
}

function SearchIcon() {
  return (
    <svg
      className="topbar__search-icon"
      width="14"
      height="14"
      viewBox="0 0 16 16"
      fill="none"
      aria-hidden="true"
    >
      <circle cx="7" cy="7" r="4.6" stroke="currentColor" strokeWidth="1.4" />
      <path d="m10.6 10.6 3.2 3.2" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" />
    </svg>
  );
}
