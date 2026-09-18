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

describe('the number mask', () => {
    const cells = (s: string) => s.padEnd(10, ' ').split('').map((c) => (c === ' ' ? '' : c));
    it('turns filled cells into the provider query', async () => {
        const { searchQueryFromCells } = await import('~/lib/phoneFormat');
        expect(searchQueryFromCells(cells(''))).toEqual({ area_code: null, contains: null });
        expect(searchQueryFromCells(cells('424'))).toEqual({ area_code: '424', contains: null });
        expect(searchQueryFromCells(cells('424242'))).toEqual({ area_code: null, contains: '424242****' });
        expect(searchQueryFromCells(cells('   555'))).toEqual({ area_code: null, contains: '***555****' });
        expect(searchQueryFromCells(cells('   noclick'))).toEqual({ area_code: null, contains: '***NOCLICK' });
    });
});
