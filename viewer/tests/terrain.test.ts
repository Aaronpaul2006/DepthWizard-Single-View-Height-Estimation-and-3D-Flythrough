import test from 'node:test';
import assert from 'node:assert/strict';
import { Box3, Ray, Vector3 } from 'three';
import {
  buildMesh,
  compare,
  decodeDSM,
  gradient,
  profile,
  range,
  sampleHeight,
  validateMeta,
  validateReference,
  type Meta,
} from '../src/terrain';
import { pickGrid } from '../src/picking';
const meta: Meta = {
  width: 5,
  height: 4,
  pixel_size_m: 2,
  min_h: 100,
  max_h: 120,
  units: 'm',
  crs: 'EPSG:32643',
  bounds: [0, 0, 10, 8],
};
const plane = new Float32Array(
  Array.from({ length: 20 }, (_, i) => 100 + (i % 5) * 2 + Math.floor(i / 5) * 4),
);
const near = (a: number, b: number, eps = 1e-5) => assert.ok(Math.abs(a - b) < eps, `${a} ≈ ${b}`);
test('validates input shape, storage length, units and actual finite range', () => {
  assert.equal(validateMeta({ ...meta, units: undefined }).units, 'relative');
  for (const bad of [
    { width: 1 },
    { width: 3.5 },
    { pixel_size_m: 0 },
    { pixel_size_m: Infinity },
    { min_h: 121 },
    { units: 'feet' },
  ])
    assert.throws(() => validateMeta({ ...meta, ...bad }));
  assert.throws(() => decodeDSM(new ArrayBuffer(4), meta));
  const bin = new ArrayBuffer(80),
    view = new DataView(bin);
  for (let i = 0; i < 20; i++) view.setFloat32(i * 4, plane[i], true);
  assert.deepEqual(decodeDSM(bin, meta), plane);
  assert.deepEqual(range(plane), { min: 100, max: 120, count: 20 });
  assert.throws(() => range(new Float32Array([NaN, Infinity])));
});
test('bilinear interpolation, edges and no-data semantics', () => {
  near(sampleHeight(plane, meta, 1.5, 2.5)!, 113);
  assert.equal(sampleHeight(plane, meta, 4, 3), 120);
  assert.equal(sampleHeight(plane, meta, -0.1, 1), null);
  const holes = plane.slice();
  holes[6] = NaN;
  assert.equal(sampleHeight(holes, meta, 1, 1), null);
  assert.equal(sampleHeight(holes, meta, 0.5, 0.5), null);
  assert.equal(sampleHeight(holes, meta, 0, 0), 100);
});
test('geometry uses source pixel spacing, true slope, upward normals and pixel-centre UVs', () => {
  const mesh = buildMesh(plane, meta, 3);
  assert.equal(mesh.cols, 3);
  assert.equal(mesh.rows, 3);
  near(mesh.positions[0], -4);
  near(mesh.positions[2], -3);
  near(mesh.positions.at(-3)!, 4);
  near(mesh.positions.at(-1)!, 3);
  near(mesh.positions.at(-2)!, 20);
  near(mesh.uvs[0], 0.1);
  near(mesh.uvs[1], 0.875);
  near(mesh.uvs.at(-2)!, 0.9);
  near(mesh.uvs.at(-1)!, 0.125);
  near(mesh.slopes[0], (Math.atan(Math.sqrt(5)) * 180) / Math.PI);
  assert.deepEqual(gradient(plane, meta, 0, 0), [1, 2]);
  assert.deepEqual(gradient(plane, meta, 2, 2), [1, 2]);
  const a = new Vector3().fromArray(mesh.positions, mesh.indices[0] * 3),
    b = new Vector3().fromArray(mesh.positions, mesh.indices[1] * 3),
    c = new Vector3().fromArray(mesh.positions, mesh.indices[2] * 3);
  assert.ok(b.sub(a).cross(c.sub(a)).y > 0);
});
test('mesh caps both axes at 1024, preserves extent, aspect and finite geometry', () => {
  const m = { ...meta, width: 1300, height: 7 },
    data = new Float32Array(9100).fill(110);
  data[0] = NaN;
  const mesh = buildMesh(data, m, 2000);
  assert.equal(mesh.cols, 1024);
  assert.ok(mesh.rows <= 1024);
  assert.ok(mesh.positions.every(Number.isFinite));
  assert.equal(mesh.valid[0], 0);
  assert.ok(!mesh.indices.includes(0));
  near(mesh.positions.at(-3)!, 1299);
});
test('reference metrics use every valid pair, signed source-minus-reference, including off-mesh cells', () => {
  const ref = plane.slice();
  for (let i = 0; i < ref.length; i++) ref[i] -= 2;
  ref[3] = NaN;
  const metrics = compare(plane, ref);
  assert.deepEqual(metrics, { rmse: 2, mae: 2, bias: 2, count: 19, maxAbs: 2 });
  const mesh = buildMesh(plane, meta, 3, ref);
  assert.equal(mesh.errors[0], 2);
  const outlier = plane.slice();
  outlier[6] -= 10;
  near(compare(plane, outlier).rmse, Math.sqrt(5));
  assert.throws(() => compare(new Float32Array([NaN]), new Float32Array([0])));
});
test('reference rejects misregistration / units, accepts reordered bounds keys', () => {
  for (const bad of [
    { width: 6 },
    { height: 6 },
    { pixel_size_m: 1 },
    { units: 'relative' },
    { crs: 'EPSG:4326' },
    { bounds: [1, 0, 11, 8] },
  ])
    assert.throws(() => validateReference(meta, { ...meta, ...bad } as Meta));
  validateReference(
    { ...meta, bounds: { west: 0, east: 10 } },
    { ...meta, bounds: { east: 10, west: 0 } },
  );
});
test('profile samples the original grid, physical distance, endpoints and gaps', () => {
  const points = profile(plane, meta, { col: 0, row: 0 }, { col: 4, row: 3 });
  near(points.at(-1)!.distance, 10);
  assert.equal(points[0].height, 100);
  assert.equal(points.at(-1)!.height, 120);
  const data = plane.slice();
  data[6] = NaN;
  assert.ok(
    profile(data, meta, { col: 0, row: 0 }, { col: 4, row: 3 }).some((p) => p.height === null),
  );
});
test('grid ray picking matches the actual displayed triangles without a full mesh scan', () => {
  const mesh = buildMesh(plane, meta, 5),
    box = new Box3().setFromArray(mesh.positions);
  const ray = new Ray(new Vector3(0, 100, 0), new Vector3(0, -1, 0));
  const hit = pickGrid(ray, mesh, box);
  assert.ok(hit);
  near(hit.y, 10);
  assert.equal(pickGrid(new Ray(new Vector3(20, 100, 0), new Vector3(0, -1, 0)), mesh, box), null);
  for (let i = 0; i < 50; i++) {
    const origin = new Vector3((i % 5) - 2, 50, -15 + i * 0.2),
      direction = new Vector3(0.01, -1, 0.4).normalize();
    const ray = new Ray(origin, direction);
    const fast = pickGrid(ray, mesh, box);
    let slow: Vector3 | null = null;
    for (let t = 0; t < mesh.indices.length; t += 3) {
      const a = new Vector3().fromArray(mesh.positions, mesh.indices[t] * 3),
        b = new Vector3().fromArray(mesh.positions, mesh.indices[t + 1] * 3),
        c = new Vector3().fromArray(mesh.positions, mesh.indices[t + 2] * 3);
      const p = ray.intersectTriangle(a, b, c, false, new Vector3());
      if (p && (!slow || origin.distanceTo(p) < origin.distanceTo(slow))) slow = p;
    }
    assert.equal(!!fast, !!slow);
    if (fast && slow) near(fast.distanceTo(slow), 0);
  }
});
