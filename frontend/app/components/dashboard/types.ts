// The data contract the Dashboard tab renders. Every field maps to something the
// backend already stores (see the per-section notes) so a winning design
// translates 1:1 into socket events later; nothing here is invented UI state.
//
// Sources, per section:
//   attention    approval_requests · conversations.pending_ask · builder_input_links
//                · conversations.events[builder_prompt] · credential_requests
//                · credentials.revoked_at / connection_status · trigger_error mirrors
//   runs         workflow_executions (+ cas_manifests for per-node truth)
//   agents       tool_call_events · conversations · sandbox presence registry
//   files        workflow_resources (R2) · noclick-ws-* per-conversation volumes
//                · noclick-fs-* FilesystemNode volumes · the builder's org workspace
//   credentials  credentials (+ credential_refresh_events, recurring_charges)
//   triggers     webhooks · webhook_subscriptions · schedule mirrors in node config
//   credits      user_usage_events via plan_limits.get_credit_usage
//   notifications user_notifications (read_at reserved for exactly this feed)

export interface WorkflowRef {
    id: string;
    name: string;
    /** Node types whose brand marks identify the workflow at a glance. */
    marks: string[];
}

export interface AgentRef {
    nodeId: string;
    label: string;
    /** `config.model` — a CLI harness slug (claude-code, codex, …) or an API model id. */
    model: string;
}

export type TriggerSource =
    | 'manual'
    | 'webhook'
    | 'cron'
    | 'mcp'
    | 'api'
    | 'email'
    | 'agent_turn'
    | 'shared_agent'
    | 'builder_event'
    | 'agent_email_reply'
    | 'error_handler';

// ---------------------------------------------------------------------------
// Attention — everything waiting on a human.

export type AttentionKind =
    /** Approval node parked a run (approval_requests, execution awaiting_approval). */
    | 'approval'
    /** The AI builder parked on <ask/> (conversations.pending_ask). */
    | 'builder_ask'
    /** An agent proposed a builder edit to its own workflow (builder_prompt card). */
    | 'builder_prompt'
    /** A /b/{id} bridge link is out for a credential only a human can connect. */
    | 'bridge_link'
    /** An outgoing credential request to someone else is still unanswered. */
    | 'credential_request'
    /** A connected credential is revoked or its session is dead. */
    | 'credential_dead'
    /** A trigger's registration failed — the workflow will never wake. */
    | 'trigger_broken';

export interface AttentionField {
    name: string;
    type: 'string' | 'number' | 'boolean' | 'select' | 'list' | 'text' | 'media';
    label: string;
    description?: string;
    options?: string[];
    value?: unknown;
}

export interface AttentionItem {
    id: string;
    kind: AttentionKind;
    title: string;
    detail?: string;
    workflow: WorkflowRef;
    /** Who is asking — the agent or builder that parked. */
    from?: AgentRef;
    createdAt: string;
    /** Editable payload (approval values, ask answers) — the queue answers in place. */
    fields?: AttentionField[];
    /** Multiple-choice asks. */
    choices?: string[];
    /** Builder asks: the builder's own input requests, answered with its wizard. */
    inputs?: unknown[];
    /** Public bridge URL for credential asks (absolute, or a path like /b/{id}). */
    link?: string;
    /** Provider node type to show for credential-shaped items. */
    provider?: string;
    /** Credential type (e.g. slack_oauth) when the item is about a credential and no node type is known. */
    credentialType?: string;
    /** Backend identifiers the actions need (approval id, conversation id, link id, …). */
    meta?: Record<string, unknown>;
}

// ---------------------------------------------------------------------------
// Runs

export interface DayBucket {
    /** YYYY-MM-DD, local. */
    date: string;
    ok: number;
    failed: number;
}

export type RunStatus = 'completed' | 'error' | 'running' | 'awaiting_approval' | 'awaiting_delay';

export interface RunRow {
    id: string;
    workflow: WorkflowRef;
    status: RunStatus;
    startedAt: string;
    durationMs: number | null;
    trigger: TriggerSource;
    nodesExecuted: number;
    error?: string;
    /** The node that failed, when known from cas_manifests. */
    failedNode?: { label: string; type: string };
    /** The agent's closing words, when an agent ran. */
    summary?: string;
}

export interface WorkflowRunStats {
    workflow: WorkflowRef;
    runs: number;
    failed: number;
    lastRunAt: string;
    lastStatus: 'ok' | 'failed' | 'running';
    days: DayBucket[];
}

export interface RunsData {
    days: DayBucket[];
    byWorkflow: WorkflowRunStats[];
    recent: RunRow[];
}

// ---------------------------------------------------------------------------
// Agents

export interface RunningAgent {
    workflow: WorkflowRef;
    agent: AgentRef;
    conversationTitle: string;
    /** Busy = mid-turn; idle = warm sandbox waiting (still billing). */
    busy: boolean;
    sinceIso: string;
}

export interface ToolCallSummary {
    /** `{provider}__{operation}` or a platform tool name. */
    tool: string;
    providerType: string;
    operation: string;
    status: 'success' | 'error';
    durationMs: number;
    /** Salient argument, e.g. the channel or the recipient. */
    detail?: string;
    error?: string;
    /** The call's arguments, for the inspector (bounded server-side). */
    arguments?: unknown;
    /** The call's result preview text, for the inspector. */
    result?: string | null;
    /** When the call happened. */
    at?: string | null;
}

export interface AgentTurn {
    id: string;
    /** The run this turn belongs to, when it ran as a workflow execution. */
    executionId?: string | null;
    conversationId?: string | null;
    workflow: WorkflowRef;
    agent: AgentRef;
    conversationTitle: string;
    startedAt: string;
    durationMs: number;
    trigger: TriggerSource;
    /** What woke the agent — the inbound event in one line. */
    inbound?: { provider: string; text: string; from?: string };
    toolCalls: ToolCallSummary[];
    response: string;
    status: 'ok' | 'error' | 'awaiting';
    /** Credits the turn cost, when the source knows it. */
    credits?: number;
}

export interface AgentsData {
    running: RunningAgent[];
    turns: AgentTurn[];
}

// ---------------------------------------------------------------------------
// Files — one view over four storage surfaces.

export type FileSourceKind =
    /** workflow_resources: uploads, chat attachments, node outputs, upload_file. */
    | 'resources'
    /** noclick-ws-* per-(workflow, agent, conversation) volume mounted at /workspace. */
    | 'workspace'
    /** noclick-fs-* FilesystemNode named volume. */
    | 'volume'
    /** The AI builder's org/personal sandbox workspace. */
    | 'builder';

export type FileKind = 'image' | 'video' | 'audio' | 'doc' | 'data' | 'code' | 'archive' | 'other';

export interface FileEntry {
    path: string;
    size: number;
    mtime: string;
    kind: FileKind;
    /** workflow_resources id, for resources; workspace files are addressed by path. */
    resourceId?: string;
    /** Signed read path for workspace files (agent_workspace:list). */
    urlPath?: string;
    /** Browser-resolvable URL for resources (public CDN on hosted, presigned locally). */
    url?: string | null;
    mime?: string | null;
    resourceType?: string | null;
    /** Dataset row count, for datasets (they have no blob). */
    rows?: number | null;
}

export interface FileSource {
    id: string;
    kind: FileSourceKind;
    label: string;
    /** The volume/bucket story in one line: "mounted at /workspace", "R2". */
    sublabel: string;
    workflow?: WorkflowRef;
    agent?: AgentRef;
    conversationTitle?: string;
    /** Workspace sources: the conversation the volume belongs to. */
    conversationKey?: string;
    mount?: string;
    files: FileEntry[];
    truncated?: boolean;
    /** The viewer may upload into and delete from this place. */
    writable?: boolean;
    /** Workspace sources: signed upload path (edit access only). */
    uploadUrlPath?: string;
}

// ---------------------------------------------------------------------------
// Credentials

export type CredentialHealth = 'ok' | 'disconnected' | 'revoked' | 'unknown';

export interface CredentialEntry {
    id: string;
    name: string;
    credentialType: string;
    /** Node type whose brand mark represents the provider; resolved from the credential type when absent. */
    nodeType?: string;
    access: 'owner' | 'shared' | 'shared_org';
    health: CredentialHealth;
    healthDetail?: string;
    createdAt: string;
    lastRefreshAt?: string;
    usedBy: WorkflowRef[];
    /** Recurring cost, for connection-backed credentials (WhatsApp QR). */
    recurringPerHour?: number;
}

// ---------------------------------------------------------------------------
// Triggers

export type TriggerKind = 'schedule' | 'webhook' | 'app_event' | 'email' | 'form' | 'poll';

export interface TriggerEntry {
    id: string;
    workflow: WorkflowRef;
    nodeType: string;
    label: string;
    kind: TriggerKind;
    /** Node id inside the workflow, for opening the trigger. */
    nodeId?: string;
    armed: boolean;
    error?: string | null;
    /** Human schedule, e.g. "Every 30 min · 9:00–18:00 · Mon–Fri". */
    schedule?: string | null;
    nextRunAt?: string | null;
    lastFiredAt?: string | null;
    fireCount: number;
}

// ---------------------------------------------------------------------------
// Upcoming — what will run next, from three sources.

export type UpcomingKind =
    /** A schedule/poll trigger's next fire (cron-scheduler next_run mirror). */
    | 'schedule'
    /** An alarm the agent set for itself (alarm node, run-once schedule). */
    | 'alarm'
    /** A delayed run resuming (workflow_executions.wake_at, awaiting_delay). */
    | 'resume';

export interface UpcomingRun {
    id: string;
    kind: UpcomingKind;
    /** ISO; null when the schedule is not registered (broken trigger). */
    at: string | null;
    workflow: WorkflowRef;
    /** What will happen, in the user's words: the schedule name, the alarm note, the resume reason. */
    label: string;
    /** The agent that wakes, when the trigger feeds one. */
    agent?: AgentRef | null;
    nodeType: string;
    recurrence?: string | null;
    /** Why `at` is null. */
    error?: string | null;
}

// ---------------------------------------------------------------------------
// Credits + notifications

export interface CreditsSummary {
    used: number;
    cap: number;
    period: 'day' | 'month';
    nextRefreshAt: string;
    topup: number;
    tier: string;
    /** Same window as runs.days. */
    spendByDay: number[];
    topSpenders: { workflow: WorkflowRef; credits: number }[];
}

export type NotificationCategory =
    | 'run_failure'
    | 'credits'
    | 'digest'
    | 'credential_revoked'
    | 'channel_disconnected';

export interface NotificationEntry {
    id: string;
    category: NotificationCategory;
    title: string;
    body: string;
    createdAt: string;
    readAt?: string | null;
    suppressedCount: number;
    workflow?: WorkflowRef | null;
    ctaUrl?: string | null;
}

// ---------------------------------------------------------------------------

export interface DashboardData {
    workspace: { name: string; kind: 'personal' | 'org'; userName: string };
    /** Fixed clock so relative times render identically on server and client. */
    now: string;
    attention: AttentionItem[];
    runs: RunsData;
    agents: AgentsData;
    files: FileSource[];
    credentials: CredentialEntry[];
    triggers: TriggerEntry[];
    upcoming: UpcomingRun[];
    credits: CreditsSummary;
    notifications: NotificationEntry[];
}

/** A drill-down target: the section shown full-screen. */
export type FocusId =
    | 'attention'
    | 'runs'
    | 'agents'
    | 'files'
    | 'credentials'
    | 'triggers'
    | 'upcoming'
    | 'credits'
    | 'notifications';

export const FOCUS_TITLES: Record<FocusId, string> = {
    attention: 'Needs you',
    runs: 'Runs',
    agents: 'Agents',
    files: 'Files',
    credentials: 'Credentials',
    triggers: 'Triggers',
    upcoming: 'Upcoming',
    credits: 'Credits',
    notifications: 'Notifications',
};
