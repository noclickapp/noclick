// An MCP server NoClick hosts on the platform, as its connect card reads it: the server (its link, what it serves) and
// the clients that reached it (`/v1/mcp_servers/{id}/clients`, recorded by the server itself as they connect), read
// again the moment one connects (a platform:resource frame for the server) and on a slow timer as the backstop. Its
// status is the hosted link's own shape, so the card says connected, waiting or replaced as every MCP card does.
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useClient } from '@/sdk/client';
import { McpServer, NotFound } from 'noclick';
import { useWorkFrames } from '@/sdk/live';
import { deriveMcpConnectState, type HostedLinkStatus, type McpConnectState } from '@/lib/mcpConnectState';

/** How often a card still waiting on a client reads again when no frame came. */
export const WAITING_READ_MS = 15_000;

export interface McpServerView {
    id: string;
    name: string;
    url: string;
    tools: unknown[];
    tool_count: number;
    last_client_at: string | null;
}

export interface McpClientView {
    name: string;
    version: string | null;
    first_seen_at: string;
    last_seen_at: string;
    tool_count: number | null;
}

/** A served entry's tool name ("reddit.get_subreddit_posts", or an entry naming one). */
export function servedToolName(entry: unknown): string | undefined {
    if (typeof entry === 'string') return entry;
    if (entry && typeof entry === 'object') {
        const named = (entry as Record<string, unknown>).tool ?? (entry as Record<string, unknown>).name;
        return typeof named === 'string' ? named : undefined;
    }
    return undefined;
}

/** The server and its clients as a hosted link's status: the newest client is the one connected, if it was seen
 *  lately; the link has worked once a client listed tools. */
export function linkStatusOf(server: McpServerView, clients: readonly McpClientView[], now: number): HostedLinkStatus {
    const latest = clients[0];
    const listed = clients.filter((c) => (c.tool_count ?? 0) > 0);
    return {
        exists: true,
        is_active: true,
        liveness_available: true,
        client_name: latest?.name ?? null,
        client_version: latest?.version ?? null,
        tool_count: latest?.tool_count ?? null,
        seconds_since_seen: latest ? Math.max(0, (now - Date.parse(latest.last_seen_at)) / 1000) : null,
        first_tools_at: listed.length ? Math.min(...listed.map((c) => Date.parse(c.first_seen_at) / 1000)) : null,
        tools_ready: server.tool_count,
        tools_sample: server.tools.map(servedToolName).filter((n): n is string => !!n),
    };
}

export function useMcpServerConnect(serverId: string, { enabled = true }: { enabled?: boolean } = {}) {
    const client = useClient();
    const handle = useMemo(() => McpServer.fromId(serverId, { client, user: null }), [client, serverId]);
    const [server, setServer] = useState<McpServerView | null>(null);
    const [clients, setClients] = useState<McpClientView[] | null>(null);
    const [gone, setGone] = useState(false);
    const [now, setNow] = useState(() => Date.now());
    const shownAt = useRef(Date.now());

    const read = useCallback(async () => {
        try {
            // Read first: the handle then knows the server, and its clients are one call more.
            const view = await handle.refresh();
            const seen = await handle.clients();
            setServer(view.raw as unknown as McpServerView);
            setClients(seen.map((c) => c.raw as unknown as McpClientView));
            setNow(Date.now());
        } catch (error) {
            if (error instanceof NotFound) setGone(true);
            else console.warn('[coordinator] reading the MCP server failed:', error);
        }
    }, [handle]);

    useWorkFrames(
        'platform:resource',
        (frame) => {
            if (enabled && frame.kind === 'mcp_server' && frame.id === serverId) void read();
        }
    );

    const status = server && clients ? linkStatusOf(server, clients, now) : null;
    const state: McpConnectState = deriveMcpConnectState(status, { hasUrl: !!server, waitedMs: now - shownAt.current });
    const waiting = state.phase !== 'connected';

    useEffect(() => {
        if (!enabled || gone) return;
        void read();
        const look = () => void read();
        window.addEventListener('focus', look);
        const timer = waiting ? window.setInterval(look, WAITING_READ_MS) : undefined;
        return () => {
            window.removeEventListener('focus', look);
            window.clearInterval(timer);
        };
    }, [enabled, gone, waiting, read]);

    /** A new link in place of this one: the old one stops answering at once. */
    const renew = useCallback(async () => {
        setServer((await handle.rotate()).raw as unknown as McpServerView);
    }, [handle]);

    return { server, status, state, gone, renew };
}
