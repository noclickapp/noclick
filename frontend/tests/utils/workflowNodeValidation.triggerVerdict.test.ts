// @vitest-environment jsdom
//
// A trigger whose registration is live but whose provider will not deliver
// (Slack: the app is not in the channel) mirrors that verdict as
// trigger_error. The canvas must paint it incomplete — badge, navigator,
// Setup — while a MANUAL run is never held for it.

import { beforeAll, describe, expect, test } from 'vitest';
import type { Node } from '@xyflow/react';

let validateNode: typeof import('~/utils/workflowNodeValidation').validateNode;
let getNodeIssueSummary: typeof import('~/utils/workflowNodeValidation').getNodeIssueSummary;
let issueBlocksRun: typeof import('~/utils/workflowNodeValidation').issueBlocksRun;
let getIncompleteRunPrompt: typeof import('~/utils/incompleteRunPrompt').getIncompleteRunPrompt;

beforeAll(async () => {
    ({ validateNode, getNodeIssueSummary, issueBlocksRun } = await import('~/utils/workflowNodeValidation'));
    ({ getIncompleteRunPrompt } = await import('~/utils/incompleteRunPrompt'));
}, 30000);

const VERDICT = "@noclick isn't in #support, so Slack won't send its events here.";

function slack(data: Record<string, unknown>): Node {
    return { id: 'slack1', type: 'automation-slack', position: { x: 0, y: 0 }, data } as Node;
}

describe('a registered-but-deaf trigger', () => {
    test('is an incomplete node with the verdict as its issue', () => {
        const node = slack({
            operation: 'on_channel_message',
            credentialIds: { slack: 'c2' },
            config: { channel: 'C1', trigger_registered: true, trigger_error: VERDICT },
        });
        const result = validateNode(node);
        expect(result.isComplete).toBe(false);
        expect(result.issues).toEqual([{ type: 'trigger_not_receiving', message: VERDICT }]);
        expect(getNodeIssueSummary(node)).toContain('#support');
    });

    test('never holds a manual run', () => {
        const node = slack({
            operation: 'on_channel_message',
            credentialIds: { slack: 'c2' },
            config: { channel: 'C1', trigger_registered: true, trigger_error: VERDICT },
        });
        expect(validateNode(node).issues.some(issueBlocksRun)).toBe(false);
        expect(getIncompleteRunPrompt([node])).toBeNull();
    });

    test('a stale mirror on an action operation paints nothing', () => {
        const node = slack({
            operation: 'send_message',
            credentialIds: { slack: 'c2' },
            config: { channel: 'C1', text: 'hi', trigger_error: VERDICT },
        });
        expect(validateNode(node).issues.some((i) => i.type === 'trigger_not_receiving')).toBe(false);
    });

    test('a missing credential is the first ask, not the verdict', () => {
        const node = slack({
            operation: 'on_channel_message',
            credentialIds: {},
            config: { channel: 'C1', trigger_error: 'Connect a credential to activate this trigger' },
        });
        expect(validateNode(node).issues.map((i) => i.type)).toEqual(['missing_credentials']);
    });
});
