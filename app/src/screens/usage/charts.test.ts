// The day columns' axis: a few round ticks from $0 up past the period's biggest day, each its own label, whether the
// biggest day is a fraction of a cent or thousands of dollars.
import { describe, expect, it } from 'vitest';
import { niceTicks } from './charts';

describe('niceTicks', () => {
    it.each<[number, number[]]>([
        [0, [0, 1]],
        [0.001, [0, 0.01]],
        [0.005, [0, 0.01]],
        [0.01, [0, 0.01]],
        [0.03, [0, 0.01, 0.02, 0.03]],
        [0.07, [0, 0.05, 0.1]],
        [1, [0, 0.5, 1]],
        [7.3, [0, 2.5, 5, 7.5]],
        [400.16, [0, 200, 400, 600]],
        [1234, [0, 500, 1000, 1500]],
    ])('reads a biggest day of $%s as %j', (max, ticks) => {
        expect(niceTicks(max)).toEqual(ticks);
    });

    it('gives every maximum distinct ticks a whole number of cents apart, the last at or above it', () => {
        for (let max = 0.0001; max < 100_000; max *= 1.01) {
            const ticks = niceTicks(max);
            expect(new Set(ticks).size, `${max}`).toBe(ticks.length);
            expect(ticks[0]).toBe(0);
            expect(ticks[ticks.length - 1], `${max}`).toBeGreaterThanOrEqual(max);
            expect(ticks.length, `${max}`).toBeLessThanOrEqual(5);
            for (const tick of ticks) expect(Math.round(tick * 100) / 100, `${max}`).toBe(tick);
        }
    });
});
