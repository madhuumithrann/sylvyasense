/** Presentation helpers. Rounding lives here so it is consistent everywhere. */

const nf = (min: number, max: number) =>
  new Intl.NumberFormat('en-GB', {
    minimumFractionDigits: min,
    maximumFractionDigits: max,
  });

const int = new Intl.NumberFormat('en-GB', { maximumFractionDigits: 0 });

export function num(value: number | null | undefined, digits = 1): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return '—';
  return nf(digits, digits).format(value);
}

export function integer(value: number | null | undefined): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return '—';
  return int.format(value);
}

export function signed(value: number | null | undefined, digits = 1): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return '—';
  const formatted = nf(digits, digits).format(Math.abs(value));
  if (value > 0) return `+${formatted}`;
  if (value < 0) return `−${formatted}`;
  return formatted;
}

export function pct(value: number | null | undefined, digits = 1): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return '—';
  return `${nf(digits, digits).format(value)}%`;
}

/** 0–1 score as a percentage. */
export function score(value: number | null | undefined, digits = 0): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return '—';
  return `${nf(digits, digits).format(value * 100)}%`;
}

export function area(km2: number | null | undefined): string {
  if (km2 === null || km2 === undefined || !Number.isFinite(km2)) return '—';
  if (km2 < 1) return `${nf(1, 1).format(km2 * 100)} ha`;
  return `${nf(2, 2).format(km2)} km²`;
}

/** Large stock figures read better abbreviated. */
export function compact(value: number | null | undefined, unit = ''): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return '—';
  const abs = Math.abs(value);
  const suffix = unit ? ` ${unit}` : '';
  if (abs >= 1e9) return `${nf(2, 2).format(value / 1e9)}B${suffix}`;
  if (abs >= 1e6) return `${nf(2, 2).format(value / 1e6)}M${suffix}`;
  if (abs >= 1e3) return `${nf(1, 1).format(value / 1e3)}k${suffix}`;
  return `${nf(0, 0).format(value)}${suffix}`;
}

export function coord(value: number | null | undefined, digits = 5): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return '—';
  return value.toFixed(digits);
}

export function latLon(lat: number, lon: number): string {
  const ns = lat >= 0 ? 'N' : 'S';
  const ew = lon >= 0 ? 'E' : 'W';
  return `${Math.abs(lat).toFixed(5)}°${ns}  ${Math.abs(lon).toFixed(5)}°${ew}`;
}

export function date(iso: string | null | undefined): string {
  if (!iso) return '—';
  const parsed = new Date(iso);
  if (Number.isNaN(parsed.getTime())) return iso;
  return parsed.toLocaleDateString('en-GB', {
    year: 'numeric',
    month: 'short',
    day: '2-digit',
  });
}

export function distance(metres: number | null | undefined): string {
  if (metres === null || metres === undefined || !Number.isFinite(metres)) return '—';
  if (metres >= 1000) return `${nf(1, 1).format(metres / 1000)} km`;
  return `${int.format(metres)} m`;
}

/** SIGNIFICANT_CHANGE -> "Significant change" */
export function humanise(token: string | null | undefined): string {
  if (!token) return '—';
  const spaced = token.replace(/_/g, ' ').toLowerCase();
  return spaced.charAt(0).toUpperCase() + spaced.slice(1);
}

/** p-values below the printable threshold should say so, not read as zero. */
export function pValue(value: number | null | undefined): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return '—';
  if (value < 0.0001) return '< 0.0001';
  return value.toFixed(4);
}
