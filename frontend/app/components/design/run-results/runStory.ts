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

/** One delivery run's result for a node the agent consumed. */
export interface AgentInputRun {
    executionId: string;
    status: string | null;
    output: unknown;
}

/** One node across the deliveries an agent response consumed (`runs` > 1
    when it fired in several). */
export interface AgentInputGroup {
    nodeId: string;
    label: string;
    iconHtml?: string;
    iconColor?: string;
    nodeType: string;
    /** The node's CURRENT operation (off the graph), so a provider-type node
        is recognised as the fired trigger the way the canvas does. */
    operation?: string;
    runs: AgentInputRun[];
}

export interface StoryInput {
    results: StoryNodeResult[];
    /** For a RESPONSE run (a warm agent's finished turn, fired as its own
        run): the deliveries the turn consumed, resolved from the agent
        output's `input_execution_ids`. The inbound event comes from here —
        the run's own trigger node never fired in it. */
    agentInputs?: AgentInputGroup[];
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

/** What the inbound frame needs to know about the node that fired. */
type StoryNodeIdentity = Pick<StoryNodeResult, 'nodeId' | 'nodeType' | 'label' | 'operation'>;

/** `no_event_output` (backend): a push trigger executed with no delivery. */
export const isNoEventOutput = (output: unknown): boolean =>
    asDict(output).status === 'no_event';

/** A response run's agent output — the callback-built package carrying the
    delivery runs the turn consumed. */
export const isResponsePackage = (output: unknown): boolean =>
    Array.isArray(asDict(output).input_execution_ids);

const asDict = (v: unknown): Dict => (v && typeof v === 'object' ? (v as Dict) : {});

function str(d: Dict, ...keys: string[]): string | undefined {
    for (const k of keys) {
        let v = d[k];
        // Some senders take lists (to_addresses, media_urls) — the first
        // entry is the one worth showing.
        if (Array.isArray(v)) v = v[0];
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
    // A push trigger run WITHOUT a live delivery (manual/test run) reports an
    // explanation, not an event — its `message` is prose about the run, and
    // reading it as the inbound text showed "No live event: …" as a guest's
    // words (2026-09-02).
    if (isNoEventOutput(d)) return null;

    if (slug === 'whatsapp' || slug === 'telegram') {
        const body = str(d, 'body', 'text', 'message');
        if (!body) return null;
        // No author fallback to the address — author AND handle both reading
        // "1415…@c.us" printed the id twice in the bubble header.
        const author = str(d, 'sender_name', 'from_name', 'pushName', 'author');
        const handle = str(d, 'from', 'phone', 'chat_id');
        return {
            title: author ?? handle ?? 'Message',
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
export function toScenario(node: StoryNodeIdentity, lead: Lead): Scenario {
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

export interface StoryMedia {
    kind: 'image' | 'video' | 'audio' | 'file';
    /** Public URL when the call carried one — renders a real preview. An
        opaque media_id keeps the kind but shows an attachment chip. */
    url?: string;
}

export interface StorySend {
    provider: string;
    to: string;
    /** The message text/caption, when the call carried one. A media send
        without a caption is still a send. */
    text?: string;
    media?: StoryMedia;
    subject?: string;
    toolName: string;
    /** Index of the tool call that made this send — anchors the send to its
        trace row. */
    callIndex: number;
    ms?: number;
    /** Wall clock of the send, for the "Sent · 09:41" stamp. */
    clock?: string;
}

/** Verb-anchored: an op SENDS when it starts with a sending verb. Segment
    matching alone counted get_post, on_post_sent and send_http_get_request
    as sends (2026-08-24 catalog sweep: 264 send-shaped ops, dozens of them
    CRUD/telemetry/typing-indicators). */
const SEND_OP_RE = /^(send|reply|post|publish|submit)(_|$)/;

/** Text argument keys across the sender catalog, preferred-first: plain text
    beats caption beats html beats an embed's description. Includes twitter/
    salesforce message_text, linkedin commentary, mailgun/resend html. */
const TEXT_ARG_KEYS = [
    'text',
    'body',
    'message',
    'message_text',
    'content',
    'commentary',
    'caption',
    'text_content',
    'html_content',
    'html',
    'description',
];

/** Destination keys across the catalog — telegram's camelCase chatId, twilio
    to_number, salesforce to_addresses (array), twitter participant_id, … */
const DEST_ARG_KEYS = [
    'to',
    'recipient',
    'recipient_id',
    'channel',
    'channel_id',
    'chat_id',
    'chatId',
    'to_number',
    'to_email',
    'to_emails',
    'to_addresses',
    'participant_id',
    'to_channel',
    'to_contact',
    'username',
    'email',
    'conversation_id',
    'convo_id',
    'thread_id',
];

/** Media argument keys, by the vocabulary the sender nodes actually use —
    whatsapp's image_url/video_url/…, telegram's BARE photo/video/voice/
    document/animation/sticker (URL or file id), instagram's attachment_url. */
const MEDIA_URL_KEYS: Array<[string, StoryMedia['kind']]> = [
    ['image_url', 'image'],
    ['photo_url', 'image'],
    ['photo', 'image'],
    ['sticker_url', 'image'],
    ['sticker', 'image'],
    ['video_url', 'video'],
    ['video', 'video'],
    ['video_note', 'video'],
    ['gif_url', 'video'],
    ['animation', 'video'],
    ['audio_url', 'audio'],
    ['audio', 'audio'],
    ['voice_url', 'audio'],
    ['voice', 'audio'],
    ['document_url', 'file'],
    ['document', 'file'],
    ['file_url', 'file'],
    ['media_url', 'file'],
    ['media_urls', 'file'],
    ['attachment_url', 'file'],
];

function mediaKindFromOp(op: string): StoryMedia['kind'] | undefined {
    // Segment-anchored, not substring: send_inVOICE is not a voice note.
    if (/(^|_)(image|photo|picture|sticker)(_|$)/.test(op)) return 'image';
    if (/(^|_)(video|gif|animation|animated)(_|$)/.test(op)) return 'video';
    if (/(^|_)(audio|voice)(_|$)/.test(op)) return 'audio';
    if (/(^|_)(document|file|attachment)(_|$)/.test(op)) return 'file';
    return undefined;
}

function deriveMedia(op: string, args: Dict): StoryMedia | undefined {
    const opKind = mediaKindFromOp(op);
    for (const [key, kind] of MEDIA_URL_KEYS) {
        const v = str(args, key);
        // The op's own kind beats the key's default (media_urls on a photo
        // op is an image, not a generic file).
        if (v) return { kind: opKind ?? kind, url: /^https?:\/\//.test(v) ? v : undefined };
    }
    if (!opKind) return undefined;
    // A media op with only a generic url argument (facebook send_attachment).
    const generic = str(args, 'url');
    if (generic && /^https?:\/\//.test(generic)) return { kind: opKind, url: generic };
    // No URL at all (media_id uploads) — the frame shows an attachment chip.
    return { kind: opKind };
}

/** A send needs BOTH halves: intent from the op name (a sending verb, never
    a text-argument gate — a captionless image send that vanished from the
    outcome taught us that) AND a renderable payload (text, media or a
    subject — which is what keeps send_http_get_request, typing indicators
    and campaign-id-only sends out of the outcome). */
export function deriveSends(toolCalls: ReplayToolCall[]): StorySend[] {
    const sends: StorySend[] = [];
    toolCalls.forEach((tc, i) => {
        if (tc.result_status === 'error') return; // it did NOT go out
        const op = tc.operation ?? tc.tool_name.split('__').slice(1).join('__');
        if (!SEND_OP_RE.test(op)) return;
        const args = asDict(tc.arguments);
        const text = str(args, ...TEXT_ARG_KEYS);
        const media = deriveMedia(op, args);
        const subject = str(args, 'subject', 'subject_line');
        if (!text && !media && !subject) return;
        sends.push({
            provider: tc.tool_name.split('__')[0],
            to: str(args, ...DEST_ARG_KEYS) ?? '',
            subject,
            text,
            media,
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

/* -------------------------------------------------------------- inbound */

/** Envelope keys the delivery plumbing adds around a fired event — internal
    ids and routing that mean nothing to the person reading the run. */
const ENVELOPE_KEYS = new Set([
    'schedule_id',
    'workflow_id',
    'user_id',
    'node_id',
    'execution_id',
    'webhook_id',
    'event_id',
    'triggered_at',
    'source',
]);

const stripEnvelope = (d: Dict): Dict =>
    Object.fromEntries(
        Object.entries(d).filter(([k]) => !k.startsWith('_') && !ENVELOPE_KEYS.has(k))
    );

/** The fired event with the delivery envelope removed — what a person would
    call "the event". An object-valued payload/data/body wrapper is unwrapped
    (WhatsApp delivers {event: 'message', payload: {...}}; webhooks deliver
    {…ids…, payload: {...}}); scalar siblings like event: "message" are
    envelope, not content. Empty result means the event has no
    user-meaningful content (a schedule tick). */
export function sanitizeEventPayload(raw: unknown): Dict {
    let d = stripEnvelope(asDict(raw));
    for (const key of ['payload', 'data', 'body', 'event', 'message']) {
        const inner = d[key];
        if (inner && typeof inner === 'object' && !Array.isArray(inner)) {
            d = stripEnvelope(asDict(inner));
            break;
        }
    }
    return d;
}

/* -------------------------------------------------------- tool providers */

export interface StoryToolProvider {
    nodeId: string;
    nodeType: string;
    label: string;
    /** Allowlisted operation names, as stored (snake_case). */
    operations: string[];
    credentialLabel?: string;
    /** Hosted-MCP node aggregating other providers (bundle). */
    isBundle: boolean;
}

/** Sentence-cased operation name — "send_message_to_channel" reads as
    "Send message to channel" (same treatment as trace-row labels). */
export function humanizeOp(op: string): string {
    const s = op.replace(/_/g, ' ').trim();
    return s.charAt(0).toUpperCase() + s.slice(1);
}

const PROVIDER_OUTPUT_TYPES = new Set([
    'node_op_tool_provider',
    'node_op_tool_provider_bundle',
]);

function toToolProvider(node: StoryNodeResult): StoryToolProvider | null {
    const out = asDict(node.output);
    const type = typeof out.type === 'string' ? out.type : '';
    if (!PROVIDER_OUTPUT_TYPES.has(type)) return null;
    const isBundle = type === 'node_op_tool_provider_bundle';
    const operations = isBundle
        ? (Array.isArray(out.providers) ? out.providers : []).flatMap((p) => {
              const ops = asDict(p).allowed_operations;
              return Array.isArray(ops) ? ops.map(String) : [];
          })
        : Array.isArray(out.allowed_operations)
          ? out.allowed_operations.map(String)
          : [];
    return {
        nodeId: node.nodeId,
        nodeType: node.nodeType,
        label: node.label,
        operations,
        credentialLabel:
            typeof out.credential_label === 'string' ? out.credential_label : undefined,
        isBundle,
    };
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
            it in the app's native frame. */
        scenario?: Scenario;
        /** The event has no user-meaningful content (a schedule tick) — the
            view renders the minimal "fired on schedule" card. */
        bare?: { time?: string };
        /** Neither lead nor bare: the SANITIZED event (delivery envelope
            stripped) for the raw fallback. */
        event?: Dict;
        /** The trigger ran with NO delivery (a manual/test run) — its own
            explanation of why nothing came in. Rendered instead of `bare`. */
        notice?: string;
        /** Response runs: how many deliveries fed the turn (the package's
            true total). The framed event is the latest; the resolved rest
            sit in the inputs rail. */
        deliveries?: number;
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
    /** Nodes wired as the agent's tool providers — they equipped the agent,
        they didn't "run" in the user sense. */
    providers: StoryToolProvider[];
    /** Every other node that ran, in given order. */
    supporting: StoryNodeResult[];
    /** The consumed-deliveries rail: every input group except a lone
        trigger delivery, which IS "What came in". */
    inputs: AgentInputGroup[];
    stats: {
        ran: number;
        toolCalls: number;
        sends: number;
        failed: boolean;
        durationLabel?: string;
    };
}

/** The inbound frame for one fired event. */
function triggerFrom(
    node: StoryNodeIdentity,
    output: unknown,
    deliveries?: number
): NonNullable<RunStory['trigger']> {
    const slug = slugOfType(node.nodeType);
    const d = asDict(output);
    if (isNoEventOutput(d)) {
        return {
            nodeId: node.nodeId,
            label: node.label,
            slug,
            operation: node.operation,
            bare: {},
            notice: typeof d.message === 'string' ? d.message : 'No event was delivered.',
        };
    }
    // The message often rides inside a payload wrapper — probe the raw
    // output first (top-level shapes), then the unwrapped event.
    const lead = deriveLead(slug, output) ?? deriveLead(slug, sanitizeEventPayload(output));
    const scenario = lead ? toScenario(node, lead) : undefined;
    let bare: { time?: string } | undefined;
    let event: Dict | undefined;
    if (!scenario) {
        const sanitized = sanitizeEventPayload(output);
        const time = clockOf(str(d, 'triggered_at', 'timestamp', 'date'));
        if (Object.keys(sanitized).length === 0) bare = { time };
        else event = sanitized;
    }
    return { nodeId: node.nodeId, label: node.label, slug, operation: node.operation, scenario, bare, event, deliveries };
}

export function buildRunStory(input: StoryInput): RunStory {
    const { results } = input;
    // The packaged agent (a warm turn's response) is THE agent of the run even
    // when a downstream SDK agent's row lands first in the detail.
    const agentNode =
        results.find((r) => r.isAgent && isResponsePackage(r.output)) ??
        results.find((r) => r.isAgent);
    const agentInputs = input.agentInputs ?? [];
    const pkg = asDict(agentNode?.output);

    // A response run's trigger node did not fire in it (whatever it holds
    // is the node's last output, restored as context — stale by
    // construction). The event that fed the turn is the LATEST consumed
    // delivery; none retained means no inbound section, never a guess.
    const isResponseRun = !!agentNode && isResponsePackage(pkg);
    // Delivery order rides the package (oldest → newest): the framed event is
    // the trigger group holding the newest delivery, not the first group seen.
    const orderOf = new Map<string, number>(
        (isResponseRun ? (pkg.input_execution_ids as unknown[]) : []).map((id, i) => [String(id), i])
    );
    const newest = (g: AgentInputGroup) =>
        Math.max(-1, ...g.runs.map((r) => orderOf.get(r.executionId) ?? -1));
    // The same predicate the canvas uses — a node is the fired event's source
    // only if its CURRENT operation is a trigger op.
    const triggerGroup = isResponseRun
        ? agentInputs
              .filter((g) => g.runs.length > 0 && isTriggerSourceLite(g.nodeType, g.operation))
              .sort((a, b) => newest(b) - newest(a))[0]
        : undefined;
    const triggerNode = isResponseRun
        ? undefined
        : results.find((r) => !r.isAgent && isTriggerSourceLite(r.nodeType, r.operation));

    let trigger: RunStory['trigger'];
    let triggerOutput: unknown;
    if (triggerGroup) {
        triggerOutput = triggerGroup.runs[triggerGroup.runs.length - 1].output;
        // The turn's true delivery count: the resolved runs are capped and
        // per node, the package's total is neither.
        const inputsTotal = typeof pkg.inputs_total === 'number' ? pkg.inputs_total : 0;
        trigger = triggerFrom(
            triggerGroup,
            triggerOutput,
            Math.max(inputsTotal, orderOf.size, triggerGroup.runs.length)
        );
    } else if (triggerNode) {
        triggerOutput = triggerNode.output;
        trigger = triggerFrom(triggerNode, triggerOutput);
    }
    // A lone trigger delivery IS "What came in"; several keep the rail so
    // the earlier ones stay reachable.
    const inputs = agentInputs.filter((g) => g !== triggerGroup || g.runs.length > 1);

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
            Object.values(asDict(triggerOutput)).filter((v): v is string => typeof v === 'string')
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

    const providers: StoryToolProvider[] = [];
    const supporting: StoryNodeResult[] = [];
    for (const r of results) {
        if (r.nodeId === triggerNode?.nodeId || r.nodeId === agentNode?.nodeId) continue;
        // A response run fires no trigger: a trigger node among its results is
        // restored context (rows written before context stopped persisting),
        // never a step that ran.
        if (isResponseRun && !r.isAgent && isTriggerSourceLite(r.nodeType, r.operation)) continue;
        const provider = toToolProvider(r);
        if (provider) providers.push(provider);
        else supporting.push(r);
    }

    const failed = results.some((r) => r.status === 'error');
    return {
        workflowName: input.workflowName,
        agentName: input.agentName ?? agentNode?.label,
        startedAt: input.startedAt,
        trigger,
        agent,
        providers,
        supporting,
        inputs,
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

/* -------------------------------------------------------------- outcome */

export type OutcomeMode = 'sends' | 'reply' | 'restraint' | 'error' | 'none';

/** Which framing the outcome section earns. "Nothing went out" is a verdict
    about restraint — it only makes sense when the agent actually worked (an
    event arrived or tools were called) and chose not to send. A bare chat
    turn's reply IS the outcome and must not be buried under it. */
export function outcomeModeFor(story: RunStory): OutcomeMode {
    const a = story.agent;
    if (!a) return 'none';
    if (a.status === 'error') return 'error';
    if (a.sends.length > 0) return 'sends';
    const toolCalls = a.rows.filter((r) => r.kind === 'tool').length;
    if (a.response && toolCalls === 0 && !story.trigger) return 'reply';
    return 'restraint';
}
