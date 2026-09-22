import { buildMesh, compare, profile, range, type Meta } from '../src/terrain';
import { pickGrid } from '../src/picking';
import { Box3, Ray, Vector3 } from 'three';
const data = new Float32Array(4000 * 4000),
  reference = new Float32Array(data.length);
for (let i = 0; i < data.length; i++) {
  data[i] = 1000 + Math.sin((i % 4000) / 200) * 50 + Math.cos(Math.floor(i / 4000) / 300) * 100;
  reference[i] = data[i] - 2;
}
const meta: Meta = {
  width: 4000,
  height: 4000,
  pixel_size_m: 1,
  min_h: 850,
  max_h: 1150,
  units: 'm',
};
const measure = <T>(label: string, run: () => T) => {
  const start = performance.now();
  const value = run();
  console.log(`${label}: ${(performance.now() - start).toFixed(1)} ms`);
  return value;
};
const r = measure('Scan 16 million elevations', () => range(data));
meta.min_h = r.min;
meta.max_h = r.max;
const mesh = measure('Build 513 × 513 mesh', () => buildMesh(data, meta, 513));
measure('Compare 16 million reference pairs', () => compare(data, reference));
measure('2,048-point diagonal profile', () =>
  profile(data, meta, { col: 0, row: 0 }, { col: 3999, row: 3999 }),
);
const box = new Box3().setFromArray(mesh.positions);
const ray = new Ray(new Vector3(0, 4000, 0), new Vector3(0.2, -1, 0.1).normalize());
measure('1,000 grid-ray picks', () => {
  for (let i = 0; i < 1000; i++) pickGrid(ray, mesh, box);
});
console.log(`Mesh: ${mesh.cols * mesh.rows} vertices, ${mesh.indices.length / 3} triangles`);
console.log(
  `Source + reference storage: ${((data.byteLength + reference.byteLength) / 1024 / 1024).toFixed(1)} MiB`,
);
console.log('CPU timings only. The app runs scan, mesh, profile and comparison in a Web Worker.');
