// The step form lab's scenes: the form for one step of the made-up workflow (../fixtures/world.ts) each, in the state a
// person meets it. The same list draws the lab's index and is what the tests open, as the owner and as a key.
import { WORKFLOW } from '../fixtures/world';
import type { NodeConfigProps } from '../NodeConfig';

export interface StepFormScene {
    id: string;
    title: string;
    group: 'A trigger' | 'An action' | 'Other states';
    /** The form's props, but its change handler (the lab keeps what it's told). */
    step: Omit<NodeConfigProps, 'onChange'>;
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
];

/** A scene's address in the lab. */
export function sceneSearch(scene: StepFormScene): string {
    return `?${new URLSearchParams({ scene: scene.id })}`;
}
