// The step form lab's scenes: the form for one step of the made-up workflow (../fixtures/world.ts) each, or its
// accounts, in the state a person meets them. The same list draws the lab's index and is what the tests open, as the
// owner and as a key.
import { WORKFLOW } from '../fixtures/world';
import type { NodeConfigProps } from '../NodeConfig';

export interface StepFormScene {
    id: string;
    title: string;
    group: 'A trigger' | 'An action' | 'Other states' | 'A step’s accounts';
    /** The form's props, but its change handler (the lab keeps what it's told). */
    step: Omit<NodeConfigProps, 'onChange'>;
    /** What it draws of the step: its settings (the form), or its accounts (the pickers). */
    part?: 'settings' | 'accounts';
}

const MAIL = { nodeType: 'example-mail', nodeId: 'mail', workflowId: WORKFLOW };
const CONNECTED = { example_mail_token: 'cred_mail' };

export const SCENES: readonly StepFormScene[] = [
    { id: 'hook', title: 'A webhook: its address loaded for the step', group: 'A trigger', step: { nodeType: 'example-hook', nodeId: 'hook', workflowId: WORKFLOW, config: {} } },
    { id: 'mail-trigger', title: 'A mail trigger: its address and folder', group: 'A trigger', step: { ...MAIL, nodeId: 'mail-in', operation: 'on_message', config: {}, credentialIds: CONNECTED } },
    { id: 'mail-pick', title: 'An action with no operation picked yet', group: 'An action', step: { ...MAIL, config: {}, credentialIds: CONNECTED } },
    {
        id: 'mail-send',
        title: 'Sending a message: a channel to pick, a body that references the trigger',
        group: 'An action',
        step: { ...MAIL, operation: 'send_message', config: { channel: 'C02', body: "New order from {{ $('hook').body.name }}" }, credentialIds: CONNECTED },
    },
    { id: 'mail-unconnected', title: 'Sending a message before its account is connected', group: 'An action', step: { ...MAIL, operation: 'send_message', config: {} } },
    { id: 'state', title: 'A step that keeps state between runs, with Clear state', group: 'Other states', step: { nodeType: 'state-manager', nodeId: 'state', workflowId: WORKFLOW, config: { key: 'last_order' } } },
    { id: 'settings', title: 'A step’s Settings view', group: 'Other states', step: { ...MAIL, operation: 'send_message', config: { channel: 'C01' }, credentialIds: CONNECTED, activeView: 'settings' } },
    { id: 'unknown', title: 'A step type the API doesn’t know', group: 'Other states', step: { nodeType: 'example-gone', nodeId: 'gone', workflowId: WORKFLOW, config: {} } },
    {
        id: 'accounts-picked',
        title: 'An account picked, among the account’s connections',
        group: 'A step’s accounts',
        part: 'accounts',
        step: { ...MAIL, operation: 'send_message', config: { channel: 'C02' }, credentialIds: CONNECTED },
    },
    {
        id: 'accounts-named',
        title: 'An account a named connection holds, as the step keeps it',
        group: 'A step’s accounts',
        part: 'accounts',
        step: { ...MAIL, operation: 'send_message', config: { channel: 'C02' }, credentialIds: { example_mail_token: 'cred_mail_shipping' } },
    },
    {
        id: 'accounts-revoked',
        title: 'An account that was disconnected',
        group: 'A step’s accounts',
        part: 'accounts',
        step: { ...MAIL, operation: 'send_message', config: {}, credentialIds: { example_mail_token: 'cred_mail_old' } },
    },
    {
        id: 'accounts-optional',
        title: 'No account yet, on a step NoClick’s key runs',
        group: 'A step’s accounts',
        part: 'accounts',
        step: { nodeType: 'example-search', nodeId: 'search', workflowId: WORKFLOW, operation: 'search', config: { query: 'orders' } },
    },
    {
        id: 'accounts-agent',
        title: 'An agent’s AI account, by the provider its model names',
        group: 'A step’s accounts',
        part: 'accounts',
        step: { nodeType: 'agent', nodeId: 'agent', workflowId: WORKFLOW, config: { model: 'openai/gpt-5.4-mini' }, credentialIds: { agent_openai: 'cred_openai' } },
    },
];

/** A scene's address in the lab. */
export function sceneSearch(scene: StepFormScene): string {
    return `?${new URLSearchParams({ scene: scene.id })}`;
}
