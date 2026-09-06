// The connect status is one derivation for three surfaces (Setup finale, MCP
// node panel, connect modal). It must keep the server side ("link ready")
// and the client side ("client connected") apart, and never render "cannot
// judge" as "never connected".
import { describe, expect, it } from 'vitest';
import {
    CONNECTED_WINDOW_S,
    PATIENCE_MS,
    deriveMcpConnectState,
    describeClient,
} from '~/lib/mcpConnectState';

const linked = {
    exists: true,
    is_active: true,
    liveness_available: true,
    tools_ready: 9,
    tools_sample: ['notion__search_pages_and_databases'],
};

describe('deriveMcpConnectState', () => {
    it('is minting until the URL is on screen and the row exists', () => {
        expect(deriveMcpConnectState(null, { hasUrl: false, waitedMs: 0 }).phase).toBe('minting');
        expect(deriveMcpConnectState({ exists: false }, { hasUrl: true, waitedMs: 0 }).phase).toBe('minting');
        expect(deriveMcpConnectState(linked, { hasUrl: false, waitedMs: 0 }).phase).toBe('minting');
    });

    it('waits, then escalates once the patience window passes', () => {
        const early = deriveMcpConnectState(linked, { hasUrl: true, waitedMs: PATIENCE_MS - 1 });
        expect(early.phase).toBe('waiting');
        expect(early.toolsReady).toBe(9);
        expect(early.toolsSample).toEqual(['notion__search_pages_and_databases']);
        expect(deriveMcpConnectState(linked, { hasUrl: true, waitedMs: PATIENCE_MS }).phase).toBe('waiting_long');
    });

    it('a fresh handshake is connected, carrying what the client was served', () => {
        const s = deriveMcpConnectState(
            {
                ...linked,
                seconds_since_seen: 12,
                client_name: 'opencode',
                client_version: '1.18.21',
                tool_count: 9,
                tool_names: ['a', 'b'],
            },
            { hasUrl: true, waitedMs: 999_999 }
        );
        expect(s.phase).toBe('connected');
        expect(s.toolCount).toBe(9);
        expect(s.toolNames).toEqual(['a', 'b']);
        expect(describeClient(s, 'your agent')).toBe('opencode 1.18.21');
    });

    it('a stale handshake is not connected — clients re-list on every start', () => {
        const s = deriveMcpConnectState(
            { ...linked, seconds_since_seen: CONNECTED_WINDOW_S, client_name: 'opencode' },
            { hasUrl: true, waitedMs: 0 }
        );
        expect(s.phase).toBe('waiting');
        expect(describeClient(s, 'your agent')).toBe('opencode');
    });

    it('an unreadable client side is unknown, never "waiting"', () => {
        const s = deriveMcpConnectState(
            { ...linked, liveness_available: false, seconds_since_seen: null },
            { hasUrl: true, waitedMs: PATIENCE_MS * 2 }
        );
        expect(s.phase).toBe('unknown');
    });

    it('a connected client outranks an unreadable blob and a long wait', () => {
        const s = deriveMcpConnectState(
            { ...linked, liveness_available: false, seconds_since_seen: 1 },
            { hasUrl: true, waitedMs: PATIENCE_MS * 2 }
        );
        expect(s.phase).toBe('connected');
    });

    it('a rotated link is inactive regardless of history', () => {
        const s = deriveMcpConnectState(
            { ...linked, is_active: false, seconds_since_seen: 1, client_name: 'codex' },
            { hasUrl: true, waitedMs: 0 }
        );
        expect(s.phase).toBe('inactive');
    });

    it('keeps the server story when the poll did not ask for tools', () => {
        const s = deriveMcpConnectState({ exists: true, is_active: true }, { hasUrl: true, waitedMs: 0 });
        expect(s.toolsReady).toBeNull();
        expect(s.toolsSample).toEqual([]);
    });
});
