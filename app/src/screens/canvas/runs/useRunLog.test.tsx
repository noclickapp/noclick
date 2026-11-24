// @vitest-environment happy-dom
// The run counts are read again once a burst of changes settles, while the run log is mounted; once it has gone,
// nothing reads them.
import { act, renderHook } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { RunReads } from './reads';
import { useRunLog } from './useRunLog';

beforeEach(() => {
    vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout'] });
});

afterEach(() => {
    vi.useRealTimers();
});

function runLog() {
    const counts = vi.fn(async () => ({ total: 0, by_status: {}, by_trigger: {} }) as never);
    const reads = { counts, runs: vi.fn(async () => ({ logs: [], next: null })), history: vi.fn(), outputShape: vi.fn(), narrows: {} } as unknown as RunReads;
    const hook = renderHook(() => useRunLog({ workflowId: 'wf_orders', reads, setLogs: () => undefined }));
    return { hook, counts };
}

describe('the run log’s counts', () => {
    it('are read again once changes settle', () => {
        const { hook, counts } = runLog();
        // Read once as the workflow opens, then again for the burst.
        expect(counts).toHaveBeenCalledOnce();
        act(() => hook.result.current.countsChanged());
        act(() => vi.runAllTimers());
        expect(counts).toHaveBeenCalledTimes(2);
        hook.unmount();
    });

    it('are read by nobody once the run log has gone', () => {
        const { hook, counts } = runLog();
        act(() => hook.result.current.countsChanged());
        expect(vi.getTimerCount()).toBe(1);
        hook.unmount();
        expect(vi.getTimerCount()).toBe(0);
        vi.runAllTimers();
        expect(counts).toHaveBeenCalledOnce();
    });
});
