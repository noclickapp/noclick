// @vitest-environment happy-dom
// Who is typing: your own typing and another channel's never show, a mark lapses a few seconds after its last change
// and clears when they stop, and the composer says it's typing at most every few seconds, stops on clear or send, and
// tries again at the next key when it couldn't say it.
import { act, renderHook } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { ChannelChange, ChannelsTransport } from './transport';
import { TYPING_BEAT_MS, TYPING_TTL_MS, typingSignal, typistsAfter, useChannelTypists, useTypingSignal } from './typing';

afterEach(() => vi.useRealTimers());

const CHANNEL = '6b1f2c3d-4e5f-4a6b-8c7d-9e0f1a2b3c4d';
const T0 = Date.parse('2026-11-14T09:41:00Z');

const typing = (id: string, on = true, channelId = CHANNEL): ChannelChange => ({ kind: 'typing', channelId, typist: { id, name: id === 'account' ? 'Olu Owner' : 'Asha', typing: on } });

/** A transport that only follows changes and records what it was told you're typing. */
function following() {
    const listeners = new Set<(change: ChannelChange) => void>();
    const said: [string, boolean][] = [];
    const transport = {
        subscribe: (listener: (change: ChannelChange) => void) => {
            listeners.add(listener);
            return () => void listeners.delete(listener);
        },
        typing: async (channelId: string, on: boolean) => void said.push([channelId, on]),
    } as unknown as ChannelsTransport;
    return { transport, said, deliver: (change: ChannelChange) => listeners.forEach((listener) => listener(change)) };
}

describe('who is typing', () => {
    it('never shows your own typing, nor another channel’s, nor any other change', () => {
        expect(typistsAfter([], typing('account'), CHANNEL, 'account', T0)).toEqual([]);
        expect(typistsAfter([], typing('usr_asha', true, 'ch_other'), CHANNEL, 'account', T0)).toEqual([]);
        expect(typistsAfter([], { kind: 'message', channelId: CHANNEL }, CHANNEL, 'account', T0)).toEqual([]);
        // In a space you joined you're your user there; its owner is someone else.
        expect(typistsAfter([], typing('account'), CHANNEL, 'usr_me', T0)).toEqual([{ id: 'account', name: 'Olu Owner', until: T0 + TYPING_TTL_MS }]);
    });

    it('marks a typist until a few seconds after their last change, renewed by each, cleared when they stop', () => {
        vi.useFakeTimers({ now: T0 });
        const { transport, deliver } = following();
        const { result } = renderHook(() => useChannelTypists(transport, CHANNEL, 'account'));
        act(() => deliver(typing('usr_asha')));
        expect(result.current.map((t) => t.name)).toEqual(['Asha']);
        act(() => void vi.advanceTimersByTime(TYPING_TTL_MS - 1_000));
        expect(result.current).toHaveLength(1);
        // Renewed, it lasts from the renewal.
        act(() => deliver(typing('usr_asha')));
        act(() => void vi.advanceTimersByTime(TYPING_TTL_MS - 1_000));
        expect(result.current).toHaveLength(1);
        // No change for a while: it lapses by itself.
        act(() => void vi.advanceTimersByTime(1_001));
        expect(result.current).toEqual([]);
        act(() => deliver(typing('usr_asha')));
        act(() => deliver(typing('usr_asha', false)));
        expect(result.current).toEqual([]);
        // Yours never shows.
        act(() => deliver(typing('account')));
        expect(result.current).toEqual([]);
    });

    it('is said by the composer at most every few seconds while keys are pressed, and stopped on clear or send', () => {
        let now = T0;
        const sent: boolean[] = [];
        const signal = typingSignal(CHANNEL, async (_, on) => void sent.push(on), () => now);
        signal.stop();
        expect(sent).toEqual([]);
        signal.input('H');
        now += 1_000;
        signal.input('He');
        now += TYPING_BEAT_MS;
        signal.input('Hey');
        expect(sent).toEqual([true, true]);
        signal.input('  ');
        expect(sent).toEqual([true, true, false]);
        signal.input('Hey again');
        signal.stop();
        signal.stop();
        expect(sent).toEqual([true, true, false, true, false]);
    });

    it('tries again at the next key when it couldn’t be said', async () => {
        const now = T0;
        const sent: boolean[] = [];
        let refuse = true;
        const signal = typingSignal(CHANNEL, (_, on) => (sent.push(on), refuse ? Promise.reject(new Error('Not connected.')) : Promise.resolve()), () => now);
        signal.input('H');
        await Promise.resolve();
        refuse = false;
        // Within the same beat, but the first never reached anyone.
        signal.input('He');
        signal.input('Hey');
        expect(sent).toEqual([true, true]);
    });

    it('is said through the transport, and stopped when the page leaves the channel', () => {
        const { transport, said } = following();
        const { result, rerender, unmount } = renderHook(({ id }) => useTypingSignal(transport, id), { initialProps: { id: CHANNEL } });
        result.current.input('Hi');
        rerender({ id: 'ch_next' });
        result.current.input('Yo');
        unmount();
        expect(said).toEqual([
            [CHANNEL, true],
            [CHANNEL, false],
            ['ch_next', true],
            ['ch_next', false],
        ]);
    });
});
