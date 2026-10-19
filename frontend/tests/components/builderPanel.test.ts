// The builder panel reads a chat as changes to its automation: each request with the actions the builder took (said
// from the ops it reports, "Added step · Google Calendar", each settling as it ran or failed) and what it said on the
// way, folded under its answer, its last words; the steps of the canvas it touched (added, changed or removed); while
// it runs, only the batch running now and the words of its turn. A question it docks on the composer is named by the
// step it's about; history says each chat's request once.
import { beforeAll, describe, expect, it, vi } from 'vitest';
import type { Message } from '~/components/chat/types';
import { askSubject } from '~/components/chat/builder/BuilderAskCard';
import { historyRowWords } from '~/components/chat/builder/BuilderHistory';
import { deriveBuilderNodes } from '~/components/chat/builderProgress/model';
import { createGraphRecord, graphRecords } from '~/lib/liveGraphStore';
import { builderTurns, genSegments, isUnstartedChat, liveWork, replyWork, stepWords, BUILDER_WELCOME } from '~/lib/builderSteps';
import { loadFieldTitles } from '~/lib/fieldTitles';
import { setNodeIconData } from '~/lib/nodeIconRegistry';
import type { SerializedNodeMeta } from '~/lib/nodeCatalogTypes';

// Field titles come from the node schemas; a light stand-in keeps the 9MB of real ones out of the test.
vi.mock('~/utils/nodeSchemas', () => ({
    getNodeSchema: (type: string) =>
        ({
            'automation-slack': { $defs: { Post: { properties: { channel: { title: 'Channel' } } } } },
            'automation-google-calendar': { properties: { calendar_id: { title: 'Calendar' } } },
        })[type],
}));

beforeAll(async () => {
    setNodeIconData({
        'automation-google-calendar': { label: 'Google Calendar' } as SerializedNodeMeta,
        'automation-slack': { label: 'Slack' } as SerializedNodeMeta,
        'automation-gmail': { label: 'Gmail' } as SerializedNodeMeta,
    });
    await loadFieldTitles();
});

const step = (e: Record<string, unknown>) => ({ type: 'builder_step', status: 'completed', id: '', timestamp: 0, ...e }) as never;

const reply = (events: unknown[], extra: Partial<Message> = {}): Message => ({
    text: '',
    isUser: false,
    isComplete: true,
    editSegments: [{ type: 'text', text: 'Adding it now.' }, { type: 'events', events: events as never }],
    ...extra,
});

const GCAL = { op: 'add_node', target: 'Google Calendar', node_type: 'automation-google-calendar' };
const CHANNEL = { op: 'field', target: 'Slack', node_type: 'automation-slack', field: 'channel' };

describe('the actions a reply took', () => {
    const stepsOf = (message: Message) => replyWork(message.editSegments).items.flatMap((item) => (item.kind === 'step' ? [item.step] : []));

    it('reads the ops the builder reported, in order, each settled by how it ran', () => {
        const message = reply([
            step({ ...GCAL, batch: 1, index: 0, state: 'running' }),
            step({ ...CHANNEL, batch: 1, index: 1, state: 'running' }),
            { type: 'node_added', nodeId: 'gcal', nodeType: 'automation-google-calendar', nodeLabel: 'Google Calendar', status: 'completed' },
            step({ ...GCAL, batch: 1, index: 0, state: 'ok' }),
            step({ ...CHANNEL, batch: 1, index: 1, state: 'failed', reason: "that step isn't there" }),
        ]);
        expect(stepsOf(message)).toEqual([
            { ...GCAL, batch: 1, index: 0, state: 'ok' },
            { ...CHANNEL, batch: 1, index: 1, state: 'failed', reason: "that step isn't there" },
        ]);
    });

    it('settles a step where its plan was even when it ran in a later part of the reply, and keeps runs apart', () => {
        const message: Message = {
            text: '',
            isUser: false,
            isComplete: true,
            editSegments: [
                { type: 'events', events: [step({ ...GCAL, run: 'a', batch: 1, index: 0, state: 'running' })] as never },
                { type: 'text', text: 'Still going.' },
                { type: 'events', events: [step({ ...GCAL, run: 'a', batch: 1, index: 0, state: 'ok' })] as never },
                // A run that started again numbers its batches from 1 again: another step, not the same one.
                { type: 'events', events: [step({ ...CHANNEL, run: 'b', batch: 1, index: 0, state: 'ok' })] as never },
                { type: 'text', text: 'Done.' },
            ],
        };
        expect(stepsOf(message).map((s) => [s.op, s.state])).toEqual([['add_node', 'ok'], ['field', 'ok']]);
        expect(replyWork(message.editSegments).items.map((item) => item.kind)).toEqual(['step', 'said', 'step']);
    });

    it('a reply from before the builder reported its ops has none', () => {
        expect(stepsOf({ text: 'Done', isUser: false, editSteps: ['Modifying workflow'] })).toEqual([]);
    });
});

describe('an action in words', () => {
    it('says what it did to which step, now, once done, and when it failed', () => {
        expect(stepWords(GCAL, 'doing')).toEqual({ head: 'Adding step', tail: ' · Google Calendar' });
        expect(stepWords(GCAL, 'done')).toEqual({ head: 'Added step', tail: ' · Google Calendar' });
        expect(stepWords({ ...GCAL, target: 'Bogus' }, 'failed')).toEqual({ head: 'Couldn’t add step', tail: ' · Bogus' });
    });

    it('names a step it only knows by its app with the app, an edge by both ends', () => {
        expect(stepWords({ op: 'add_node', node_type: 'automation-slack' }, 'done')).toEqual({ head: 'Added step', tail: ' · Slack' });
        expect(stepWords({ op: 'query_operations', node_type: 'automation-google-calendar' }, 'doing')).toEqual({ head: 'Looking up', tail: ' Google Calendar' });
        const edge = { op: 'add_edge', ends: [{ node_type: 'automation-gmail' }, { label: 'Claude Code' }] };
        expect(stepWords(edge, 'done')).toEqual({ head: 'Connected steps', tail: ' · Gmail → Claude Code' });
        expect(stepWords({ op: 'add_edge' }, 'done')).toEqual({ head: 'Connected steps' });
    });

    it('says the field it set as the step calls it, never its key', () => {
        expect(stepWords(CHANNEL, 'done')).toEqual({ head: 'Set channel', tail: ' · Slack' });
        expect(stepWords({ op: 'field', node_type: 'automation-google-calendar', field: 'calendar_id' }, 'done').head).toBe('Set calendar');
        expect(stepWords({ op: 'field', target: 'Claude Code', node_type: 'agent', field: 'agent_tool_operations' }, 'doing')).toEqual({ head: 'Setting its actions', tail: ' · Claude Code' });
    });

    it('reads a docs topic and a variable as words, quotes what it searched for, and says an op with no target alone', () => {
        expect(stepWords({ op: 'read', target: 'agent-tools' }, 'done')).toEqual({ head: 'Read the docs on', tail: ' agent tools' });
        expect(stepWords({ op: 'define_variable', target: 'slack_channel' }, 'done')).toEqual({ head: 'Added a variable', tail: ' · slack channel' });
        expect(stepWords({ op: 'list_workflows', target: 'brief' }, 'done')).toEqual({ head: 'Searched automations for', tail: ' “brief”' });
        expect(stepWords({ op: 'bash' }, 'done')).toEqual({ head: 'Ran a command' });
    });
});

describe('a finished reply', () => {
    it('answers with its last words; what it said on the way folds in with its actions, in order', () => {
        const ran = (batch: number, op: Record<string, unknown>) => step({ ...op, batch, index: 0, state: 'ok' });
        const work = replyWork([
            { type: 'text', text: 'I’ll add Gmail.' },
            { type: 'events', events: [ran(1, { op: 'add_node', node_type: 'automation-gmail' }), { type: 'node_added', nodeId: 'gm', status: 'completed' }] as never },
            { type: 'text', text: '  ' },
            { type: 'text', text: 'Connecting it.' },
            { type: 'events', events: [ran(2, { op: 'add_edge' })] as never },
            { type: 'text', text: 'Gmail now feeds the agent.' },
        ]);
        expect(work.answer).toBe('Gmail now feeds the agent.');
        expect(work.items).toEqual([
            { kind: 'said', text: 'I’ll add Gmail.' },
            { kind: 'step', step: { op: 'add_node', node_type: 'automation-gmail', batch: 1, index: 0, state: 'ok' } },
            { kind: 'said', text: 'Connecting it.' },
            { kind: 'step', step: { op: 'add_edge', batch: 2, index: 0, state: 'ok' } },
        ]);
    });
});

describe('a run while it runs', () => {
    const turn = (n: number, at: number) => ({ type: 'builder_turn', turn: n, text_at: at });
    const text = 'I’ll add Gmail.Connecting it.';

    it('shows the batch running now, and once that batch ran, none', () => {
        const planned = [turn(1, 0), { type: 'builder_step', ...GCAL, batch: 1, index: 0, state: 'running' }];
        expect(liveWork(text, planned).step).toEqual({ ...GCAL, batch: 1, index: 0, state: 'running' });
        expect(liveWork(text, [...planned, { type: 'builder_step', ...GCAL, batch: 1, index: 0, state: 'ok' }]).step).toBeUndefined();
    });

    it('says only the words of the turn it’s on', () => {
        expect(liveWork(text, [turn(1, 0), turn(2, 15)]).said).toBe('Connecting it.');
        expect(liveWork('', [turn(1, 0)]).said).toBeUndefined();
    });

    it('puts a run’s words back with the events they came with', () => {
        const added = { type: 'node_added', nodeId: 'gm' };
        expect(genSegments(text, [turn(1, 0), added, turn(2, 15)])).toEqual([
            { type: 'text', text: 'I’ll add Gmail.' },
            { type: 'events', events: [{ ...added, status: 'completed' }] },
            { type: 'text', text: 'Connecting it.' },
        ]);
        // A stream with no turns marked is one turn: its words, then its events.
        expect(genSegments('Done.', [added])).toEqual([{ type: 'text', text: 'Done.' }, { type: 'events', events: [{ ...added, status: 'completed' }] }]);
    });
});

describe('a chat as changes', () => {
    const welcome: Message = { text: BUILDER_WELCOME, isUser: false, isComplete: true };

    it('a chat that only has the greeting has not started', () => {
        expect(isUnstartedChat([])).toBe(true);
        expect(isUnstartedChat([welcome])).toBe(true);
        expect(isUnstartedChat([welcome, { text: 'Add a step', isUser: true }])).toBe(false);
    });

    it('pairs each request with the replies under it, and leaves the greeting out', () => {
        const ask: Message = { text: 'Add my calendar', isUser: true };
        const first = reply([]);
        const second: Message = { text: 'Google Calendar is connected now.', isUser: false };
        const next: Message = { text: 'Make it shorter', isUser: true };
        expect(builderTurns([welcome, ask, first, second, next])).toEqual([
            { request: ask, replies: [first, second] },
            { request: next, replies: [] },
        ]);
    });

    it('keeps a reply that came with no request of its own (a note added to the chat) as a change of its own', () => {
        const note: Message = { text: 'Your run failed at Slack.', isUser: false };
        expect(builderTurns([note])).toEqual([{ replies: [note] }]);
    });
});

describe('the steps a change touched', () => {
    it('says which were added, which changed and which were removed', () => {
        const parts = deriveBuilderNodes([
            { id: '1', type: 'node_added', nodeId: 'gcal', nodeType: 'automation-google-calendar', nodeLabel: 'Google Calendar', timestamp: 1, status: 'completed' },
            { id: '2', type: 'node_updated', nodeId: 'gcal', timestamp: 2, status: 'completed' },
            { id: '3', type: 'node_config_filling', nodeId: 'slack', nodeType: 'automation-slack', nodeLabel: 'Slack', timestamp: 3, status: 'completed', field: 'channel' } as never,
            { id: '4', type: 'node_updated', nodeId: 'slack', timestamp: 4, status: 'completed' },
            { id: '5', type: 'node_removed', nodeId: 'old', nodeType: 'automation-gmail', nodeLabel: 'Gmail', timestamp: 5, status: 'completed' },
        ]);
        expect(parts.map((p) => [p.label, p.state, p.change, p.fields])).toEqual([
            ['Google Calendar', 'done', 'added', []],
            ['Slack', 'done', 'updated', ['channel']],
            ['Gmail', 'removed', 'removed', []],
        ]);
    });
});

describe('the docked question', () => {
    it('is named by the step it asks about, as the canvas names it and with its app’s mark, or by how many steps', () => {
        graphRecords['wf-ask'] = createGraphRecord('wf-ask', false, [
            { id: 'linear-1', type: 'automation-linear', position: { x: 0, y: 0 }, data: { label: 'File issues' } },
        ]);
        const linear = { nodeId: 'linear-1', label: 'Which Linear account should the agent use?', nodeType: 'automation-linear' };
        expect(askSubject([linear], 'wf-ask')).toEqual({ about: 'File issues', nodeType: 'automation-linear' });
        expect(askSubject([linear, { ...linear, label: 'Which team?' }], 'wf-ask')).toEqual({ about: 'File issues', nodeType: 'automation-linear' });
        // Several steps: how many, with no one app's mark on it.
        expect(askSubject([linear, { nodeId: 'slack-1', label: 'Which channel?', nodeType: 'automation-slack' }], 'wf-ask')).toEqual({ about: '2 steps need an answer' });
        // A step the canvas doesn't hold yet: its app.
        expect(askSubject([{ nodeId: 'new-1', label: 'Connect Google Calendar', nodeType: 'automation-google-calendar' }], 'wf-ask')).toEqual({
            about: 'Google Calendar', nodeType: 'automation-google-calendar',
        });
        // Not its own question again: the form under it asks that.
        expect(askSubject([{ nodeId: 'new-1', label: 'Which account?' }], 'wf-ask')).toEqual({ about: 'The builder has a question', nodeType: undefined });
    });
});

describe('a chat in history', () => {
    it('reads its request once when its title was cut from it, and keeps a title of its own with its preview', () => {
        const request = 'Add a Linear step so Claude Code files an issue for anything in the brief that needs a fix';
        expect(historyRowWords({ title: request.slice(0, 50), preview: request })).toEqual({ title: request });
        expect(historyRowWords({ title: 'Make the brief shorter', preview: 'It now keeps the brief under 120 words.' })).toEqual({
            title: 'Make the brief shorter',
            preview: 'It now keeps the brief under 120 words.',
        });
        expect(historyRowWords({ title: '', preview: '' })).toEqual({ title: 'Untitled chat', preview: undefined });
    });
});
