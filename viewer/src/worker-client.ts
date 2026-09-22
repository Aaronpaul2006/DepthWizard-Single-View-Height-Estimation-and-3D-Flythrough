export class TerrainWorker {
  private worker = new Worker(new URL('./terrain.worker.ts', import.meta.url), { type: 'module' });
  private next = 0;
  private pending = new Map<
    number,
    {
      resolve: (value: any) => void;
      reject: (e: Error) => void;
    }
  >();
  constructor() {
    this.worker.onmessage = ({ data }) => {
      const call = this.pending.get(data.id);
      if (!call) return;
      this.pending.delete(data.id);
      if (data.error) call.reject(new Error(data.error));
      else call.resolve(data.result);
    };
    this.worker.onerror = () =>
      this.fail(
        new Error(
          'Terrain worker stopped unexpectedly. Try a smaller dataset or reload the viewer.',
        ),
      );
  }
  call<T>(type: string, payload: unknown = {}): Promise<T> {
    return new Promise((resolve, reject) => {
      const id = ++this.next;
      this.pending.set(id, { resolve, reject });
      this.worker.postMessage({ id, type, payload });
    });
  }
  private fail(error: Error) {
    for (const call of this.pending.values()) call.reject(error);
    this.pending.clear();
  }
  dispose() {
    this.worker.terminate();
    this.fail(new Error('Dataset replaced.'));
  }
}
