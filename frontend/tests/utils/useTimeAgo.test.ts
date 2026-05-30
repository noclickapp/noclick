// Unit tests for formatTimeAgo, the pure relative-time core of ~/hooks/useTimeAgo.
// Every case passes an explicit `now` argument so the assertions are deterministic
// and never depend on the real wall clock. Added because formatTimeAgo was exported
// but untested; these lock in the bucket boundaries plus the non-finite and
// future-timestamp (clock-skew) guards.

import { describe, it, expect } from 'vitest';
import { formatTimeAgo } from '~/hooks/useTimeAgo';

describe('formatTimeAgo', () => {
    // Fixed reference point so every case is wall-clock independent.
    const now = 1_700_000_000_000;
    const sec = 1000;
    const min = 60 * sec;
    const hr = 60 * min;
    const day = 24 * hr;

    it('renders "just now" under 3 seconds', () => {
        expect(formatTimeAgo(now, now)).toBe('just now');
        expect(formatTimeAgo(now - 2 * sec, now)).toBe('just now');
    });

    it('renders seconds between 3s and 59s', () => {
        expect(formatTimeAgo(now - 5 * sec, now)).toBe('5s ago');
        expect(formatTimeAgo(now - 59 * sec, now)).toBe('59s ago');
    });

    it('renders minutes between 1m and 59m', () => {
        expect(formatTimeAgo(now - 1 * min, now)).toBe('1m ago');
        expect(formatTimeAgo(now - 5 * min, now)).toBe('5m ago');
        expect(formatTimeAgo(now - 59 * min, now)).toBe('59m ago');
    });

    it('renders hours between 1h and 23h', () => {
        expect(formatTimeAgo(now - 1 * hr, now)).toBe('1h ago');
        expect(formatTimeAgo(now - 23 * hr, now)).toBe('23h ago');
    });

    it('renders days at 24h and beyond', () => {
        expect(formatTimeAgo(now - 1 * day, now)).toBe('1d ago');
        expect(formatTimeAgo(now - 10 * day, now)).toBe('10d ago');
    });

    it('returns the empty string for a non-finite timestamp (NaN guard)', () => {
        expect(formatTimeAgo(NaN, now)).toBe('');
        expect(formatTimeAgo(Infinity, now)).toBe('');
    });

    it('clamps a future timestamp to "just now" (clock-skew guard)', () => {
        expect(formatTimeAgo(now + 10 * min, now)).toBe('just now');
    });
});
