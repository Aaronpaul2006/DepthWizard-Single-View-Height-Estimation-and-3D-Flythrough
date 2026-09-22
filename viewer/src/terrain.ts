export interface Meta {
  width: number;
  height: number;
  pixel_size_m: number;
  min_h: number;
  max_h: number;
  units: 'm' | 'relative';
  bounds?: unknown;
  crs?: string | null;
}
export interface GridPoint {
  col: number;
  row: number;
}
export interface Sample extends GridPoint {
  height: number | null;
  slope: number | null;
  error?: number | null;
}
export interface ProfilePoint extends Sample {
  distance: number;
}
export interface Metrics {
  rmse: number;
  mae: number;
  bias: number;
  count: number;
  maxAbs: number;
}
export interface MeshData {
  positions: Float32Array;
  normals: Float32Array;
  uvs: Float32Array;
  slopes: Float32Array;
  errors: Float32Array;
  errorValid: Uint8Array;
  indices: Uint32Array;
  valid: Uint8Array;
  cols: number;
  rows: number;
  min: number;
  max: number;
}
export function validateMeta(value: unknown): Meta {
  if (!value || typeof value !== 'object') throw new Error('meta.json must contain an object.');
  const m = value as Record<string, unknown>;
  for (const key of ['width', 'height']) {
    if (!Number.isInteger(m[key]) || Number(m[key]) < 2)
      throw new Error(`${key} must be an integer of at least 2.`);
  }
  if (Number(m.width) * Number(m.height) > 100000000)
    throw new Error('This viewer supports up to 100 million source cells.');
  if (typeof m.pixel_size_m !== 'number' || !Number.isFinite(m.pixel_size_m) || m.pixel_size_m <= 0)
    throw new Error('pixel_size_m must be a positive, finite number.');
  if (
    typeof m.min_h !== 'number' ||
    typeof m.max_h !== 'number' ||
    !Number.isFinite(m.min_h) ||
    !Number.isFinite(m.max_h) ||
    m.min_h > m.max_h
  )
    throw new Error('min_h and max_h must be finite and ordered.');
  if (m.units != null && m.units !== 'm' && m.units !== 'relative')
    throw new Error('units must be "m" or "relative".');
  if (m.crs != null && typeof m.crs !== 'string') throw new Error('crs must be a string or null.');
  return { ...m, units: m.units ?? 'relative' } as unknown as Meta;
}
export function decodeDSM(buffer: ArrayBuffer, meta: Meta): Float32Array {
  const expected = meta.width * meta.height * 4;
  if (buffer.byteLength !== expected)
    throw new Error(
      `DSM size mismatch: expected ${expected.toLocaleString()} bytes, received ${buffer.byteLength.toLocaleString()}. Use little-endian Float32, with no header.`,
    );
  // The backend protocol is explicitly little-endian, including on a big-endian host.
  if (new Uint8Array(new Uint32Array([1]).buffer)[0] === 1) return new Float32Array(buffer);
  const values = new Float32Array(expected / 4),
    view = new DataView(buffer);
  for (let i = 0; i < values.length; i++) values[i] = view.getFloat32(i * 4, true);
  return values;
}
export function range(data: Float32Array): {
  min: number;
  max: number;
  count: number;
} {
  let min = Infinity,
    max = -Infinity,
    count = 0;
  for (const h of data)
    if (Number.isFinite(h)) {
      min = Math.min(min, h);
      max = Math.max(max, h);
      count++;
    }
  if (!count) throw new Error('The DSM has no finite elevations. Encode missing cells as NaN.');
  return { min, max, count };
}
export function sampleHeight(data: Float32Array, m: Meta, col: number, row: number): number | null {
  if (col < 0 || col > m.width - 1 || row < 0 || row > m.height - 1) return null;
  const x0 = Math.floor(col),
    y0 = Math.floor(row),
    x1 = Math.min(x0 + 1, m.width - 1),
    y1 = Math.min(y0 + 1, m.height - 1);
  const tx = col - x0,
    ty = row - y0;
  const hs = [
    data[y0 * m.width + x0],
    data[y0 * m.width + x1],
    data[y1 * m.width + x0],
    data[y1 * m.width + x1],
  ];
  const weights = [(1 - tx) * (1 - ty), tx * (1 - ty), (1 - tx) * ty, tx * ty];
  let value = 0;
  for (let i = 0; i < 4; i++)
    if (weights[i] > 1e-10) {
      if (!Number.isFinite(hs[i])) return null;
      value += hs[i] * weights[i];
    }
  return value;
}
export function gradient(
  data: Float32Array,
  m: Meta,
  col: number,
  row: number,
): [number, number] | null {
  const c = Math.round(col),
    r = Math.round(row);
  const xl = Math.max(0, c - 1),
    xr = Math.min(m.width - 1, c + 1),
    yt = Math.max(0, r - 1),
    yb = Math.min(m.height - 1, r + 1);
  const a = data[r * m.width + xl],
    b = data[r * m.width + xr],
    d = data[yt * m.width + c],
    e = data[yb * m.width + c];
  if (![a, b, d, e].every(Number.isFinite)) return null;
  return [(b - a) / ((xr - xl) * m.pixel_size_m), (e - d) / ((yb - yt) * m.pixel_size_m)];
}
export function sample(data: Float32Array, m: Meta, p: GridPoint, ref?: Float32Array): Sample {
  const height = sampleHeight(data, m, p.col, p.row),
    g = height === null ? null : gradient(data, m, p.col, p.row);
  const reference = ref ? sampleHeight(ref, m, p.col, p.row) : null;
  return {
    ...p,
    height,
    slope: g ? (Math.atan(Math.hypot(...g)) * 180) / Math.PI : null,
    error: height !== null && reference !== null ? height - reference : null,
  };
}
export function buildMesh(data: Float32Array, m: Meta, cap = 513, ref?: Float32Array): MeshData {
  cap = Math.max(2, Math.min(1024, Math.floor(cap)));
  const factor = Math.min(1, (cap - 1) / Math.max(m.width - 1, m.height - 1));
  const cols = Math.max(2, Math.round((m.width - 1) * factor) + 1),
    rows = Math.max(2, Math.round((m.height - 1) * factor) + 1);
  const n = cols * rows,
    positions = new Float32Array(n * 3),
    normals = new Float32Array(n * 3),
    uvs = new Float32Array(n * 2);
  const slopes = new Float32Array(n),
    errors = new Float32Array(n),
    errorValid = new Uint8Array(n),
    valid = new Uint8Array(n);
  const extX = (m.width - 1) * m.pixel_size_m,
    extZ = (m.height - 1) * m.pixel_size_m;
  for (let r = 0; r < rows; r++)
    for (let c = 0; c < cols; c++) {
      const i = r * cols + c,
        col = (c / (cols - 1)) * (m.width - 1),
        row = (r / (rows - 1)) * (m.height - 1);
      const h = sampleHeight(data, m, col, row),
        g = gradient(data, m, col, row);
      valid[i] = h === null ? 0 : 1;
      positions.set(
        [
          col * m.pixel_size_m - extX / 2,
          (h ?? m.min_h) - m.min_h,
          row * m.pixel_size_m - extZ / 2,
        ],
        i * 3,
      );
      const gx = g?.[0] ?? 0,
        gz = g?.[1] ?? 0,
        length = Math.hypot(gx, 1, gz);
      normals.set([-gx / length, 1 / length, -gz / length], i * 3);
      // Grid vertices denote pixel CENTERS. Row zero is north / the top image row.
      uvs.set([(col + 0.5) / m.width, 1 - (row + 0.5) / m.height], i * 2);
      slopes[i] = g ? (Math.atan(Math.hypot(...g)) * 180) / Math.PI : -1;
      const rh = ref ? sampleHeight(ref, m, col, row) : null;
      errorValid[i] = rh !== null && h !== null ? 1 : 0;
      errors[i] = rh !== null && h !== null ? h - rh : 0;
    }
  const indices = new Uint32Array((cols - 1) * (rows - 1) * 6);
  let cursor = 0;
  for (let r = 0; r < rows - 1; r++)
    for (let c = 0; c < cols - 1; c++) {
      const a = r * cols + c,
        b = a + 1,
        d = a + cols,
        e = d + 1;
      if (valid[a] && valid[d] && valid[b]) {
        indices[cursor++] = a;
        indices[cursor++] = d;
        indices[cursor++] = b;
      }
      if (valid[b] && valid[d] && valid[e]) {
        indices[cursor++] = b;
        indices[cursor++] = d;
        indices[cursor++] = e;
      }
    }
  return {
    positions,
    normals,
    uvs,
    slopes,
    errors,
    errorValid,
    valid,
    indices: indices.slice(0, cursor),
    cols,
    rows,
    min: m.min_h,
    max: m.max_h,
  };
}
function canonical(value: unknown): string {
  if (Array.isArray(value)) return `[${value.map(canonical).join(',')}]`;
  if (value && typeof value === 'object')
    return JSON.stringify(
      Object.keys(value)
        .sort()
        .map((k) => [k, canonical((value as Record<string, unknown>)[k])]),
    );
  return JSON.stringify(value) ?? 'null';
}
export function validateReference(base: Meta, reference: Meta) {
  for (const key of ['width', 'height', 'pixel_size_m', 'units', 'crs', 'bounds'] as const) {
    if (canonical(base[key]) !== canonical(reference[key]))
      throw new Error(
        `Reference ${key} does not match. Reproject/resample the reference onto the source grid in Python first.`,
      );
  }
}
export function compare(data: Float32Array, ref: Float32Array): Metrics {
  if (data.length !== ref.length) throw new Error('Reference grid size does not match.');
  let squared = 0,
    absolute = 0,
    sum = 0,
    count = 0,
    maxAbs = 0;
  for (let i = 0; i < data.length; i++)
    if (Number.isFinite(data[i]) && Number.isFinite(ref[i])) {
      const d = data[i] - ref[i];
      squared += d * d;
      absolute += Math.abs(d);
      sum += d;
      count++;
      maxAbs = Math.max(maxAbs, Math.abs(d));
    }
  if (!count) throw new Error('Source and reference have no overlapping valid cells.');
  return {
    rmse: Math.sqrt(squared / count),
    mae: absolute / count,
    bias: sum / count,
    count,
    maxAbs,
  };
}
export function profile(
  data: Float32Array,
  m: Meta,
  a: GridPoint,
  b: GridPoint,
  ref?: Float32Array,
): ProfilePoint[] {
  const cells = Math.hypot(b.col - a.col, b.row - a.row),
    length = cells * m.pixel_size_m;
  const count = Math.min(2048, Math.max(2, Math.ceil(cells) + 1));
  return Array.from({ length: count }, (_, i) => {
    const t = i / (count - 1);
    return {
      ...sample(
        data,
        m,
        { col: a.col + (b.col - a.col) * t, row: a.row + (b.row - a.row) * t },
        ref,
      ),
      distance: length * t,
    };
  });
}
