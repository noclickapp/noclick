import { describe, it, expect } from 'vitest';

import { formatQuantity } from './formatQuantity';

describe('formatQuantity', () => {
    it('labels the unit instead of showing a bare "tokens" number', () => {
        expect(formatQuantity(30, 'seconds')).toBe('30 seconds'); // a sandbox interval
        expect(formatQuantity(7, 'requests')).toBe('7 requests');
        expect(formatQuantity(1234, 'tokens')).toBe('1K tokens');
        expect(formatQuantity(2_500_000, 'tokens')).toBe('2.5M tokens');
    });

    it('singularizes a count of 1', () => {
        expect(formatQuantity(1, 'requests')).toBe('1 request');
        expect(formatQuantity(1, 'images')).toBe('1 image');
    });

    it('defaults to tokens and renders zero as a dash', () => {
        expect(formatQuantity(500)).toBe('500 tokens');
        expect(formatQuantity(0, 'seconds')).toBe('-');
    });
});
