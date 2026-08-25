// Module-level owner of WorkflowPresenceService connections, decoupled
// from React mount lifecycle. Two signals keep a connection alive on a
// workflow: the canvas being mounted, OR an active gen running for that
// workflow. When neither is true, the connection is torn down.
//
// Why this exists: the originating FE used to drop its presence
// connection on canvas unmount, so agentic mutations during background
// gens never reached the workflow relay (no relay), and remote manual
// edits never reached liveGraphStore. Lifting the lifecycle here lets
// us:
//   • Forward `active_gen:graph_event` mutations into the gen's
//     workflow's room — other viewers see the agent's edits live, even
//     when this FE has navigated to a different workflow.
//   • Subscribe to remote workflow-change events even when the canvas
//     is unmounted, applying them to liveGraphStore so the background
//     graph stays current.
//
// The hook (useCollaborativePresence) delegates connect/disconnect to
// this manager via acquireForCanvas / releaseFromCanvas — it remains
// the React-state surface for collaborator avatars / cursors / etc.,
// but no longer owns the WebSocket lifetime.

import { sendEventAsync } from '~/lib/socket-sender';
import { onSocketEvent } from '~/lib/socket-receiver';
import { activeGenStore } from '~/lib/activeGenStore';
import {
    getWorkflowPresenceService,
    disposeWorkflowPresenceService,
} from '~/lib/collaboration/workflowPresenceService';
import {
    isCanvasMountedFor,
    applyRemoteNodeAdd,
    applyRemoteNodeUpdate,
    applyRemoteNodeRemove,
    applyRemoteEdgeAdd,
    applyRemoteEdgeRemove,
} from '~/lib/liveGraphStore';

interface LocalUser {
    id: string;
    name: string;
    email?: string;
    avatarUrl?: string;
}

const DEFAULT_LOCAL_USER: LocalUser = {
    id: 'local-user',
    name: 'You',
    email: 'you@example.com',
};

interface ManagedConnection {
    workflowId: string;
    /** True while this manager has called `service.connect` and not yet `service.disconnect`. */
    connected: boolean;
    /** Token cached so we don't re-fetch on every acquire. */
    token: string | null;
    tokenExpiry: number;
    /** Reference holders — connection lives while either is true. */
    canvasHeld: boolean;
    genHeld: boolean;
    /** In-flight token fetch / connect, awaited by concurrent acquirers. */
    connectInFlight: Promise<void> | null;
    /** Subscription that applies remote workflow-change events into
     *  liveGraphStore while the canvas is unmounted (the canvas hook
     *  has its own subscription that updates canvas state when mounted). */
    unsubRemoteForBackground: (() => void) | null;
}

const connections: Map<string, ManagedConnection> = new Map();

async function fetchToken(workflowId: string): Promise<string | null> {
    try {
        const response = await sendEventAsync({
            event_name: 'workflow:collab_token',
            workflow_id: workflowId,
        } as never) as { success?: boolean; token?: string; expires_at?: number; message?: string } | null;
        if (response?.success && response.token) {
            const conn = connections.get(workflowId);
            if (conn) {
                conn.token = response.token;
                conn.tokenExpiry = response.expires_at || 0;
            }
            return response.token;
        }
        console.error('[presenceManager] token fetch failed:', response?.message);
    } catch (e) {
        console.error('[presenceManager] token fetch error:', e);
    }
    return null;
}

function tokenIsValid(conn: ManagedConnection): boolean {
    if (!conn.token) return false;
    if (!conn.tokenExpiry) return true; // unset → assume valid for this session
    return Date.now() / 1000 < conn.tokenExpiry - 60;
}

async function ensureConnected(conn: ManagedConnection, localUser: LocalUser): Promise<void> {
    if (conn.connected) return;
    if (conn.connectInFlight) return conn.connectInFlight;

    conn.connectInFlight = (async () => {
        try {
            const token = tokenIsValid(conn) ? conn.token! : await fetchToken(conn.workflowId);
            if (!token) return;
            // Concurrent release may have flipped both holders to false
            // while the token fetch was in flight; bail in that case.
            if (!conn.canvasHeld && !conn.genHeld) return;
            const service = getWorkflowPresenceService(conn.workflowId);
            service.connect({ workflowId: conn.workflowId, localUser, token });
            conn.connected = true;

            // Background-only remote-edit subscription. While the canvas
            // is mounted, useCollaborativePresence subscribes
            // independently and routes remote events to setNodes (which
            // flows into liveGraphStore via recordGraphSnapshot). When
            // unmounted, this subscription writes directly to the store
            // so the background graph stays current.
            conn.unsubRemoteForBackground = service.subscribeToWorkflowChanges((event) => {
                if (isCanvasMountedFor(conn.workflowId)) return;
                switch (event.type) {
                    case 'node:add':
                        applyRemoteNodeAdd(conn.workflowId, event.data);
                        break;
                    case 'node:remove':
                        applyRemoteNodeRemove(conn.workflowId, event.data as string);
                        break;
                    case 'node:update':
                        if (event.nodeId) {
                            applyRemoteNodeUpdate(conn.workflowId, event.nodeId, event.data as Record<string, unknown>);
                        }
                        break;
                    case 'edge:add':
                        applyRemoteEdgeAdd(conn.workflowId, event.data);
                        break;
                    case 'edge:remove':
                        applyRemoteEdgeRemove(conn.workflowId, event.data as string);
                        break;
                }
            });
        } finally {
            conn.connectInFlight = null;
        }
    })();
    return conn.connectInFlight;
}

function tryDispose(workflowId: string): void {
    const conn = connections.get(workflowId);
    if (!conn) return;
    if (conn.canvasHeld || conn.genHeld) return;
    if (conn.unsubRemoteForBackground) {
        conn.unsubRemoteForBackground();
        conn.unsubRemoteForBackground = null;
    }
    if (conn.connected) {
        disposeWorkflowPresenceService(workflowId);
        conn.connected = false;
    }
    connections.delete(workflowId);
}

function getOrCreate(workflowId: string): ManagedConnection {
    let conn = connections.get(workflowId);
    if (!conn) {
        conn = {
            workflowId,
            connected: false,
            token: null,
            tokenExpiry: 0,
            canvasHeld: false,
            genHeld: false,
            connectInFlight: null,
            unsubRemoteForBackground: null,
        };
        connections.set(workflowId, conn);
    }
    return conn;
}

// ── Public API ──────────────────────────────────────────────────────────

export function acquireForCanvas(workflowId: string, localUser: LocalUser = DEFAULT_LOCAL_USER): void {
    const conn = getOrCreate(workflowId);
    conn.canvasHeld = true;
    void ensureConnected(conn, localUser);
}

export function releaseFromCanvas(workflowId: string): void {
    const conn = connections.get(workflowId);
    if (!conn) return;
    conn.canvasHeld = false;
    tryDispose(workflowId);
}

export function acquireForGen(workflowId: string, localUser: LocalUser = DEFAULT_LOCAL_USER): void {
    const conn = getOrCreate(workflowId);
    conn.genHeld = true;
    void ensureConnected(conn, localUser);
}

export function releaseFromGen(workflowId: string): void {
    const conn = connections.get(workflowId);
    if (!conn) return;
    conn.genHeld = false;
    tryDispose(workflowId);
}

// ── Wire active_gen lifecycle ───────────────────────────────────────────

let _wired = false;

function wire(): void {
    if (_wired) return;
    _wired = true;

    onSocketEvent('active_gen:started' as never, ((data: { workflow_id?: string | null }) => {
        if (data?.workflow_id) acquireForGen(data.workflow_id);
    }) as never);

    onSocketEvent('active_gen:terminal' as never, ((data: { gen_id?: string }) => {
        const gen_id = data?.gen_id;
        if (!gen_id) return;
        const wfId = activeGenStore.gens[gen_id]?.workflow_id;
        if (!wfId) return;
        // Only release when the LAST gen for this workflow ends. The
        // activeGenStore listener evicts the gen on the same frame, so
        // we filter by `gen_id !== this`.
        const remaining = (activeGenStore.byWorkflow[wfId] || []).filter(id => id !== gen_id);
        if (remaining.length === 0) releaseFromGen(wfId);
    }) as never);

    // Forward agentic graph mutations into the gen's workflow room.
    // This is the originating FE acting as a relay so other viewers see
    // the agent's edits live; it works regardless of canvas mount on
    // this side because the manager keeps the connection alive while
    // any gen owns the workflow.
    onSocketEvent('active_gen:graph_event' as never, ((data: { gen_id?: string; event?: Record<string, unknown> }) => {
        const gen_id = data?.gen_id;
        const ev = data?.event;
        if (!gen_id || !ev) return;
        const wfId = activeGenStore.gens[gen_id]?.workflow_id;
        if (!wfId) return;
        const conn = connections.get(wfId);
        if (!conn || !conn.connected) return;
        const service = getWorkflowPresenceService(wfId);
        const evType = ev.type as string | undefined;
        switch (evType) {
            case 'node_added':
                service.broadcastNodeAdd(ev);
                break;
            case 'node_removed':
                if (typeof ev.nodeId === 'string') service.broadcastNodeRemove(ev.nodeId);
                break;
            case 'node_updated':
                if (typeof ev.nodeId === 'string') service.broadcastNodeUpdate(ev.nodeId, ev);
                break;
            case 'edge_added':
                service.broadcastEdgeAdd(ev);
                break;
            case 'edge_removed':
                if (typeof ev.edgeId === 'string') service.broadcastEdgeRemove(ev.edgeId);
                break;
        }
    }) as never);
}

wire();
