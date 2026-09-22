import type { Meta } from './terrain';
function hash(x: number, y: number) {
  let n = Math.imul(x, 374761393) + Math.imul(y, 668265263);
  n = Math.imul(n ^ (n >>> 13), 1274126177);
  return ((n ^ (n >>> 16)) >>> 0) / 4294967295;
}
function noise(x: number, y: number) {
  const ix = Math.floor(x),
    iy = Math.floor(y),
    fx = x - ix,
    fy = y - iy,
    s = fx * fx * (3 - 2 * fx),
    t = fy * fy * (3 - 2 * fy);
  return (
    (hash(ix, iy) * (1 - s) + hash(ix + 1, iy) * s) * (1 - t) +
    (hash(ix, iy + 1) * (1 - s) + hash(ix + 1, iy + 1) * s) * t
  );
}
export async function makeDemo(size = 768) {
  const data = new Float32Array(size * size),
    rgba = new Uint8ClampedArray(size * size * 4);
  let min = Infinity,
    max = -Infinity;
  for (let r = 0; r < size; r++)
    for (let c = 0; c < size; c++) {
      const x = c / (size - 1),
        y = r / (size - 1);
      const ridgeCenter = 0.47 + 0.13 * Math.sin(y * 5.5) - 0.07 * Math.cos(y * 13);
      const dist = Math.abs(x - ridgeCenter);
      const ridge =
        Math.exp(-dist * dist * 22) * (0.5 + 0.5 * Math.pow(Math.sin(y * 6.6 + 0.4), 2));
      const foothill = Math.exp(-((x - 0.76) ** 2 * 30 + (y - 0.7) ** 2 * 13)) * 0.4;
      const fbm =
        noise(x * 7 + 3, y * 7) * 0.5 +
        noise(x * 16, y * 16) * 0.25 +
        noise(x * 38, y * 38) * 0.14 +
        noise(x * 90, y * 90) * 0.07 +
        noise(x * 180, y * 180) * 0.04;
      const folds = Math.abs(Math.sin((x + y * 0.32) * 40 + noise(x * 9, y * 9) * 6));
      const elevation =
        1080 + ridge * 670 + foothill * 360 + fbm * (90 + ridge * 190) + folds * ridge * 65;
      data[r * size + c] = elevation;
      min = Math.min(min, elevation);
      max = Math.max(max, elevation);
    }
  for (let r = 0; r < size; r++)
    for (let c = 0; c < size; c++) {
      const i = r * size + c,
        h = data[i],
        level = (h - min) / (max - min),
        x = c / size,
        y = r / size;
      const slope = Math.hypot(
        data[r * size + Math.min(c + 1, size - 1)] - data[r * size + Math.max(0, c - 1)],
        data[Math.min(r + 1, size - 1) * size + c] - data[Math.max(0, r - 1) * size + c],
      );
      const n = noise(x * 160, y * 160),
        speckle = hash(c, r);
      const rock = Math.max(0, Math.min(1, (level - 0.53) * 4 + slope * 0.012));
      const vegetation = [54 + n * 36, 72 + n * 39, 48 + n * 22],
        stone = [145 + n * 50, 143 + n * 43, 126 + n * 40];
      const light = 0.8 + speckle * 0.25;
      for (let k = 0; k < 3; k++)
        rgba[i * 4 + k] = (vegetation[k] * (1 - rock) + stone[k] * rock) * light;
      rgba[i * 4 + 3] = 255;
    }
  const canvas = new OffscreenCanvas(size, size),
    ctx = canvas.getContext('2d')!;
  ctx.putImageData(new ImageData(rgba, size, size), 0, 0);
  const image = await canvas.convertToBlob({ type: 'image/png' });
  const meta: Meta = {
    width: size,
    height: size,
    pixel_size_m: 3,
    min_h: min,
    max_h: max,
    units: 'm',
    bounds: [0, 0, size * 3, size * 3],
    crs: 'LOCAL · Synthetic demo',
  };
  return { data, meta, image };
}
