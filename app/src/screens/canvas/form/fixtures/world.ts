// The step form's made-up world: a workflow's steps of three made-up step types (a mail service's, with an action and a
// trigger; a webhook; a stateful step), their settings schemas as `GET /v1/step_types/{type}` serves them, and the
// platform API answering the form's reads as it does: a dropdown's choices, a trigger's address, an expression's
// preview, clearing a step's state. The account holds secrets the API never answers (a webhook's signing secret, the
// mail account's token): the tests hold that none reaches the form, nor goes back in what it sends.
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
            credentials: { anyOf: [{ $ref: '#/$defs/ExampleMailCredential' }, { type: 'null' }], default: null },
        },
        $defs: {
            ExampleMailConfig: { anyOf: [{ $ref: '#/$defs/ExampleMailSendConfig' }, { $ref: '#/$defs/ExampleMailReceiveConfig' }] },
            ExampleMailSendConfig: MAIL_SEND,
            ExampleMailReceiveConfig: MAIL_RECEIVE,
            ExampleMailCredential: { type: 'object', properties: { token: { type: 'string', 'ui:widget': 'password' } } },
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
        connection: { needed: true, integration: 'example_mail', credential_types: ['example_mail_token'] },
    },
    'example-hook': { label: 'Webhook', operations: [], connection: null },
    'state-manager': { label: 'State', operations: [], connection: null },
};

/** The channels the mail account lists. */
const CHANNELS = [
    { value: 'C01', label: '#general', metadata: null },
    { value: 'C02', label: '#orders', metadata: { members: 12 } },
];

export type Observe = (method: string, path: string, answered: Promise<Response>, body: Record<string, unknown>) => void;

function refused(status: number, type: string, message: string): Response {
    return Response.json({ error: { type, message } }, { status });
}

/** The platform API's answers for the form's reads. Acting as one of the account's keys (`key`), what the API refuses a
 *  key is refused here too. */
export function formFetch({ actsAs = 'owner', observe }: { actsAs?: 'owner' | 'key'; observe?: Observe } = {}): typeof fetch {
    const answer = async (method: string, url: URL, body: Json): Promise<Response> => {
        const path = decodeURIComponent(url.pathname);
        if (actsAs === 'key' && refusedToAccountKey(method, url.pathname)) return refused(403, 'permission_denied', 'A key can’t do this: only the account’s signed-in owner can.');
        const type = path.match(/^\/v1\/step_types\/([^/]+)$/)?.[1];
        if (method === 'GET' && type) {
            if (!SCHEMAS[type]) return refused(404, 'not_found', `No step type '${type}'.`);
            return Response.json({ object: 'step_type', type, description: null, category: null, kinds: [], trigger: false, retired: null, ...STEP_TYPES[type], schema: SCHEMAS[type] });
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
