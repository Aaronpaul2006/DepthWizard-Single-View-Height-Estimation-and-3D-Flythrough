import { Box3, Ray, Vector3 } from 'three';
import type { MeshData } from './terrain';
// Traverse only the grid cells crossed by the ray; never raycast a million triangles.
export function pickGrid(ray: Ray, mesh: MeshData, box: Box3): Vector3 | null {
  const entry = ray.intersectBox(box, new Vector3());
  if (!entry) return null;
  const sx = (box.max.x - box.min.x) / (mesh.cols - 1),
    sz = (box.max.z - box.min.z) / (mesh.rows - 1);
  const start = box.containsPoint(ray.origin) ? ray.origin : entry;
  let c = Math.min(mesh.cols - 2, Math.max(0, Math.floor((start.x - box.min.x) / sx))),
    r = Math.min(mesh.rows - 2, Math.max(0, Math.floor((start.z - box.min.z) / sz)));
  const dx = Math.sign(ray.direction.x),
    dz = Math.sign(ray.direction.z);
  const tdx = dx ? sx / Math.abs(ray.direction.x) : Infinity,
    tdz = dz ? sz / Math.abs(ray.direction.z) : Infinity;
  let tx = dx
    ? (box.min.x + (c + (dx > 0 ? 1 : 0)) * sx - ray.origin.x) / ray.direction.x
    : Infinity;
  let tz = dz
    ? (box.min.z + (r + (dz > 0 ? 1 : 0)) * sz - ray.origin.z) / ray.direction.z
    : Infinity;
  const a = new Vector3(),
    b = new Vector3(),
    d = new Vector3(),
    hit = new Vector3();
  for (let step = 0; step < mesh.cols + mesh.rows + 4; step++) {
    const i = r * mesh.cols + c;
    let nearest: Vector3 | null = null;
    for (const [ia, ib, ic] of [
      [i, i + mesh.cols, i + 1],
      [i + 1, i + mesh.cols, i + mesh.cols + 1],
    ]) {
      if (!mesh.valid[ia] || !mesh.valid[ib] || !mesh.valid[ic]) continue;
      a.fromArray(mesh.positions, ia * 3);
      b.fromArray(mesh.positions, ib * 3);
      d.fromArray(mesh.positions, ic * 3);
      if (
        ray.intersectTriangle(a, b, d, false, hit) &&
        (!nearest || ray.origin.distanceToSquared(hit) < ray.origin.distanceToSquared(nearest))
      )
        nearest = hit.clone();
    }
    if (nearest) return nearest;
    if (!Number.isFinite(tx) && !Number.isFinite(tz)) break;
    if (tx < tz) {
      c += dx;
      tx += tdx;
    } else {
      r += dz;
      tz += tdz;
    }
    if (c < 0 || r < 0 || c >= mesh.cols - 1 || r >= mesh.rows - 1) break;
  }
  return null;
}
