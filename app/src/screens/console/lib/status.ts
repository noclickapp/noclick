// Status → pill look. Waiting is shape and words ("Waiting · approval"), never a
// hue; success is an ink check; red is failure only, green is running right now only.

/** `live` is work running right now (the one green); `filled` is any other active state. */
export type StatusGlyph = 'hollow' | 'filled' | 'live' | 'check' | 'cross' | 'waiting' | 'muted';
export type StatusTone = 'ink' | 'muted' | 'failure';

export interface StatusLook {
    label: string;
    /** Rendered inside the pill after a `·`. */
    reason?: string | null;
    glyph: StatusGlyph;
    tone: StatusTone;
}

/** A failed operation's error type as the short reason its pill carries. */
export const ERROR_REASONS: Readonly<Record<string, string>> = {
    spend_cap_exceeded: 'spend cap',
    policy_denied: 'policy',
    needs_connection: 'needs connection',
    credential_disconnected: 'disconnected',
    payment_required: 'payment',
    plan_required: 'plan',
    price_exceeded: 'price',
    approval_required: 'needs approval',
    permission_denied: 'permission',
    invalid_request: 'invalid request',
    unauthenticated: 'auth',
    not_found: 'not found',
    conflict: 'conflict',
    not_available: 'unavailable',
    action_required: 'action required',
    expired: 'expired',
    quota_exceeded: 'quota',
    rate_limited: 'rate limited',
    server_error: 'server error',
};

/** Reasons the server records on a generic error (`platform_error`). */
const DETAIL_REASONS: Readonly<Record<string, string>> = {
    interrupted: 'interrupted',
};

export function errorReason(errorType?: string | null, detailReason?: string | null): string | null {
    if (detailReason && DETAIL_REASONS[detailReason]) return DETAIL_REASONS[detailReason];
    return (errorType && ERROR_REASONS[errorType]) || null;
}

/** What an `awaiting_human` operation of this kind is held on. */
function heldOn(kind?: string | null): string {
    switch (kind) {
        case 'human.ask':
            return 'answer';
        case 'credential.connect':
            return 'connection';
        case 'inbox.wait_for':
            return 'reply';
        case 'phone.port_in': // designed: the account holder signs the letter of authorization
            return 'signature';
        case 'agent.task': // designed: a spawned task waits on its ask, a held call or a sign-in
            return 'a person';
        default:
            return 'approval';
    }
}

/** `step` is where a CLI-harness turn is (`delivering`, then `working`), or a port (`submitted`, then `scheduled`), in the API's own words. */
export function operationStatus(
    status: string,
    error?: { type?: string | null; reason?: string | null } | null,
    kind?: string | null,
    step?: string | null
): StatusLook {
    switch (status) {
        case 'queued':
            return { label: 'Queued', glyph: 'hollow', tone: 'ink' };
        case 'running':
            return { label: 'Running', ...(step ? { reason: step } : {}), glyph: 'live', tone: 'ink' };
        case 'awaiting_human':
            return { label: 'Waiting', reason: heldOn(kind), glyph: 'waiting', tone: 'ink' };
        case 'succeeded':
            return { label: 'Succeeded', glyph: 'check', tone: 'ink' };
        case 'failed':
            return { label: 'Failed', reason: errorReason(error?.type, error?.reason), glyph: 'cross', tone: 'failure' };
        case 'canceled':
            return { label: 'Canceled', glyph: 'muted', tone: 'muted' };
        case 'expired':
            // Designed: a spawned task expires when its agent's time to live runs out first.
            return { label: 'Expired', reason: kind === 'agent.task' ? 'time ran out' : 'no answer', glyph: 'muted', tone: 'muted' };
        default:
            return { label: status, glyph: 'hollow', tone: 'muted' };
    }
}

export function humanRequestStatus(status: string): StatusLook {
    switch (status) {
        case 'pending':
            return { label: 'Pending', glyph: 'waiting', tone: 'ink' };
        case 'answered':
            return { label: 'Answered', glyph: 'check', tone: 'ink' };
        case 'delivered':
            return { label: 'Delivered', glyph: 'check', tone: 'ink' };
        case 'expired':
            return { label: 'Expired', glyph: 'muted', tone: 'muted' };
        case 'canceled':
            return { label: 'Canceled', glyph: 'muted', tone: 'muted' };
        default:
            return { label: status, glyph: 'hollow', tone: 'muted' };
    }
}

/**
 * A named connection: waiting for a person until an account lands, then the
 * provider's verdict on it (the account it proved is the reason), and red once
 * it's revoked. `link` says whether a connect link is open.
 */
export function connectionStatus(c: { status: string; account?: string | null; reachable?: boolean | null; link?: boolean }): StatusLook {
    if (c.status === 'pending') return { label: 'Waiting to connect', reason: c.link ? 'link open' : 'no open link', glyph: 'waiting', tone: 'ink' };
    if (c.status === 'disconnected') return { label: 'Disconnected', reason: c.link ? 'reconnect link open' : null, glyph: 'cross', tone: 'failure' };
    if (c.reachable === false) return { label: 'Rejected', glyph: 'cross', tone: 'failure' };
    return { label: 'Connected', reason: c.account ?? (c.reachable === true ? null : 'not verified'), glyph: 'check', tone: 'ink' };
}

/** A conversation that isn't simply active (designed): waiting on a person, or handed to one. Null when active. */
export function conversationStatus(status: string | null, handedOffTo?: string | null): StatusLook | null {
    if (status === 'awaiting_human') return { label: 'Waiting', reason: 'a person', glyph: 'waiting', tone: 'ink' };
    if (status === 'handed_off') return { label: 'Handed off', reason: handedOffTo ?? null, glyph: 'hollow', tone: 'ink' };
    return null;
}

export function sandboxStatus(status: string, reason?: string | null): StatusLook {
    switch (status) {
        case 'starting':
            return { label: 'Starting', glyph: 'hollow', tone: 'ink' };
        case 'running':
            return { label: 'Running', glyph: 'live', tone: 'ink' };
        case 'terminated':
            return { label: 'Terminated', reason: reason ?? null, glyph: 'muted', tone: 'muted' };
        case 'failed':
            return { label: 'Failed', reason: reason ?? null, glyph: 'cross', tone: 'failure' };
        default:
            return { label: status, glyph: 'hollow', tone: 'muted' };
    }
}

export function toolCallStatus(status: string | null): StatusLook {
    if (status === 'error') return { label: 'Failed', glyph: 'cross', tone: 'failure' };
    if (status === 'success') return { label: 'Succeeded', glyph: 'check', tone: 'ink' };
    return { label: status ?? 'Unknown', glyph: 'hollow', tone: 'muted' };
}

/** An HTTP status in the request log: 4xx/5xx are failures. */
export function httpStatus(code: number): StatusLook {
    return code >= 400
        ? { label: String(code), glyph: 'cross', tone: 'failure' }
        : { label: String(code), glyph: 'check', tone: 'ink' };
}

/** An agent's live status: `working` with its running turns, `idle`, or `expired` past its `ttl_s`. */
export function agentStatus(status: string | null, runningTurns: number | null): StatusLook | null {
    switch (status) {
        case 'working':
            return { label: 'Working', reason: runningTurns ? `${runningTurns} ${runningTurns === 1 ? 'turn' : 'turns'}` : null, glyph: 'live', tone: 'ink' };
        case 'idle':
            return { label: 'Idle', glyph: 'hollow', tone: 'muted' };
        case 'expired':
            return { label: 'Expired', glyph: 'muted', tone: 'muted' };
        default:
            return null;
    }
}

/** A wake-up (designed): waiting for its moment, delivered as a turn, canceled, or failed to run. */
export function wakeupStatus(status: string, errorType?: string | null): StatusLook {
    switch (status) {
        case 'pending':
            return { label: 'Pending', glyph: 'waiting', tone: 'ink' };
        case 'delivered':
            return { label: 'Woke it', glyph: 'check', tone: 'ink' };
        case 'canceled':
            return { label: 'Canceled', glyph: 'muted', tone: 'muted' };
        case 'failed':
            return { label: 'Failed', reason: errorReason(errorType), glyph: 'cross', tone: 'failure' };
        default:
            return { label: status, glyph: 'hollow', tone: 'muted' };
    }
}

/** A channel or workspace subscription (designed): quiet while it delivers, red once it can't. */
export function subscriptionStatus(status: string | null): StatusLook | null {
    return status === 'error' ? { label: "Can't deliver", glyph: 'cross', tone: 'failure' } : null;
}

/** Non-terminal operation statuses (what `status:live` means). */
export const LIVE_OPERATION_STATUSES: ReadonlySet<string> = new Set(['queued', 'running', 'awaiting_human']);
