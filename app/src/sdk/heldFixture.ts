// The platform API holding calls for the account's owner, as it does those an app makes with the key NoClick gave it
// (a purchase, a deletion that can't be undone): a fetch over another that answers each matching call 402
// `approval_required` with the held call as an operation and where the owner was sent the link (never the link), and
// answers that operation's reads and its wait as it stands. `approve` and `decline` answer it as the owner would and
// say the frame the account's stream then carries, for a test to deliver. Tests import it; no screen does.
import type { PlatformResourceEvent } from '@/sdk/frames';

type Json = Record<string, unknown>;

export interface HeldRoute {
    method: string;
    /** The path, or a pattern of it. */
    path: string | RegExp;
    /** What NoClick stamps on the call when the owner approves it: the terms they accepted on the approval page. */
    accepted?: (body: Json) => Json;
}

interface Held {
    approvalId: string;
    operationId: string;
    method: string;
    path: string;
    body: Json | null;
    status: 'awaiting_human' | 'succeeded' | 'failed';
    response: unknown;
    decided: Promise<void>;
    decide: () => void;
    /** Makes the call as NoClick does once it's approved: through the API underneath. */
    make: () => Promise<Response>;
}

export interface HoldingApi {
    fetch: typeof fetch;
    /** The calls held so far, oldest first, with what each sent. */
    held: Held[];
    /** The owner approves the call held `index`th (the latest by default), and NoClick makes it. Returns the frame. */
    approve(index?: number): Promise<PlatformResourceEvent>;
    /** The owner declines it. Returns the frame. */
    decline(index?: number): PlatformResourceEvent;
}

const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } });

export function holding(inner: typeof fetch, routes: HeldRoute[], { sentTo = ['email'] }: { sentTo?: string[] } = {}): HoldingApi {
    const held: Held[] = [];
    const matches = (route: HeldRoute, method: string, path: string) =>
        route.method === method && (typeof route.path === 'string' ? route.path === path : route.path.test(path));
    const view = (h: Held) => ({
        object: 'operation',
        id: h.operationId,
        kind: 'gate.held_call',
        status: h.status,
        created_at: '2026-11-23T10:00:00Z',
        updated_at: '2026-11-23T10:00:00Z',
        ...(h.status === 'succeeded' ? { result: { status: 200, response: h.response } } : {}),
        ...(h.status === 'failed' ? { error: { type: 'policy_denied', message: 'The person declined it.', next_step: 'Don’t retry it without asking them again.' } } : {}),
    });

    const answer: typeof fetch = async (input, init) => {
        const url = new URL(typeof input === 'string' ? input : input instanceof URL ? input.href : input.url);
        const method = (init?.method ?? 'GET').toUpperCase();
        const own = held.find((h) => url.pathname === `/v1/operations/${h.operationId}` || url.pathname === `/v1/operations/${h.operationId}/wait`);
        if (own) {
            if (url.pathname.endsWith('/wait')) await own.decided;
            return json(view(own));
        }
        const route = routes.find((r) => matches(r, method, url.pathname));
        if (!route) return inner(input, init);
        let decide!: () => void;
        const decided = new Promise<void>((done) => (decide = done));
        const n = held.length + 1;
        const body = typeof init?.body === 'string' && init.body ? (JSON.parse(init.body) as Json) : null;
        const h: Held = { approvalId: `apr_held_${n}`, operationId: `op_held_${n}`, method, path: url.pathname, body, status: 'awaiting_human', response: null, decided, decide, make: () => inner(input, body && route.accepted ? { ...init, body: JSON.stringify(route.accepted(body)) } : init) };
        held.push(h);
        return json(
            {
                error: {
                    type: 'approval_required',
                    message: `${method} ${url.pathname}: it waits for the account’s owner, who approves it from the link NoClick sent them (email).`,
                    next_step: 'Tell whoever asked that it waits for the account’s owner.',
                    status: 'awaiting_approval',
                    approval_id: h.approvalId,
                    operation_id: h.operationId,
                    summary: `${method} ${url.pathname}`,
                    sent_to: sentTo,
                },
            },
            402
        );
    };

    const at = (index: number | undefined) => {
        const h = held[index ?? held.length - 1];
        if (!h) throw new Error('Nothing is held.');
        return h;
    };
    return {
        fetch: answer,
        held,
        approve: async (index) => {
            const h = at(index);
            const made = await h.make();
            if (!made.ok) throw new Error(`The held ${h.method} ${h.path} failed when made: ${made.status}`);
            h.response = made.status === 204 ? null : await made.json();
            h.status = 'succeeded';
            h.decide();
            return { kind: 'approval', id: h.approvalId, status: 'approved' };
        },
        decline: (index) => {
            const h = at(index);
            h.status = 'failed';
            h.decide();
            return { kind: 'approval', id: h.approvalId, status: 'declined' };
        },
    };
}
