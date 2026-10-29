// Series colours for charts, by theme. Both were checked with the dataviz skill's validate_palette.js (24 Oct 2026):
//   light on #fcfcfb: all checks pass; worst adjacent CVD ΔE 9.1, normal-vision ΔE 22.9; aqua and yellow sit below
//     3:1 contrast, so every multi-series chart carries a legend, end-of-line labels and a data-table view.
//   dark on #151a20: all checks pass; worst adjacent CVD ΔE 8.4, normal-vision ΔE 19.8, every slot >= 3:1.
// Slot 1 is CoSE blue; brand navy, teal and mint failed as a series palette (navy reads grey; teal and mint are
// below 3:1 on light), so they stay on the interface. Order is fixed: a colour follows its metric, never its rank.
export const SERIES = {
  light: ['#3B6EA5', '#eb6834', '#1baf7a', '#eda100'],
  dark: ['#3987e5', '#d95926', '#199e70', '#c98500'],
} as const;

export const SURFACE = { light: '#fcfcfb', dark: '#151a20' } as const;

export type Mode = 'light' | 'dark';

export function vegaConfig(mode: Mode) {
  const ink = mode === 'light'
    ? { text: '#1a2230', muted: '#5a6473', grid: '#e9edf2', domain: '#c9d1dc', warn: '#9a6512' }
    : { text: '#e6ebf2', muted: '#9aa6b6', grid: '#232c39', domain: '#3a4656', warn: '#e3b25c' };
  return {
    background: null,
    font: '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif',
    view: { stroke: null },
    range: { category: [...SERIES[mode]] },
    axis: { labelColor: ink.muted, titleColor: ink.muted, gridColor: ink.grid, domainColor: ink.domain,
      tickColor: ink.domain, labelFontSize: 11, titleFontSize: 11, titleFontWeight: 500 },
    legend: { labelColor: ink.text, titleColor: ink.muted, labelFontSize: 11, symbolType: 'stroke', symbolStrokeWidth: 2 },
    title: { color: ink.text, fontSize: 13, fontWeight: 600, subtitleColor: ink.warn, subtitleFontSize: 11,
      subtitleFontWeight: 600, subtitlePadding: 4 },
    text: { color: ink.text },
    rule: { color: ink.muted },
    line: { strokeWidth: 2 },
  };
}
