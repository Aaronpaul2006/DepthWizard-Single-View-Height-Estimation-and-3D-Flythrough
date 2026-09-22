import type { Meta, ProfilePoint } from './terrain';
export class ProfileChart {
  private ctx: CanvasRenderingContext2D;
  private points: ProfilePoint[] = [];
  private meta?: Meta;
  private selected = -1;
  private observer: ResizeObserver;
  onHover?: (point: ProfilePoint | null, index: number) => void;
  constructor(readonly canvas: HTMLCanvasElement) {
    this.ctx = canvas.getContext('2d')!;
    this.observer = new ResizeObserver(() => this.draw());
    this.observer.observe(canvas);
    canvas.addEventListener('pointermove', (e) => {
      if (!this.points.length) return;
      const rect = canvas.getBoundingClientRect(),
        t = Math.max(0, Math.min(1, (e.clientX - rect.left - 58) / (rect.width - 80)));
      this.selected = Math.round(t * (this.points.length - 1));
      this.onHover?.(this.points[this.selected], this.selected);
      this.draw();
    });
    canvas.addEventListener('pointerleave', () => {
      this.selected = -1;
      this.onHover?.(null, -1);
      this.draw();
    });
  }
  set(points: ProfilePoint[], meta: Meta) {
    this.points = points;
    this.meta = meta;
    this.selected = -1;
    this.draw();
  }
  clear() {
    this.points = [];
    this.draw();
  }
  private draw() {
    const w = this.canvas.clientWidth,
      h = this.canvas.clientHeight;
    if (!w || !h) return;
    const dpr = Math.min(devicePixelRatio, 2);
    this.canvas.width = w * dpr;
    this.canvas.height = h * dpr;
    const ctx = this.ctx;
    ctx.scale(dpr, dpr);
    ctx.clearRect(0, 0, w, h);
    if (!this.points.length) return;
    const values = this.points.filter((p) => p.height !== null).map((p) => p.height!);
    if (!values.length) return;
    let min = Math.min(...values),
      max = Math.max(...values);
    const pad = Math.max((max - min) * 0.18, 0.5);
    min -= pad;
    max += pad;
    const left = 58,
      right = w - 22,
      top = 12,
      bottom = h - 27,
      distance = this.points.at(-1)!.distance;
    const x = (p: ProfilePoint) => left + (right - left) * (distance ? p.distance / distance : 0),
      y = (value: number) => bottom - ((value - min) / (max - min)) * (bottom - top);
    ctx.font = '10px "Segoe UI", sans-serif';
    ctx.lineWidth = 1;
    for (let i = 0; i < 4; i++) {
      const v = min + ((max - min) * i) / 3,
        py = y(v);
      ctx.strokeStyle = '#e9ece7';
      ctx.beginPath();
      ctx.moveTo(left, py);
      ctx.lineTo(right, py);
      ctx.stroke();
      ctx.fillStyle = '#7b847c';
      ctx.textAlign = 'right';
      const shown = this.meta?.units === 'm' ? v : v * 100; // DepthWizard patch: relative as %
      ctx.fillText(shown.toFixed(max - min < 10 ? 1 : 0), left - 12, py + 3);
    }
    for (let i = 0; i < 5; i++) {
      ctx.textAlign = i === 0 ? 'left' : i === 4 ? 'right' : 'center';
      ctx.fillStyle = '#7b847c';
      ctx.fillText(`${((distance * i) / 4).toFixed(0)} m`, left + ((right - left) * i) / 4, h - 6);
    }
    const fill = ctx.createLinearGradient(0, top, 0, bottom);
    fill.addColorStop(0, '#42877438');
    fill.addColorStop(1, '#42877403');
    const segments: ProfilePoint[][] = [];
    let segment: ProfilePoint[] = [];
    for (const p of this.points) {
      if (p.height === null) {
        if (segment.length) segments.push(segment);
        segment = [];
      } else segment.push(p);
    }
    if (segment.length) segments.push(segment);
    for (const part of segments) {
      ctx.beginPath();
      ctx.moveTo(x(part[0]), bottom);
      for (const p of part) ctx.lineTo(x(p), y(p.height!));
      ctx.lineTo(x(part.at(-1)!), bottom);
      ctx.closePath();
      ctx.fillStyle = fill;
      ctx.fill();
      ctx.beginPath();
      part.forEach((p, i) => (i ? ctx.lineTo(x(p), y(p.height!)) : ctx.moveTo(x(p), y(p.height!))));
      ctx.strokeStyle = '#3f7b66';
      ctx.lineWidth = 1.7;
      ctx.stroke();
    }
    ctx.textAlign = 'left';
    ctx.fillStyle = '#4c6456';
    ctx.font = 'bold 10px "Segoe UI", sans-serif';
    ctx.fillText('A', left, top + 2);
    ctx.textAlign = 'right';
    ctx.fillText('B', right, top + 2);
    if (this.selected >= 0) {
      const p = this.points[this.selected],
        px = x(p);
      ctx.strokeStyle = '#647c6d';
      ctx.setLineDash([3, 3]);
      ctx.beginPath();
      ctx.moveTo(px, top);
      ctx.lineTo(px, bottom);
      ctx.stroke();
      ctx.setLineDash([]);
      if (p.height !== null) {
        ctx.beginPath();
        ctx.arc(px, y(p.height), 3.5, 0, Math.PI * 2);
        ctx.fillStyle = '#2d6f57';
        ctx.fill();
      }
      const label =
        p.height === null
          ? 'No data'
          : this.meta?.units === 'm'
            ? `${p.height.toFixed(2)} m`
            : `${(p.height * 100).toFixed(1)} %`; // DepthWizard patch: relative as %
      ctx.font = '11px "Segoe UI", sans-serif';
      const tw = ctx.measureText(label).width + 18,
        bx = Math.min(right - tw, Math.max(left, px - tw / 2));
      ctx.fillStyle = '#264c3f';
      ctx.beginPath();
      ctx.roundRect(bx, top, tw, 23, 4);
      ctx.fill();
      ctx.fillStyle = '#fff';
      ctx.textAlign = 'center';
      ctx.fillText(label, bx + tw / 2, top + 15);
    }
  }
}
