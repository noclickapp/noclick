import { describe, expect, it } from 'vitest';
import { secureRandomId } from './secureRandom';

describe('secureRandomId', () => {
    it('returns distinct UUID-shaped values', () => {
        const first = secureRandomId();
        const second = secureRandomId();

        expect(first).toMatch(
            /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i
        );
        expect(second).not.toBe(first);
    });
});
