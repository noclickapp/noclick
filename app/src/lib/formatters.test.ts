import { describe, expect, it } from 'vitest';
import { formatDollars, usageDollars } from './formatters';

describe('formatDollars', () => {
    it('reads a price in dollars to the cent, grouped', () => {
        expect(formatDollars(12.99)).toBe('$12.99');
        expect(formatDollars(5)).toBe('$5.00');
        expect(formatDollars(1234.5)).toBe('$1,234.50');
        expect(formatDollars(0.004)).toBe('$0.00');
    });
});

describe('usageDollars', () => {
    it('reads a metered amount to the cent from a dime up', () => {
        expect(usageDollars(150)).toBe('$150.00');
        expect(usageDollars(3.2)).toBe('$3.20');
        expect(usageDollars(0.125)).toBe('$0.13');
    });

    it('keeps a small charge to two significant figures instead of rounding it away', () => {
        expect(usageDollars(0.00625)).toBe('$0.0063'); // a 30s sandbox beat
        expect(usageDollars(0.0125)).toBe('$0.013'); // a full minute
        expect(usageDollars(0.0001)).toBe('$0.0001'); // the boundary stays exact
    });

    it('says nothing was charged, or less than a hundredth of a cent', () => {
        expect(usageDollars(0)).toBe('$0');
        expect(usageDollars(0.00001)).toBe('<$0.0001');
    });
});
