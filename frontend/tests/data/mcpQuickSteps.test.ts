// The client snippets are copied verbatim into terminals and config files, so
// each one pins the shape its client's docs specify (verified 2026-09), and
// every client that has a guide must say what makes it connect — the
// "waiting for it" line alone lost a visitor whose client only connects on
// launch (2026-09-05).
import { describe, expect, it } from 'vitest';
import {
    MCP_CONNECT_HINTS,
    MCP_QUICK_STEPS,
    connectHintFor,
    cursorDeeplink,
} from '~/data/mcpQuickSteps';
import { MCP_CLIENT_GUIDES } from '~/components/workflow/MCPConnectModal';

const URL = 'https://mcp.noclick.app/s/00000000-0000-4000-8000-000000000000';
const NAME = 'noclick-notion';

function codeBlocks(key: string): string[] {
    const guide = MCP_CLIENT_GUIDES.find((g) => g.key === key);
    if (!guide) throw new Error(`no guide for ${key}`);
    return guide
        .blocks(URL, NAME)
        .filter((b): b is { kind: 'code'; title: string; code: string } => b.kind === 'code')
        .map((b) => b.code);
}

function firstJson(key: string): Record<string, any> {
    for (const code of codeBlocks(key)) {
        if (code.trim().startsWith('{')) return JSON.parse(code);
    }
    throw new Error(`no JSON block for ${key}`);
}

describe('connect hints', () => {
    it('every client guide and every quick-step client names what makes it connect', () => {
        const keys = new Set([...MCP_CLIENT_GUIDES.map((g) => g.key), ...Object.keys(MCP_QUICK_STEPS)]);
        const missing = [...keys].filter((k) => !MCP_CONNECT_HINTS[k]?.trigger);
        expect(missing).toEqual([]);
    });

    it('unknown clients fall back to the generic hint', () => {
        expect(connectHintFor('some-new-client')).toBe(MCP_CONNECT_HINTS.other);
    });

    it('the CLIs whose list command probes the server offer it as the check', () => {
        expect(MCP_CONNECT_HINTS['claude-code'].check).toMatchObject({ code: 'claude mcp list', terminal: true });
        expect(MCP_CONNECT_HINTS.opencode.check).toMatchObject({ code: 'opencode mcp list', terminal: true });
        // opencode mcp add writes config only — the hint must say so.
        expect(MCP_CONNECT_HINTS.opencode.trigger).toMatch(/only saves the config/);
    });
});

describe('client snippets match their docs', () => {
    it('claude code: http transport, name before url; .mcp.json uses mcpServers + type http', () => {
        expect(MCP_QUICK_STEPS['claude-code'](URL, NAME)[0].code).toBe(`claude mcp add --transport http ${NAME} ${URL}`);
        expect(firstJson('claude-code')).toEqual({ mcpServers: { [NAME]: { type: 'http', url: URL } } });
    });

    it('codex: --url flag and a [mcp_servers.<name>] TOML table', () => {
        expect(MCP_QUICK_STEPS.codex(URL, NAME)[0].code).toBe(`codex mcp add ${NAME} --url ${URL}`);
        expect(codeBlocks('codex')).toContain(`[mcp_servers.${NAME}]\nurl = "${URL}"`);
    });

    it('opencode: remote type in opencode.json under mcp', () => {
        expect(firstJson('opencode')).toEqual({ mcp: { [NAME]: { type: 'remote', url: URL, enabled: true } } });
    });

    it('cursor: url-only entry and a deeplink whose config decodes to {url}', () => {
        expect(firstJson('cursor')).toEqual({ mcpServers: { [NAME]: { url: URL } } });
        const link = cursorDeeplink(URL, NAME);
        expect(link.startsWith('cursor://anysphere.cursor-deeplink/mcp/install?')).toBe(true);
        const params = new URLSearchParams(link.slice(link.indexOf('?') + 1));
        expect(params.get('name')).toBe(NAME);
        expect(JSON.parse(atob(params.get('config')!))).toEqual({ url: URL });
    });

    it('vs code: servers + type http, and the code --add-mcp one-liner', () => {
        expect(firstJson('vscode')).toEqual({ servers: { [NAME]: { type: 'http', url: URL } } });
        const oneLiner = MCP_QUICK_STEPS.vscode(URL, NAME)[0].code!;
        expect(oneLiner.startsWith("code --add-mcp '")).toBe(true);
        expect(JSON.parse(oneLiner.slice("code --add-mcp '".length, -1))).toEqual({ name: NAME, type: 'http', url: URL });
    });

    it('windsurf: serverUrl key in mcp_config.json', () => {
        expect(firstJson('windsurf')).toEqual({ mcpServers: { [NAME]: { serverUrl: URL } } });
    });

    it('zed: native remote url under context_servers, mcp-remote only as the legacy bridge', () => {
        const [primary, legacy] = codeBlocks('zed').map((c) => JSON.parse(c));
        expect(primary).toEqual({ context_servers: { [NAME]: { url: URL } } });
        expect(legacy.context_servers[NAME].args).toEqual(['-y', 'mcp-remote', URL]);
    });

    it('generic clients get streamable-http', () => {
        expect(firstJson('other')).toEqual({ mcpServers: { [NAME]: { type: 'streamable-http', url: URL } } });
    });

    it('every snippet carries the real URL, never a placeholder', () => {
        for (const guide of MCP_CLIENT_GUIDES) {
            const codes = codeBlocks(guide.key).join('\n');
            expect(codes, guide.key).toContain(URL);
        }
    });
});
