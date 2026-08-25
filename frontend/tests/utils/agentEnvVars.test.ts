// Client-side validation for agent sandbox env vars. Pins the mirror of
// backend/nodes/agent/user_env.py — if the two drift, a user gets a name
// accepted in the editor that fails the run at dispatch.

import { describe, expect, it } from 'vitest';
import {
    blankValueNames,
    isReservedEnvName,
    parseRequestedEnvNames,
    rowsToEnv,
    validateEnvName,
} from '~/components/workflow/agentEnvVars';

describe('validateEnvName', () => {
    it('accepts ordinary names', () => {
        for (const name of ['STRIPE_KEY', 'api_base', '_X', 'A1']) {
            expect(validateEnvName(name)).toBeNull();
        }
    });

    it('rejects malformed names', () => {
        for (const name of ['1LEADING', 'HAS-DASH', 'HAS SPACE', 'a;b']) {
            expect(validateEnvName(name)).toMatch(/letters, digits/);
        }
    });

    it('rejects process-control variables', () => {
        for (const name of ['PATH', 'HOME', 'PYTHONPATH', 'LD_PRELOAD']) {
            expect(validateEnvName(name)).toMatch(/reserved/);
        }
    });

    it('rejects runtime-managed names by prefix', () => {
        expect(isReservedEnvName('NC_INTERNAL_TOKEN')).toBe(true);
        expect(validateEnvName('NC_ANYTHING')).toMatch(/reserved/);
    });

    it('rejects provider auth that belongs on the model credential', () => {
        for (const name of ['OPENAI_API_KEY', 'ANTHROPIC_API_KEY', 'CODEX_ACCESS_TOKEN']) {
            expect(validateEnvName(name)).toMatch(/reserved/);
        }
    });
});

describe('parseRequestedEnvNames', () => {
    it('reads both string and {name} entries, skipping malformed', () => {
        expect(parseRequestedEnvNames(['STRIPE_KEY', { name: 'SENTRY_DSN', description: 'd' }]))
            .toEqual(['STRIPE_KEY', 'SENTRY_DSN']);
        expect(parseRequestedEnvNames([{ nope: 1 }, '', '  ', 42])).toEqual([]);
    });

    it('returns [] for a non-array (the common no-declaration case)', () => {
        expect(parseRequestedEnvNames(undefined)).toEqual([]);
        expect(parseRequestedEnvNames(null)).toEqual([]);
        expect(parseRequestedEnvNames('STRIPE_KEY')).toEqual([]);
    });
});

describe('blankValueNames', () => {
    it('flags the vars an edit would silently erase', () => {
        // credential:update replaces the whole blob and the browser never holds the
        // stored values, so saving a blank field wipes a working secret.
        expect(blankValueNames({ A: 'set', B: '', C: '' })).toEqual(['B', 'C']);
    });

    it('reports nothing when every value is supplied', () => {
        expect(blankValueNames({ A: '1', B: '2' })).toEqual([]);
        expect(blankValueNames({})).toEqual([]);
    });
});

describe('rowsToEnv', () => {
    it('collapses rows into a bundle', () => {
        expect(
            rowsToEnv([
                { key: 'STRIPE_KEY', value: 'sk_1' },
                { key: 'API_BASE', value: 'https://x' },
            ])
        ).toEqual({ STRIPE_KEY: 'sk_1', API_BASE: 'https://x' });
    });

    it('skips untouched blank rows but keeps empty-valued vars', () => {
        expect(rowsToEnv([{ key: '', value: '' }, { key: 'A', value: '' }])).toEqual({ A: '' });
    });

    it('throws rather than dropping an invalid name', () => {
        expect(() => rowsToEnv([{ key: 'OK', value: '1' }, { key: 'PATH', value: '/evil' }]))
            .toThrow(/reserved/);
    });

    it('rejects a value with no name', () => {
        expect(() => rowsToEnv([{ key: '', value: 'orphan' }])).toThrow(/needs a variable name/);
    });

    it('rejects duplicates instead of silently last-wins', () => {
        expect(() => rowsToEnv([{ key: 'A', value: '1' }, { key: 'A', value: '2' }]))
            .toThrow(/more than once/);
    });
});
