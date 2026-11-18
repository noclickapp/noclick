import { describe, expect, it } from 'vitest';
import { formatPhoneForDisplay, patternSpan } from '@/lib/phoneFormat';

describe('phone formatting', () => {
    it('groups a number for display', () => {
        expect(formatPhoneForDisplay('+12065550142')).toBe('+1 206 555 0142');
        expect(formatPhoneForDisplay('+919812345678')).toBe('+91 981 234 5678');
    });

    it('finds where a keypad pattern matched', () => {
        expect(patternSpan('+12065550142', '655')).toEqual([3, 6]);
        expect(patternSpan('+12065550142', '6*5')).toEqual([3, 6]);
        expect(patternSpan('+12065550142', 'MJK')).toEqual([3, 6]); // M=6, J=5, K=5
        expect(patternSpan('+12065550142', '999')).toBeNull();
        expect(patternSpan('+12065550142', '')).toBeNull();
    });
});

describe('the number search', () => {
    it('reads one string as an area code or an anywhere pattern', async () => {
        const { searchQueryFromText } = await import('@/lib/phoneFormat');
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
