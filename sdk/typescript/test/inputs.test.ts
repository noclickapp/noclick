// useInputs/onInputsChanged accumulation semantics. Each test gets a fresh module
// instance (vi.resetModules) because inputs.ts holds module-level currentInputs.
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { createFakeHost, type FakeHost } from './helpers/fakeHost';

let inputs: typeof import('../src/inputs');
let transport: typeof import('../src/core/transport');
let host: FakeHost;

beforeEach(async () => {
  vi.resetModules();
  transport = await import('../src/core/transport');
  inputs = await import('../src/inputs');
  host = createFakeHost();
  transport.setTransport(host.transport);
});

describe('inputs', () => {
  it('merges successive inputs:changed payloads instead of clobbering', () => {
    const seen: Record<string, unknown>[] = [];
    inputs.onInputsChanged((i) => seen.push({ ...i }));

    host.emitEvent('inputs:changed', { a: 1 });
    host.emitEvent('inputs:changed', { b: 2 });

    // A later event for one upstream node must not wipe earlier inputs.
    expect(inputs.currentInputs).toEqual({ a: 1, b: 2 });
    expect(seen[seen.length - 1]).toEqual({ a: 1, b: 2 });
  });

  it('updates an existing key in place', () => {
    inputs.onInputsChanged(() => {});
    host.emitEvent('inputs:changed', { a: 1, b: 2 });
    host.emitEvent('inputs:changed', { a: 99 });
    expect(inputs.currentInputs).toEqual({ a: 99, b: 2 });
  });
});
