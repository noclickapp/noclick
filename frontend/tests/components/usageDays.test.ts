// The usage page's days are the reader's: whatever zone the test runs in (CI is UTC; run it with TZ=Asia/Kolkata or
// TZ=America/Los_Angeles too), a day key and the instant it starts agree, and a window's days are the ones it touches.
import { expect, it } from 'vitest';
import { DAY_MS, ZONE, dayKey, dayStartOf, nextDay, periodOf, timeLabel } from '~/components/usage/page/derive';

const inZone = (t: number, opts: Intl.DateTimeFormatOptions) => new Intl.DateTimeFormat('en-US', { ...opts, timeZone: ZONE }).format(t);

it('names the day an instant falls on in the reader’s zone', () => {
    const t = Date.parse('2026-10-02T20:00:00Z');
    const [m, d, y] = inZone(t, { year: 'numeric', month: '2-digit', day: '2-digit' }).split('/');
    expect(dayKey(t)).toBe(`${y}-${m}-${d}`);
    expect(timeLabel('2026-10-02T20:00:00Z')).toBe(inZone(t, { hour: 'numeric', minute: '2-digit' }));
});

it('starts each day at its local midnight, across a month and a clock change', () => {
    for (let k = '2026-10-25'; k <= '2026-11-08'; k = nextDay(k)) {
        const start = dayStartOf(k);
        expect(dayKey(start)).toBe(k);
        expect(dayKey(start - 1)).toBe(nextDay(k, -1));
        expect(inZone(start, { hour: '2-digit', minute: '2-digit', hourCycle: 'h23' })).toBe('00:00');
    }
});

it('gives a window every day it touches, and today where now falls', () => {
    const p = periodOf('2026-11-01T00:00:00Z', '2026-12-01T00:00:00Z', '2026-11-15T07:18:00Z');
    expect(p.days[0]).toBe(dayKey(Date.parse('2026-11-01T00:00:00Z')));
    expect(p.days[p.days.length - 1]).toBe(dayKey(Date.parse('2026-12-01T00:00:00Z') - 1));
    expect(p.days.length).toBeGreaterThanOrEqual(30);
    expect(new Set(p.days).size).toBe(p.days.length);
    expect(p.todayKey).toBe(dayKey(Date.parse('2026-11-15T07:18:00Z')));
    expect(p.todayFraction).toBeGreaterThanOrEqual(0);
    expect(p.todayFraction).toBeLessThan(25 / 24);
    expect(p.remainingDays).toBeCloseTo((Date.parse('2026-12-01T00:00:00Z') - Date.parse('2026-11-15T07:18:00Z')) / DAY_MS);
});
