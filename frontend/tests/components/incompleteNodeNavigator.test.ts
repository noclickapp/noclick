// @vitest-environment jsdom
//
// Regression tests for the yellow incomplete-nodes pill (IncompleteNodeNavigator)
// and the node validator it depends on.
//
// Added while debugging two reported bugs:
//   1. validateNode read required config fields flat off `node.data` instead of
//      `node.data.config` (the authoritative location) — so every configured
//      node looked incomplete.
//   2. IncompleteNodeNavigator rendered prev/next arrows whenever the *display*
//      count (effectiveCount) was > 0 — including when that count came purely
//      from the setup-step fallback (minCount) with no per-node list behind it.
//      The arrows rendered but their handlers no-op'd (guarded on incompleteCount),
//      so the pill showed dead arrows that navigated nowhere.
//
// The wizard describes that used to live here (buildRequiredSteps /
// countUnfilledSetupSteps / buildSessionFromNodes) went away with the
// schema-driven Setup wizard — the Setup tab is now setup-node-only. The
// pill's own source of truth is still pinned below.
//
// Written as a .ts file (regular vitest config) using React.createElement so it
// runs under jsdom — the browser-mode integration config is currently broken by
// a vitest 4 provider API change.

import { afterEach, beforeAll, describe, expect, test, vi } from 'vitest';
import { createElement } from 'react';
import { render, cleanup, screen, fireEvent } from '@testing-library/react';
import type { Edge, Node } from '@xyflow/react';

let IncompleteNodeNavigator: typeof import('~/components/workflow/IncompleteNodeNavigator').IncompleteNodeNavigator;
let getIncompleteNodes: typeof import('~/utils/workflowNodeValidation').getIncompleteNodes;
let isFieldEmpty: typeof import('~/utils/workflowNodeValidation').isFieldEmpty;
let isFieldRequired: typeof import('~/utils/workflowNodeValidation').isFieldRequired;
let validateNode: typeof import('~/utils/workflowNodeValidation').validateNode;
let getNodeIssueSummary: typeof import('~/utils/workflowNodeValidation').getNodeIssueSummary;
let buildNodeValidationContext: typeof import('~/utils/workflowNodeValidation').buildNodeValidationContext;

// jsdom has no ResizeObserver; the pill observes its parent for width.
beforeAll(async () => {
    globalThis.ResizeObserver ??= class {
        observe() {}
        unobserve() {}
        disconnect() {}
    } as unknown as typeof ResizeObserver;

    const storage = new Map<string, string>();
    Object.defineProperty(window, 'localStorage', {
        configurable: true,
        value: {
            getItem: (key: string) => storage.get(key) ?? null,
            setItem: (key: string, value: string) => {
                storage.set(key, String(value));
            },
            removeItem: (key: string) => {
                storage.delete(key);
            },
            clear: () => {
                storage.clear();
            },
        },
    });

    ({ IncompleteNodeNavigator } = await import('~/components/workflow/IncompleteNodeNavigator'));
    ({ getIncompleteNodes, isFieldEmpty, isFieldRequired, validateNode, getNodeIssueSummary, buildNodeValidationContext } =
        await import('~/utils/workflowNodeValidation'));
}, 30000);

afterEach(cleanup);

function makeNode(id: string, type: string, data: Record<string, unknown>): Node {
    return { id, type, position: { x: 0, y: 0 }, data } as Node;
}

function makeEdge(source: string, target: string, targetHandle?: string): Edge {
    return { id: `${source}-${target}-${targetHandle ?? 'default'}`, source, target, targetHandle } as Edge;
}

// The pill renders itself only — CanvasNavigatorPills owns where it sits, so
// there are no positioning props to pass here.
const baseProps = {
    selectedNodeId: null,
};

describe('validateNode reads config from data.config', () => {
    // A CLI harness with no credential is incomplete in its own right (see the
    // credentials test below), so these field-location fixtures link one to
    // keep the assertions about field state alone.
    const agentCred = { agent_opencode: 'c1' };

    test('an agent node with its required field nested in data.config is complete', () => {
        const n = makeNode('a1', 'agent', {
            operation: 'default',
            config: { model: 'opencode', message: 'Hello' },
            credentialIds: agentCred,
        });
        expect(validateNode(n).isComplete).toBe(true);
    });

    test('an agent node missing its required field is incomplete', () => {
        const n = makeNode('a2', 'agent', {
            operation: 'default',
            config: { model: 'opencode' },
            credentialIds: agentCred,
        });
        const result = validateNode(n);
        expect(result.isComplete).toBe(false);
        expect(result.issues.some((i) => /message/i.test(i.message))).toBe(true);
    });

    test('a CLI-harness agent with no credential is incomplete', () => {
        // opencode / hermes used to validate clean with nothing linked — their
        // sub-model's provider is usage-based, but an isolated CLI harness has
        // no platform-key path, so the run died on the backend credential gate
        // with no prior warning anywhere in the UI.
        const n = makeNode('a4', 'agent', {
            operation: 'default',
            config: { model: 'opencode', message: 'Hello' },
        });
        const result = validateNode(n);
        expect(result.isComplete).toBe(false);
        expect(result.issues.some((i) => i.type === 'missing_credentials')).toBe(true);
    });

    test('a required field placed flat on data (the old, wrong location) does NOT count', () => {
        // The exact bug: before the fix the validator read data[fieldKey]. With the
        // value flat on data and data.config empty, the node must still read as
        // incomplete — the validator must only trust data.config.
        const n = makeNode('a3', 'agent', {
            operation: 'default',
            message: 'Hello', // flat — wrong place
            config: { model: 'opencode' }, // authoritative location: no message
        });
        expect(validateNode(n).isComplete).toBe(false);
    });
});

describe('a node with no action selected', () => {
    // Running one throws an error phrased for a developer ("operation is
    // required"), and nothing warned first: the discriminator is excluded from
    // the required-field loop, so such a node read as complete to the pill, the
    // canvas border and the Run gate alike.

    test('is incomplete when the node type offers a choice of actions', () => {
        const slack = makeNode('s1', 'automation-slack', { config: {} });
        const result = validateNode(slack);
        expect(result.isComplete).toBe(false);
        expect(result.issues.some((i) => i.type === 'missing_operation')).toBe(true);
    });

    test('is complete again once an action is picked', () => {
        const slack = makeNode('s1', 'automation-slack', {
            operation: 'send_message',
            config: {},
            credentialIds: { slack: 'c1' },
        });
        expect(
            validateNode(slack).issues.some((i) => i.type === 'missing_operation')
        ).toBe(false);
    });

    test('does NOT fire for a union the schema derives rather than asks about', () => {
        // AgentNode infers model_type from the model string — every variant is
        // x-flatten-union, so there is no picker and nothing to choose. Flagging
        // it would put every agent on the canvas permanently in the pill.
        const agent = makeNode('a1', 'agent', {
            config: { message: 'hi' },
        });
        expect(
            validateNode(agent).issues.some((i) => i.type === 'missing_operation')
        ).toBe(false);
    });

    test('the pill says so rather than reporting nothing', () => {
        const slack = makeNode('s1', 'automation-slack', { config: {} });
        expect(getNodeIssueSummary(slack)).toContain('no action selected');
    });

    test('does not also demand the FIRST action’s fields', () => {
        // getFieldsForOption falls back to option 0 when no operation is set,
        // so validating past the missing action reported some arbitrary
        // action's requirements as this node's. A Google Sheets node with
        // nothing picked was asking for a spreadsheet before anyone had said
        // whether it was reading, appending or creating one — and filling it
        // could satisfy validation for a field the chosen action never uses.
        const sheets = makeNode('g1', 'automation-google-sheets', { config: {} });
        const issues = validateNode(sheets).issues;

        expect(issues.some((i) => i.type === 'missing_operation')).toBe(true);
        expect(issues.filter((i) => i.type === 'missing_required_field')).toEqual([]);
    });

    test('the fields appear once the action is known', () => {
        const before = validateNode(
            makeNode('g1', 'automation-google-sheets', { config: {} })
        ).issues;
        const after = validateNode(
            makeNode('g1', 'automation-google-sheets', {
                operation: 'read_sheet_data',
                config: {},
                credentialIds: { google: 'c1' },
            })
        ).issues;

        expect(before.some((i) => i.type === 'missing_required_field')).toBe(false);
        expect(after.some((i) => i.type === 'missing_required_field')).toBe(true);
    });
});

describe('getIncompleteNodes — the pill source of truth', () => {
    // The pill reads getIncompleteNodes while the canvas border reads
    // validateNode/configValid. When they disagreed the pill persisted over a
    // canvas that already knew nothing was broken, and its arrows navigated to
    // nodes that looked fine. Same predicate, so: same answer.

    test('a fully-configured agent node is complete from both perspectives', () => {
        // model_type has a schema default + `ui:hidden`, so the user has nothing
        // to pick, and `message` is filled.
        const nodes = [makeNode('a1', 'agent', { config: { message: 'hi' } })];
        expect(getIncompleteNodes(nodes).length).toBe(0);
        expect(validateNode(nodes[0]).isComplete).toBe(true);
    });

    test('a node missing its required config field is incomplete from both perspectives', () => {
        const nodes = [makeNode('a2', 'agent', { config: {} })];
        expect(getIncompleteNodes(nodes).length).toBe(1);
        expect(validateNode(nodes[0]).isComplete).toBe(false);
    });

    test('filling the required field clears it from both perspectives', () => {
        const filled = [makeNode('a3', 'agent', { config: { message: 'h' } })];
        expect(getIncompleteNodes(filled).length).toBe(0);
        expect(validateNode(filled[0]).isComplete).toBe(true);
    });

    test('a provider-wired node needs its allowlist, not its operation', () => {
        // Wiring slack into an agent's bottom handle swaps operation/config
        // validation for "pick at least one action to expose".
        const nodes = [
            makeNode('slack1', 'automation-slack', { config: {}, credentialIds: { slack_oauth: 'c1' } }),
            makeNode('agent1', 'agent', { config: { message: 'hi' }, credentialIds: { agent_openrouter: 'c1' } }),
        ];
        const edges = [makeEdge('slack1', 'agent1', 'bottom')];
        const ctx = buildNodeValidationContext(nodes, edges);
        const issues = validateNode(nodes[0], ctx).issues;
        expect(issues.some((i) => i.fieldKey === 'agent_tool_operations')).toBe(true);
    });
});

describe('isFieldRequired — schema-shape rule (no live data)', () => {
    test('skips fields with a schema default', () => {
        expect(isFieldRequired({ key: 'temperature', required: true, prop: { default: 0.7 } })).toBe(false);
    });

    test('skips Optional[T] (anyOf with null type)', () => {
        expect(isFieldRequired({
            key: 'note',
            required: true,
            prop: { anyOf: [{ type: 'string' }, { type: 'null' }] },
        })).toBe(false);
    });

    test('skips whichever field the caller names as the discriminator', () => {
        // Whatever the schema says the discriminator is — `operation`,
        // `model_type`, `mode`, whatever — the caller passes it in and the
        // predicate skips it. Not hardcoded by name.
        expect(isFieldRequired({ key: 'operation', required: true, prop: {} }, 'operation')).toBe(false);
        expect(isFieldRequired({ key: 'model_type', required: true, prop: {} }, 'model_type')).toBe(false);
        // Without the arg, non-discriminator required fields still pass.
        expect(isFieldRequired({ key: 'operation', required: true, prop: {} })).toBe(true);
    });

    test('passes a required field with no default and no discriminator-match', () => {
        // Crucially does NOT consult any live value — same answer for an
        // empty config and a filled one. This is what lets the wizard keep
        // showing a step while the user is typing in it.
        expect(isFieldRequired({ key: 'message', required: true, prop: {} })).toBe(true);
    });
});

describe('isFieldEmpty — live-value rule', () => {
    test('treats undefined / null / blank string / empty array as empty', () => {
        expect(isFieldEmpty(undefined)).toBe(true);
        expect(isFieldEmpty(null)).toBe(true);
        expect(isFieldEmpty('')).toBe(true);
        expect(isFieldEmpty('   ')).toBe(true);
        expect(isFieldEmpty([])).toBe(true);
    });

    test('any non-blank value counts as filled', () => {
        expect(isFieldEmpty('a')).toBe(false);
        expect(isFieldEmpty(0)).toBe(false);
        expect(isFieldEmpty(false)).toBe(false);
        expect(isFieldEmpty(['a'])).toBe(false);
    });
});

describe('IncompleteNodeNavigator — incomplete-nodes pill', () => {
    test('does not render when every node is complete', () => {
        // Agent node fully configured — validateNode says complete, pill is hidden.
        const nodes = [
            makeNode('a1', 'agent', { config: { message: 'hi' } }),
        ];
        const { container } = render(
            createElement(IncompleteNodeNavigator, {
                ...baseProps,
                nodes,
                onNavigateToNode: vi.fn(),
            }),
        );
        expect(container.textContent?.trim()).toBe('');
    });

    test('renders synchronously off node data — no debounced configValid prerequisite', () => {
        // Slack node with no operation picked is incomplete per validateNode.
        // The pill must surface that immediately on first render, before any
        // useNodeConfigValidation debounce could fire.
        const nodes = [makeNode('s1', 'automation-slack', {})];
        render(
            createElement(IncompleteNodeNavigator, {
                ...baseProps,
                nodes,
                onNavigateToNode: vi.fn(),
            }),
        );
        expect(screen.getByTitle('Next incomplete node')).toBeTruthy();
        expect(screen.getByTitle('Previous incomplete node')).toBeTruthy();
        expect(screen.getByText('1 / 1')).toBeTruthy();
    });

    test('offers no hand-off into the Setup tab', () => {
        // The pill used to carry a "Guided Setup" button into the schema-driven
        // Setup wizard. That wizard is gone and the Setup tab now belongs to the
        // setup-node flow only, so incomplete nodes are fixed in the config
        // panel — a button routing to a tab that may not exist is a dead end.
        const nodes = [makeNode('s1', 'automation-slack', {})];
        const { container } = render(
            createElement(IncompleteNodeNavigator, {
                ...baseProps,
                nodes,
                onNavigateToNode: vi.fn(),
            }),
        );
        expect(container.textContent).not.toMatch(/Guided Setup/i);
        expect(container.querySelectorAll('button').length).toBe(2);
    });

    test('does not position itself — the shared row owns the gap to the error pill', () => {
        // The gap bug: the pill placed itself at a hardcoded `left: 170px`
        // standing in for "16px + the red error pill's width". The red pill is
        // really ~125px, so a ~30px gap opened between them — and it moved with
        // the digit count, eventually overlapping. Positioning belongs to
        // CanvasNavigatorPills; re-adding it here brings the bug back.
        const nodes = [makeNode('s1', 'automation-slack', {})];
        const { container } = render(
            createElement(IncompleteNodeNavigator, {
                ...baseProps,
                nodes,
                onNavigateToNode: vi.fn(),
            }),
        );
        const root = container.firstElementChild as HTMLElement;
        expect(root.className).not.toMatch(/\babsolute\b/);
        expect(root.style.left).toBe('');
        expect(root.style.bottom).toBe('');
    });

    test('arrows cycle through incomplete nodes', () => {
        const onNavigate = vi.fn();
        // Two slack nodes with no operation set → both incomplete.
        const nodes = [
            makeNode('n1', 'automation-slack', {}),
            makeNode('n2', 'automation-slack', {}),
        ];
        render(
            createElement(IncompleteNodeNavigator, {
                ...baseProps,
                nodes,
                onNavigateToNode: onNavigate,
            }),
        );
        const next = screen.getByTitle('Next incomplete node');
        fireEvent.click(next);
        expect(onNavigate).toHaveBeenCalledWith('n2');
    });
});
