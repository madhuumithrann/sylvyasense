/** Map colours, kept in step with the CSS tokens in styles/tokens.css. */

export const COLORS = {
  water: '#070b0e',
  land: '#121a20',
  border: 'rgba(148, 176, 194, 0.26)',
  graticule: 'rgba(148, 176, 194, 0.2)',

  aoiFill: 'rgba(63, 185, 132, 0.10)',
  aoiLine: '#3fb984',
  aoiLineHalo: 'rgba(4, 8, 10, 0.75)',

  draftFill: 'rgba(86, 213, 156, 0.12)',
  draftLine: '#56d59c',

  vertex: '#e6f7ef',
  vertexStroke: '#1c6b48',
  vertexActive: '#56d59c',

  siteHigh: '#e5645d',
  siteMedium: '#e0a526',
  siteLow: '#59a5e0',
  siteHalo: 'rgba(4, 8, 10, 0.85)',

  inspectRing: '#56d59c',
} as const;

export const PRIORITY_COLOR: Record<string, string> = {
  HIGH: COLORS.siteHigh,
  MEDIUM: COLORS.siteMedium,
  LOW: COLORS.siteLow,
};
