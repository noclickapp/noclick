// Pins the edition flag's default. isLocalEdition() gates surfaces the hosted
// service must keep (Google sign-in, the onboarding questionnaire), so a flipped
// default would silently strip them from production — where the var is unset.

import { describe, it, expect, afterEach } from 'vitest';
import { isLocalEdition } from '~/lib/edition';

const setFlag = (value: string | undefined) => {
    if (value === undefined) delete (import.meta.env as Record<string, unknown>).VITE_NOCLICK_LOCAL;
    else (import.meta.env as Record<string, unknown>).VITE_NOCLICK_LOCAL = value;
};

describe('isLocalEdition', () => {
    afterEach(() => setFlag(undefined));

    it('is false when the flag is unset — the hosted default', () => {
        setFlag(undefined);
        expect(isLocalEdition()).toBe(false);
    });

    it('is true only for the exact "1" the launcher writes', () => {
        setFlag('1');
        expect(isLocalEdition()).toBe(true);
    });

    it.each(['0', 'true', '', 'yes'])('does not treat %o as local', (value) => {
        setFlag(value);
        expect(isLocalEdition()).toBe(false);
    });
});
