/* The run-results derivation: turns what the popup receives (NodeRunResult
   rows + the agent's recorded tool calls) into the rehearsal screen's
   vocabulary — an inbound Scenario for InboundMessage, trace rows with salient
   argument details, and the sends that actually went out for OutboundMessage.
   Consumed by the production RunResultsDialog; the Story view in variants.tsx
   is a rendering of this. */

import type { Scenario } from '~/components/design/rehearsal/fixture';
import type { ReplayRow } from '~/components/design/rehearsal/useReplay';
import { toReplayRows, type LiveRow } from '~/components/design/rehearsal/useLiveRun';
import type { ReplayToolCall } from '~/components/workflow/ReplayToolCallsPanel';
import type { ErrorAction } from '~/components/workflow/ErrorActionButton';
import { formatDuration } from '~/components/workflow/WorkflowExecutionLogs';
import { isTriggerSourceLite } from '~/lib/nodeIconRegistry';

/** One node's result, as the popup receives it (NodeRunResult minus the icon
    fields, which the views resolve themselves) plus `operation` — read off the
    graph node, so the trigger can be recognised the way the canvas does. */
export interface StoryNodeResult {
    nodeId: string;
    nodeType: string;
    label: string;
    operation?: string;
    status: 'completed' | 'error' | 'skipped';
    output: unknown;
    error?: string;
    errorAction?: ErrorAction;
    isAgent: boolean;
    toolCalls: ReplayToolCall[];
}

export interface StoryInput {
    results: StoryNodeResult[];
    workflowName: string;
    /** Overrides the agent node's label in the outbound frames' byline. */
    agentName?: string;
    /** The run's start (ISO) — from the execution log; absent for runs whose
        log row isn't loaded. */
    startedAt?: string;
    durationMs?: number;
}

/** `automation-google-sheets` → `google_sheets` — the slug appThemes, tool
    names and the icon map all key on. */
export function slugOfType(type: string): string {
    return type.replace(/^automation-/, '').replace(/-/g, '_');
}

const pad2 = (n: number) => String(n).padStart(2, '0');

/** Local wall clock HH:MM — undefined for unparseable input. */
export function clockOf(iso: string | null | undefined): string | undefined {
    if (!iso) return undefined;
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return undefined;
    return `${pad2(d.getHours())}:${pad2(d.getMinutes())}`;
}

/** HH:MM:SS — trace rows land seconds apart, so their stamps need them. */
export function clockSecOf(iso: string | null | undefined): string | undefined {
    if (!iso) return undefined;
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return undefined;
    return `${pad2(d.getHours())}:${pad2(d.getMinutes())}:${pad2(d.getSeconds())}`;
}

type Lead = Scenario['lead'];
type Dict = Record<string, unknown>;

const asDict = (v: unknown): Dict => (v && typeof v === 'object' ? (v as Dict) : {});

function str(d: Dict, ...keys: string[]): string | undefined {
    for (const k of keys) {
        const v = d[k];
        if (typeof v === 'string' && v.trim()) return v.trim();
        if (typeof v === 'number' && Number.isFinite(v)) return String(v);
    }
    return undefined;
}

/** "Priya Raman <priya@northwind.io>" → the two halves. */
function splitAddress(from?: string): { author?: string; handle?: string } {
    if (!from) return {};
    const m = from.match(/^(.*?)\s*<([^>]+)>$/);
    if (m) return { author: m[1].trim() || undefined, handle: m[2].trim() };
    return from.includes('@') ? { handle: from } : { author: from };
}

/** The fired event as a lead the native frames can wear. Null when the payload
    has no recognisable message shape — the views then show the raw event
    instead of dressing noise up as a message. */
export function deriveLead(slug: string, output: unknown): Lead | null {
    const d = asDict(output);

    if (slug === 'whatsapp' || slug === 'telegram') {
        const body = str(d, 'body', 'text', 'message');
        if (!body) return null;
        const author = str(d, 'sender_name', 'from_name', 'author') ?? str(d, 'from');
        const handle = str(d, 'from', 'phone', 'chat_id');
        return {
            title: author ?? 'Message',
            meta: handle ?? '',
            body,
            author,
            handle,
            time: clockOf(str(d, 'timestamp', 'date')),
        };
    }

    if (slug === 'gmail' || slug === 'microsoft_outlook' || slug === 'email') {
        const body = str(d, 'body', 'snippet', 'text');
        const title = str(d, 'subject');
        if (!body && !title) return null;
        const from = splitAddress(str(d, 'from', 'sender'));
        return {
            title: title ?? '(no subject)',
            meta: str(d, 'from') ?? '',
            body: body ?? '',
            ...from,
            time: clockOf(str(d, 'date', 'timestamp')),
        };
    }

    if (slug === 'slack' || slug === 'discord' || slug === 'teams') {
        const body = str(d, 'text', 'message', 'body');
        if (!body) return null;
        const channel = str(d, 'channel', 'channel_name');
        return {
            title: channel ? (channel.startsWith('#') ? channel : `#${channel}`) : 'Message',
            meta: channel ?? '',
            body,
            author: str(d, 'user_name', 'username', 'user', 'author'),
            time: clockOf(str(d, 'timestamp', 'date')),
        };
    }

    if (slug === 'stripe') {
        const cents = d.amount_due ?? d.amount ?? d.amount_paid;
        const currency = (str(d, 'currency') ?? 'usd').toUpperCase();
        const title =
            typeof cents === 'number'
                ? `${currency === 'USD' ? '$' : `${currency} `}${(cents / 100).toFixed(2)}`
                : (str(d, 'number', 'invoice') ?? 'Payment');
        const number = str(d, 'number', 'invoice');
        const attempt = typeof d.attempt_count === 'number' ? d.attempt_count : undefined;
        const retry = str(d, 'next_payment_attempt');
        const failure = str(d, 'failure_message', 'description');
        const body = [
            failure,
            number && attempt ? `Attempt ${attempt} for ${number}.` : undefined,
            retry ? `Next retry ${retry}.` : undefined,
        ]
            .filter(Boolean)
            .join(' ');
        if (!body) return null;
        return {
            title,
            meta: number ?? '',
            body,
            author: str(d, 'customer_name', 'customer'),
            handle: str(d, 'customer_email'),
        };
    }

    if (slug === 'typeform' || slug === 'google_forms') {
        const body = str(d, 'message', 'answer', 'text', 'body');
        if (!body) return null;
        return {
            title: str(d, 'form', 'form_name', 'title') ?? 'Form response',
            meta: str(d, 'email') ?? '',
            body,
            author: str(d, 'name', 'respondent'),
            handle: str(d, 'email'),
            time: clockOf(str(d, 'submitted_at', 'timestamp')),
        };
    }

    // Generic probe — enough shape to frame, or nothing at all.
    const body = str(d, 'body', 'text', 'message', 'snippet', 'description');
    const title = str(d, 'subject', 'title', 'name');
    if (!body || !title) return null;
    const from = splitAddress(str(d, 'from', 'sender', 'author'));
    return { title, meta: str(d, 'from') ?? '', body, ...from, time: clockOf(str(d, 'timestamp', 'date')) };
}

/** Minimal Scenario for InboundMessage: provider 'generic' + iconSlug routes
    the themed frame by the node's real slug; the rehearsal-only fields are
    inert here. */
export function toScenario(node: StoryNodeResult, lead: Lead): Scenario {
    const slug = slugOfType(node.nodeType);
    return {
        slug,
        name: node.label,
        nodeName: node.label,
        triggerLabel: node.label,
        provider: 'generic',
        iconSlug: slug,
        operation: node.operation,
        key: `run:${node.nodeId}`,
        lead,
        events: [],
        doneAt: 0,
        artifacts: null,
    };
}

/* ---------------------------------------------------------------- sends */

export interface StorySend {
    provider: string;
    to: string;
    text: string;
    subject?: string;
    toolName: string;
    /** Index of the tool call that made this send — anchors the send to its
        trace row. */
    callIndex: number;
    ms?: number;
    /** Wall clock of the send, for the "Sent · 09:41" stamp. */
    clock?: string;
}

const SEND_OP_RE = /(^|_)(send|reply|post)(_|$)/;

/** The text a send-shaped call carried — undefined disqualifies the call. A
    FAILED call never yields a send: it did not go out, and the trace row's
    error owns that story. */
function outboundText(tc: ReplayToolCall): string | undefined {
    if (tc.result_status === 'error') return undefined;
    const op = tc.operation ?? tc.tool_name.split('__').slice(1).join('__');
    if (!SEND_OP_RE.test(op)) return undefined;
    return str(asDict(tc.arguments), 'text', 'body', 'message', 'content');
}

export function deriveSends(toolCalls: ReplayToolCall[]): StorySend[] {
    const sends: StorySend[] = [];
    toolCalls.forEach((tc, i) => {
        const text = outboundText(tc);
        if (!text) return;
        const args = asDict(tc.arguments);
        sends.push({
            provider: tc.tool_name.split('__')[0],
            to: str(args, 'to', 'recipient', 'channel', 'channel_id', 'chat_id', 'email') ?? '',
            subject: str(args, 'subject'),
            text,
            toolName: tc.tool_name,
            callIndex: i,
            ms: tc.duration_ms ?? undefined,
            clock: clockOf(tc.timestamp),
        });
    });
    return sends;
}

/* ---------------------------------------------------------------- trace */

/** ReplayRow plus what real runs know that rehearsals don't: the provider's
    error text, the wall clock, and the call's salient argument. */
export type StoryRow = ReplayRow & { error?: string; clock?: string; detail?: string };

/** The one argument worth putting on the row itself — where the call was
    aimed (channel, recipient, url, sheet, query). Rows that say only "Send
    message" report that a tool ran; "Send message · #orders" reports what
    happened. Priority order: destinations first, then subjects of reads. */
const DETAIL_KEYS = [
    'channel',
    'channel_id',
    'to',
    'recipient',
    'email',
    'chat_id',
    'url',
    'spreadsheet',
    'sheet',
    'query',
    'form',
    'subject',
    // Output-shaped keys (deriveNodeDetail probes results, not arguments).
    'updated_range',
    'domain',
];

function deriveCallDetail(
    args: Dict,
    pretty?: (v: string) => string
): string | undefined {
    for (const key of DETAIL_KEYS) {
        const v = str(args, key);
        if (!v) continue;
        if (key === 'url') return v.replace(/^https?:\/\//, '');
        return pretty ? pretty(v) : v;
    }
    return undefined;
}

/** Same probe over a plain node's OUTPUT — what it produced ("Leads!A213",
    "#sales") — so supporting rows carry the same one-glance detail as the
    agent's trace rows. */
export function deriveNodeDetail(output: unknown): string | undefined {
    return deriveCallDetail(asDict(output));
}

export function toolCallsToRows(
    toolCalls: ReplayToolCall[],
    /** Maps opaque destination ids back to the person the fired event names
        (chat ids → sender) — shared with deriveSends via buildRunStory. */
    pretty?: (v: string) => string
): StoryRow[] {
    const live: LiveRow[] = toolCalls.map((tc, i) => {
        let result: Record<string, unknown> | undefined;
        if (tc.result_preview) {
            try {
                const parsed = JSON.parse(tc.result_preview);
                result =
                    parsed && typeof parsed === 'object' && !Array.isArray(parsed)
                        ? (parsed as Record<string, unknown>)
                        : { result: parsed };
            } catch {
                result = { preview: tc.result_preview };
            }
        }
        return {
            id: `${tc.tool_name}-${i}`,
            tool: tc.tool_name,
            status: tc.result_status === 'error' ? 'error' : 'completed',
            startedAt: tc.timestamp ? Date.parse(tc.timestamp) : 0,
            ms: tc.duration_ms ?? undefined,
            args: tc.arguments ?? undefined,
            result,
        };
    });
    return toReplayRows(live, 0).map((row, i) => ({
        ...row,
        error: toolCalls[i].error ?? undefined,
        clock: clockSecOf(toolCalls[i].timestamp),
        detail: deriveCallDetail(asDict(toolCalls[i].arguments), pretty),
    }));
}

/* ---------------------------------------------------------------- story */

export interface RunStory {
    workflowName: string;
    agentName?: string;
    startedAt?: string;
    trigger?: {
        nodeId: string;
        label: string;
        slug: string;
        operation?: string;
        /** Set when the payload derived a real lead — InboundMessage renders
            it; absent lead means the views show the raw event. */
        scenario?: Scenario;
        raw: unknown;
    };
    agent?: {
        nodeId: string;
        label: string;
        status: StoryNodeResult['status'];
        error?: string;
        errorAction?: ErrorAction;
        response?: string;
        rows: StoryRow[];
        sends: StorySend[];
    };
    /** Every other node that ran, in given order. */
    supporting: StoryNodeResult[];
    stats: {
        ran: number;
        toolCalls: number;
        sends: number;
        failed: boolean;
        durationLabel?: string;
    };
}

export function buildRunStory(input: StoryInput): RunStory {
    const { results } = input;
    // The same predicate the canvas uses — a node is the fired event's source
    // only if its CURRENT operation is a trigger op.
    const triggerNode = results.find(
        (r) => !r.isAgent && isTriggerSourceLite(r.nodeType, r.operation)
    );
    const agentNode = results.find((r) => r.isAgent);

    let trigger: RunStory['trigger'];
    if (triggerNode) {
        const slug = slugOfType(triggerNode.nodeType);
        const lead = deriveLead(slug, triggerNode.output);
        trigger = {
            nodeId: triggerNode.nodeId,
            label: triggerNode.label,
            slug,
            operation: triggerNode.operation,
            scenario: lead ? toScenario(triggerNode, lead) : undefined,
            raw: triggerNode.output,
        };
    }

    let agent: RunStory['agent'];
    if (agentNode) {
        const out = asDict(agentNode.output);
        const response = typeof out.response === 'string' && out.response.trim() ? out.response : undefined;
        // A destination often arrives as an opaque channel id (919…@c.us).
        // When it matches a value on the fired event, the person it names is
        // the readable truth — show them, not the id. Shared by the sent
        // frames and the trace rows' detail suffix.
        const author = trigger?.scenario?.lead.author;
        const rawValues = new Set(
            triggerNode
                ? Object.values(asDict(triggerNode.output)).filter(
                      (v): v is string => typeof v === 'string'
                  )
                : []
        );
        const pretty = (v: string) => (author && rawValues.has(v) ? author : v);
        const sends = deriveSends(agentNode.toolCalls);
        for (const s of sends) {
            if (s.to) s.to = pretty(s.to);
        }
        agent = {
            nodeId: agentNode.nodeId,
            label: agentNode.label,
            status: agentNode.status,
            error: agentNode.error,
            errorAction: agentNode.errorAction,
            response,
            rows: toolCallsToRows(agentNode.toolCalls, pretty),
            sends,
        };
    }

    const supporting = results.filter(
        (r) => r.nodeId !== triggerNode?.nodeId && r.nodeId !== agentNode?.nodeId
    );

    const failed = results.some((r) => r.status === 'error');
    return {
        workflowName: input.workflowName,
        agentName: input.agentName ?? agentNode?.label,
        startedAt: input.startedAt,
        trigger,
        agent,
        supporting,
        stats: {
            ran: results.length,
            toolCalls: agentNode?.toolCalls.length ?? 0,
            sends: agent?.sends.length ?? 0,
            failed,
            durationLabel:
                input.durationMs !== undefined ? formatDuration(input.durationMs) : undefined,
        },
    };
}
