/// <reference lib="webworker" />
import {
  buildMesh,
  compare,
  decodeDSM,
  profile,
  range,
  sample,
  validateMeta,
  validateReference,
} from './terrain';
import type { Meta, Metrics } from './terrain';
import { makeDemo } from './demo';
let data: Float32Array,
  meta: Meta,
  reference: Float32Array | undefined,
  metrics: Metrics | undefined;
self.onmessage = async ({ data: message }) => {
  const { id, type, payload } = message;
  try {
    let result: unknown,
      transfer: Transferable[] = [];
    if (type === 'load' || type === 'demo') {
      let image: Blob | undefined;
      if (type === 'demo') {
        const d = await makeDemo();
        data = d.data;
        meta = d.meta;
        image = d.image;
      } else {
        meta = validateMeta(payload.meta);
        data = decodeDSM(await (payload.file as File).arrayBuffer(), meta);
      }
      const actual = range(data);
      const declared = { min: meta.min_h, max: meta.max_h };
      meta = { ...meta, min_h: actual.min, max_h: actual.max };
      reference = undefined;
      metrics = undefined;
      const mesh = buildMesh(data, meta, payload.cap);
      result = { meta, mesh, image, validCount: actual.count, declared };
      transfer = [
        mesh.positions.buffer,
        mesh.normals.buffer,
        mesh.uvs.buffer,
        mesh.slopes.buffer,
        mesh.errors.buffer,
        mesh.indices.buffer,
        mesh.valid.buffer,
        mesh.errorValid.buffer,
      ];
    } else if (!data) throw new Error('Load a terrain first.');
    else if (type === 'mesh') {
      const mesh = buildMesh(data, meta, payload.cap, reference);
      result = mesh;
      transfer = [
        mesh.positions.buffer,
        mesh.normals.buffer,
        mesh.uvs.buffer,
        mesh.slopes.buffer,
        mesh.errors.buffer,
        mesh.indices.buffer,
        mesh.valid.buffer,
        mesh.errorValid.buffer,
      ];
    } else if (type === 'sample') result = sample(data, meta, payload, reference);
    else if (type === 'profile') result = profile(data, meta, payload.a, payload.b, reference);
    else if (type === 'reference') {
      if (payload.meta) validateReference(meta, validateMeta(payload.meta));
      const candidate = decodeDSM(await (payload.file as File).arrayBuffer(), meta);
      const stats = compare(data, candidate);
      reference = candidate;
      metrics = stats;
      const mesh = buildMesh(data, meta, payload.cap, reference);
      result = { metrics, mesh };
      transfer = [
        mesh.positions.buffer,
        mesh.normals.buffer,
        mesh.uvs.buffer,
        mesh.slopes.buffer,
        mesh.errors.buffer,
        mesh.indices.buffer,
        mesh.valid.buffer,
        mesh.errorValid.buffer,
      ];
    } else throw new Error('Unknown worker request.');
    self.postMessage({ id, result }, { transfer });
  } catch (e) {
    self.postMessage({ id, error: e instanceof Error ? e.message : String(e) });
  }
};
