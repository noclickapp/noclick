// @vitest-environment happy-dom
// The instance's capabilities are read once per page, however many surfaces ask as it loads.
import { cleanup, renderHook, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
    vi.resetModules();
});

const answer = (capabilities: Record<string, unknown>) => new Response(JSON.stringify({ capabilities }), { headers: { 'content-type': 'application/json' } });

describe('useInstanceCapabilities', () => {
    it('reads once for every surface that mounts while the first read is under way', async () => {
        const fetch = vi.fn(async () => answer({ publishing: false }));
        vi.stubGlobal('fetch', fetch);
        const { useInstanceCapabilities } = await import('~/hooks/useInstanceCapabilities');
        const hooks = [1, 2, 3].map(() => renderHook(() => useInstanceCapabilities()));
        for (const { result } of hooks) await waitFor(() => expect(result.current.publishing).toBe(false));
        expect(fetch).toHaveBeenCalledTimes(1);
        // A surface mounting later takes what was read.
        expect(renderHook(() => useInstanceCapabilities()).result.current.publishing).toBe(false);
        expect(fetch).toHaveBeenCalledTimes(1);
    });

    it('asks again on the next surface when a read answered nothing', async () => {
        const fetch = vi.fn<() => Promise<Response>>().mockRejectedValueOnce(new Error('offline')).mockResolvedValue(answer({ publishing: false }));
        vi.stubGlobal('fetch', fetch);
        const { useInstanceCapabilities } = await import('~/hooks/useInstanceCapabilities');
        const first = renderHook(() => useInstanceCapabilities());
        await waitFor(() => expect(fetch).toHaveBeenCalledTimes(1));
        await new Promise((r) => setTimeout(r, 0));
        expect(first.result.current.publishing).toBe(true);
        const second = renderHook(() => useInstanceCapabilities());
        await waitFor(() => expect(second.result.current.publishing).toBe(false));
        expect(fetch).toHaveBeenCalledTimes(2);
    });
});
