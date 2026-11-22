// @vitest-environment happy-dom
// A workflow's Setup tab on the platform API alone (its slots' standards, standards.tsx): the steps it derives through
// the lens (an account to connect, a variable to fill, a field left blank, which agent runs it, then the Test Run),
// each judged against its step type as the API describes it; an account proved by its connection; a variable asked
// with its bound field's own picker and written as a `define_variable` edit; one whose value the API holds back shown
// as saved and hidden, never cleared; one with no value yet asked for; one typed written once; the setup check as the
// workflow's readiness says it; the staged message with the Test Run asked for; and the three parts only a host has
// in full, each saying plainly what it does here.
import { cleanup, fireEvent, render, renderHook, screen, waitFor } from '@testing-library/react';
import type { Edge, Node } from '@xyflow/react';
import { MotionGlobalConfig } from 'framer-motion';
import { NoClick, Workflow } from 'noclick';
import { useState } from 'react';
import { afterEach, beforeAll, beforeEach, describe, expect, it } from 'vitest';
import { ClientProvider } from '@/sdk/client';
import { standing } from '@/slots';
import { applyNodeUpdate, createWorkflowNode } from '../applyNodeUpdate';
import { WORKFLOW } from '../graph/fixtures';
import { SETUP, SETUP_COVER, SETUP_MCP, SETUP_RUNTIME, TEST_RUN } from '../slots';
import { forgetAuthoring } from '../testRun/authoring';
import { forgetTestRuns } from '../testRun/standards';
import { declaredVariables, setupFetch, setupGraph, VARIABLE_SECRET } from './fixtures';
import { SetupView } from './SetupView';
import {
    definitionsOfSettings,
    heldBackValues,
    HIDDEN_VARIABLE_PLACEHOLDER,
    holdsHiddenValue,
    isVariableFilled,
    savedVariableDefinitions,
    useSavedVariables,
    withHiddenValues,
    type WorkflowVariableDefinition,
} from './variables';

type Json = Record<string, unknown>;

interface Call {
    method: string;
    path: string;
    body: Json;
}

beforeAll(async () => {
    // Each step as it settles: drawn where its motion ends.
    MotionGlobalConfig.skipAnimations = true;
    Element.prototype.scrollIntoView ??= () => undefined;
    // What the standards load when first used: the SDK, the step form, the Markdown a frame draws with.
    await Promise.all([import('../standardsSdk'), import('../form/NodeConfig'), import('./RuntimeAccounts'), import('@/screens/resources/CodeView'), import('@/ui/connectStandards')]);
});

beforeEach(() => {
    forgetAuthoring();
    forgetTestRuns();
});
afterEach(cleanup);

function graph(): { nodes: Node[]; edges: Edge[] } {
    const stored = setupGraph();
    return {
        nodes: stored.nodes.map((n) => createWorkflowNode(String(n.id), String(n.type), n.position as { x: number; y: number }, n.config as Record<string, unknown>)),
        edges: stored.edges as unknown as Edge[],
    };
}

interface Opened {
    container: HTMLElement;
    calls: Call[];
    /** What the tab handed its host, in order. */
    told: string[];
    variables: { held: Json[] };
}

/** The tab on the fixtures' workflow, its variables read and written on the API as the app's page does, and what it
 *  hands its host (a step's accounts) applied to the workflow, as a canvas applies it. */
function open(more: { slack?: boolean; variables?: Json[]; hostHolds?: WorkflowVariableDefinition[]; asOwner?: boolean } = {}): Opened {
    const shown = graph();
    const calls: Call[] = [];
    const told: string[] = [];
    const variables = { held: more.variables ?? declaredVariables() };
    const client = new NoClick({
        apiKey: 'nk_test',
        baseUrl: 'https://api.test',
        maxRetries: 0,
        fetch: setupFetch({ variables, slack: more.slack, observe: (method, path, _answered, body) => void calls.push({ method, path, body }) }),
    });
    function Tab() {
        const [nodes, setNodes] = useState(shown.nodes);
        const read = useSavedVariables(more.hostHolds ? undefined : WORKFLOW, { asOwner: more.asOwner });
        // A host that holds the variables itself (a canvas that read them with its workflow) and saves the list whole.
        const [held, setHeld] = useState(more.hostHolds ?? []);
        const saved = more.hostHolds
            ? {
                  definitions: held,
                  change: (next: WorkflowVariableDefinition[]) => {
                      told.push(`variables ${JSON.stringify(savedVariableDefinitions(next))}`);
                      setHeld(next);
                  },
              }
            : read;
        return (
            <SetupView
                nodes={nodes}
                edges={shown.edges}
                workflowId={WORKFLOW}
                onConfigChange={(id, config) => void told.push(`settings ${id} ${JSON.stringify(config)}`)}
                onOperationChange={(id, operation) => void told.push(`operation ${id} ${operation}`)}
                onCredentialIdsChange={(id, ids) => {
                    told.push(`accounts ${id} ${JSON.stringify(ids)}`);
                    setNodes((held) => held.map((n) => (n.id === id ? applyNodeUpdate(n, { credentialIds: ids }) : n)));
                }}
                onOpenTestRun={() => void told.push('open the Test Run')}
                variableDefinitions={saved.definitions}
                onVariableDefinitionsChange={saved.change}
            />
        );
    }
    const { container } = render(
        <ClientProvider client={client}>
            <Tab />
        </ClientProvider>
    );
    return { container, calls, told, variables };
}

const heading = (container: Element) => container.querySelector('h2')?.textContent ?? '';
const button = (container: Element, text: string) => [...container.querySelectorAll('button')].find((b) => b.textContent?.trim() === text) as HTMLButtonElement;
const line = ({ method, path }: Call) => `${method} ${path}`;

async function next(opened: Opened): Promise<string> {
    const before = heading(opened.container);
    fireEvent.click(button(opened.container, 'Continue'));
    await waitFor(() => expect(heading(opened.container)).not.toBe(before));
    return heading(opened.container);
}

/** A rail row's words, by some of them. */
const railRow = (opened: Opened, text: string) =>
    [...opened.container.querySelectorAll('aside nav button')].find((b) => b.textContent?.includes(text))?.textContent?.replace(/\s+/g, ' ').trim();

/** Opens the rail and the row whose words include `text`. */
async function pick(opened: Opened, text: string): Promise<void> {
    const expand = opened.container.querySelector('button[aria-label="Expand sidebar"]');
    if (expand) fireEvent.click(expand);
    const row = await waitFor(() => {
        const found = [...opened.container.querySelectorAll('aside nav button')].find((b) => b.textContent?.includes(text));
        expect(found).toBeTruthy();
        return found as HTMLButtonElement;
    });
    fireEvent.click(row);
}

describe('a workflow’s Setup tab on the platform API', () => {
    it('derives its steps from the workflow, in order: accounts, variables, settings, the agent, then the Test Run', async () => {
        const opened = open();
        // The tab opens once every step type has been read, on the first thing still missing: the tool's account.
        await waitFor(() => expect(heading(opened.container)).toBe('Slack tools'));
        expect(opened.container.textContent).toContain('Send messages and read channels in your Slack workspace.');
        const order = [heading(opened.container)];
        for (let i = 0; i < 5; i += 1) order.push(await next(opened));
        expect(order).toEqual(['Slack tools', 'Channel', 'Reply to', 'Tell the CRM', 'Which agent runs it', 'Test Run']);
        // Each type was read once; nothing else was asked for the steps themselves.
        expect(opened.calls.map(line).filter((l) => l.startsWith('GET /v1/step_types/')).sort()).toEqual([
            'GET /v1/step_types/agent',
            'GET /v1/step_types/automation-http-request',
            'GET /v1/step_types/automation-slack',
            'GET /v1/step_types/trigger-webhook',
        ]);
    });

    it('lists each step in the rail with how it stands', async () => {
        const opened = open();
        await waitFor(() => expect(heading(opened.container)).toBe('Slack tools'));
        fireEvent.click(opened.container.querySelector('button[aria-label="Expand sidebar"]')!);
        const rail = await waitFor(() => {
            const nav = opened.container.querySelector('aside nav');
            expect(nav?.textContent).toContain('Test Run');
            return nav as HTMLElement;
        });
        const rows = [...rail.querySelectorAll('button')].map((b) => b.textContent?.replace(/\s+/g, ' ').trim());
        expect(rows).toEqual([
            'Slack tools0/1',
            'Connect an accountCredential',
            'Variables1/2',
            'ChannelField',
            'Reply toField',
            'Tell the CRM0/1',
            '1 field to fillField',
            'Agent1/1',
            'openai/gpt-5Agent',
            'Test Run',
        ]);
        // The agent's message isn't missing: a trigger feeds it. The tool wired to it is asked for its account, not
        // for an action.
        expect(opened.container.querySelector('aside')?.textContent).toContain('2 of 5 done');
    });

    it('gives a step the account’s one account of its kind, and proves it through the connection that holds it', async () => {
        const opened = open({ slack: true });
        // The one Slack account is chosen without asking: the tab hands it to the canvas and goes on to what's next.
        await waitFor(() => expect(opened.told).toEqual(['accounts tools {"slack_oauth":"cred_slack"}']));
        await waitFor(() => expect(heading(opened.container)).toBe('Channel'));
        // Its step stays in the rail, done; opened, it shows what the provider said of the account.
        await pick(opened, 'Connected');
        await waitFor(() => expect(heading(opened.container)).toBe('Slack tools'));
        expect(opened.container.textContent).toContain('It can send message. Nothing else.');
        await waitFor(() => expect(opened.container.textContent).toContain('#general, #orders'));
        expect(opened.container.textContent).toContain('and 7 more');
        expect(button(opened.container, 'Test again')).toBeTruthy();
        const verified = opened.calls.filter((c) => c.path.endsWith('/verify'));
        expect(verified.map(line)).toEqual(['POST /v1/connections/conn_acme-slack/verify']);
        // The check sends no body: the account is named in the address.
        expect(verified[0].body).toEqual({});
    });

    it('asks a variable bound to a field with that field’s own choices, and writes the pick as a define_variable edit', async () => {
        const opened = open();
        await waitFor(() => expect(heading(opened.container)).toBe('Slack tools'));
        expect(await next(opened)).toBe('Channel');
        expect(opened.container.textContent).toContain('Where new orders are announced.');
        fireEvent.focus(opened.container.querySelector('input[data-field-key="channel"]')!);
        const choice = await screen.findByText('#orders');
        // The choices are the bound step's own: read for that step, with its saved settings.
        expect(opened.calls.filter((c) => c.path.endsWith('/steps/tell/options')).map((c) => c.body.field)).toEqual(['channel']);
        fireEvent.mouseDown(choice);
        fireEvent.click(choice);
        await waitFor(() => expect(opened.variables.held[0].value).toBe('C02'));
        const edit = opened.calls.filter((c) => line(c) === `POST /v1/workflows/${WORKFLOW}/edits`).at(-1)!;
        // Its description and whose it is go with it, as they were read; the other variable isn't written.
        expect(edit.body.ops).toEqual([{ op: 'define_variable', name: 'channel', value: 'C02', description: 'Where new orders are announced.', per_user: true }]);
    });

    it('shows a variable whose value the API holds back as saved and hidden, counts it as filled, and never clears it', async () => {
        const opened = open();
        await waitFor(() => expect(heading(opened.container)).toBe('Slack tools'));
        // It isn't asked for (the walk in the first test never stops on it); opened from the rail, it reads as filled.
        await pick(opened, 'Reply to');
        await waitFor(() => expect(heading(opened.container)).toBe('Reply to'));
        expect(railRow(opened, 'Variables')).toContain('1/2');
        const input = opened.container.querySelector(`input[placeholder="${HIDDEN_VARIABLE_PLACEHOLDER}"]`) as HTMLInputElement;
        expect(input.value).toBe('');
        expect(opened.container.textContent).not.toContain(VARIABLE_SECRET);
        // The field opens focused: leaving it as it was, by blur or Enter, writes nothing.
        fireEvent.blur(input);
        fireEvent.keyDown(input, { key: 'Enter' });
        fireEvent.blur(input);
        // Typed over, the new value is written, once.
        fireEvent.change(input, { target: { value: 'orders@acme.example' } });
        fireEvent.blur(input);
        await waitFor(() => expect(opened.variables.held[1].value).toBe('orders@acme.example'));
        const edits = () => opened.calls.filter((c) => line(c) === `POST /v1/workflows/${WORKFLOW}/edits`).map((e) => e.body.ops);
        expect(edits()).toEqual([[{ op: 'define_variable', name: 'reply_to', value: 'orders@acme.example' }]]);
        // Emptied again, it stays saved (the edit never clears a value): nothing is written, and the field says it's
        // saved and hidden, not that a value is needed.
        fireEvent.change(input, { target: { value: '' } });
        fireEvent.blur(input);
        await waitFor(() => expect(opened.container.querySelector(`input[placeholder="${HIDDEN_VARIABLE_PLACEHOLDER}"]`)).toBeTruthy());
        fireEvent.blur(opened.container.querySelector(`input[placeholder="${HIDDEN_VARIABLE_PLACEHOLDER}"]`)!);
        expect(railRow(opened, 'Variables')).toContain('1/2');
        expect(edits()).toHaveLength(1);
        expect(opened.variables.held[1].value).toBe('orders@acme.example');
        expect(JSON.stringify(opened.calls)).not.toContain(VARIABLE_SECRET);
    });

    it('shows the workflow’s owner a held-back value from their own read of it, and writes it only once changed', async () => {
        const opened = open({ asOwner: true });
        await waitFor(() => expect(heading(opened.container)).toBe('Slack tools'));
        await pick(opened, 'Reply to');
        await waitFor(() => expect(heading(opened.container)).toBe('Reply to'));
        // Read apart from the graph, once, and shown in the field a key's page leaves hidden.
        expect(opened.calls.filter((c) => line(c) === `GET /v1/workflows/${WORKFLOW}/variables`)).toHaveLength(1);
        const input = opened.container.querySelector('input[placeholder="Enter a value"]') as HTMLInputElement;
        expect(input.value).toBe(VARIABLE_SECRET);
        expect(railRow(opened, 'Variables')).toContain('1/2');
        // Left as it was read, by blur or Enter, nothing is written.
        fireEvent.blur(input);
        fireEvent.keyDown(input, { key: 'Enter' });
        const edits = () => opened.calls.filter((c) => line(c) === `POST /v1/workflows/${WORKFLOW}/edits`).map((e) => e.body.ops);
        expect(edits()).toEqual([]);
        // Changed, it's written once, and nothing else of the list goes with it.
        fireEvent.change(input, { target: { value: 'orders@acme.example' } });
        fireEvent.blur(input);
        await waitFor(() => expect(opened.variables.held[1].value).toBe('orders@acme.example'));
        expect(edits()).toEqual([[{ op: 'define_variable', name: 'reply_to', value: 'orders@acme.example' }]]);
        // Nothing the page sent carries the value it read.
        expect(JSON.stringify(opened.calls)).not.toContain(VARIABLE_SECRET);
    });

    it('never asks for the values where its client isn’t the owner’s: each stays hidden', async () => {
        const opened = open();
        await waitFor(() => expect(heading(opened.container)).toBe('Slack tools'));
        await pick(opened, 'Reply to');
        await waitFor(() => expect(heading(opened.container)).toBe('Reply to'));
        expect(opened.container.querySelector(`input[placeholder="${HIDDEN_VARIABLE_PLACEHOLDER}"]`)).toBeTruthy();
        expect(opened.calls.map(line)).not.toContain(`GET /v1/workflows/${WORKFLOW}/variables`);
    });

    it('asks for a variable with no value yet, and writes what’s typed once', async () => {
        // Neither is bound to a field: each is asked in a plain field. One has no value yet, one has.
        const opened = open({ variables: [{ name: 'region', value: '' }, { name: 'reply_to', value: VARIABLE_SECRET }] });
        await waitFor(() => expect(heading(opened.container)).toBe('Slack tools'));
        // The blank one is a step still to do; the one that's set isn't.
        expect(await next(opened)).toBe('Region');
        const input = opened.container.querySelector('input[placeholder="Enter a value"]') as HTMLInputElement;
        expect(input.value).toBe('');
        fireEvent.click(opened.container.querySelector('button[aria-label="Expand sidebar"]')!);
        await waitFor(() => expect(railRow(opened, 'Variables')).toContain('1/2'));
        expect(railRow(opened, 'Region')).toBe('RegionField');
        // Left blank, by blur or Enter, nothing is written: it still needs a value.
        fireEvent.blur(input);
        fireEvent.keyDown(input, { key: 'Enter' });
        // Typed, it's written once, however many times the field is left after.
        fireEvent.change(input, { target: { value: 'eu-west-1' } });
        fireEvent.keyDown(input, { key: 'Enter' });
        fireEvent.blur(input);
        await waitFor(() => expect(opened.variables.held[0].value).toBe('eu-west-1'));
        await waitFor(() => expect(railRow(opened, 'Variables')).toContain('2/2'));
        fireEvent.blur(opened.container.querySelector('input[placeholder="Enter a value"]')!);
        const edits = () => opened.calls.filter((c) => line(c) === `POST /v1/workflows/${WORKFLOW}/edits`).map((e) => e.body.ops);
        expect(edits()).toEqual([[{ op: 'define_variable', name: 'region', value: 'eu-west-1' }]]);
        // Emptied, it's still saved (an edit never clears a value): it reads as saved and hidden, not as needing one.
        fireEvent.change(opened.container.querySelector('input[placeholder="Enter a value"]')!, { target: { value: '' } });
        fireEvent.blur(opened.container.querySelector('input[placeholder="Enter a value"]')!);
        await waitFor(() => expect(opened.container.querySelector(`input[placeholder="${HIDDEN_VARIABLE_PLACEHOLDER}"]`)).toBeTruthy());
        expect(railRow(opened, 'Variables')).toContain('2/2');
        expect(edits()).toHaveLength(1);
        expect(opened.variables.held[0].value).toBe('eu-west-1');
    });

    it('hands a host that saves the variables whole only what was typed: never an empty value over a saved one', async () => {
        // As a canvas holds them: one whose value its read held back, one with no value yet, one it holds whole.
        const opened = open({ hostHolds: [{ name: 'reply_to', hidden: true }, { name: 'region', value: '' }, { name: 'team', value: 'eu' }] });
        await waitFor(() => expect(heading(opened.container)).toBe('Slack tools'));
        // Only the one with no value is a step still to do.
        fireEvent.click(opened.container.querySelector('button[aria-label="Expand sidebar"]')!);
        await waitFor(() => expect(railRow(opened, 'Variables')).toContain('2/3'));
        const saves = () => opened.told.filter((t) => t.startsWith('variables '));
        const field = () => opened.container.querySelector('input[placeholder]') as HTMLInputElement;

        // The hidden one: its field opens focused and empty. Leaving it writes nothing.
        await pick(opened, 'Reply to');
        await waitFor(() => expect(heading(opened.container)).toBe('Reply to'));
        expect([field().value, field().placeholder]).toEqual(['', HIDDEN_VARIABLE_PLACEHOLDER]);
        fireEvent.blur(field());
        fireEvent.keyDown(field(), { key: 'Enter' });
        expect(saves()).toEqual([]);

        // The one held whole: shown, and left as it is it writes nothing either.
        await pick(opened, 'Team');
        await waitFor(() => expect(heading(opened.container)).toBe('Team'));
        expect(field().value).toBe('eu');
        fireEvent.blur(field());
        expect(saves()).toEqual([]);

        // The blank one: asked for; typed, the list is saved once, the hidden one going with no value so it's kept.
        await pick(opened, 'Region');
        await waitFor(() => expect(heading(opened.container)).toBe('Region'));
        expect([field().value, field().placeholder]).toEqual(['', 'Enter a value']);
        fireEvent.blur(field());
        fireEvent.change(field(), { target: { value: 'eu-west-1' } });
        fireEvent.blur(field());
        await waitFor(() => expect(railRow(opened, 'Variables')).toContain('3/3'));
        fireEvent.keyDown(field(), { key: 'Enter' });
        fireEvent.blur(field());
        expect(saves()).toEqual(['variables [{"name":"reply_to"},{"name":"region","value":"eu-west-1"},{"name":"team","value":"eu"}]']);

        // The hidden one typed over is saved with its new value; emptied again, no value goes, so the saved one stays.
        await pick(opened, 'Reply to');
        await waitFor(() => expect(heading(opened.container)).toBe('Reply to'));
        fireEvent.change(field(), { target: { value: 'orders@acme.example' } });
        fireEvent.blur(field());
        await waitFor(() => expect(saves()).toHaveLength(2));
        expect(saves()[1]).toBe('variables [{"name":"reply_to","value":"orders@acme.example"},{"name":"region","value":"eu-west-1"},{"name":"team","value":"eu"}]');
        fireEvent.change(field(), { target: { value: '' } });
        fireEvent.blur(field());
        await waitFor(() => expect(saves()).toHaveLength(3));
        expect(saves()[2]).toBe('variables [{"name":"reply_to"},{"name":"region","value":"eu-west-1"},{"name":"team","value":"eu"}]');
        await waitFor(() => expect(field().placeholder).toBe(HIDDEN_VARIABLE_PLACEHOLDER));
        expect(railRow(opened, 'Variables')).toContain('3/3');
        expect(opened.calls.filter((c) => c.method !== 'GET' && !c.path.endsWith('/options'))).toEqual([]);
    });

    it('reads which variables still need a value from what a read of the workflow says', () => {
        const read = definitionsOfSettings(
            { variable_definitions: [{ name: 'channel', value: '', description: 'Where.', per_user: true }, { name: 'reply_to' }, { name: '' }, { name: 'team', value: null }] },
            ['variable_definitions[1].value']
        );
        const expected: WorkflowVariableDefinition[] = [{ name: 'channel', description: 'Where.', per_user: true }, { name: 'reply_to', hidden: true }, { name: 'team' }];
        expect(read).toEqual(expected);
        expect(read.map(isVariableFilled)).toEqual([false, true, false]);
        expect(definitionsOfSettings(null, null)).toEqual([]);
    });

    it('says in one place how a variable stands: blank, shown, or saved and hidden', () => {
        // Only a row the read names is hidden: a read holds back a value that's there, never a blank one.
        const rows: WorkflowVariableDefinition[] = [{ name: 'api_base' }, { name: 'region', value: '' }, { name: 'team', value: 'eu' }];
        const [hidden, blank, shown] = withHiddenValues(rows, ['variable_definitions[0].value', 'graph.nodes[1].url', 'variable_definitions[7].value']);
        expect([hidden, blank, shown]).toEqual([{ name: 'api_base', hidden: true }, { name: 'region', value: '' }, { name: 'team', value: 'eu' }]);
        expect(withHiddenValues(rows, null)).toEqual(rows);
        expect([hidden, blank, shown].map(isVariableFilled)).toEqual([true, false, true]);
        expect(isVariableFilled({ name: 'region', value: ' ' })).toBe(false);
        // A hidden value keeps its variable's name until one is typed in its place.
        expect([hidden, blank, shown].map(holdsHiddenValue)).toEqual([true, false, false]);
        expect(holdsHiddenValue({ ...hidden, value: 'typed' })).toBe(false);
        // A save sends no value for it, left as it was or emptied again, so the saved one stays; typed over, the new
        // one goes. The read's mark is never saved.
        expect(savedVariableDefinitions([hidden, { ...hidden, value: '' }, { ...hidden, value: 'https://eu.example' }])).toEqual([
            { name: 'api_base' },
            { name: 'api_base' },
            { name: 'api_base', value: 'https://eu.example' },
        ]);
        // A variable held whole is saved as it stands, an emptied value too.
        expect(savedVariableDefinitions([{ name: 'region', value: '', per_user: true }])).toEqual([{ name: 'region', value: '', per_user: true }]);

        // Where the reader's own read of the values answered (the workflow's owner's), a held-back one is shown, by
        // name: the two reads are apart, so one the values no longer list stays hidden.
        const values = [{ name: 'newer', value: 'n' }, { name: 'api_base', value: 'https://eu.example' }, { name: 'region', value: 'us' }];
        const [read, , untouched] = withHiddenValues(rows, ['variable_definitions[0].value'], values);
        expect(read).toEqual({ name: 'api_base', value: 'https://eu.example', read: { name: 'api_base', value: 'https://eu.example' } });
        expect(untouched).toEqual({ name: 'team', value: 'eu' });
        expect(withHiddenValues(rows, ['variable_definitions[0].value'], [{ name: 'other', value: 'x' }])[0]).toEqual(hidden);
        expect([isVariableFilled(read), holdsHiddenValue(read)]).toEqual([true, false]);
        // A save names a read value only once its person changed it, or its name (a save keeps a value under the
        // variable's name); left as read, or typed over and back, it stays the server's. The mark is never saved.
        const sent = (definition: WorkflowVariableDefinition) => savedVariableDefinitions([definition])[0];
        expect(sent(read)).toEqual({ name: 'api_base' });
        expect(sent({ ...read, description: 'Where the API lives', per_user: true })).toEqual({ name: 'api_base', description: 'Where the API lives', per_user: true });
        expect(sent({ ...read, value: 'https://us.example' })).toEqual({ name: 'api_base', value: 'https://us.example' });
        expect(sent({ ...read, value: '' })).toEqual({ name: 'api_base', value: '' });
        expect(sent({ ...read, name: 'api_root' })).toEqual({ name: 'api_root', value: 'https://eu.example' });
    });

    it('asks for the held-back values only of a workflow its reader owns or can edit that holds some, and takes a refusal as none read', async () => {
        const asked: string[] = [];
        const answers = (status: number) =>
            new NoClick({
                apiKey: 'nk_test', baseUrl: 'https://api.test', maxRetries: 0,
                fetch: async (input) => {
                    asked.push(new URL(String(input instanceof Request ? input.url : input)).pathname);
                    return status === 200
                        ? Response.json({ object: 'workflow_variables', workflow_id: WORKFLOW, version: 4, definitions: [{ name: 'reply_to', value: 'x' }], variables: { page: 3 } })
                        : Response.json({ error: { type: status === 403 ? 'permission_denied' : status === 404 ? 'not_found' : 'invalid_request', message: 'No.' } }, { status });
                },
            });
        const graph = (more: Json) => ({ access: 'owner', settingsWithheld: ['variable_definitions[0].value'], variablesWithheld: [], ...more }) as never;
        const read = (status: number, more: Json = {}, asOwner = true) => heldBackValues(Workflow.fromId(WORKFLOW, { client: answers(status) }), graph(more), asOwner);
        expect((await read(200))?.variables).toEqual({ page: 3 });
        expect((await read(200, { settingsWithheld: [], variablesWithheld: ['page'] }))?.definitions).toEqual([{ name: 'reply_to', value: 'x' }]);
        // A teammate who can edit the workflow reads them as its owner does.
        expect((await read(200, { access: 'editor' }))?.variables).toEqual({ page: 3 });
        expect(asked).toHaveLength(3);
        // Not asked: a client that isn't a person's own, someone who only views the workflow, one that holds no value.
        expect([await read(200, {}, false), await read(200, { access: 'editor' }, false), await read(200, { access: 'viewer' }), await read(200, { access: null }), await read(200, { settingsWithheld: ['graph.nodes[0].url'] })]).toEqual([null, null, null, null, null]);
        expect(asked).toHaveLength(3);
        // Refused, or an API that doesn't serve the read yet: none read, no error. Any other failure is one.
        expect([await read(403), await read(404)]).toEqual([null, null]);
        await expect(read(400)).rejects.toThrow('No.');
    });

    it('ends on the Test Run: what isn’t connected, the workflow’s readiness, and the staged message to run', async () => {
        const opened = open();
        await waitFor(() => expect(heading(opened.container)).toBe('Slack tools'));
        await pick(opened, 'Test Run');
        await waitFor(() => expect(heading(opened.container)).toBe('Test Run'));
        // What still isn't connected, by what it breaks.
        expect(opened.container.textContent).toContain('Without Slack tools, your agent can\'t act.');
        // The setup check: the workflow's readiness as the API reads it.
        await waitFor(() => expect(opened.container.textContent).toContain('Setup isn’t finished: something below is in the way.'));
        expect([...opened.container.querySelectorAll('li')].map((li) => li.textContent)).toEqual(['Slack tools has no account connected.']);
        expect(opened.container.textContent).toContain('Slack tools is one of the agent’s tools: only a call to it fails.');
        expect(opened.container.textContent).toContain('Tell the CRM hasn’t completed a run yet.');
        // The staged message, as the Test Run screen shows it, and the run asked for.
        await waitFor(() => expect(opened.container.textContent).toContain('Sample event'));
        // (The rail names its last group the same: the step's own button is the last so named.)
        fireEvent.click([...opened.container.querySelectorAll('button')].filter((b) => b.textContent?.trim() === 'Test Run').at(-1)!);
        await waitFor(() => expect(opened.told).toContain('open the Test Run'));
        const { result, unmount } = renderHook(() => standing(TEST_RUN).useKept<Json | null>(`autorun-${WORKFLOW}`, null));
        await waitFor(() => expect(result.current[0]).toEqual({ trigger: 'trigger-webhook', run: 'generic:trigger-webhook' }));
        unmount();
        // Going back from the card names the step that connects it.
        fireEvent.click(button(opened.container, 'Connect Slack tools'));
        await waitFor(() => expect(heading(opened.container)).toBe('Slack tools'));
    });

    it('says which model the agent runs on, and connects its AI account', async () => {
        const opened = open();
        await waitFor(() => expect(heading(opened.container)).toBe('Slack tools'));
        await pick(opened, 'openai/gpt-5');
        await waitFor(() => expect(heading(opened.container)).toBe('Which agent runs it'));
        expect(opened.container.textContent).toContain('This workflow’s agent runs on openai/gpt-5.');
        expect(opened.container.textContent).toContain('is in NoClick’s app');
        // Its account's picker lists the account's AI accounts.
        await waitFor(() => expect(opened.calls.map(line)).toContain('GET /v1/connections'));
        // The API names no model to fall back on: the step just goes on.
        expect(button(opened.container, 'Continue')).toBeTruthy();
    });
});

describe('the parts of Setup only a host has in full', () => {
    it('say what they do here, and read nothing', () => {
        const calls: Call[] = [];
        const client = new NoClick({ apiKey: 'nk_test', baseUrl: 'https://api.test', maxRetries: 0, fetch: setupFetch({ observe: (method, path, _a, body) => void calls.push({ method, path, body }) }) });
        const Mcp = standing(SETUP_MCP);
        const Cover = standing(SETUP_COVER);
        const { container } = render(
            <ClientProvider client={client}>
                <Mcp workflowId={WORKFLOW} nodeId="mcp" nodeLabel="Team tools" />
                <Cover />
            </ClientProvider>
        );
        expect(container.textContent).toContain('Team tools serves its tools to a coding agent');
        expect(container.textContent).toContain('shown only in NoClick’s app');
        expect((container.querySelector('a') as HTMLAnchorElement).href).toBe(`https://noclick.com/dashboard?workflow=${WORKFLOW}`);
        // The cover draws nothing: this app opens Setup in place.
        expect(container.querySelectorAll('.fixed')).toHaveLength(0);
        expect(calls).toEqual([]);
        // The agent's step is never held unmet here, and there's no way on to name.
        expect(standing(SETUP_RUNTIME).useStep).toBeTypeOf('function');
        expect(standing(SETUP).askForTestRun).toBeTypeOf('function');
    });
});
