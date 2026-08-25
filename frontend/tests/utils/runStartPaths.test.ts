// @vitest-environment jsdom
//
// Tests for the Run popup's entry-point list — which nodes a full run starts
// from, and so which paths the user can pick between.
//
// The subtlety is tool providers. A provider's edge points INTO its agent, so
// counting it as "fed into" would hide the agent (the real entry point) and
// surface the providers instead, which cannot start anything on their own.

import { beforeAll, describe, expect, test } from 'vitest';
import type { Edge, Node } from '@xyflow/react';

let getRunStartPaths: typeof import('~/utils/incompleteRunPrompt').getRunStartPaths;
let toolProviderTitles: typeof import('~/utils/incompleteRunPrompt').toolProviderTitles;

beforeAll(async () => {
    ({ getRunStartPaths, toolProviderTitles } = await import(
        '~/utils/incompleteRunPrompt'
    ));
}, 30000);

const node = (
    id: string,
    type: string,
    data: Record<string, unknown> = {}
): Node => ({ id, type, position: { x: 0, y: 0 }, data }) as Node;

const edge = (source: string, target: string, targetHandle?: string): Edge =>
    ({ id: `${source}-${target}`, source, target, targetHandle }) as Edge;

const ids = (nodes: Node[], edges: Edge[]) =>
    getRunStartPaths(nodes, edges).map((p) => p.nodeId);

describe('getRunStartPaths', () => {
    test('a linear chain has one entry point', () => {
        const nodes = [
            node('a', 'automation-slack'),
            node('b', 'automation-gmail'),
        ];
        expect(ids(nodes, [edge('a', 'b')])).toEqual(['a']);
    });

    test('independent branches are separate entry points', () => {
        const nodes = [
            node('a', 'automation-slack'),
            node('b', 'automation-gmail'),
            node('c', 'automation-notion'),
        ];
        expect(ids(nodes, [edge('a', 'c'), edge('b', 'c')]).sort()).toEqual([
            'a',
            'b',
        ]);
    });

    test('an agent with tool providers is the entry point, not its providers', () => {
        // The regression this guards: bottom-handle edges point provider →
        // agent, so naive in-degree makes the agent look mid-graph and offers
        // Telegram and Sheets as things to run, which they cannot be.
        const nodes = [
            node('agent', 'agent'),
            node('telegram', 'automation-telegram'),
            node('sheets', 'automation-google-sheets'),
        ];
        const edges = [
            edge('telegram', 'agent', 'bottom'),
            edge('sheets', 'agent', 'bottom'),
        ];
        expect(ids(nodes, edges)).toEqual(['agent']);
    });

    test('skips disabled nodes, which the backend will not execute', () => {
        const nodes = [
            node('a', 'automation-slack'),
            node('off', 'automation-gmail', { disabled: true }),
        ];
        expect(ids(nodes, [])).toEqual(['a']);
    });

    test('skips sticky notes and collaborator cursors', () => {
        const nodes = [
            node('a', 'automation-slack'),
            node('n1', 'stickyNote'),
            node('cursor-bob', 'agent'),
        ];
        expect(ids(nodes, [])).toEqual(['a']);
    });

    test('skips interface blocks that head no branch', () => {
        // A standalone HTML/React app (or a display block) is a UX surface —
        // offering it as "Runs on its own" next to a real entry point is
        // noise, and skipping it loses nothing because it has no downstream.
        const nodes = [
            node('agent', 'agent'),
            node('app', 'interface-html-react'),
            node('img', 'interface-file'),
        ];
        expect(ids(nodes, [])).toEqual(['agent']);
    });

    test('keeps an interface block that heads a branch', () => {
        // Ticked paths become the run's scope, so excluding a form that FEEDS
        // a pipeline would silently drop everything downstream of it.
        const nodes = [
            node('form', 'interface-form'),
            node('slack', 'automation-slack'),
        ];
        expect(ids(nodes, [edge('form', 'slack')])).toEqual(['form']);
    });

    test('prefills an agent entry point with its saved message', () => {
        const nodes = [
            node('agent', 'agent', {
                config: { message: 'Summarise my inbox' },
            }),
        ];
        const [path] = getRunStartPaths(nodes, []);
        expect(path.isAgent).toBe(true);
        expect(path.message).toBe('Summarise my inbox');
    });

    test('a non-agent entry point carries no message', () => {
        const nodes = [
            node('a', 'automation-slack', { config: { message: 'hi' } }),
        ];
        expect(getRunStartPaths(nodes, [])[0].isAgent).toBe(false);
    });
});

// A row that names only the head of a branch asks the user to tick a path while
// showing them one node of it, so each path also carries what it runs.
//
// Names come from the icon registry first and the user's label second. The
// registry is populated from the live node catalog and is empty under jsdom, so
// these fixtures carry labels — which is the branch that resolves here.
describe('what each entry point runs', () => {
    const named = (id: string, type: string, label: string) =>
        node(id, type, { label });

    test('names the whole downstream chain, in graph order', () => {
        const nodes = [
            named('a', 'automation-slack', 'Slack'),
            named('b', 'automation-gmail', 'Gmail'),
            named('c', 'automation-notion', 'Notion'),
        ];
        const edges = [edge('a', 'b'), edge('b', 'c')];
        expect(getRunStartPaths(nodes, edges)[0].downstream).toEqual([
            'Gmail',
            'Notion',
        ]);
    });

    test('names a fan-out once per node, not once per edge', () => {
        // A diamond reaches the join through both arms; listing it twice would
        // overstate what the branch does.
        const nodes = [
            named('a', 'automation-slack', 'Slack'),
            named('l', 'automation-gmail', 'Gmail'),
            named('r', 'automation-notion', 'Notion'),
            named('end', 'automation-airtable', 'Airtable'),
        ];
        const edges = [
            edge('a', 'l'),
            edge('a', 'r'),
            edge('l', 'end'),
            edge('r', 'end'),
        ];
        expect(getRunStartPaths(nodes, edges)[0].downstream).toEqual([
            'Gmail',
            'Notion',
            'Airtable',
        ]);
    });

    test('leaves disabled steps out of the chain', () => {
        const nodes = [
            named('a', 'automation-slack', 'Slack'),
            node('off', 'automation-gmail', { label: 'Gmail', disabled: true }),
        ];
        expect(
            getRunStartPaths(nodes, [edge('a', 'off')])[0].downstream
        ).toEqual([]);
    });

    test('terminates on a loop in the chain', () => {
        const nodes = [
            named('root', 'trigger-run', 'Run'),
            named('a', 'automation-slack', 'Slack'),
            named('b', 'automation-gmail', 'Gmail'),
        ];
        // b loops back to a; an unguarded walk would never return. (The loop
        // needs a root outside it — a pure cycle has no entry point at all.)
        const edges = [edge('root', 'a'), edge('a', 'b'), edge('b', 'a')];
        expect(getRunStartPaths(nodes, edges).map((p) => p.downstream)).toEqual(
            [['Slack', 'Gmail']]
        );
    });

    test('lists tool providers separately from the chain', () => {
        // They only run if the agent calls them, so folding them into
        // "then …" would misdescribe the run.
        const nodes = [
            named('agent', 'agent', 'Agent'),
            named('telegram', 'automation-telegram', 'Telegram'),
            named('next', 'automation-gmail', 'Gmail'),
        ];
        const edges = [
            edge('telegram', 'agent', 'bottom'),
            edge('agent', 'next'),
        ];
        const [path] = getRunStartPaths(nodes, edges);
        expect(path.tools).toEqual(['Telegram']);
        expect(path.downstream).toEqual(['Gmail']);
    });

    test('a lone node runs nothing else', () => {
        const [path] = getRunStartPaths(
            [named('a', 'automation-slack', 'Slack')],
            []
        );
        expect(path.downstream).toEqual([]);
        expect(path.tools).toEqual([]);
    });
});

// A node-scoped run ("Run from here") describes only its start node, so it
// cannot reuse getRunStartPaths' whole-graph walk — but the message screen
// still wants to name the agent's tools.
describe('toolProviderTitles', () => {
    const named = (id: string, type: string, label: string) =>
        node(id, type, { label });

    test('names the providers wired into the node', () => {
        const nodes = [
            named('agent', 'agent', 'Agent'),
            named('telegram', 'automation-telegram', 'Telegram'),
            named('drive', 'automation-google-drive', 'Drive'),
        ];
        const edges = [
            edge('telegram', 'agent', 'bottom'),
            edge('drive', 'agent', 'bottom'),
        ];
        expect(toolProviderTitles('agent', nodes, edges)).toEqual([
            'Telegram',
            'Drive',
        ]);
    });

    test('ignores dataflow edges and other nodes providers', () => {
        const nodes = [
            named('agent', 'agent', 'Agent'),
            named('up', 'automation-slack', 'Slack'),
            named('other', 'automation-telegram', 'Telegram'),
            named('agent2', 'agent', 'Agent 2'),
        ];
        const edges = [edge('up', 'agent'), edge('other', 'agent2', 'bottom')];
        expect(toolProviderTitles('agent', nodes, edges)).toEqual([]);
    });

    test('skips disabled providers, which will not run', () => {
        const nodes = [
            named('agent', 'agent', 'Agent'),
            node('off', 'automation-telegram', {
                label: 'Telegram',
                disabled: true,
            }),
        ];
        expect(
            toolProviderTitles('agent', nodes, [edge('off', 'agent', 'bottom')])
        ).toEqual([]);
    });
});

// An agent that renders as a generic robot next to its own message reads as the
// wrong node, so it resolves to the mark of the harness it actually runs under.
describe('agent harness icons', () => {
    test('uses the harness mark when the registry has one', async () => {
        const { setNodeIconData } = await import('~/lib/nodeIconRegistry');
        setNodeIconData({
            agent: { label: 'AI Agent', iconHtml: '<generic/>', iconColor: '' },
            'agent:codex': {
                label: 'Agent (Codex)',
                iconHtml: '<codex/>',
                iconColor: '#fff',
            },
        } as never);
        const [path] = getRunStartPaths(
            [node('a', 'agent', { config: { model: 'codex' } })],
            []
        );
        expect(path.iconHtml).toBe('<codex/>');
        // The harness entry captions the MARK ("Agent (Codex)"); the node is
        // still called what the plain type says.
        expect(path.title).toBe('AI Agent');
    });

    test('falls back to the generic agent icon for an API model', () => {
        const [path] = getRunStartPaths(
            [
                node('a', 'agent', {
                    config: { model: 'openrouter/openai/gpt-5' },
                }),
            ],
            []
        );
        expect(path.iconHtml).toBe('<generic/>');
    });

    test('falls back to the generic icon when the harness entry is missing', () => {
        // The synthetic entries arrive with the rest of the registry, so a miss
        // means "not loaded yet", not "this agent has no icon".
        const [path] = getRunStartPaths(
            [node('a', 'agent', { config: { model: 'openclaw' } })],
            []
        );
        expect(path.iconHtml).toBe('<generic/>');
    });
});
