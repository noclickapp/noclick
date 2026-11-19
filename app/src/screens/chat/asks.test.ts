// @vitest-environment happy-dom
// A draft for the chat is taken once: one asked here (on its event, or when the chat opens), else one a page of a site
// left in storage while it's this visit's.
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { consumePendingAsk, onAskNoClick, stageAsk, STAGED_KEY } from './asks';

beforeEach(() => {
    window.localStorage.clear();
    consumePendingAsk();
});
afterEach(() => vi.useRealTimers());

describe('a draft for the chat', () => {
    it('tells an open chat, and is taken once with what it points at', () => {
        const heard = vi.fn();
        const stop = onAskNoClick(heard);
        const references = [{ kind: 'automation' as const, id: 'wf-1', label: 'Morning brief' }];
        stageAsk('Ask Morning brief to ', references);
        expect(heard).toHaveBeenCalledTimes(1);
        expect(consumePendingAsk()).toEqual({ text: 'Ask Morning brief to ', references });
        expect(consumePendingAsk()).toBeNull();
        stop();
        stageAsk('Again');
        expect(heard).toHaveBeenCalledTimes(1);
    });

    it('comes before a page’s draft, which waits for the next take', () => {
        window.localStorage.setItem(STAGED_KEY, JSON.stringify({ text: 'Set up my line', ts: Date.now() }));
        stageAsk('Build me an automation that ');
        expect(consumePendingAsk()).toEqual({ text: 'Build me an automation that ', references: undefined });
        expect(consumePendingAsk()).toEqual({ text: 'Set up my line' });
        expect(window.localStorage.getItem(STAGED_KEY)).toBeNull();
    });

    it('drops a page’s draft once it is no longer this visit’s, or unreadable', () => {
        vi.useFakeTimers();
        window.localStorage.setItem(STAGED_KEY, JSON.stringify({ text: 'Set up my line', ts: Date.now() }));
        vi.advanceTimersByTime(31 * 60 * 1000);
        expect(consumePendingAsk()).toBeNull();
        expect(window.localStorage.getItem(STAGED_KEY)).toBeNull();
        window.localStorage.setItem(STAGED_KEY, '{not json');
        expect(consumePendingAsk()).toBeNull();
        expect(window.localStorage.getItem(STAGED_KEY)).toBeNull();
    });
});
