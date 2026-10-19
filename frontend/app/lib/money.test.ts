import { afterEach, describe, expect, it } from 'vitest';

import { HOSTED_CREDITS_PER_DOLLAR, formatUsage, formatUsd, setCreditsPerDollar } from './money';

describe('money', () => {
    afterEach(() => setCreditsPerDollar(HOSTED_CREDITS_PER_DOLLAR));

    it('reads credits as dollars at the hosted rate', () => {
        setCreditsPerDollar(HOSTED_CREDITS_PER_DOLLAR);
        expect(formatUsd(100)).toBe('$25.00');
        expect(formatUsage(600)).toBe('$150.00');
        expect(formatUsage(12.8)).toBe('$3.20');
        expect(formatUsage(0.5)).toBe('$0.13');
    });

    it('keeps small sandbox charges accurate instead of rounding them', () => {
        setCreditsPerDollar(HOSTED_CREDITS_PER_DOLLAR);
        expect(formatUsage(0.025)).toBe('$0.0063'); // a 30s warm-sandbox beat
        expect(formatUsage(0.05)).toBe('$0.013'); // a full minute
    });

    it('floors below a hundredth of a cent instead of showing zero', () => {
        setCreditsPerDollar(HOSTED_CREDITS_PER_DOLLAR);
        expect(formatUsage(0)).toBe('$0');
        expect(formatUsage(0.00004)).toBe('<$0.0001'); // a ~28-token model call
        expect(formatUsage(0.0004)).toBe('$0.0001'); // the boundary stays exact
    });

    it('counts dollars where the instance bills nobody', () => {
        setCreditsPerDollar(1);
        expect(formatUsd(3.2)).toBe('$3.20');
        expect(formatUsage(0.025)).toBe('$0.025');
    });
});
