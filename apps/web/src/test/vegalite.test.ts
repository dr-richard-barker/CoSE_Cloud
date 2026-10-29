// @vitest-environment node
// The Python chart builder's output must compile in Vega-Lite. The fixtures are written by the Python test suite
// (services/tests/test_sim_catalog_charts.py::test_write_spec_fixtures) from the real builder.
import { existsSync, readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { compile } from 'vega-lite';

const path = fileURLToPath(new URL('./fixtures/specs.json', import.meta.url));

test.runIf(existsSync(path))('server-built chart specs compile', () => {
  const specs = JSON.parse(readFileSync(path, 'utf8')) as Record<string, object>;
  expect(Object.keys(specs).length).toBeGreaterThan(0);
  for (const [name, spec] of Object.entries(specs)) {
    const out = compile(spec as never);
    expect(out.spec, name).toBeTruthy();
  }
});
