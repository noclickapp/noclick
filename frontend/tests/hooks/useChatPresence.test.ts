// @vitest-environment jsdom
// A message the chat shows is also texted unless its person is watching the
// chat, so the tab claims "live" only while the chat is on screen in a visible
// tab of the focused window that was touched within the last minute, renews
// the claim every 15s, and withdraws it the moment any of that stops.

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { act, cleanup, renderHook } from '@testing-library/react';

const { sendEvent } = vi.hoisted(() => ({ sendEvent: vi.fn() }));
vi.mock('~/lib/socket-sender', () => ({ sendEvent }));

import {
    CHAT_BEAT_MS,
    CHAT_IDLE_MS,
    useChatPresence,
} from '~/hooks/useChatPresence';

let focused = true;

function setVisibility(state: 'visible' | 'hidden') {
    Object.defineProperty(document, 'visibilityState', {
        value: state,
        configurable: true,
    });
}

const fire = (target: EventTarget, type: string) =>
    act(() => void target.dispatchEvent(new Event(type)));
const touch = () => fire(window, 'pointermove');
const advance = (ms: number) => act(() => void vi.advanceTimersByTime(ms));
const requests = () =>
    sendEvent.mock.calls.map(
        (call) =>
            call[0] as { event_name: string; tab_id: string; live: boolean }
    );
/** The claims sent so far, true for "live" and false for a withdrawal. */
const sent = () =>
    requests().map((request) => {
        expect(request.event_name).toBe('presence:chat');
        return request.live;
    });

beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date('2026-10-20T12:00:00Z'));
    setVisibility('visible');
    focused = true;
    vi.spyOn(document, 'hasFocus').mockImplementation(() => focused);
    sendEvent.mockReset();
    sendEvent.mockReturnValue(true);
});

afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
    vi.useRealTimers();
});

describe('useChatPresence', () => {
    it('claims nothing until the person touches the page, then claims at once', () => {
        renderHook(() => useChatPresence());
        advance(CHAT_BEAT_MS * 2);
        expect(sent()).toEqual([]);
        touch();
        expect(sent()).toEqual([true]);
    });

    it('renews the claim every 15s while the person keeps at it', () => {
        renderHook(() => useChatPresence());
        touch();
        for (let i = 0; i < 3; i++) {
            advance(CHAT_BEAT_MS - 1000);
            touch();
            advance(1000);
        }
        expect(sent()).toEqual([true, true, true, true]);
    });

    it('never claims from a hidden tab, whatever reaches it', () => {
        setVisibility('hidden');
        renderHook(() => useChatPresence());
        touch();
        fire(window, 'keydown');
        fire(window, 'focus');
        advance(CHAT_BEAT_MS * 3);
        expect(sent()).toEqual([]);
    });

    it('never claims from a visible tab whose window lacks focus', () => {
        focused = false;
        renderHook(() => useChatPresence());
        touch();
        advance(CHAT_BEAT_MS * 3);
        touch();
        expect(sent()).toEqual([]);
    });

    it('withdraws once a minute passes untouched, and claims again on the next touch', () => {
        renderHook(() => useChatPresence());
        touch();
        advance(CHAT_IDLE_MS - 1);
        expect(sent()).toEqual([true, true, true, true]);
        advance(1);
        expect(sent()).toEqual([true, true, true, true, false]);
        // Idle past a minute and no more beats: still nothing live.
        advance(1000);
        advance(CHAT_BEAT_MS * 2);
        expect(sent().at(-1)).toBe(false);
        expect(sent()).toHaveLength(5);
        touch();
        expect(sent().at(-1)).toBe(true);
    });

    it('withdraws the moment the window loses focus, before any beat', () => {
        renderHook(() => useChatPresence());
        touch();
        focused = false;
        fire(window, 'blur');
        expect(sent()).toEqual([true, false]);
        advance(CHAT_BEAT_MS * 2);
        touch();
        expect(sent()).toEqual([true, false]);
    });

    it('withdraws when the tab is hidden and when the page goes away', () => {
        renderHook(() => useChatPresence());
        touch();
        setVisibility('hidden');
        fire(document, 'visibilitychange');
        expect(sent()).toEqual([true, false]);

        setVisibility('visible');
        advance(5000);
        touch();
        expect(sent()).toEqual([true, false, true]);
        fire(window, 'pagehide');
        expect(sent()).toEqual([true, false, true, false]);
    });

    it('withdraws when the chat leaves the screen (unmount)', () => {
        const { unmount } = renderHook(() => useChatPresence());
        touch();
        unmount();
        expect(sent()).toEqual([true, false]);
        touch();
        advance(CHAT_BEAT_MS * 2);
        expect(sent()).toEqual([true, false]);
    });

    it('counts a scroll inside the thread, which never bubbles', () => {
        renderHook(() => useChatPresence());
        const thread = document.body.appendChild(document.createElement('div'));
        fire(thread, 'scroll');
        expect(sent()).toEqual([true]);
        thread.remove();
    });

    it('spaces a claim after a withdrawal, so focus flapping stays inside the rate limit', () => {
        renderHook(() => useChatPresence());
        touch();
        for (let i = 0; i < 5; i++) {
            focused = false;
            fire(window, 'blur');
            focused = true;
            fire(window, 'focus');
            advance(200);
        }
        // One claim, one withdrawal: refocusing within the gap claims nothing yet...
        expect(sent()).toEqual([true, false]);
        // ...and the claim comes once the gap is over.
        advance(3000);
        expect(sent()).toEqual([true, false, true]);
    });

    it('tries a claim the socket could not take again at the next beat', () => {
        sendEvent.mockReturnValueOnce(false);
        renderHook(() => useChatPresence());
        touch();
        expect(sent()).toEqual([true]);
        // Nothing reached the server, so there is nothing to withdraw.
        focused = false;
        fire(window, 'blur');
        focused = true;
        fire(window, 'focus');
        expect(sent()).toEqual([true]);
        advance(CHAT_BEAT_MS - 1000);
        touch();
        advance(1000);
        expect(sent()).toEqual([true, true]);
    });

    it('withdraws only its own claim: each mount claims under an id of its own', () => {
        const first = renderHook(() => useChatPresence());
        renderHook(() => useChatPresence());
        touch();
        const ids = requests().map((request) => request.tab_id);
        expect(new Set(ids).size).toBe(2);
        first.unmount();
        expect(requests().at(-1)).toMatchObject({
            tab_id: ids[0],
            live: false,
        });
    });
});
