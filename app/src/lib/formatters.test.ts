import { describe, expect, it } from 'vitest';
import { formatDollars } from './formatters';

describe('formatDollars', () => {
    it('reads a price in dollars to the cent, grouped', () => {
        expect(formatDollars(12.99)).toBe('$12.99');
        expect(formatDollars(5)).toBe('$5.00');
        expect(formatDollars(1234.5)).toBe('$1,234.50');
        expect(formatDollars(0.004)).toBe('$0.00');
    });
});
