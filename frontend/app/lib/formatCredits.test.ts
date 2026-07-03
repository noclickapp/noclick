import { describe, it, expect } from 'vitest';

import { formatCredits } from './formatCredits';

describe('formatCredits', () => {
    it('shows small sandbox charges accurately (was misleadingly rounded to 0.03)', () => {
        expect(formatCredits(0.025)).toBe('0.025 credits'); // a 30s sandbox interval = 0.05 cr/min
        expect(formatCredits(0.05)).toBe('0.050 credits'); // a full minute
    });

    it('keeps larger amounts compact', () => {
        expect(formatCredits(0)).toBe('0 credits');
        expect(formatCredits(0.5)).toBe('0.50 credits');
        expect(formatCredits(3.2)).toBe('3.2 credits');
        expect(formatCredits(150)).toBe('150 credits');
    });

    it('uses 4 decimals for sub-milli amounts', () => {
        expect(formatCredits(0.0005)).toBe('0.0005 credits');
    });

    it('floors below 0.0001 instead of rounding real charges to "0.0000"', () => {
        expect(formatCredits(0.00004)).toBe('<0.0001 credits'); // ~28-token gpt-4o-mini call
        expect(formatCredits(0.0001)).toBe('0.0001 credits'); // boundary stays exact
    });
});
