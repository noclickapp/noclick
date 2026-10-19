import { afterEach, describe, expect, it, vi } from 'vitest';
import { webcrypto } from 'node:crypto';
import { secureRandomId } from './secureRandom';

const UUID_V4 = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

describe('secureRandomId', () => {
    afterEach(() => {
        vi.unstubAllGlobals();
    });

    it('returns distinct UUID-shaped values', () => {
        const first = secureRandomId();
        const second = secureRandomId();

        expect(first).toMatch(UUID_V4);
        expect(second).not.toBe(first);
    });

    it('mints a UUID v4 where randomUUID is missing (a non-secure origin)', () => {
        // Plain-http pages lack crypto.randomUUID but keep getRandomValues; the
        // builder accepts only a UUID as a new chat's id.
        vi.stubGlobal('crypto', { getRandomValues: webcrypto.getRandomValues.bind(webcrypto) });

        const first = secureRandomId();
        expect(first).toMatch(UUID_V4);
        expect(secureRandomId()).not.toBe(first);
    });
});
