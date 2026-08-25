// The XHR upload helper and the byte-weighted multi-file progress math in
// uploadWorkspaceFiles: overall fraction must be weighted by file size (not
// file count), zero-byte selections fall back to count, and error bodies
// surface the server's JSON `error` when present.
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { uploadWithProgress } from '~/lib/uploadWithProgress';
import {
  uploadWorkspaceFiles,
  type WorkspaceUploadProgress,
} from '~/hooks/useAgentWorkspaceFiles';

type ProgressEvt = { lengthComputable: boolean; loaded: number; total: number };

class FakeXHR {
  static instances: FakeXHR[] = [];
  upload: { onprogress: ((e: ProgressEvt) => void) | null } = { onprogress: null };
  onload: (() => void) | null = null;
  onerror: (() => void) | null = null;
  onabort: (() => void) | null = null;
  status = 0;
  statusText = '';
  responseText = '';
  method = '';
  url = '';
  headers: Record<string, string> = {};
  open(method: string, url: string) { this.method = method; this.url = url; }
  setRequestHeader(name: string, value: string) { this.headers[name] = value; }
  send(_body: unknown) { FakeXHR.instances.push(this); }

  emitProgress(loaded: number, total: number) {
    this.upload.onprogress?.({ lengthComputable: true, loaded, total });
  }
  finish(status: number, body = '') {
    this.status = status;
    this.statusText = status === 200 ? 'OK' : 'Error';
    this.responseText = body;
    this.onload?.();
  }
}

beforeEach(() => {
  FakeXHR.instances = [];
  vi.stubGlobal('XMLHttpRequest', FakeXHR);
});
afterEach(() => vi.unstubAllGlobals());

const nextXhr = (n: number) =>
  vi.waitFor(() => {
    expect(FakeXHR.instances.length).toBe(n);
    return FakeXHR.instances[n - 1];
  });

describe('uploadWithProgress', () => {
  it('reports byte fractions and resolves with the response', async () => {
    const fractions: number[] = [];
    const promise = uploadWithProgress('https://r2/put', new Blob(['abcd']), {
      method: 'PUT',
      headers: { 'Content-Type': 'text/plain' },
      onProgress: f => fractions.push(f),
    });
    const xhr = await nextXhr(1);
    expect(xhr.method).toBe('PUT');
    expect(xhr.headers['Content-Type']).toBe('text/plain');
    xhr.emitProgress(2, 4);
    xhr.finish(200, 'done');
    await expect(promise).resolves.toEqual({
      ok: true, status: 200, statusText: 'OK', text: 'done',
    });
    // load always lands on 1 even if the last progress event was partial
    expect(fractions).toEqual([0.5, 1]);
  });

  it('rejects on network error', async () => {
    const promise = uploadWithProgress('https://r2/put', new Blob(['x']));
    const xhr = await nextXhr(1);
    xhr.onerror?.();
    await expect(promise).rejects.toThrow('Network error during upload');
  });
});

describe('uploadWorkspaceFiles', () => {
  const fileA = new File(['x'.repeat(100)], 'a.txt');
  const fileB = new File(['y'.repeat(300)], 'b.txt');

  it('weights overall progress by bytes across sequential files', async () => {
    const events: WorkspaceUploadProgress[] = [];
    const promise = uploadWorkspaceFiles(
      '/agent/workspace/upload?token=t', [fileA, fileB], p => events.push(p),
    );

    const first = await nextXhr(1);
    expect(first.url).toContain('path=a.txt');
    first.emitProgress(50, 100); // a.txt halfway: 50/400 total bytes
    first.finish(200);

    const second = await nextXhr(2);
    expect(second.url).toContain('path=b.txt');
    second.emitProgress(150, 300); // (100 + 150)/400
    second.finish(200);
    await promise;

    expect(events.map(e => [e.fileName, e.fileIndex, e.fraction])).toEqual([
      ['a.txt', 0, 0.125],
      ['a.txt', 0, 0.25],
      ['b.txt', 1, 0.625],
      ['b.txt', 1, 1],
    ]);
    expect(events.every(e => e.fileCount === 2)).toBe(true);
  });

  it('falls back to count-based progress for zero-byte selections', async () => {
    const events: WorkspaceUploadProgress[] = [];
    const promise = uploadWorkspaceFiles(
      '/u?token=t', [new File([], 'empty.txt')], p => events.push(p),
    );
    (await nextXhr(1)).finish(200);
    await promise;
    expect(events.at(-1)?.fraction).toBe(1);
  });

  it('surfaces the server JSON error and stops at the first failure', async () => {
    const promise = uploadWorkspaceFiles('/u?token=t', [fileA, fileB]);
    (await nextXhr(1)).finish(413, '{"error":"File too large (max 100MB)"}');
    await expect(promise).rejects.toThrow('File too large (max 100MB)');
    expect(FakeXHR.instances.length).toBe(1); // b.txt never started
  });

  it('falls back to a filename message on a non-JSON error body', async () => {
    const promise = uploadWorkspaceFiles('/u?token=t', [fileA]);
    (await nextXhr(1)).finish(500, 'Internal Server Error');
    await expect(promise).rejects.toThrow('Upload failed for a.txt');
  });

  it('rejects files over 100MB before any bytes fly', async () => {
    const big = new File(['x'], 'big.bin');
    Object.defineProperty(big, 'size', { value: 100 * 1024 * 1024 + 1 });
    await expect(uploadWorkspaceFiles('/u?token=t', [fileA, big])).rejects.toThrow(
      /big\.bin is too large .*Maximum size is 100 MB/,
    );
    expect(FakeXHR.instances.length).toBe(0); // nothing uploaded, a.txt included
  });
});
