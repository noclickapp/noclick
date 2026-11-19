// The words a plan's usage reads in: when a window resets (a countdown later today, the day and time after), how much
// of it is used, and what the pill adds once the plan is near its limit.
import { describe, expect, it } from 'vitest';
import { clockAt, planShortfall, resetWhen, windowReset, windowUse } from './planWords';

// Tuesday 17 November 2026, 11:00 in the runner's own zone.
const NOW = new Date(2026, 10, 17, 11, 0, 0);
const at = (day: number, hour: number, minute = 0) =>
    new Date(2026, 10, day, hour, minute);

describe('resetWhen', () => {
    it('counts down to a reset later today, in minutes under an hour', () => {
        expect(resetWhen(at(17, 12, 40), NOW)).toBe('in 1 h 40 min');
        expect(resetWhen(at(17, 11, 38), NOW)).toBe('in 38 min');
        expect(resetWhen(at(17, 14, 0), NOW)).toBe('in 3 h');
        expect(resetWhen(new Date(NOW.getTime() + 20_000), NOW)).toBe(
            'in 1 min'
        );
    });

    it('names the day and time with AM/PM for anything later', () => {
        expect(resetWhen(at(18, 9), NOW)).toBe('tomorrow 9:00 AM');
        expect(resetWhen(at(19, 9), NOW)).toBe('Thu 9:00 AM');
        expect(resetWhen(at(23, 21, 30), NOW)).toBe('Mon 9:30 PM');
        expect(resetWhen(at(30, 9), NOW)).toBe('Nov 30 9:00 AM');
    });

    it('reads a reset already past as a minute away', () => {
        expect(resetWhen(at(17, 10), NOW)).toBe('in 1 min');
    });
});

describe('clockAt', () => {
    it('reads a moment as its clock today, with its day after', () => {
        expect(clockAt(at(17, 15, 20), NOW)).toBe('3:20 PM');
        expect(clockAt(at(17, 9, 5), NOW)).toBe('9:05 AM');
        expect(clockAt(at(18, 9), NOW)).toBe('tomorrow 9:00 AM');
        expect(clockAt(at(19, 9), NOW)).toBe('Thu 9:00 AM');
        expect(clockAt(at(30, 9), NOW)).toBe('Nov 30 9:00 AM');
    });

    it('reads a moment past as yesterday, else its date', () => {
        expect(clockAt(at(16, 15, 10), NOW)).toBe('yesterday 3:10 PM');
        expect(clockAt(at(15, 9), NOW)).toBe('Nov 15, 9:00 AM');
        expect(clockAt(at(3, 15, 10), NOW)).toBe('Nov 3, 3:10 PM');
    });
});

describe('a window', () => {
    it('says how much is used, never 100% before it is used up', () => {
        expect(windowUse({ used: 0.62, state: 'ok' })).toBe('62% used');
        expect(windowUse({ used: 0.998, state: 'near' })).toBe('99% used');
        expect(windowUse({ used: 1, state: 'used_up' })).toBe('Used up');
    });

    it('says when it resets, or once used up when it is back', () => {
        expect(
            windowReset({ state: 'near', resetsAt: at(17, 12, 40) }, NOW)
        ).toBe('resets in 1 h 40 min');
        expect(
            windowReset({ state: 'used_up', resetsAt: at(19, 9) }, NOW)
        ).toBe('back Thu 9:00 AM');
        expect(windowReset({ state: 'ok', resetsAt: null }, NOW)).toBeNull();
    });
});

describe('planShortfall', () => {
    const tightest = {
        kind: 'five_hour',
        label: '5-hour',
        models: [],
        used: 0.913,
        left: 0.087,
        resetsAt: null,
        state: 'near',
        raw: {},
    };
    it('says what is left, rounded down, once near; used up once used up; nothing below that', () => {
        expect(planShortfall({ state: 'near', tightest })).toBe('8% left');
        expect(
            planShortfall({
                state: 'near',
                tightest: { ...tightest, left: 0.09 },
            })
        ).toBe('9% left');
        expect(planShortfall({ state: 'used_up', tightest })).toBe('used up');
        expect(planShortfall({ state: 'ok', tightest })).toBeNull();
        expect(planShortfall({ state: 'unknown', tightest: null })).toBeNull();
        expect(planShortfall(null)).toBeNull();
    });
});
