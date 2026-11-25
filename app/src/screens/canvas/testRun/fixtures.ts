// The platform API's answers for a workflow's Test Run: the test runs it offers, the test runs it keeps in its settings
// (read with its graph, written as an `update_workflow` edit), a run of one (its operation and the operation's wait),
// and the workflow's own steps with what's still unconnected. Everything else is the graph fixtures' (its graph, its
// step types).
import { refusedToAccountKey } from '@/screens/console/ownerOnly';
import { graphFetch, WORKFLOW, type Observe } from '../graph/fixtures';

type Json = Record<string, unknown>;

const HOOK = { type: 'trigger-webhook', label: 'Webhook', operation: null };

/** The staged event NoClick offers for the workflow's webhook. */
export const SAMPLE = { title: 'Sample event', meta: 'trigger-webhook', body: '{"order": "ord_81", "total": 42.5}' };

/** The test runs the workflow keeps: one it added, a name it gave it. */
export const AUTHORING: Json = {
    runs: { 'trigger-webhook': [{ slug: 'run-late', backendKey: 'generic:trigger-webhook', lead: { title: 'Order ord_80 is late', meta: 'trigger-webhook', body: 'Where is my order?', author: 'Ana' } }] },
    names: { 'trigger-webhook:run-late': 'A late order' },
    edits: {},
    hidden: [],
};

/** What a finished test run settles with: the agent's words, a call the world answered (with what it would have sent),
 *  a search, then its closing words. */
export const REHEARSAL: Json = {
    workflow_id: WORKFLOW,
    test_run: { key: 'generic:trigger-webhook', name: 'Sample event', custom: false },
    trigger: { step_id: 'hook', type: 'trigger-webhook', name: 'Webhook' },
    reply: 'I told #orders about ord_81.',
    tool_calls: [],
    transcript: [
        { role: 'assistant', text: 'A new order: tell the team.' },
        { role: 'tool', tool: 'slack__send_message', arguments: { channel: '#orders', text: 'Order ord_81 came in: 42.50, paid.' }, result: { ok: true }, outbound: 'Order ord_81 came in: 42.50, paid.' },
        { role: 'tool', tool: 'web_search', arguments: { query: 'ord_81' }, result: { results: [] } },
        { role: 'assistant', text: 'I told #orders about ord_81.' },
    ],
    scenario: 'An ordinary working day.',
    cost_usd: 0.004,
};

function refused(status: number, type: string, message: string): Response {
    return Response.json({ error: { type, message } }, { status });
}

export interface TestRunFetchOptions {
    actsAs?: 'owner' | 'key';
    observe?: Observe;
    /** The test runs the workflow keeps in its settings (AUTHORING by default); an edit replaces them. */
    authoring?: { held: Json | null };
    /** What a run settles with (REHEARSAL by default), or the error it fails with; a promise holds the run open. */
    played?: () => { result: Json } | { error: Json } | Promise<{ result: Json } | { error: Json }>;
    /** Why the list can't be read. */
    listRefused?: string;
}

/** The platform API's answers for a workflow's Test Run, the graph fixtures answering the rest. Acting as one of the
 *  account's keys (`key`), what the API refuses a key is refused here too. */
export function testRunFetch(options: TestRunFetchOptions = {}): typeof fetch {
    const graph = graphFetch({ actsAs: options.actsAs });
    const authoring = options.authoring ?? { held: structuredClone(AUTHORING) };
    const played = options.played ?? (() => ({ result: REHEARSAL }));
    const workflow = `/v1/workflows/${WORKFLOW}`;

    /** The list as the API gives it: the offered situations under the workflow's names and edits, less the ones it
     *  removed, then the runs it added. */
    const offered = (): Json[] => {
        const held = (authoring.held ?? {}) as { runs?: Record<string, Json[]>; names?: Record<string, string>; edits?: Record<string, Json>; hidden?: string[] };
        const key = 'trigger-webhook:generic:trigger-webhook';
        const sample = (held.hidden ?? []).includes(key)
            ? []
            : [{ object: 'workflow_test_run', key: 'generic:trigger-webhook', name: held.names?.[key] ?? 'Sample event', custom: false, trigger: HOOK, message: { ...SAMPLE, ...(held.edits?.[key] ?? {}) } }];
        const added = (held.runs?.['trigger-webhook'] ?? []).map((run) => {
            const { meta: _meta, ...message } = run.lead as Json;
            return { object: 'workflow_test_run', key: run.slug, name: held.names?.[`trigger-webhook:${String(run.slug)}`] ?? 'Test run', custom: true, trigger: HOOK, message };
        });
        return [...sample, ...added];
    };

    const answer = async (method: string, url: URL, body: Json, input: RequestInfo | URL, init: RequestInit | undefined): Promise<Response | null> => {
        const path = decodeURIComponent(url.pathname);
        if (options.actsAs === 'key' && refusedToAccountKey(method, url.pathname)) {
            return refused(403, 'permission_denied', 'A key can’t do this: only the account’s signed-in owner can.');
        }
        if (method === 'GET' && path === `${workflow}/test_runs`) {
            if (options.listRefused) return refused(403, 'permission_denied', options.listRefused);
            return Response.json({ object: 'list', next_cursor: null, data: offered() });
        }
        if (method === 'GET' && path === `${workflow}/graph`) {
            const read = (await (await graph(input, init)).json()) as Json;
            return Response.json({ ...read, settings: authoring.held ? { rehearsal_authoring: authoring.held } : {} });
        }
        if (method === 'POST' && path === `${workflow}/edits`) {
            for (const op of (body.ops ?? []) as Json[]) {
                const settings = op.op === 'update_workflow' ? (op.settings as Json | undefined) : undefined;
                if (settings && 'rehearsal_authoring' in settings) authoring.held = settings.rehearsal_authoring as Json;
            }
            return graph(input, init);
        }
        // The workflow's room, which the screen joins for a run to hear its steps as they move (`FixtureRoomSocket`).
        if (method === 'POST' && path === `/v1/rooms/workflow:${WORKFLOW}/tokens`) {
            return Response.json({ object: 'room_token', url: `wss://relay.test/v1/rooms/socket/workflow:${WORKFLOW}?ticket=tk`, token: 'tok', access: 'edit', expires_at: null, connection_ends_at: null });
        }
        if (method === 'POST' && path === `${workflow}/rehearsals`) {
            if (!offered().some((run) => run.key === body.test_run || run.name === body.test_run)) {
                return refused(404, 'not_found', `'Orders' offers no test run '${String(body.test_run)}'.`);
            }
            return Response.json({ object: 'operation', id: 'op_test', kind: 'workflow.rehearse', status: 'queued', summary: 'Orders: a test run', created_at: '2026-10-16T15:00:00.000Z', updated_at: '2026-10-16T15:00:00.000Z', result: null, error: null }, { status: 202 });
        }
        if (method === 'GET' && (path === '/v1/operations/op_test/wait' || path === '/v1/operations/op_test')) {
            const settled = await played();
            const base = { object: 'operation', id: 'op_test', kind: 'workflow.rehearse', summary: 'Orders: a test run', created_at: '2026-10-16T15:00:00.000Z', updated_at: '2026-10-16T15:00:09.000Z' };
            return Response.json('result' in settled ? { ...base, status: 'succeeded', result: settled.result, error: null } : { ...base, status: 'failed', result: null, error: settled.error });
        }
        if (method === 'GET' && path === workflow) {
            return Response.json({
                object: 'workflow', id: WORKFLOW, name: 'Orders', description: null, inputs: {}, app_url: null,
                steps: [
                    { id: 'hook', name: 'Webhook', type: 'trigger-webhook', operation: null, enabled: true, settings: {}, connection: null, trigger: { error: null, paused_reason: null, next_run: null } },
                    { id: 'agent', name: 'Agent', type: 'agent', operation: 'default', enabled: true, settings: {}, connection: { attached: true, healthy: true, hint: null }, trigger: null },
                    { id: 'slack', name: 'Tell the team', type: 'automation-slack', operation: 'send_message', enabled: true, settings: {}, connection: { attached: false, healthy: null, hint: null }, trigger: null },
                ],
                edges: [{ from: 'hook', to: 'agent', kind: 'data' }, { from: 'slack', to: 'agent', kind: 'tools' }],
                readiness: { status: 'needs_setup', meaning: 'A step needs an account.', issues: [], warnings: [], unverified: [] },
            });
        }
        return null;
    };
    return async (input, init) => {
        const request = new Request(input, init);
        const url = new URL(request.url);
        const text = request.method === 'GET' ? '' : await request.clone().text();
        const body = text ? (JSON.parse(text) as Json) : {};
        const mine = await answer(request.method, url, body, input, init);
        const answered = mine ?? (await graph(input, init));
        options.observe?.(request.method, url.pathname, Promise.resolve(answered), body, init);
        return answered;
    };
}

/** A workflow's room as a page joins it (the SDK's `Room`, given this as its WebSocket): the page is let in at once,
 *  and a test publishes a run's steps there (`publish`), as NoClick does while a test run plays. */
export class FixtureRoomSocket {
    static open: FixtureRoomSocket[] = [];
    onopen: (() => void) | null = null;
    onmessage: ((event: { data: string }) => void) | null = null;
    onclose: ((event: { code: number; reason: string }) => void) | null = null;
    onerror: ((error: unknown) => void) | null = null;
    readyState = 1;
    private heard = 0;

    constructor(public url: string) {
        FixtureRoomSocket.open.push(this);
        queueMicrotask(() => {
            this.onopen?.();
            const me = { id: 'm_me', user: { id: 'me', name: 'Me' }, color: '#F87171', data: {}, joined_at: 1 };
            this.hear({ type: 'ready', member: me, members: [me], access: 'edit', ends_at: Math.floor(Date.now() / 1000) + 900, runs: [], resumed: false });
        });
    }

    send(): void {}

    close(): void {
        this.readyState = 3;
        FixtureRoomSocket.open = FixtureRoomSocket.open.filter((socket) => socket !== this);
    }

    /** NoClick's `rehearsal:progress` frame of the run `operation` in the room. */
    publish(operation: string, frame: Json): void {
        this.heard += 1;
        this.hear({ type: 'event', id: `ev-${this.heard}`, event: 'rehearsal:progress', from: null, data: { operation_id: operation, rehearsed: true, ...frame } });
    }

    private hear(frame: Json): void {
        this.onmessage?.({ data: JSON.stringify(frame) });
    }
}
