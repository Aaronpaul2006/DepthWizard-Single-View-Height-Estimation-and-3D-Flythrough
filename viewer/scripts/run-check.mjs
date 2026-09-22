import { build } from 'esbuild';
import { spawnSync } from 'node:child_process';
import { mkdir } from 'node:fs/promises';
const benchmark = process.argv.includes('--benchmark');
await mkdir('test-results', { recursive: true });
const output = `test-results/${benchmark ? 'benchmark' : 'terrain.test'}.mjs`;
await build({
  entryPoints: [benchmark ? 'scripts/benchmark.ts' : 'tests/terrain.test.ts'],
  outfile: output,
  bundle: true,
  platform: 'node',
  format: 'esm',
  packages: 'external',
});
const result = spawnSync(process.execPath, [...(benchmark ? [] : ['--test']), output], {
  stdio: 'inherit',
});
process.exitCode = result.status ?? 1;
