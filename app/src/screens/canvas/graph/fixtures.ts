// A made-up workflow and the platform API's answers for the graph store's calls (its read and its edits) and the step
// types the canvas's drawing and its palette read, for the store's tests and the canvas acting as a key
// (../canvasAsKey.test.tsx). The server holds secrets in some steps' settings and never reads one back, as the API
// withholds them (`withheld`).
import { refusedToAccountKey } from '@/screens/console/ownerOnly';

type Json = Record<string, unknown>;

export const WORKFLOW = 'wf_orders';

/** Values the account's steps hold that no read carries and no request may send. */
export const SECRETS = { signingSecret: 'the hook signing value', agentKey: 'the agent api key value' } as const;

const step = (id: string, type: string, x: number, config: Json): Json => ({ id, type, position: { x, y: 0 }, config });

/** The workflow as the server stores it: a webhook, an agent with Slack as its next step, a note; secrets included. */
export function stored(): { nodes: Json[]; edges: Json[] } {
    return {
        nodes: [
            step('hook', 'trigger-webhook', 0, { label: 'Webhook', http_method: 'POST', signing_secret: SECRETS.signingSecret }),
            step('agent', 'agent', 320, {
                label: 'Agent', message: 'Sort the order', model: 'openai/gpt-5', api_key: SECRETS.agentKey,
                credentialIds: { agent_openai: 'cred_openai' },
            }),
            step('slack', 'automation-slack', 640, { label: 'Slack', operation: 'send_message', channel: 'C01', credentialIds: { slack_oauth: 'cred_slack' } }),
            step('victim', 'log', 960, { label: 'Victim' }),
        ],
        edges: [
            { id: 'hook-agent', source: 'hook', target: 'agent', sourceHandle: null, targetHandle: null },
            { id: 'agent-slack', source: 'agent', target: 'slack', sourceHandle: null, targetHandle: null },
        ],
    };
}

/** Where each step's secrets are, by path: what the API names as withheld. */
const SECRET_PATHS: Record<string, string[]> = { hook: ['signing_secret'], agent: ['api_key'] };

/** A graph as the API reads it: every secret left out and named by path. */
export function asRead(graph: { nodes: Json[]; edges: Json[] }): Json {
    const withheld: Record<string, string[]> = {};
    const nodes = graph.nodes.map((node) => {
        const paths = SECRET_PATHS[String(node.id)] ?? [];
        const config = { ...(node.config as Json) };
        const held = paths.filter((path) => path in config);
        for (const path of held) delete config[path];
        if (held.length) withheld[String(node.id)] = held;
        return { ...node, config };
    });
    return { nodes, edges: graph.edges, withheld };
}

const operation = (name: string, trigger = false): Json => ({ name, label: name, description: null, trigger, needs_account: !trigger });
const stepType = (type: string, label: string, more: Json): Json => ({
    object: 'step_type', type, label, description: null, category: null, kinds: [], trigger: false, operations: [], connection: null,
    retired: null, schema: null, ...more,
});

/** What the API says of the workflow's step types (`GET /v1/step_types/{type}`), as the canvas's drawing reads them: the
 *  webhook starts runs, Slack can be an agent's tools and starts runs on a message, a page talks through the SDK rather
 *  than connections, an older type answers as the one it became. */
export const STEP_TYPES: Record<string, Json> = {
    'trigger-webhook': stepType('trigger-webhook', 'Webhook', { kinds: ['trigger'], trigger: true }),
    agent: stepType('agent', 'AI Agent', { operations: [operation('default')] }),
    'automation-slack': stepType('automation-slack', 'Slack', {
        category: 'communication', kinds: ['trigger', 'tool'], operations: [operation('send_message'), operation('on_channel_message', true)],
    }),
    log: stepType('log', 'Log', { operations: [operation('default')] }),
    'interface-html-react': stepType('interface-html-react', 'Page', { schema: { type: 'object', 'x-connectionless': true } }),
    'trigger-form-input': stepType('interface-form', 'Form', { kinds: ['trigger'], trigger: true }),
};

/** The step types a listing (`GET /v1/step_types`) holds, in the API's order, each as a listing gives it (no schema;
 *  an older type's name isn't listed, only the type it became). */
export function listedStepTypes(): Json[] {
    return Object.entries(STEP_TYPES)
        .filter(([name, found]) => found.type === name)
        .map(([, found]) => ({ ...found, schema: null }));
}

export type Observe = (method: string, path: string, answered: Promise<Response>, body: Json, init: RequestInit | undefined) => void;

/** How the API answers an edit: it landed at `version`, or was refused for a stale version with the graph as it stands. */
export type EditAnswer = { version: number } | { conflict: { version: number; graph: { nodes: Json[]; edges: Json[] } } };

function refused(status: number, type: string, message: string, more: Json = {}): Response {
    return Response.json({ error: { type, message, ...more } }, { status });
}

/** The platform API's answers for the graph store: `GET /v1/workflows/{id}/graph` (the workflow as `server()` holds it,
 *  at `version()`) and `POST /v1/workflows/{id}/edits` (as `edit` answers each). Acting as one of the account's keys
 *  (`key`), what the API refuses a key is refused here too. */
export function graphFetch(options: {
    actsAs?: 'owner' | 'key';
    observe?: Observe;
    server?: () => { nodes: Json[]; edges: Json[] };
    version?: () => number;
    edit?: (body: Json) => EditAnswer;
}): typeof fetch {
    const server = options.server ?? stored;
    const version = options.version ?? (() => 4);
    const edit = options.edit ?? ((body: Json) => ({ version: ((body.if_version as number | undefined) ?? version()) + 1 }));
    const answer = async (method: string, url: URL, body: Json): Promise<Response> => {
        const path = decodeURIComponent(url.pathname);
        if (options.actsAs === 'key' && refusedToAccountKey(method, url.pathname)) {
            return refused(403, 'permission_denied', 'A key can’t do this: only the account’s signed-in owner can.');
        }
        const read = path.match(/^\/v1\/workflows\/([^/]+)\/graph$/);
        if (method === 'GET' && read) {
            if (read[1] !== WORKFLOW) return refused(404, 'not_found', 'No such workflow.');
            return Response.json({
                object: 'workflow_graph', workflow_id: WORKFLOW, version: version(), name: 'Orders', description: null,
                settings: {}, settings_withheld: [], display_metadata: null, graph: asRead(server()),
            });
        }
        if (method === 'GET' && path === '/v1/step_types') {
            const q = (url.searchParams.get('q') ?? '').toLowerCase();
            const data = listedStepTypes().filter((t) => !q || `${t.type} ${t.label}`.toLowerCase().includes(q));
            return Response.json({ object: 'list', data, next_cursor: null });
        }
        const kind = path.match(/^\/v1\/step_types\/([^/]+)$/);
        if (method === 'GET' && kind) {
            const found = STEP_TYPES[kind[1]];
            return found ? Response.json(found) : refused(404, 'not_found', `No step type '${kind[1]}'.`);
        }
        const edits = path.match(/^\/v1\/workflows\/([^/]+)\/edits$/);
        if (method === 'POST' && edits) {
            if (edits[1] !== WORKFLOW) return refused(404, 'not_found', 'No such workflow.');
            const ops = (body.ops ?? []) as Json[];
            const answered = edit(body);
            if ('conflict' in answered) {
                return refused(409, 'conflict', `The workflow is at version ${answered.conflict.version}.`, {
                    next_step: 'Apply the edits to the graph returned here.', workflow_id: WORKFLOW,
                    version: answered.conflict.version, graph: asRead(answered.conflict.graph),
                });
            }
            return Response.json({
                object: 'workflow_edit', workflow_id: WORKFLOW, version: answered.version, changed: true, history_version: null,
                summary: null, results: ops.map((op) => ({ op: op.op, id: op.id })), steps: {},
            });
        }
        return refused(404, 'not_found', `The fixtures answer no ${method} ${path}.`);
    };
    return async (input, init) => {
        const request = new Request(input, init);
        const url = new URL(request.url);
        const text = request.method === 'GET' ? '' : await request.text();
        const body = text ? (JSON.parse(text) as Json) : {};
        const answered = answer(request.method, url, body);
        options.observe?.(request.method, url.pathname, answered, body, init);
        return answered;
    };
}
