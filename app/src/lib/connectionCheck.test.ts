import { describe, expect, it } from 'vitest';
import { checkVerdict } from './connectionCheck';

describe('a check’s verdict', () => {
    it('is working or rejected only on the provider’s own answer', () => {
        expect(checkVerdict({ reachable: true })).toBe('working');
        expect(checkVerdict({ reachable: false })).toBe('rejected');
        expect(checkVerdict({ reachable: null })).toBe('unverified');
        expect(checkVerdict({})).toBe('unverified');
        expect(checkVerdict(null)).toBe('unverified');
        expect(checkVerdict(undefined)).toBe('unverified');
    });
});
