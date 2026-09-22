import { mkdir, writeFile } from 'node:fs/promises';
import { resolve } from 'node:path';
import { deflateSync } from 'node:zlib';
import { pathToFileURL } from 'node:url';
function crc32(bytes) {
  let crc = 0xffffffff;
  for (const byte of bytes) {
    crc ^= byte;
    for (let i = 0; i < 8; i++) crc = (crc >>> 1) ^ (crc & 1 ? 0xedb88320 : 0);
  }
  return (crc ^ 0xffffffff) >>> 0;
}
function chunk(name, data) {
  const type = Buffer.from(name),
    result = Buffer.alloc(data.length + 12);
  result.writeUInt32BE(data.length);
  type.copy(result, 4);
  data.copy(result, 8);
  result.writeUInt32BE(crc32(Buffer.concat([type, data])), data.length + 8);
  return result;
}
function image() {
  const w = 512,
    h = 512,
    rows = Buffer.alloc(h * (1 + w * 3));
  for (let y = 0; y < h; y++)
    for (let x = 0; x < w; x++) {
      const i = y * (1 + w * 3) + 1 + x * 3,
        c =
          y < h / 2
            ? x < w / 2
              ? [220, 40, 40]
              : [40, 200, 60]
            : x < w / 2
              ? [40, 70, 220]
              : [230, 210, 40];
      for (let k = 0; k < 3; k++) rows[i + k] = c[k];
    }
  const header = Buffer.alloc(13);
  header.writeUInt32BE(w, 0);
  header.writeUInt32BE(h, 4);
  header[8] = 8;
  header[9] = 2;
  return Buffer.concat([
    Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]),
    chunk('IHDR', header),
    chunk('IDAT', deflateSync(rows)),
    chunk('IEND', Buffer.alloc(0)),
  ]);
}
export async function makeFixtures(size = 4000) {
  const dir = resolve('test-results', `fixture-${size}`);
  await mkdir(dir, { recursive: true });
  const data = Buffer.alloc(size * size * 4),
    ref = Buffer.alloc(data.length);
  for (let r = 0; r < size; r++)
    for (let c = 0; c < size; c++) {
      const i = (r * size + c) * 4;
      data.writeFloatLE(100 + (c / (size - 1)) * 20 + (r / (size - 1)) * 10, i);
      ref.writeFloatLE(data.readFloatLE(i) - 2, i);
    }
  const meta = {
    width: size,
    height: size,
    pixel_size_m: 1,
    min_h: 100,
    max_h: 130,
    units: 'm',
    bounds: [0, 0, size, size],
    crs: 'LOCAL TEST GRID',
  };
  await Promise.all([
    writeFile(resolve(dir, 'dsm.bin'), data),
    writeFile(resolve(dir, 'reference.bin'), ref),
    writeFile(resolve(dir, 'ortho.png'), image()),
    writeFile(resolve(dir, 'meta.json'), JSON.stringify(meta)),
    writeFile(
      resolve(dir, 'reference-meta.json'),
      JSON.stringify({ ...meta, min_h: 98, max_h: 128 }),
    ),
    writeFile(resolve(dir, 'mismatch.json'), JSON.stringify({ ...meta, pixel_size_m: 2 })),
    writeFile(resolve(dir, 'relative.json'), JSON.stringify({ ...meta, units: undefined })),
    writeFile(resolve(dir, 'bad.bin'), new Uint8Array(3)),
  ]);
  return dir;
}
if (process.argv[1] && import.meta.url === pathToFileURL(resolve(process.argv[1])).href)
  console.log(await makeFixtures(Number(process.argv[2] ?? 4000)));
