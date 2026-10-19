// The app's MCP setup guides name one server: this backend's own /mcp unless the deployment registers its own.
import { describe, expect, it, vi } from 'vitest';

describe('noclickMcp', () => {
    it('names this backend’s /mcp by default and the registered server once one is', async () => {
        vi.resetModules();
        vi.stubEnv('VITE_API_URL', 'https://api.example.test');
        const { noclickMcp, registerNoClickMcp } = await import('~/lib/noclickMcp');
        expect(noclickMcp().url).toBe('https://api.example.test/mcp');
        registerNoClickMcp({ url: 'https://mcp.example.test', intro: 'Everything.' });
        expect(noclickMcp()).toEqual({ url: 'https://mcp.example.test', intro: 'Everything.' });
        vi.unstubAllEnvs();
    });
});
