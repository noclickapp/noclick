// What a hosted MCP link's status means for the person waiting on it.
//
// `mcp_host:status` carries two independent stories: the SERVER side
// (`tools_ready` — what the link serves right now, resolved from the graph
// without any client) and the CLIENT side (the liveness blob a client's
// handshake stamps). One spinner conflating them left an owner unable to tell
// "NoClick is broken" from "my agent hasn't started yet" (2026-09-05: OpenCode
// connected 84s after the owner gave up on the finale). This derivation is
// pure so every surface — Setup finale, node panel, connect modal — reads the
// same status identically.

export interface HostedLinkStatus {
    exists?: boolean;
    is_active?: boolean;
    /** False when the client-side blob could not be read — "cannot judge", never "never connected". */
    liveness_available?: boolean;
    seconds_since_seen?: number | null;
    client_name?: string | null;
    client_version?: string | null;
    tool_count?: number | null;
    tool_names?: string[];
    last_method?: string | null;
    call_count?: number;
    /** Server side: what tools/list would return right now (null = not asked / unresolvable). */
    tools_ready?: number | null;
    tools_sample?: string[];
}

export type McpConnectPhase =
    /** No link yet (minting, or not minted). */
    | 'minting'
    /** Link exists but was rotated/revoked. */
    | 'inactive'
    /** The client-side blob is unreadable right now. */
    | 'unknown'
    /** A client handshook recently. */
    | 'connected'
    /** No recent handshake; the owner has waited past the patience window. */
    | 'waiting_long'
    /** No recent handshake yet. */
    | 'waiting';

export interface McpConnectState {
    phase: McpConnectPhase;
    /** Server side — true once the graph resolves to at least one tool. Null when not asked. */
    toolsReady: number | null;
    toolsSample: string[];
    clientName: string | null;
    clientVersion: string | null;
    /** Tools served on the last handshake (client side). */
    toolCount: number | null;
    toolNames: string[];
}

/** A handshake inside this window counts as connected. Clients re-list
 *  tools on every session start, so a stale blob means the client is gone. */
export const CONNECTED_WINDOW_S = 600;
/** After this long with no handshake, escalate from "waiting" to the
 *  client-specific check command — the usual cause is the client not having
 *  been started, which the waiting copy alone did not say. */
export const PATIENCE_MS = 45_000;

export function deriveMcpConnectState(
    status: HostedLinkStatus | null | undefined,
    opts: { hasUrl: boolean; waitedMs: number }
): McpConnectState {
    const base: McpConnectState = {
        phase: 'waiting',
        toolsReady: status?.tools_ready ?? null,
        toolsSample: status?.tools_sample ?? [],
        clientName: status?.client_name ?? null,
        clientVersion: status?.client_version ?? null,
        toolCount: status?.tool_count ?? null,
        toolNames: status?.tool_names ?? [],
    };
    if (!opts.hasUrl || !status?.exists) return { ...base, phase: 'minting' };
    if (status.is_active === false) return { ...base, phase: 'inactive' };
    if (
        status.seconds_since_seen != null &&
        status.seconds_since_seen < CONNECTED_WINDOW_S
    ) {
        return { ...base, phase: 'connected' };
    }
    if (status.liveness_available === false) return { ...base, phase: 'unknown' };
    return {
        ...base,
        phase: opts.waitedMs >= PATIENCE_MS ? 'waiting_long' : 'waiting',
    };
}

/** "opencode 1.18.21" / "Claude Code" — the client as it introduced itself. */
export function describeClient(state: McpConnectState, fallback: string): string {
    if (!state.clientName) return fallback;
    return state.clientVersion
        ? `${state.clientName} ${state.clientVersion}`
        : state.clientName;
}
