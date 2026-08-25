// @vitest-environment jsdom
//
// Pins the endpoint resolvers for this edition. Their failure mode is silent
// and expensive in both directions: a resolver that guessed a hosted default
// would route an operator's uploads, cursors and MCP clients through somebody
// else's infrastructure while appearing to work, and a resolver that refused
// to derive anything would make a single-origin install — the shape every
// one-click deploy takes — impossible to configure at all.

import { describe, it, expect, beforeEach, afterEach } from 'vitest';
import {
    relayBaseUrl,
    apiBaseUrl,
    mcpServerUrl,
} from '~/lib/hostedDefaults';

const env = import.meta.env as Record<string, unknown>;
const VARS = ['VITE_RELAY_URL', 'VITE_API_URL'];

const set = (key: string, value: string | undefined) => {
    if (value === undefined) delete env[key];
    else env[key] = value;
};

// A developer's .env populates VITE_API_URL, so clear before as well as after:
// each case must control its own environment.
const clearAll = () => VARS.forEach((v) => set(v, undefined));
beforeEach(clearAll);
afterEach(clearAll);

describe('configured explicitly', () => {
    it('uses the configured URLs and trims trailing slashes', () => {
        set('VITE_API_URL', 'https://noclick.example.com/');
        set('VITE_RELAY_URL', 'wss://relay.example.com/');
        expect(apiBaseUrl()).toBe('https://noclick.example.com');
        expect(relayBaseUrl()).toBe('wss://relay.example.com');
        expect(mcpServerUrl()).toBe('https://noclick.example.com/mcp');
    });
});

describe('one origin, nothing configured', () => {
    it('answers with the origin the page came from', () => {
        // jsdom's default location. The single-container image and every
        // one-click host serve the app and the API from one hostname, so this
        // is the whole configuration for that deployment.
        expect(apiBaseUrl()).toBe('http://localhost:3000');
        expect(mcpServerUrl()).toBe('http://localhost:3000/mcp');
    });

    it('derives the relay from it, as ws on the same host', () => {
        expect(relayBaseUrl()).toBe('ws://localhost:3000/relay');
    });

});

describe('no origin to derive from', () => {
    it('fails loudly rather than guessing', () => {
        const { window: w } = globalThis as unknown as { window?: unknown };
        delete (globalThis as unknown as { window?: unknown }).window;
        try {
            expect(() => apiBaseUrl()).toThrow(/VITE_API_URL/);
            expect(() => relayBaseUrl()).toThrow(/VITE_RELAY_URL/);
        } finally {
            (globalThis as unknown as { window?: unknown }).window = w;
        }
    });
});
