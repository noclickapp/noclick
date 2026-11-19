// @vitest-environment happy-dom
// A reset has Work read again what it shows: each of its mounted reads once, however many views show it, and none of
// anyone else's. With no live source, the host resets every minute while the page is shown, and not while it's hidden.
import { act, cleanup, render, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { NoClick } from 'noclick';
import { createWorkLive, resetEvery, WorkLiveContext, type WorkLive } from '@/sdk/live';
import { useV1 } from '@/sdk/useV1';
import { useWorkV1 } from './agents/reads';
import { WorkClientContext } from './client';
import { useReadsAgainOnReset } from './rereads';

afterEach(() => {
    cleanup();
    vi.useRealTimers();
});

const client = {} as NoClick;

function Views({ reads }: { reads: Record<'agents' | 'machines' | 'elsewhere', () => Promise<number>> }) {
    useReadsAgainOnReset();
    // Two views of the agents, as a list and a profile draw them.
    useWorkV1('work:agents', reads.agents);
    useWorkV1('work:agents', reads.agents);
    useWorkV1('resources:machines/own', reads.machines);
    useV1('status', reads.elsewhere, { client });
    return null;
}

function mount(live: WorkLive) {
    const reads = { agents: vi.fn(async () => 1), machines: vi.fn(async () => 2), elsewhere: vi.fn(async () => 3) };
    render(
        <WorkClientContext.Provider value={client}>
            <WorkLiveContext.Provider value={live}>
                <Views reads={reads} />
            </WorkLiveContext.Provider>
        </WorkClientContext.Provider>
    );
    return reads;
}

describe('a reset', () => {
    it('reads each of Work’s mounted reads again once, and nothing else', async () => {
        const live = createWorkLive();
        const reads = mount(live);
        await waitFor(() => expect([reads.agents, reads.machines, reads.elsewhere].map((r) => r.mock.calls.length)).toEqual([1, 1, 1]));

        act(() => live.deliver('reset', { why: 'backstop' }));

        await waitFor(() => expect([reads.agents, reads.machines].map((r) => r.mock.calls.length)).toEqual([2, 2]));
        expect(reads.elsewhere).toHaveBeenCalledTimes(1);
    });
});

describe('the backstop', () => {
    it('resets every minute while the page is shown, never while it’s hidden, and stops when stopped', () => {
        vi.useFakeTimers();
        const live = createWorkLive();
        const heard: string[] = [];
        live.on('reset', (reset) => heard.push(reset.why));
        let visibility: DocumentVisibilityState = 'visible';
        const shown = vi.spyOn(document, 'visibilityState', 'get').mockImplementation(() => visibility);
        const stop = resetEvery(live);

        vi.advanceTimersByTime(59_999);
        expect(heard).toEqual([]);
        vi.advanceTimersByTime(1);
        expect(heard).toEqual(['backstop']);

        visibility = 'hidden';
        vi.advanceTimersByTime(120_000);
        expect(heard).toEqual(['backstop']);

        visibility = 'visible';
        vi.advanceTimersByTime(60_000);
        expect(heard).toEqual(['backstop', 'backstop']);

        stop();
        vi.advanceTimersByTime(180_000);
        expect(heard).toEqual(['backstop', 'backstop']);
        shown.mockRestore();
    });
});
