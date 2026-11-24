// @vitest-environment happy-dom
// Work a canvas component puts off runs while it's mounted, and is dropped when it unmounts: nothing left pending, and
// nothing scheduled by a handler that asks only after the component has gone.
import { renderHook } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { useLater, useNextFrame } from './useLater';

beforeEach(() => {
    vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout', 'requestAnimationFrame', 'cancelAnimationFrame'] });
});

afterEach(() => {
    vi.useRealTimers();
});

describe('useLater', () => {
    it('runs what it was given once the time is up', () => {
        const { result, unmount } = renderHook(() => useLater());
        const fn = vi.fn();
        result.current(fn, 100);
        vi.advanceTimersByTime(99);
        expect(fn).not.toHaveBeenCalled();
        vi.advanceTimersByTime(1);
        expect(fn).toHaveBeenCalledOnce();
        expect(vi.getTimerCount()).toBe(0);
        unmount();
    });

    it('drops every timer still waiting when the component unmounts', () => {
        const { result, unmount } = renderHook(() => useLater());
        const fn = vi.fn();
        result.current(fn);
        result.current(fn, 2000);
        expect(vi.getTimerCount()).toBe(2);
        unmount();
        expect(vi.getTimerCount()).toBe(0);
        vi.runAllTimers();
        expect(fn).not.toHaveBeenCalled();
    });

    it('schedules nothing once the component has gone', () => {
        const { result, unmount } = renderHook(() => useLater());
        const later = result.current;
        unmount();
        const fn = vi.fn();
        later(fn, 10);
        expect(vi.getTimerCount()).toBe(0);
        vi.runAllTimers();
        expect(fn).not.toHaveBeenCalled();
    });

    it('is the same function for the component’s life', () => {
        const { result, rerender, unmount } = renderHook(() => useLater());
        const first = result.current;
        rerender();
        expect(result.current).toBe(first);
        unmount();
    });
});

describe('useNextFrame', () => {
    it('runs on the next frame while mounted, and is dropped when the component unmounts', () => {
        const { result, unmount } = renderHook(() => useNextFrame());
        const ran = vi.fn();
        result.current(ran);
        vi.advanceTimersToNextFrame();
        expect(ran).toHaveBeenCalledOnce();

        const dropped = vi.fn();
        result.current(dropped);
        expect(vi.getTimerCount()).toBe(1);
        unmount();
        expect(vi.getTimerCount()).toBe(0);
        vi.runAllTimers();
        expect(dropped).not.toHaveBeenCalled();
        result.current(dropped);
        expect(vi.getTimerCount()).toBe(0);
    });
});
