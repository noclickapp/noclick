import { describe, expect, it } from 'vitest';
import { formatPhoneForDisplay, patternSpan } from '~/lib/phoneFormat';

describe('phone formatting', () => {
    it('groups a number for display', () => {
        expect(formatPhoneForDisplay('+15674833618')).toBe('+1 567 483 3618');
        expect(formatPhoneForDisplay('+919717440092')).toBe('+91 971 744 0092');
    });

    it('finds where a keypad pattern matched', () => {
        expect(patternSpan('+15674833618', '483')).toEqual([4, 7]);
        expect(patternSpan('+15674833618', '4*3')).toEqual([4, 7]);
        expect(patternSpan('+15674833618', 'HUD')).toEqual([4, 7]); // H=4, U=8, D=3
        expect(patternSpan('+15674833618', '999')).toBeNull();
        expect(patternSpan('+15674833618', '')).toBeNull();
    });
});

describe('the number search', () => {
    it('reads one string as an area code or an anywhere pattern', async () => {
        const { searchQueryFromText } = await import('~/lib/phoneFormat');
        expect(searchQueryFromText('')).toEqual({ area_code: null, contains: null });
        expect(searchQueryFromText('415')).toEqual({ area_code: '415', contains: null });
        expect(searchQueryFromText('(415) ')).toEqual({ area_code: '415', contains: null });
        expect(searchQueryFromText('555')).toEqual({ area_code: '555', contains: null });
        expect(searchQueryFromText('4242')).toEqual({ area_code: null, contains: '4242' });
        expect(searchQueryFromText('no click')).toEqual({ area_code: null, contains: 'NOCLICK' });
        expect(searchQueryFromText('4*2')).toEqual({ area_code: null, contains: '4*2' });
        expect(searchQueryFromText('12345678901234')).toEqual({ area_code: null, contains: '1234567890' });
    });
});
