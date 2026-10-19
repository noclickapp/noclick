// The builder's work in words. The builder reports each op of a batch as it starts (planned) and again once the batch
// ran (ok, or failed with why), and marks where each brain turn's words begin (`builder_step` and `builder_turn`
// events beside its graph events, live and kept with the turn: backend coder/workflow/agentic/steps.py). This says an
// op as what it's doing now ("Adding step · Google Calendar"), did, or couldn't do; reads a finished reply as its
// answer (its last words) over the actions it took and what it said on the way; and a running one as the batch it's
// on and the words of its turn. It also reads a builder chat as changes: each request with the replies under it.
import type { EditSegment, Message } from '~/components/chat/types';
import { fieldTitle, fieldWords } from '~/lib/fieldTitles';
import { getNodeIconMeta } from '~/lib/nodeIconRegistry';

/** One end of an edge: its label, else its app. */
export interface StepEnd {
    label?: string;
    node_type?: string;
}

/** One op the builder ran: what it did, and what to (a step by its label, else its app; the field it set; words it
 *  searched for; an edge's ends), and how it went: `running` while its batch runs (in a reply that has ended, it never
 *  finished), then `ok` or `failed` (with `reason`). A step kept before outcomes were reported has no state. */
export interface BuilderStep {
    op: string;
    target?: string;
    node_type?: string;
    field?: string;
    ends?: StepEnd[];
    state?: 'running' | 'ok' | 'failed';
    reason?: string;
    batch?: number;
    index?: number;
}

/** The greeting a builder chat opens with until the first request. */
export const BUILDER_WELCOME = 'How can I help?';

type Event = Record<string, unknown>;

const KEYS = ['op', 'target', 'node_type', 'field', 'ends', 'state', 'reason', 'batch', 'index'] as const;

function stepOf(event: Event): BuilderStep {
    const step: Record<string, unknown> = {};
    for (const key of KEYS) if (event[key] !== undefined && event[key] !== null && event[key] !== '') step[key] = event[key];
    return step as unknown as BuilderStep;
}

/** Adds the steps among events to `list`, each once, where it first came, as it last stood: how an op ran replaces its
 *  plan. A step is known by its run (a run that starts again numbers its batches from 1 again), batch and place. */
function addSteps<T>(events: Event[], list: T[], at: Map<string, number>, item: (step: BuilderStep) => T): void {
    for (const event of events) {
        if (event.type !== 'builder_step' || typeof event.op !== 'string') continue;
        const step = item(stepOf(event));
        const key = event.batch !== undefined && event.index !== undefined ? `${event.run ?? ''}:${event.batch}:${event.index}` : null;
        if (key && at.has(key)) list[at.get(key)!] = step;
        else {
            if (key) at.set(key, list.length);
            list.push(step);
        }
    }
}

function stepsIn(events: Event[]): BuilderStep[] {
    const steps: BuilderStep[] = [];
    addSteps(events, steps, new Map(), (step) => step);
    return steps;
}

export type WorkItem = { kind: 'said'; text: string } | { kind: 'step'; step: BuilderStep };

/** A finished reply: its answer, its last words; and before it, in order, what it said on the way and each action it
 *  took. */
export function replyWork(segments: EditSegment[] = []): { items: WorkItem[]; answer?: string } {
    const said = (s: EditSegment) => (s.type === 'text' ? s.text.trim() : '');
    let last = -1;
    segments.forEach((segment, i) => {
        if (said(segment)) last = i;
    });
    const items: WorkItem[] = [];
    const at = new Map<string, number>();
    segments.forEach((segment, i) => {
        if (segment.type === 'text') {
            if (i !== last && said(segment)) items.push({ kind: 'said', text: said(segment) });
        } else addSteps<WorkItem>(segment.events as unknown as Event[], items, at, (step) => ({ kind: 'step', step }));
    });
    return { items, answer: last >= 0 ? said(segments[last]) : undefined };
}

/** What a running gen is on: the batch it's running now (its first op), if it's mid-batch; and the words of the turn
 *  it's on. Read from the gen's own text and events, so nothing from before it (a turn before an answered question)
 *  reads as now. */
export function liveWork(text: string, events: Event[]): { step?: BuilderStep; said?: string } {
    const running = stepsIn(events).filter((s) => s.state === 'running');
    const batch = running.length ? Math.max(...running.map((s) => s.batch ?? 0)) : undefined;
    const marks = events.filter((e) => e.type === 'builder_turn');
    const from = marks.length ? Number(marks[marks.length - 1].text_at) || 0 : 0;
    const said = text.slice(from).trim();
    return { step: running.find((s) => (s.batch ?? 0) === batch), ...(said ? { said } : {}) };
}

/** A gen's text and events back in the order they came: each turn's words, then that turn's events. A stream with no
 *  turns marked is one turn. */
export function genSegments(text: string, events: Event[]): EditSegment[] {
    const turns: { at: number; events: Event[] }[] = [{ at: 0, events: [] }];
    for (const event of events) {
        if (event.type === 'builder_turn') turns.push({ at: Number(event.text_at) || 0, events: [] });
        else turns[turns.length - 1].events.push(event);
    }
    const segments: EditSegment[] = [];
    turns.forEach((turn, i) => {
        const words = text.slice(turn.at, i + 1 < turns.length ? turns[i + 1].at : text.length);
        if (words.trim()) segments.push({ type: 'text', text: words });
        if (turn.events.length) {
            segments.push({ type: 'events', events: turn.events.map((e) => ({ ...e, status: 'completed' })) as never });
        }
    });
    return segments;
}

type Phase = 'doing' | 'done' | 'failed';
/** An op said now, once done, and when it couldn't be; `lead` is the words its target completes ("Looked up" +
 *  " Google Calendar"). */
interface Said {
    doing: string;
    done: string;
    failed: string;
    lead?: [string, string];
    /** Its target is words it was given: quoted. */
    quote?: boolean;
    /** Its target is a name it gave (a slug or an identifier): said as words. */
    words?: boolean;
}

const SAID: Record<string, Said> = {
    add_node: { doing: 'Adding step', done: 'Added step', failed: 'Couldn’t add step' },
    remove_node: { doing: 'Removing step', done: 'Removed step', failed: 'Couldn’t remove step' },
    add_edge: { doing: 'Connecting steps', done: 'Connected steps', failed: 'Couldn’t connect steps' },
    remove_edge: { doing: 'Disconnecting steps', done: 'Disconnected steps', failed: 'Couldn’t disconnect steps' },
    field: { doing: 'Setting {field}', done: 'Set {field}', failed: 'Couldn’t set {field}' },
    set_credentials: { doing: 'Attaching an account', done: 'Attached an account', failed: 'Couldn’t attach an account' },
    update_settings: { doing: 'Updating settings', done: 'Updated settings', failed: 'Couldn’t update settings' },
    add_sticky_note: { doing: 'Adding a note', done: 'Added a note', failed: 'Couldn’t add a note' },
    query_operations: { doing: 'Looking up a step', done: 'Looked up a step', failed: 'Couldn’t look up a step', lead: ['Looking up', 'Looked up'] },
    query_schema: { doing: 'Looking up a step', done: 'Looked up a step', failed: 'Couldn’t look up a step', lead: ['Looking up', 'Looked up'] },
    search_credentials: {
        doing: 'Looking for accounts',
        done: 'Looked for accounts',
        failed: 'Couldn’t look for accounts',
        lead: ['Looking for accounts like', 'Looked for accounts like'],
        quote: true,
    },
    read: { doing: 'Reading the docs', done: 'Read the docs', failed: 'Couldn’t read the docs', lead: ['Reading the docs on', 'Read the docs on'], words: true },
    bash: { doing: 'Running a command', done: 'Ran a command', failed: 'Couldn’t run a command' },
    list_workflows: {
        doing: 'Searching automations',
        done: 'Searched automations',
        failed: 'Couldn’t search automations',
        lead: ['Searching automations for', 'Searched automations for'],
        quote: true,
    },
    open_workflow: { doing: 'Opening an automation', done: 'Opened an automation', failed: 'Couldn’t open an automation' },
    create_workflow: { doing: 'Creating an automation', done: 'Created an automation', failed: 'Couldn’t create an automation' },
    list_folders: { doing: 'Looking at folders', done: 'Looked at folders', failed: 'Couldn’t look at folders' },
    create_folder: { doing: 'Creating a folder', done: 'Created a folder', failed: 'Couldn’t create a folder' },
    delete_folder: { doing: 'Deleting a folder', done: 'Deleted a folder', failed: 'Couldn’t delete a folder' },
    move_workflow: { doing: 'Moving an automation', done: 'Moved an automation', failed: 'Couldn’t move an automation' },
    read_config: { doing: 'Reading settings', done: 'Read settings', failed: 'Couldn’t read settings' },
    get_output: { doing: 'Reading output', done: 'Read output', failed: 'Couldn’t read output' },
    list_outputs: { doing: 'Reading past output', done: 'Read past output', failed: 'Couldn’t read past output' },
    run_node: { doing: 'Running step', done: 'Ran step', failed: 'Couldn’t run step' },
    define_variable: { doing: 'Adding a variable', done: 'Added a variable', failed: 'Couldn’t add a variable', words: true },
    add_test_run: { doing: 'Writing a test run', done: 'Wrote a test run', failed: 'Couldn’t write a test run', words: true },
    run_test: { doing: 'Starting a test run', done: 'Started a test run', failed: 'Couldn’t start a test run', words: true },
};

const appOf = (nodeType?: string) => (nodeType ? getNodeIconMeta(nodeType)?.label || undefined : undefined);

/** What a step acts on, as a person reads it: its label, else its app; an edge by both its ends. */
function targetOf(step: BuilderStep): string | undefined {
    if (step.target) return step.target;
    if (step.ends) {
        const ends = step.ends.map((end) => end.label || appOf(end.node_type));
        return ends.length === 2 && ends.every(Boolean) ? ends.join(' → ') : undefined;
    }
    return appOf(step.node_type);
}

/** A step in two parts, so the target gives way first in a narrow column. */
export function stepWords(step: BuilderStep, phase: Phase): { head: string; tail?: string } {
    const verb = fieldWords(step.op);
    const said = SAID[step.op] ?? { doing: `Running ${verb}`, done: `Ran ${verb}`, failed: `Couldn’t run ${verb}` };
    const named = targetOf(step);
    const target = named && said.words ? fieldWords(named) : named;
    const field = step.field ? fieldTitle(step.node_type, step.field) : 'a field';
    const head = said[phase].replace('{field}', field);
    if (!target) return { head };
    if (said.lead && phase !== 'failed') return { head: said.lead[phase === 'doing' ? 0 : 1], tail: said.quote ? ` “${target}”` : ` ${target}` };
    return { head, tail: ` · ${target}` };
}

const isWelcome = (m: Message) => !m.isUser && m.text === BUILDER_WELCOME && !m.editSegments?.length && !m.content?.length;

/** A chat with nothing in it but the greeting. */
export function isUnstartedChat(messages: Message[]): boolean {
    return messages.every(isWelcome);
}

export interface BuilderTurn {
    /** What was asked; a reply added to the chat on its own (a note) has none. */
    request?: Message;
    replies: Message[];
}

/** The chat as changes: each request and the replies under it. */
export function builderTurns(messages: Message[]): BuilderTurn[] {
    const turns: BuilderTurn[] = [];
    for (const message of messages) {
        if (isWelcome(message)) continue;
        if (message.isUser) turns.push({ request: message, replies: [] });
        else if (turns.length) turns[turns.length - 1].replies.push(message);
        else turns.push({ replies: [message] });
    }
    return turns;
}
