// A made-up account's workflows and the platform API's answers for the workflows pages: the list with its folders, a
// new workflow, and one workflow's page (its graph, each edit, its step types with the settings their forms ask for,
// its runs, its Test Run and readiness, the account's connections), put together from the canvas's own fixtures. For
// the pages' lab and their tests; with no account and no network.
import { refusedToAccountKey } from '@/screens/console/ownerOnly';
import { stored, WORKFLOW, type Observe } from '@/screens/canvas/graph/fixtures';
import { runsFetch } from '@/screens/canvas/runs/fixtures';
import { SETUP_STEP_TYPES, VARIABLE_SECRET } from '@/screens/canvas/setup/fixtures';
import { testRunFetch } from '@/screens/canvas/testRun/fixtures';

type Json = Record<string, unknown>;

const AT = '2026-10-16T15:00:00.000Z';

const workflow = (id: string, name: string, more: Json = {}): Json => ({
    object: 'workflow', id, name, description: null, inputs: {}, app_url: null, access: 'owner', paused: false, folder_id: null, agent_id: null,
    created_at: '2026-10-01T09:00:00.000Z', updated_at: AT, ...more,
});

/** The account's workflows: the one the canvas fixtures hold, one in a folder, and one another account shared to look at. */
export function listedWorkflows(): Json[] {
    return [
        workflow(WORKFLOW, 'Orders', { description: 'Sorts each new order and tells the team.' }),
        workflow('wf_brief', 'Morning brief', { folder_id: 'fld_reports', paused: true, updated_at: '2026-10-15T07:00:00.000Z' }),
        workflow('wf_shared', 'Shared intake', { access: 'viewer', updated_at: '2026-10-12T11:30:00.000Z' }),
    ];
}

/** The open workflow's one declared variable, as the server stores it: its value is read back by its owner alone. */
export const DECLARED: Json[] = [{ name: 'reply_to', value: VARIABLE_SECRET, description: 'Who replies go to.' }];

const FOLDERS: Json[] = [{ object: 'workflow_folder', id: 'fld_reports', name: 'Reports', description: null, parent_id: null, depth: 0, workflow_count: 1, created_at: AT, updated_at: AT }];

const connection = (name: string, credentialId: string, credentialType: string, integration: string): Json => ({
    object: 'connection', id: `conn_${name}`, name, ref: `credential:${credentialId}`, origin: 'app', status: 'connected', integration, credential_id: credentialId, credential_type: credentialType,
    account: null, user_id: null, shared: null, health: { healthy: true, hint: null }, disconnected: null, verification: null, created_at: AT, updated_at: AT,
});

function refused(status: number, type: string, message: string): Response {
    return Response.json({ error: { type, message } }, { status });
}

/** Whether a fixture said it holds no answer for a call (so the next one is asked). */
async function unanswered(response: Response): Promise<boolean> {
    if (response.status !== 404) return false;
    const body = (await response.clone().json().catch(() => null)) as { error?: { message?: string } } | null;
    return (body?.error?.message ?? '').startsWith('The fixtures answer no ');
}

export interface WorkflowsFetchOptions {
    actsAs?: 'owner' | 'key';
    observe?: Observe;
    /** What the key may do with the open workflow, as its read says (`owner` by default; `viewer` only looks). */
    access?: 'owner' | 'editor' | 'viewer';
}

/** The platform API's answers for the workflows pages. The open workflow is held for the life of the fetch: an edit
 *  lands on it and moves its version, so what's read again is what was saved. */
export function workflowsFetch(options: WorkflowsFetchOptions = {}): typeof fetch {
    const held = { graph: stored(), version: 4, made: [] as Json[] };
    /** An edit's ops applied to the held graph, as far as the pages' own edits go. */
    const apply = (ops: Json[]) => {
        for (const op of ops) {
            const at = held.graph.nodes.find((n) => n.id === op.id);
            if (op.op === 'add_step') held.graph.nodes.push({ id: op.id, type: op.type, position: op.position ?? { x: 0, y: 0 }, config: { ...(op.settings as Json | undefined), ...(op.operation ? { operation: op.operation } : {}) } });
            else if (op.op === 'remove_step') held.graph.nodes = held.graph.nodes.filter((n) => n.id !== op.id);
            else if (op.op === 'update_step' && at) at.config = { ...(at.config as Json), ...(op.settings as Json | undefined), ...(op.name ? { label: op.name } : {}), ...(op.operation ? { operation: op.operation } : {}) };
            else if (op.op === 'move' && at && op.position) at.position = op.position;
            else if (op.op === 'set_connection' && at) at.config = { ...(at.config as Json), credentialIds: { ...((at.config as Json).credentialIds as Json | undefined), [String(op.slot)]: op.connection } };
            else if (op.op === 'connect') held.graph.edges.push({ id: `${String(op.from)}-${String(op.to)}`, source: op.from, target: op.to, sourceHandle: null, targetHandle: op.kind === 'tools' ? 'bottom' : null });
            else if (op.op === 'disconnect') held.graph.edges = held.graph.edges.filter((e) => !(e.source === op.from && e.target === op.to));
        }
    };
    const graph = {
        server: () => held.graph,
        version: () => held.version,
        edit: (body: Json) => {
            apply((body.ops ?? []) as Json[]);
            return { version: ++held.version };
        },
    };
    const runs = runsFetch({ actsAs: options.actsAs, graph });
    const tests = testRunFetch({ actsAs: options.actsAs });

    const mine = async (method: string, url: URL, body: Json): Promise<Response | null> => {
        const path = decodeURIComponent(url.pathname);
        if (options.actsAs === 'key' && refusedToAccountKey(method, url.pathname)) {
            return refused(403, 'permission_denied', 'A key can’t do this: only the account’s signed-in owner can.');
        }
        if (method === 'GET' && path === '/v1/workflows') return Response.json({ object: 'list', next_cursor: null, data: [...held.made, ...listedWorkflows()] });
        if (method === 'GET' && path === '/v1/workflows/folders') return Response.json({ object: 'list', next_cursor: null, data: FOLDERS });
        if (method === 'POST' && path === '/v1/workflows') {
            const made = workflow('wf_new', String(body.name));
            held.made.unshift(made);
            return Response.json(made, { status: 201 });
        }
        if (method === 'GET' && path === '/v1/connections') {
            return Response.json({ object: 'list', next_cursor: null, data: [connection('acme-slack', 'cred_slack', 'slack_oauth', 'slack'), connection('openai', 'cred_openai', 'agent_openai', 'openai')] });
        }
        // Its variables' values: the workflow's owner's own read (a key is refused it above).
        if (method === 'GET' && path === `/v1/workflows/${WORKFLOW}/variables`) {
            return Response.json({ object: 'workflow_variables', workflow_id: WORKFLOW, version: held.version, definitions: DECLARED, variables: { last_order: 'o_1042' } });
        }
        const kind = path.match(/^\/v1\/step_types\/([^/]+)$/);
        if (method === 'GET' && kind && SETUP_STEP_TYPES[kind[1]]) return Response.json(SETUP_STEP_TYPES[kind[1]]);
        const choices = path.match(/^\/v1\/workflows\/[^/]+\/steps\/([^/]+)\/options$/);
        if (method === 'POST' && choices) {
            return Response.json({ object: 'step_options', options: [{ value: 'C01', label: '#general' }, { value: 'C02', label: '#orders' }], next_page_token: null, withheld: [] });
        }
        return null;
    };

    return async (input, init) => {
        const request = new Request(input, init);
        const url = new URL(request.url);
        const text = request.method === 'GET' ? '' : await request.clone().text();
        const body = text ? (JSON.parse(text) as Json) : {};
        let answered = await mine(request.method, url, body);
        // The workflow's graph says what the key may do with it; its runs and edits are the runs fixtures'. (Each is
        // asked as a client asks it, by address: a request handed on whole can be read only once.)
        if (!answered) {
            const again: RequestInit = { method: request.method, headers: request.headers, body: text || undefined };
            answered = await runs(request.url, again);
            if (await unanswered(answered)) answered = await tests(request.url, again);
            else if (request.method === 'GET' && decodeURIComponent(url.pathname) === `/v1/workflows/${WORKFLOW}/graph`) {
                // Its declared variable's value is held back and named, and so are the graph's own.
                const read = (await answered.json()) as Json;
                answered = Response.json({
                    ...read,
                    access: options.access ?? 'owner',
                    settings: { ...(read.settings as Json), variable_definitions: DECLARED.map(({ value: _value, ...shown }) => shown) },
                    settings_withheld: ['variable_definitions[0].value'],
                    graph: { ...(read.graph as Json), variables_withheld: ['last_order'] },
                });
            }
        }
        options.observe?.(request.method, url.pathname, Promise.resolve(answered), body, init);
        return answered;
    };
}
