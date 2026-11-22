// The step form's made-up world: a workflow's steps of made-up step types (a mail service's, with an action and a
// trigger; a webhook; a stateful step; a search that runs on NoClick's key; an agent), their settings schemas as
// `GET /v1/step_types/{type}` serves them, and the platform API answering the form's reads as it does: a dropdown's
// choices, a trigger's address, an expression's preview, clearing a step's state; and a step's accounts: the account's
// connections, one connected at its connect page, and a choice saved as the step's `set_connection` edit. The account
// holds secrets the API never answers (a webhook's signing secret, the mail account's token): the tests hold that none
// reaches the form, nor goes back in what it sends.
import { refusedToAccountKey } from '@/screens/console/ownerOnly';

/** Secrets the account holds, which the API withholds from every answer. */
export const SECRETS = { signingSecret: 'the hook signing value', mailToken: 'the mail account login value' } as const;

/** The workflow the form's steps are in. */
export const WORKFLOW = 'wf_orders';

type Json = Record<string, unknown>;

const MAIL_SEND = {
    title: 'ExampleMailSendConfig',
    type: 'object',
    properties: {
        operation: { const: 'send_message', title: 'Operation', 'x-display-name': 'Send a message', 'ui:hidden': true },
        channel: {
            type: 'string',
            title: 'Channel',
            description: 'Where the message goes.',
            'x-dynamic-options': { field_name: 'channel', placeholder: 'Pick a channel', searchable: true },
        },
        subject: { type: 'string', title: 'Subject' },
        body: { type: 'string', title: 'Body', 'ui:widget': 'textarea' },
        priority: { type: 'string', title: 'Priority', enum: ['low', 'normal', 'high'], default: 'normal' },
    },
    required: ['operation', 'channel', 'body'],
};

const MAIL_RECEIVE = {
    title: 'ExampleMailReceiveConfig',
    type: 'object',
    properties: {
        operation: { const: 'on_message', title: 'Operation', 'x-display-name': 'When a message arrives', 'x-is-trigger': true, 'ui:hidden': true },
        webhook_url: { type: 'string', title: 'Address', 'ui:widget': 'webhook', 'ui:loadValue': true, 'ui:copyable': true },
        folder: { type: 'string', title: 'Folder', default: 'inbox' },
    },
    required: ['operation'],
};

/** Each step type's settings schema, as `GET /v1/step_types/{type}` serves it (the canvas's `x-`/`ui:` included). */
const SCHEMAS: Record<string, Json> = {
    'example-mail': {
        title: 'Example-mail Node Configuration',
        type: 'object',
        properties: {
            config: { $ref: '#/$defs/ExampleMailConfig' },
            credentials: { anyOf: [{ $ref: '#/$defs/ExampleMailOAuth' }, { $ref: '#/$defs/ExampleMailCredential' }, { type: 'null' }], default: null },
        },
        $defs: {
            ExampleMailConfig: { anyOf: [{ $ref: '#/$defs/ExampleMailSendConfig' }, { $ref: '#/$defs/ExampleMailReceiveConfig' }] },
            ExampleMailSendConfig: MAIL_SEND,
            ExampleMailReceiveConfig: MAIL_RECEIVE,
            ExampleMailOAuth: {
                title: 'ExampleMailOAuthCredential',
                type: 'object',
                'x-credential-type': 'oauth',
                'x-oauth-provider': 'example_mail',
                properties: { credential_type: { const: 'example_mail_oauth' } },
            },
            ExampleMailCredential: {
                title: 'ExampleMailTokenCredential',
                type: 'object',
                properties: { credential_type: { const: 'example_mail_token' }, token: { type: 'string', title: 'Token', 'ui:widget': 'password' } },
                required: ['token'],
            },
        },
    },
    'example-hook': {
        title: 'Example-hook Node Configuration',
        type: 'object',
        properties: {
            config: {
                type: 'object',
                properties: {
                    webhook_url: { type: 'string', title: 'Webhook URL', 'ui:widget': 'webhook', 'ui:loadValue': true },
                    respond: { type: 'string', title: 'Respond with', enum: ['immediately', 'last_node'], enumNames: ['Right away', 'The last step’s output'], default: 'immediately' },
                    note: { type: 'string', title: 'Note', 'ui:placeholder': 'What this hook is for' },
                },
            },
        },
    },
    'example-search': {
        title: 'Example-search Node Configuration',
        type: 'object',
        properties: {
            config: { oneOf: [{ $ref: '#/$defs/ExampleSearchConfig' }] },
            credentials: { anyOf: [{ $ref: '#/$defs/ExampleSearchKey' }, { type: 'null' }], default: null },
        },
        $defs: {
            ExampleSearchConfig: {
                title: 'ExampleSearchConfig',
                type: 'object',
                'x-credentials-optional': true,
                properties: { operation: { const: 'search', title: 'Operation', 'ui:hidden': true }, query: { type: 'string', title: 'Query' } },
                required: ['operation', 'query'],
            },
            ExampleSearchKey: {
                title: 'ExampleSearchApiKeyCredential',
                type: 'object',
                properties: { credential_type: { const: 'example_search_api_key' }, api_key: { type: 'string', title: 'API key', 'ui:widget': 'password' } },
                required: ['api_key'],
            },
        },
    },
    agent: {
        title: 'Agent Node Configuration',
        type: 'object',
        properties: {
            config: { type: 'object', properties: { model: { type: 'string', title: 'Model' }, message: { type: 'string', title: 'Message' } } },
            credentials: { anyOf: [{ $ref: '#/$defs/AgentKey' }, { type: 'null' }], default: null },
        },
        $defs: { AgentKey: { title: 'AgentApiKeyCredential', type: 'object', properties: { credential_type: { const: 'agent_api_key' } } } },
    },
    'state-manager': {
        title: 'State-manager Node Configuration',
        type: 'object',
        properties: {
            config: {
                type: 'object',
                properties: {
                    key: { type: 'string', title: 'Key' },
                    value: { type: 'string', title: 'Value' },
                },
                required: ['key'],
            },
        },
    },
};

const STEP_TYPES: Record<string, Json> = {
    'example-mail': {
        label: 'Example Mail',
        operations: [
            { name: 'send_message', label: 'Send a message', description: 'Sends a message to a channel.', trigger: false, needs_account: true },
            { name: 'on_message', label: 'When a message arrives', description: 'Starts a run for each message.', trigger: true, needs_account: true },
        ],
        connection: { needed: true, integration: 'example_mail', credential_types: ['example_mail_oauth', 'example_mail_token'] },
    },
    'example-search': {
        label: 'Example Search',
        operations: [{ name: 'search', label: 'Search the web', description: 'Searches the web.', trigger: false, needs_account: false }],
        connection: { needed: false, integration: 'example_search', credential_types: ['example_search_api_key'] },
    },
    agent: {
        label: 'AI Agent',
        operations: [],
        connection: { needed: false, integration: null, credential_types: ['agent_api_key'] },
    },
    'example-hook': { label: 'Webhook', operations: [], connection: null },
    'state-manager': { label: 'State', operations: [], connection: null },
};

/** The channels the mail account lists. */
const CHANNELS = [
    { value: 'C01', label: '#general', metadata: null },
    { value: 'C02', label: '#orders', metadata: { members: 12 } },
];

/** The account's connections, as `GET /v1/connections` lists them: accounts connected in the app (`credential:<id>`), one
 *  of them revoked and one shared with it, and a named one, each naming the account it holds (`credential_id`). Never a
 *  secret: the API answers none. */
const CONNECTIONS: Json[] = [
    connection('cred_mail', 'Orders mailbox', 'example_mail', 'example_mail_token', { account: 'orders@example.test' }),
    connection('cred_mail_2', 'Support mailbox', 'example_mail', 'example_mail_token', { account: 'support@example.test' }),
    connection('cred_mail_old', 'Old mailbox', 'example_mail', 'example_mail_token', {
        status: 'disconnected',
        disconnected: { reason: 'revoked', message: 'This Example Mail account was disconnected.', provider_said: null, since: '2026-10-01T09:00:00Z', next_step: 'Reconnect it.' },
    }),
    connection('cred_mail_team', 'Team mailbox', 'example_mail', 'example_mail_oauth', { access: 'view', shared: { with: 'you', by: { name: 'Grace Hopper', email: null } } }),
    connection('cred_openai', 'Team key', 'openai', 'agent_openai'),
    { ...connection('cred_mail_shipping', 'shipping-mail', 'example_mail', 'example_mail_token', { account: 'shipping@example.test' }), id: 'conn_shipping', origin: 'api' },
];

/** The way in a connection of each integration holds when none is named: its first. */
const FIRST_WAY: Record<string, string> = { example_mail: 'example_mail_oauth', example_search: 'example_search_api_key', openai: 'agent_openai' };

function connection(id: string, name: string, integration: string, credentialType: string, more: Json = {}): Json {
    return {
        object: 'connection', id: `credential:${id}`, credential_id: id, name, connect_link: null, integration, credential_type: credentialType, status: 'connected',
        user_id: null, disconnected: null, origin: 'app', access: 'owner', shared: null, organization_id: null, approval_operations: [],
        test_account: false, account: null, plan: null, usage: null, verification: null, health: null, used_by: [],
        connected_at: '2026-09-01T09:00:00Z', created_at: '2026-09-01T09:00:00Z', updated_at: '2026-09-01T09:00:00Z', ...more,
    };
}

export type Observe = (method: string, path: string, answered: Promise<Response>, body: Record<string, unknown>) => void;

function refused(status: number, type: string, message: string): Response {
    return Response.json({ error: { type, message } }, { status });
}

/** The platform API's answers for the form's reads. Acting as one of the account's keys (`key`), what the API refuses a
 *  key is refused here too. */
export function formFetch({ actsAs = 'owner', observe }: { actsAs?: 'owner' | 'key'; observe?: Observe } = {}): typeof fetch {
    // Named connections made at their connect page: each finishes there at once, as if the person connected an account.
    const made = new Map<string, Json>();
    const answer = async (method: string, url: URL, body: Json): Promise<Response> => {
        const path = decodeURIComponent(url.pathname);
        if (actsAs === 'key' && refusedToAccountKey(method, url.pathname)) return refused(403, 'permission_denied', 'A key can’t do this: only the account’s signed-in owner can.');
        const type = path.match(/^\/v1\/step_types\/([^/]+)$/)?.[1];
        if (method === 'GET' && type) {
            if (!SCHEMAS[type]) return refused(404, 'not_found', `No step type '${type}'.`);
            return Response.json({ object: 'step_type', type, description: null, category: null, kinds: [], trigger: false, retired: null, ...STEP_TYPES[type], schema: SCHEMAS[type] });
        }
        if (method === 'GET' && path === '/v1/connections') return Response.json({ object: 'list', data: [...CONNECTIONS, ...made.values()], next_cursor: null });
        if (method === 'POST' && path === '/v1/connections') {
            const name = String(body.name);
            const id = `conn_${name.replace(/[^a-z0-9]/gi, '').slice(0, 20)}`;
            const pending = {
                ...connection(id, name, String(body.integration), String(body.credential_type ?? FIRST_WAY[String(body.integration)]), { status: 'pending', origin: 'api', credential_id: null }),
                id,
                connect_link: { url: `https://noclick.test/connect/${encodeURIComponent(name)}`, operation_id: `op_${id}`, expires_at: '2026-11-27T12:00:00Z' },
            };
            made.set(id, pending);
            return Response.json(pending, { status: 201 });
        }
        const waited = /^\/v1\/operations\/op_([^/]+)\/wait$/.exec(path);
        if (method === 'GET' && waited && made.has(waited[1])) {
            made.set(waited[1], { ...made.get(waited[1])!, status: 'connected', connect_link: null, account: 'new@example.test', credential_id: `cred_${waited[1]}` });
            return Response.json({ object: 'operation', id: `op_${waited[1]}`, kind: 'credential.connect', status: 'succeeded', result: { connection: waited[1] }, error: null });
        }
        const one = /^\/v1\/connections\/([^/]+)$/.exec(path);
        if (method === 'GET' && one && made.has(one[1])) return Response.json(made.get(one[1]));
        const edits = path.match(/^\/v1\/workflows\/([^/]+)\/edits$/);
        if (method === 'POST' && edits) {
            if (edits[1] !== WORKFLOW) return refused(404, 'not_found', 'No such workflow.');
            const ops = (body.ops ?? []) as Json[];
            return Response.json({ workflow_id: WORKFLOW, version: 8, history_version: 3, changed: true, summary: null, results: ops.map((op) => ({ op: op.op, id: op.id, slot: op.slot })), steps: {}, graph: null });
        }
        const step = path.match(/^\/v1\/workflows\/([^/]+)\/steps\/([^/]+)\/(options|values|expression|clear_state)$/);
        if (method === 'POST' && step) {
            const [, workflowId, stepId, read] = step;
            if (workflowId !== WORKFLOW) return refused(404, 'not_found', 'No such workflow.');
            if (read === 'options') {
                if (body.field !== 'channel') return refused(400, 'invalid_request', `The step's '${String(body.field)}' has no choices to list.`);
                return Response.json({ object: 'step_options', workflow_id: workflowId, step_id: stepId, field: body.field, options: CHANNELS, next_page_token: null, withheld: [] });
            }
            if (read === 'values') {
                // The trigger's address, minted for the step; its signing secret is withheld, as the API withholds it.
                const address = `https://hooks.example.test/${stepId}`;
                return Response.json({
                    object: 'step_value', workflow_id: workflowId, step_id: stepId, field: body.field,
                    values: { webhook_url: address, webhook_id: `wh_${stepId}`, trigger_registered: true },
                    withheld: ['signing_secret'],
                });
            }
            if (read === 'expression') return Response.json({ ok: true, kind: 'string', keys: null, preview: '"Ada"', preview_tokens: [{ t: 's', v: '"Ada"' }], error: null });
            return Response.json({ step_id: stepId, state_rows_deleted: 1, conversations_deleted: 0 });
        }
        return refused(404, 'not_found', `The fixtures answer no ${method} ${path}.`);
    };
    return async (input, init) => {
        const request = new Request(input, init);
        const url = new URL(request.url);
        const text = request.method === 'GET' ? '' : await request.text();
        const body = text ? (JSON.parse(text) as Json) : {};
        const answered = answer(request.method, url, body);
        observe?.(request.method, url.pathname, answered, body);
        return answered;
    };
}
