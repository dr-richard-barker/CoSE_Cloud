import { paragraphs, safeExportHref, unsafeSpecKey } from '../lib/safety';
import { SERIES } from '../chartTheme';

test('specs with outside data, links or code keys are refused', () => {
  expect(unsafeSpecKey({ data: { values: [] }, layer: [{ mark: 'line' }] })).toBeNull();
  expect(unsafeSpecKey({ layer: [{ data: { url: 'https://evil.example/x.csv' } }] })).toBe('/layer/0/data/url');
  expect(unsafeSpecKey({ encoding: { href: { field: 'x' } } })).toBe('/encoding/href');
  expect(unsafeSpecKey({ signals: [] })).toBe('/signals');
});

test('only our own export routes become download links', () => {
  expect(safeExportHref('/api/datasets/4f8c1b2e-0d2a-4b8e-9a51-2a3c4d5e6f70/export?format=csv')).not.toBeNull();
  expect(safeExportHref('/api/devices/xseed-sim-0001/export?metrics=sensors.dome_temp_c&format=rocrate')).not.toBeNull();
  expect(safeExportHref('https://evil.example/api/datasets/x/export?format=csv')).toBeNull();
  expect(safeExportHref('javascript:alert(1)')).toBeNull();
  expect(safeExportHref('/api/auth/logout?format=csv')).toBeNull();
});

test('answers render as plain paragraphs', () => {
  expect(paragraphs('**Mean** 21.2 °C.\n\n[click](https://evil.example)')).toEqual(['Mean 21.2 °C.', '[click](https://evil.example)']);
});

test('series palettes keep the validated order', () => {
  expect(SERIES.light[0]).toBe('#3B6EA5');
  expect(SERIES.light).toHaveLength(4);
  expect(SERIES.dark).toHaveLength(4);
});
