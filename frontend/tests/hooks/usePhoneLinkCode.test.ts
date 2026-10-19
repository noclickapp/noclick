// @vitest-environment jsdom
// The link code a QR and its "Open" link carry must always have time left to scan and send. A code is shown only while
// it has more than three minutes left, judged on the wall clock (a laptop that slept, a tab that sat in the background),
// and while a fresh one is on its way nothing is shown at all.

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { act, cleanup, renderHook } from '@testing-library/react';

const { sendEventAsync } = vi.hoisted(() => ({ sendEventAsync: vi.fn() }));
vi.mock('~/lib/socket-sender', () => ({ sendEventAsync }));

import { usePhoneLink, usePhoneLinkCode } from '~/hooks/usePhoneLink';

const MIN = 60_000;
let minted = 0;
let codesAvailable = true;

function setVisibility(state: 'visible' | 'hidden') {
    Object.defineProperty(document, 'visibilityState', { value: state, configurable: true });
}

const flush = () => act(async () => void (await vi.advanceTimersByTimeAsync(0)));

function render() {
    return renderHook(() => usePhoneLinkCode(usePhoneLink({ load: false }), true));
}

beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date('2026-10-05T12:00:00Z'));
    setVisibility('visible');
    minted = 0;
    codesAvailable = true;
    sendEventAsync.mockImplementation(async (request: { event_name?: string }) => {
        if (request.event_name === 'phone:link:code') {
            if (!codesAvailable) return { error: "Linking by text isn't available on this instance", kind: 'codes_unavailable' };
            minted += 1;
            return { code: `NC-0000-000${minted}`, expires_in: 600 };
        }
        if (request.event_name === 'phone:status') return { configured: true, max_phones: 5, phones: [] };
        return { error: 'unexpected' };
    });
});

afterEach(() => {
    cleanup(); // unmount, so an earlier test's listeners can't answer this one's events
    vi.useRealTimers();
    sendEventAsync.mockReset();
});

describe('usePhoneLinkCode', () => {
    it('holds the slot until the first code lands, then shows it', async () => {
        const { result } = render();
        expect(result.current).toEqual({ code: null, pending: true });
        await flush();
        expect(result.current.pending).toBe(false);
        expect(result.current.code?.code).toBe('NC-0000-0001');
    });

    it('swaps a code for a fresh one while it still has three minutes left', async () => {
        const { result } = render();
        await flush();
        await act(async () => void (await vi.advanceTimersByTimeAsync(7 * MIN - 2000)));
        expect(result.current.code?.code).toBe('NC-0000-0001');
        await act(async () => void (await vi.advanceTimersByTimeAsync(3000)));
        expect(result.current.code?.code).toBe('NC-0000-0002');
    });

    it('drops a code that went stale while the laptop slept the moment the page is back, before showing a new one', async () => {
        const { result } = render();
        await flush();
        // Asleep: the wall clock moves on, no timer runs.
        vi.setSystemTime(Date.now() + 9 * MIN);
        let land!: () => void;
        sendEventAsync.mockImplementationOnce(
            () =>
                new Promise((resolve) => {
                    land = () => resolve({ code: 'NC-0000-0002', expires_in: 600 });
                })
        );
        await act(async () => void window.dispatchEvent(new Event('focus')));
        await flush();
        // The stale code is gone before the next one exists: nothing to scan in between.
        expect(result.current).toEqual({ code: null, pending: true });
        await act(async () => land());
        await flush();
        expect(result.current.code?.code).toBe('NC-0000-0002');
    });

    it('in a hidden tab drops a stale code and mints the next only once the page is looked at', async () => {
        const { result } = render();
        await flush();
        setVisibility('hidden');
        await act(async () => void (await vi.advanceTimersByTimeAsync(8 * MIN)));
        expect(result.current).toEqual({ code: null, pending: true });
        expect(minted).toBe(1);
        setVisibility('visible');
        await act(async () => void document.dispatchEvent(new Event('visibilitychange')));
        await flush();
        expect(minted).toBe(2);
        expect(result.current.code?.code).toBe('NC-0000-0002');
    });

    it('where codes are not available, settles on none and stops asking', async () => {
        codesAvailable = false;
        const { result } = render();
        await flush();
        await act(async () => void (await vi.advanceTimersByTimeAsync(10_000)));
        expect(result.current).toEqual({ code: null, pending: false });
        const asks = sendEventAsync.mock.calls.filter(([request]) => request.event_name === 'phone:link:code');
        expect(asks).toHaveLength(1);
    });
});
