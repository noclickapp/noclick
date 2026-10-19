import { describe, expect, it } from 'vitest';
import { getAuthAside, registerAuthAside } from './authAside';

describe('auth aside', () => {
    it('is absent until a deployment registers one, so the open edition shows the form alone', () => {
        expect(getAuthAside()).toBeNull();
        const Aside = () => null;
        registerAuthAside(Aside);
        expect(getAuthAside()).toBe(Aside);
    });
});
