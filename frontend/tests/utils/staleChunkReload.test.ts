/**
 * Tests for the stale-chunk reload helper: the per-browser transient error
 * wordings (Safari's dynamic-import message was the gap that showed iOS users
 * an error page) and the once-per-30s reload guard.
 */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import {
    isTransientChunkError,
    tryGuardedReload,
} from '~/lib/staleChunkReload';

describe('isTransientChunkError', () => {
    it.each([
        // Real prod messages from Honeycomb client.uncaught_error events
        'Failed to fetch dynamically imported module: https://www.noclick.com/assets/chunk-Becj3jr3.js',
        'TypeError: Failed to fetch',
        'NetworkError when attempting to fetch resource.',
        'Load failed',
        'Importing a module script failed.',
        'error loading dynamically imported module',
        'Unable to preload CSS for /assets/AgentChatTranscript-bCEHEDts.css',
    ])('matches transient wording: %s', (msg) => {
        expect(isTransientChunkError(msg)).toBe(true);
    });

    it.each([
        "Cannot read properties of undefined (reading 'x')",
        'Minified React error #418',
        'manifest version mismatch',
        'Request timeout',
    ])('does not match genuine bug: %s', (msg) => {
        expect(isTransientChunkError(msg)).toBe(false);
    });
});

describe('tryGuardedReload', () => {
    const reload = vi.fn();
    let store: Record<string, string>;

    beforeEach(() => {
        store = {};
        vi.stubGlobal('window', {
            sessionStorage: {
                getItem: (k: string) => store[k] ?? null,
                setItem: (k: string, v: string) => {
                    store[k] = v;
                },
            },
            location: { reload },
        });
    });

    afterEach(() => {
        vi.unstubAllGlobals();
        reload.mockClear();
    });

    it('reloads once and suppresses repeats inside the guard window', () => {
        expect(tryGuardedReload()).toBe(true);
        expect(reload).toHaveBeenCalledTimes(1);
        expect(tryGuardedReload()).toBe(false);
        expect(reload).toHaveBeenCalledTimes(1);
    });

    it('reloads again once the guard window has passed', () => {
        expect(tryGuardedReload()).toBe(true);
        store['nc_boundary_reload_at'] = String(Date.now() - 31_000);
        expect(tryGuardedReload()).toBe(true);
        expect(reload).toHaveBeenCalledTimes(2);
    });
});
