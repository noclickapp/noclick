// Plain-http self-hosted installs have no crypto.randomUUID (insecure
// context); the polyfill must produce well-formed v4 ids there and leave a
// native implementation alone.
import { describe, expect, it } from 'vitest';

describe('crypto.randomUUID polyfill', () => {
    it('fills the gap with well-formed v4 ids when the native fn is absent', async () => {
        const original = crypto.randomUUID?.bind(crypto);
        // Simulate an insecure context.
        Object.defineProperty(crypto, 'randomUUID', { value: undefined, configurable: true });
        delete (crypto as unknown as Record<string, unknown>).randomUUID;
        await import('~/lib/cryptoRandomUuidPolyfill');
        const id = crypto.randomUUID();
        expect(id).toMatch(/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/);
        expect(new Set([id, crypto.randomUUID(), crypto.randomUUID()]).size).toBe(3);
        if (original) Object.defineProperty(crypto, 'randomUUID', { value: original, configurable: true });
    });
});
