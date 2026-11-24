// @vitest-environment happy-dom
// A countdown that has run out asks for the next run two seconds later, while it's shown; once it's gone, nothing asks.
import { act, cleanup, render } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { NextRunWidget } from './NextRunWidget';

const PAST = '2020-01-01T09:00:00Z';

beforeEach(() => {
    vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout', 'setInterval', 'clearInterval'] });
});

afterEach(() => {
    cleanup();
    vi.useRealTimers();
});

describe('the next run’s countdown', () => {
    it('asks for the next run once its time has passed', () => {
        const onExpired = vi.fn();
        render(<NextRunWidget value={PAST} onExpired={onExpired} />);
        act(() => vi.advanceTimersByTime(2000));
        expect(onExpired).toHaveBeenCalledOnce();
    });

    it('asks nothing once it has gone, and leaves no timer behind', () => {
        const onExpired = vi.fn();
        // A new `onExpired` each render, as the form passes it: each render's refetch is held until the widget goes.
        const { unmount, rerender } = render(<NextRunWidget value={PAST} onExpired={() => onExpired()} />);
        rerender(<NextRunWidget value={PAST} onExpired={() => onExpired()} />);
        expect(vi.getTimerCount()).toBeGreaterThan(0);
        unmount();
        expect(vi.getTimerCount()).toBe(0);
        vi.runAllTimers();
        expect(onExpired).not.toHaveBeenCalled();
    });
});
