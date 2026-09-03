// The Dashboard tab's data: one `dashboard:overview` round trip held in a
// module-level valtio store so the tab and the navbar badge share a single
// fetch. Refetches when the workspace changes and when approvals are created or
// resolved; exposes `refresh` for the actions that change what needs the user.
import { useCallback, useEffect } from 'react';
import { proxy, useSnapshot } from 'valtio';
import { sendEventAsync } from '~/lib/socket-sender';
import { DashboardOverviewRequest } from '~/types/socket-events.generated';
import { onSocketEvent } from '~/lib/socket-receiver';
import { getLocalComponentValtio } from '~/state';
import { useOrgContext } from '~/hooks/useOrgContext';
import type {
    AgentRef,
    AgentsData,
    AttentionItem,
    CredentialEntry,
    FileSource,
    NotificationEntry,
    RunsData,
    TriggerEntry,
    UpcomingRun,
    WorkflowRef,
} from '~/components/dashboard/types';

/** A resolved approval, for the queue's "recently decided" group. */
export interface ResolvedApproval {
    id: string;
    title: string;
    workflow: WorkflowRef;
    status: 'approved' | 'rejected';
    decidedAt?: string | null;
    decidedByEmail?: string | null;
    createdAt: string;
}

/** An agent conversation whose durable /workspace volume can be listed on demand. */
export interface WorkspaceRef {
    id: string;
    workflow: WorkflowRef;
    agent: AgentRef;
    conversationKey: string;
    conversationTitle: string;
    lastActivity?: string | null;
}

/** Exactly what `dashboard:overview` returns (camelCase on the wire). */
export interface DashboardOverview {
    workspace: { name: string; kind: 'personal' | 'org'; userName: string };
    generatedAt: string;
    attention: AttentionItem[];
    resolvedApprovals: ResolvedApproval[];
    runs: RunsData;
    agents: AgentsData;
    files: FileSource[];
    workspaces: WorkspaceRef[];
    credentials: CredentialEntry[];
    triggers: TriggerEntry[];
    upcoming: UpcomingRun[];
    notifications: NotificationEntry[];
    unreadNotifications: number;
    /** Sections whose query failed; the section renders empty and the tab says so. */
    errors: Record<string, string>;
}

interface DashboardStore {
    overview: DashboardOverview | null;
    loading: boolean;
    error: string | null;
    fetchedAt: number | null;
    /** Attention items answered locally, hidden until the next refetch confirms. */
    dismissed: string[];
}

const store = proxy<DashboardStore>({ overview: null, loading: false, error: null, fetchedAt: null, dismissed: [] });

const BADGE_PATH = 'noclick-ui';
const BADGE_KEY = 'dashboardAttentionCount';

function writeBadge(count: number | null) {
    const valtio = getLocalComponentValtio(BADGE_PATH);
    if (!valtio.state) valtio.state = {};
    valtio.state[BADGE_KEY] = count;
}

let inflight: Promise<void> | null = null;

/** Fetch (or re-fetch) the overview. Concurrent callers share one request. */
export function fetchDashboardOverview(): Promise<void> {
    if (inflight) return inflight;
    store.loading = true;
    inflight = sendEventAsync(DashboardOverviewRequest.create({ days: 14 }))
        .then((response: unknown) => {
            const envelope = (response ?? {}) as { error?: string; data?: DashboardOverview };
            if (envelope.error) throw new Error(envelope.error);
            const data = (envelope.data ?? response) as DashboardOverview;
            store.overview = data;
            store.error = null;
            store.fetchedAt = Date.now();
            store.dismissed = [];
            writeBadge(data.attention.length);
        })
        .catch((e: unknown) => {
            store.error = e instanceof Error ? e.message : String(e);
        })
        .finally(() => {
            store.loading = false;
            inflight = null;
        });
    return inflight;
}

/** Hide an attention item now; the next fetch is the source of truth. */
export function dismissAttention(id: string) {
    if (!store.dismissed.includes(id)) store.dismissed.push(id);
    const remaining = (store.overview?.attention ?? []).filter((a) => !store.dismissed.includes(a.id)).length;
    writeBadge(remaining);
}

let refetchTimer: ReturnType<typeof setTimeout> | null = null;
function scheduleRefetch(delayMs = 400) {
    if (refetchTimer) clearTimeout(refetchTimer);
    refetchTimer = setTimeout(() => {
        refetchTimer = null;
        void fetchDashboardOverview();
    }, delayMs);
}

export function useDashboardOverview() {
    const snap = useSnapshot(store);
    const [orgContext] = useOrgContext();

    useEffect(() => {
        void fetchDashboardOverview();
        // Approvals arrive and resolve live; everything else is refreshed on
        // demand by the actions that change it.
        const unsubCreated = onSocketEvent('approval:request:created', () => scheduleRefetch());
        const unsubResolved = onSocketEvent('approval:request:resolved', () => scheduleRefetch());
        return () => {
            unsubCreated();
            unsubResolved();
        };
    }, [orgContext.id]);

    const refresh = useCallback(() => fetchDashboardOverview(), []);
    return {
        overview: snap.overview as DashboardOverview | null,
        loading: snap.loading,
        error: snap.error,
        dismissed: snap.dismissed as readonly string[],
        refresh,
    };
}
