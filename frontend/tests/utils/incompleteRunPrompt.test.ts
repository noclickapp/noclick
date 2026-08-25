// @vitest-environment jsdom
//
// Tests for the Run button's unconfigured-steps gate.
//
// Pressing Run used to start the workflow no matter what, so a template with
// unfilled steps ran until the backend rejected the first hole. This gate turns
// that into an up-front popup. What carries the risk is the gate's ANSWER, not
// its rendering: returning a non-null prompt blocks a run the user asked for, so
// every "not actually a blocker" case (disabled steps, collaborator cursors,
// provider-wired nodes) has to fall through to null.

import { beforeAll, describe, expect, test } from 'vitest';
import type { Edge, Node } from '@xyflow/react';

let getIncompleteRunPrompt: typeof import('~/utils/incompleteRunPrompt').getIncompleteRunPrompt;
let describeStepsForIds: typeof import('~/utils/incompleteRunPrompt').describeStepsForIds;
let CREDENTIALS_KEY: typeof import('~/utils/incompleteRunPrompt').CREDENTIALS_KEY;
let buildNodeValidationContext: typeof import('~/utils/workflowNodeValidation').buildNodeValidationContext;
let setNodeIconData: typeof import('~/lib/nodeIconRegistry').setNodeIconData;

beforeAll(async () => {
    ({ getIncompleteRunPrompt, describeStepsForIds, CREDENTIALS_KEY } =
        await import('~/utils/incompleteRunPrompt'));
    ({ buildNodeValidationContext } = await import(
        '~/utils/workflowNodeValidation'
    ));
    ({ setNodeIconData } = await import('~/lib/nodeIconRegistry'));
}, 30000);

function makeNode(
    id: string,
    type: string,
    data: Record<string, unknown>
): Node {
    return { id, type, position: { x: 0, y: 0 }, data } as Node;
}

function makeEdge(source: string, target: string, targetHandle?: string): Edge {
    return { id: `${source}-${target}`, source, target, targetHandle } as Edge;
}

/** An agent node that validates clean: message filled, credential linked. */
function completeAgent(id: string, extra: Record<string, unknown> = {}): Node {
    return makeNode(id, 'agent', {
        config: { model: 'opencode', message: 'hi' },
        credentialIds: { agent_opencode: 'c1' },
        ...extra,
    });
}

/** An agent node missing its required `message` field. */
function incompleteAgent(
    id: string,
    extra: Record<string, unknown> = {}
): Node {
    return makeNode(id, 'agent', {
        config: { model: 'opencode' },
        credentialIds: { agent_opencode: 'c1' },
        ...extra,
    });
}

describe('getIncompleteRunPrompt — whether Run is intercepted', () => {
    test('returns null when every step is configured, so Run just runs', () => {
        expect(
            getIncompleteRunPrompt([completeAgent('a1'), completeAgent('a2')])
        ).toBeNull();
    });

    test('returns null for an empty canvas', () => {
        expect(getIncompleteRunPrompt([])).toBeNull();
    });

    test('surfaces each unconfigured step with what it is missing', () => {
        const steps = getIncompleteRunPrompt([
            completeAgent('a1'),
            incompleteAgent('a2'),
        ]);
        expect(steps).not.toBeNull();
        expect(steps!.map((s) => s.nodeId)).toEqual(['a2']);
        expect(steps![0].resolved).toBe(false);
    });
});

/** A Slack node wired into an agent's bottom handle as a tool provider. */
function providerNodes(operations: string[]) {
    return [
        completeAgent('agent1'),
        makeNode('slack1', 'automation-slack', {
            config: { agent_tool_operations: operations },
            credentialIds: { slack: 'c2' },
        }),
    ];
}

function providerStep(operations: string[]) {
    const nodes = providerNodes(operations);
    const ctx = buildNodeValidationContext(nodes, [
        makeEdge('slack1', 'agent1', 'bottom'),
    ]);
    return (
        getIncompleteRunPrompt(nodes, ctx) ??
        describeStepsForIds(nodes, ['slack1'], ctx)
    ).find((s) => s.nodeId === 'slack1')!;
}

describe('getIncompleteRunPrompt — inline-editable fields vs blockers', () => {
    // The popup edits missing fields in place, so a missing field has to arrive
    // with the schema prop its control is rendered from. Anything without one
    // stays a blocker that needs the config panel — a credential is a connect
    // flow, not a value to type.

    test('a missing required field becomes an editable field carrying its schema', () => {
        const steps = getIncompleteRunPrompt([incompleteAgent('a1')]);
        const field = steps![0].fields.find((f) => f.key === 'message');
        expect(field).toBeTruthy();
        expect(field!.prop).toBeTruthy();
        expect(/message/i.test(field!.message)).toBe(true);
    });

    test('a missing credential asks for the account picker, never a text control', () => {
        const noCred = makeNode('a1', 'agent', {
            config: { model: 'opencode', message: 'hi' },
        });
        const steps = getIncompleteRunPrompt([noCred]);
        expect(steps![0].needsCredentials).toBe(true);
        expect(steps![0].credentialsConnected).toBe(false);
        // There is no schema prop to render a control from, so it must never
        // land among the inline field editors.
        expect(steps![0].fields).toEqual([]);
        expect(steps![0].resolved).toBe(false);
    });

    test('a connected credential stays listed, marked done', () => {
        // Reported live: connecting an account made the block vanish, and with
        // it the entire step body — the user finished a step and was left
        // looking at "Nothing left to fill in for this step." Every other
        // requirement is sticky for exactly this reason; credentials were the
        // one that still derived from live validation.
        const node = makeNode('a1', 'agent', {
            config: { model: 'opencode', message: 'hi' },
        });
        const [before] = getIncompleteRunPrompt([node])!;
        expect(before.needsCredentials).toBe(true);

        const connected = makeNode('a1', 'agent', {
            config: { model: 'opencode', message: 'hi' },
            credentialIds: { agent_opencode: 'c1' },
        });
        const [after] = describeStepsForIds([connected], ['a1'], undefined, {
            a1: [CREDENTIALS_KEY],
        });
        expect(after.needsCredentials).toBe(true);
        expect(after.credentialsConnected).toBe(true);
        expect(after.resolved).toBe(true);
    });

    test('an agent-tool allowlist asks for the picker, not a text control', () => {
        // `agent_tool_operations` is a canvas-level key with no Pydantic schema
        // entry, so there is no prop to render a control from — but leaving it
        // a bare blocker meant the popup could only say "select at least one
        // action" and leave the user to go find where. It gets the real
        // operation picker instead.
        const step = providerStep([]);
        expect(step.needsToolActions).toBe(true);
        expect(step.fields).toEqual([]);
        expect(
            step.blockers.some((b) => b.fieldKey === 'agent_tool_operations')
        ).toBe(false);
        expect(step.resolved).toBe(false);
    });

    test('picking one action resolves the step', () => {
        expect(providerStep(['send_message']).resolved).toBe(true);
    });

    test('the picker survives the first pick — the two-action case', () => {
        // One selection satisfies the requirement, so deriving this live tore
        // the picker out from under anyone allowlisting a second action. Same
        // stickiness, and same reason, as the field editors.
        const nodes = providerNodes(['send_message']);
        const ctx = buildNodeValidationContext(nodes, [
            makeEdge('slack1', 'agent1', 'bottom'),
        ]);
        const step = describeStepsForIds(nodes, ['slack1'], ctx, {
            slack1: ['agent_tool_operations'],
        })[0];

        expect(step.needsToolActions).toBe(true);
        // Shown, but no longer blocking — those are different questions.
        expect(step.resolved).toBe(true);
    });
});

describe('describeStepsForIds — what the popup re-reads on every edit', () => {
    test('a step whose field got filled reports resolved, and keeps its row', () => {
        // Rows must not disappear as they are fixed: the list is what the user
        // is pointing at. Resolved is a state on the row, not a removal.
        const filled = [completeAgent('a1')];
        const steps = describeStepsForIds(filled, ['a1']);
        expect(steps.length).toBe(1);
        expect(steps[0].resolved).toBe(true);
        expect(steps[0].fields).toEqual([]);
    });

    test('re-reading picks up a value written since the popup opened', () => {
        const before = describeStepsForIds([incompleteAgent('a1')], ['a1']);
        expect(before[0].fields.map((f) => f.key)).toEqual(['message']);

        const after = describeStepsForIds(
            [completeAgent('a1')],
            ['a1'],
            undefined,
            {
                a1: ['message'],
            }
        );
        expect(after[0].resolved).toBe(true);
        expect(after[0].fields.find((f) => f.key === 'message')!.filled).toBe(
            true
        );
    });

    test('a sticky field keeps its editor once filled — the typing bug', () => {
        // A field stops being "missing" on its FIRST keystroke. Deriving the
        // editors purely from what is currently missing therefore unmounted the
        // control mid-word and dropped focus, so only one character could ever
        // be typed. Verified against the live UI before this was made sticky.
        const typedOneChar = [
            makeNode('a1', 'agent', {
                config: { model: 'opencode', message: 'S' },
                credentialIds: { agent_opencode: 'c1' },
            }),
        ];
        const steps = describeStepsForIds(typedOneChar, ['a1'], undefined, {
            a1: ['message'],
        });
        const field = steps[0].fields.find((f) => f.key === 'message');
        expect(field).toBeTruthy();
        expect(field!.filled).toBe(true);
    });

    test('without a sticky key the field would vanish — pins why the arg exists', () => {
        const typedOneChar = [
            makeNode('a1', 'agent', {
                config: { model: 'opencode', message: 'S' },
                credentialIds: { agent_opencode: 'c1' },
            }),
        ];
        expect(describeStepsForIds(typedOneChar, ['a1'])[0].fields).toEqual([]);
    });

    test('a sticky key the schema no longer describes is dropped', () => {
        // Changing the operation changes the field set. An editor with no schema
        // behind it would render as an uncontrolled box writing a dead key.
        const steps = describeStepsForIds(
            [completeAgent('a1')],
            ['a1'],
            undefined,
            {
                a1: ['message', 'field_from_another_operation'],
            }
        );
        expect(steps[0].fields.map((f) => f.key)).toEqual(['message']);
    });

    test('an id with no matching node is dropped, not rendered blank', () => {
        // A collaborator can delete a step while the popup is open.
        expect(
            describeStepsForIds([completeAgent('a1')], ['a1', 'deleted']).length
        ).toBe(1);
    });

    test('preserves the given order so rows never reshuffle mid-edit', () => {
        const nodes = [
            incompleteAgent('a1'),
            incompleteAgent('a2'),
            incompleteAgent('a3'),
        ];
        expect(
            describeStepsForIds(nodes, ['a3', 'a1', 'a2']).map((s) => s.nodeId)
        ).toEqual(['a3', 'a1', 'a2']);
    });
});

describe('getIncompleteRunPrompt — what must NOT block a run', () => {
    test('a disabled step is not a blocker: the backend skips it at execution', () => {
        // The canvas pill still counts disabled nodes — it means "needs your
        // attention". The run gate answers a narrower question, and blocking a
        // run on a step that will never execute is just wrong.
        expect(
            getIncompleteRunPrompt([incompleteAgent('a1', { disabled: true })])
        ).toBeNull();
    });

    test('a disabled step drops out of a prompt raised by a live one', () => {
        const steps = getIncompleteRunPrompt([
            incompleteAgent('live'),
            incompleteAgent('off', { disabled: true }),
        ]);
        expect(steps!.map((s) => s.nodeId)).toEqual(['live']);
    });

    test('a collaborator cursor never blocks the run', () => {
        // Cursor nodes are other people's pointers, not graph content. They
        // carry no config, so an unfiltered validator would call every one of
        // them incomplete and make Run un-pressable during collaboration.
        const cursor = makeNode('cursor-bob', 'agent', { config: {} });
        expect(getIncompleteRunPrompt([cursor])).toBeNull();
    });

    test('a provider-wired node with an allowlist is complete, given the wiring context', () => {
        // Wired into an agent's bottom handle, a node exposes actions instead of
        // running one — so it needs an allowlist, not an operation. Without the
        // context passed through, Run would block on a perfectly valid graph.
        const nodes = [
            completeAgent('agent1'),
            makeNode('slack1', 'automation-slack', {
                config: { agent_tool_operations: ['send_message'] },
                credentialIds: { slack: 'c2' },
            }),
        ];
        const edges = [makeEdge('slack1', 'agent1', 'bottom')];
        const ctx = buildNodeValidationContext(nodes, edges);
        expect(getIncompleteRunPrompt(nodes, ctx)).toBeNull();
    });

    test('the same provider node with an empty allowlist does block', () => {
        const nodes = [
            completeAgent('agent1'),
            makeNode('slack1', 'automation-slack', {
                config: { agent_tool_operations: [] },
                credentialIds: { slack: 'c2' },
            }),
        ];
        const ctx = buildNodeValidationContext(nodes, [
            makeEdge('slack1', 'agent1', 'bottom'),
        ]);
        const steps = getIncompleteRunPrompt(nodes, ctx);
        expect(steps!.map((s) => s.nodeId)).toEqual(['slack1']);
    });
});

describe('getIncompleteRunPrompt — how a step is named', () => {
    test('uses the icon registry label when it is loaded', () => {
        setNodeIconData({
            agent: {
                label: 'AI Agent',
                iconHtml: '<svg />',
                iconColor: '#abc',
            },
        } as never);
        const steps = getIncompleteRunPrompt([incompleteAgent('a1')]);
        expect(steps![0].title).toBe('AI Agent');
        expect(steps![0].iconHtml).toBe('<svg />');
    });

    test('falls back to the node type when the registry has no entry', () => {
        // The registry is populated by the dashboard loader; the previous test
        // seeded only `agent`, so slack still has no entry here. A step must
        // still be named something rather than rendering blank.
        const steps = getIncompleteRunPrompt([
            makeNode('slack1', 'automation-slack', { config: {} }),
        ]);
        expect(steps![0].title).toBe('automation-slack');
    });

    test('carries the user label separately from the title', () => {
        const steps = getIncompleteRunPrompt([
            incompleteAgent('a1', { label: 'Summarizer' }),
        ]);
        expect(steps![0].label).toBe('Summarizer');
    });
});
