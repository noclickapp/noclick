// The platform API's answers for a workflow's Setup tab: what each of its step types is (with the settings its form
// asks for), the workflow's declared variables (read with its graph, a value never read back; written as
// `define_variable` edits), its readiness, the account's connections and what the provider says of one. Everything
// else is the Test Run fixtures' (the staged situations, a run) and the graph fixtures'.
import { refusedToAccountKey } from '@/screens/console/ownerOnly';
import { WORKFLOW, type Observe } from '../graph/fixtures';
import { testRunFetch } from '../testRun/fixtures';

type Json = Record<string, unknown>;

/** A value one of the account's variables holds, which no read carries. */
export const VARIABLE_SECRET = 'the reply-to value';

const operation = (name: string, trigger = false, needsAccount = !trigger): Json => ({ name, label: name, description: null, trigger, needs_account: needsAccount });

const type = (name: string, label: string, more: Json): Json => ({
    object: 'step_type', type: name, label, description: null, category: null, kinds: [], trigger: false, operations: [], connection: null,
    retired: null, schema: null, ...more,
});

/** The step types the Setup tab's workflow holds, as `GET /v1/step_types/{type}` describes them: Slack takes an account
 *  and asks for a channel and a text; the request step asks for its address; the sheet step offers two actions. */
export const SETUP_STEP_TYPES: Record<string, Json> = {
    'trigger-webhook': type('trigger-webhook', 'Webhook', { kinds: ['trigger'], trigger: true }),
    agent: type('agent', 'AI Agent', {
        operations: [operation('default', false, false)],
        schema: { type: 'object', properties: { config: { type: 'object', properties: { model: { type: 'string', title: 'Model', default: '' }, message: { type: 'string', title: 'Message', default: '' } } } } },
    }),
    'automation-slack': type('automation-slack', 'Slack', {
        description: 'Send messages and read channels in your Slack workspace.',
        kinds: ['trigger', 'tool'],
        operations: [operation('send_message'), operation('on_channel_message', true, true)],
        connection: { needed: true, integration: 'slack', credential_types: ['slack_oauth'] },
        schema: {
            title: 'Slack Node Configuration',
            type: 'object',
            properties: {
                config: { anyOf: [{ $ref: '#/$defs/SlackSend' }, { $ref: '#/$defs/SlackHeard' }] },
                credentials: { anyOf: [{ $ref: '#/$defs/SlackOAuth' }, { type: 'null' }], default: null },
            },
            $defs: {
                SlackSend: {
                    title: 'SlackSendConfig',
                    type: 'object',
                    properties: {
                        operation: { const: 'send_message', default: 'send_message', title: 'Operation', 'x-display-name': 'Send a message', 'ui:hidden': true },
                        channel: { type: 'string', title: 'Channel', 'x-dynamic-options': { field_name: 'channel', placeholder: 'Pick a channel' } },
                        text: { type: 'string', title: 'Text' },
                    },
                    required: ['operation', 'channel', 'text'],
                },
                SlackHeard: {
                    title: 'SlackHeardConfig',
                    type: 'object',
                    properties: {
                        operation: { const: 'on_channel_message', default: 'on_channel_message', title: 'Operation', 'x-display-name': 'When a message is posted', 'x-is-trigger': true, 'ui:hidden': true },
                        channel: { type: 'string', title: 'Channel' },
                    },
                    required: ['operation', 'channel'],
                },
                SlackOAuth: { title: 'SlackOAuthCredential', type: 'object', 'x-credential-type': 'oauth', 'x-oauth-provider': 'slack', properties: { credential_type: { const: 'slack_oauth' } } },
            },
        },
    }),
    'automation-http-request': type('automation-http-request', 'HTTP Request', {
        operations: [operation('send_http_post_request', false, false)],
        schema: { type: 'object', properties: { config: { type: 'object', properties: { url: { type: 'string', title: 'URL' }, body: { type: 'string', title: 'Body', default: '' } }, required: ['url'] } } },
    }),
};

/** The workflow the Setup tab is drawn on, as the canvas holds it: a webhook into an agent with Slack as its tool (no
 *  account yet), then a Slack message whose channel is a variable, and a request with no address. */
export function setupGraph(): { nodes: Json[]; edges: Json[] } {
    const step = (id: string, kind: string, config: Json): Json => ({ id, type: kind, position: { x: 0, y: 0 }, config });
    return {
        nodes: [
            step('hook', 'trigger-webhook', { label: 'Webhook' }),
            step('agent', 'agent', { label: 'Agent', model: 'openai/gpt-5', credentialIds: { agent_openai: 'cred_openai' } }),
            step('tools', 'automation-slack', { label: 'Slack tools', agent_tool_operations: ['send_message'] }),
            step('tell', 'automation-slack', { label: 'Tell the team', operation: 'send_message', channel: '{{vars.channel}}', text: 'A new order.', credentialIds: { slack_oauth: 'cred_slack' } }),
            step('crm', 'automation-http-request', { label: 'Tell the CRM', operation: 'send_http_post_request' }),
        ],
        edges: [
            { id: 'hook-agent', source: 'hook', target: 'agent', sourceHandle: null, targetHandle: null },
            { id: 'tools-agent', source: 'tools', target: 'agent', sourceHandle: 'top', targetHandle: 'bottom' },
            { id: 'agent-tell', source: 'agent', target: 'tell', sourceHandle: null, targetHandle: null },
            { id: 'tell-crm', source: 'tell', target: 'crm', sourceHandle: null, targetHandle: null },
        ],
    };
}

export interface SetupFetchOptions {
    actsAs?: 'owner' | 'key';
    observe?: Observe;
    /** The workflow's declared variables as the server stores them; an edit changes them. */
    variables?: { held: Json[] };
    /** Whether the account has a Slack account to give a step (one alone is chosen without asking). */
    slack?: boolean;
}

/** The variables the workflow declares: one with no value yet, one whose value is set (and never read back). */
export function declaredVariables(): Json[] {
    return [
        { name: 'channel', value: '', description: 'Where new orders are announced.', per_user: true },
        { name: 'reply_to', value: VARIABLE_SECRET },
    ];
}

function refused(status: number, kind: string, message: string): Response {
    return Response.json({ error: { type: kind, message } }, { status });
}

const AT = '2026-10-01T09:00:00.000Z';

/** A connection as the API lists it: by its name, the account it holds by id, never the account's values. */
const connection = (name: string, credentialId: string, credentialType: string, integration: string): Json => ({
    object: 'connection', id: `conn_${name}`, name, ref: `credential:${credentialId}`, origin: 'app', status: 'connected', integration, credential_id: credentialId, credential_type: credentialType,
    account: null, user_id: null, shared: null, health: { healthy: true, hint: null }, disconnected: null, verification: null, created_at: AT, updated_at: AT,
});

/** The platform API's answers for a workflow's Setup tab, the Test Run fixtures answering the rest. Acting as one of
 *  the account's keys (`key`), what the API refuses a key is refused here too. */
export function setupFetch(options: SetupFetchOptions = {}): typeof fetch {
    const rest = testRunFetch({ actsAs: options.actsAs });
    const variables = options.variables ?? { held: declaredVariables() };
    const workflow = `/v1/workflows/${WORKFLOW}`;

    /** The declarations as a read shows them: a value that's set is left out and named. */
    const shownVariables = (): { rows: Json[]; withheld: string[] } => {
        const withheld: string[] = [];
        const rows = variables.held.map((row, index) => {
            if (row.value === undefined || row.value === null || row.value === '') return row;
            withheld.push(`variable_definitions[${index}].value`);
            const { value: _value, ...shown } = row;
            return shown;
        });
        return { rows, withheld };
    };

    const answer = async (method: string, url: URL, body: Json, input: RequestInfo | URL, init: RequestInit | undefined): Promise<Response | null> => {
        const path = decodeURIComponent(url.pathname);
        if (options.actsAs === 'key' && refusedToAccountKey(method, url.pathname)) {
            return refused(403, 'permission_denied', 'A key can’t do this: only the account’s signed-in owner can.');
        }
        const kind = path.match(/^\/v1\/step_types\/([^/]+)$/);
        if (method === 'GET' && kind && SETUP_STEP_TYPES[kind[1]]) return Response.json(SETUP_STEP_TYPES[kind[1]]);
        if (method === 'GET' && path === `${workflow}/graph`) {
            const read = (await (await rest(input, init)).json()) as Json;
            const { rows, withheld } = shownVariables();
            return Response.json({ ...read, settings: { ...(read.settings as Json), variable_definitions: rows }, settings_withheld: withheld, graph: { ...setupGraph(), withheld: {} } });
        }
        if (method === 'POST' && path === `${workflow}/edits`) {
            const ops = (body.ops ?? []) as Json[];
            for (const op of ops) {
                if (op.op !== 'define_variable') continue;
                const next: Json = { name: op.name, value: op.value ?? '', ...(op.description ? { description: op.description } : {}), ...(op.per_user ? { per_user: true } : {}) };
                const at = variables.held.findIndex((row) => row.name === op.name);
                // A declaration with no value keeps the one already set.
                if (at >= 0) variables.held[at] = { ...variables.held[at], ...next, value: next.value || variables.held[at].value };
                else variables.held.push(next);
            }
            return rest(input, init);
        }
        if (method === 'GET' && path === workflow) {
            return Response.json({
                object: 'workflow', id: WORKFLOW, name: 'Orders', description: null, inputs: {}, app_url: null,
                steps: [],
                edges: [],
                readiness: {
                    status: 'needs_setup', meaning: 'Setup isn’t finished: something below is in the way.',
                    issues: [{ step: 'tools', code: 'credentials_missing', message: 'Slack tools has no account connected.' }],
                    warnings: [{ step: 'tools', code: 'tool_not_connected', message: 'Slack tools is one of the agent’s tools: only a call to it fails.' }],
                    unverified: [{ step: 'crm', code: 'never_ran', message: 'Tell the CRM hasn’t completed a run yet.' }],
                },
            });
        }
        if (method === 'GET' && path === '/v1/connections') {
            const slack = options.slack ? [connection('acme-slack', 'cred_slack', 'slack_oauth', 'slack')] : [];
            return Response.json({ object: 'list', next_cursor: null, data: [...slack, connection('openai', 'cred_openai', 'agent_openai', 'openai')] });
        }
        const verify = path.match(/^\/v1\/connections\/([^/]+)\/verify$/);
        if (method === 'POST' && verify) {
            return Response.json({
                ...connection('acme-slack', 'cred_slack', 'slack_oauth', 'slack'),
                verification: { reachable: true, samples: [{ label: '#general', value: 'C01' }, { label: '#orders', value: 'C02' }], noun: 'channels', total: 9, account_label: 'acme.slack.com', proves: 'account', message: null, hint: null, error: null },
            });
        }
        const options_ = path.match(/^\/v1\/workflows\/[^/]+\/steps\/([^/]+)\/options$/);
        if (method === 'POST' && options_) {
            return Response.json({ object: 'step_options', options: [{ value: 'C01', label: '#general' }, { value: 'C02', label: '#orders' }], next_page_token: null, withheld: [] });
        }
        return null;
    };
    return async (input, init) => {
        const request = new Request(input, init);
        const url = new URL(request.url);
        const text = request.method === 'GET' ? '' : await request.clone().text();
        const body = text ? (JSON.parse(text) as Json) : {};
        const mine = await answer(request.method, url, body, input, init);
        const answered = mine ?? (await rest(input, init));
        options.observe?.(request.method, url.pathname, Promise.resolve(answered), body, init);
        return answered;
    };
}
