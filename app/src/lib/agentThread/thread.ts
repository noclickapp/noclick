// An agent's conversation, as every page that draws one reads it (Work's conversations, the Chat page's), t3code's CLI
// chat: a person's messages, then each turn's work (its commands with their output and exit code, edits with their
// diffs, reads and searches, NoClick's own tools) and its reply. Built from the conversation's history (agent.history:
// each reply keeps its turn's steps) and kept current by its live events (agent.watch): a turn's steps arrive as
// tool_call, output, diff and tool_result under one call id, its words as text, its whole messages as message, and its
// end as turn_end. Pure: the hook feeds it and the rows draw it.
//
// What the Chat page's conversation adds, read here for every page: a message's words keep apart the line naming what
// it points at (its chips); a note can set up an automation (its setup card) or pass on a space's news, and one added
// while a turn is at work goes before that turn, where the conversation keeps it; a turn NoClick turned down because
// the account ran out carries what its card draws.
import { needOf, type AgentNeed } from '@/lib/agentNeeds';
import { outOfFundsOf, readMessage, turnEndText, type ChatReference } from './messages';
import type {
    AgentEvent, AgentStep, AgentStepDiff, AgentStepKind, Attachment, DiffStat, HarnessRequest, JsonObject, Message, MessageChannel, MessageSubagent, MessageTrigger, MessageVia, StepCategory, StepGroup, StepLabel, StepProgress, StepTests,
    TurnSummary,
} from 'noclick';

/** An automation a note sets up (one picked on a public page): a hosted link the owner's own agent calls (`mcp`), or
 *  an agent step NoClick runs (`agent`, as an agents page set one up before its agents were platform agents), and the
 *  agent the owner came for. */
export interface WorkflowSetupRef {
    kind: 'mcp' | 'agent';
    workflow_id: string;
    client?: string | null;
}

/** An agent picked on an agents page, already made with its channel (`channel_id`), the apps it works in and what it
 *  waited on when it was made (`needs`), and the harness the page was for (`client`). */
export interface AgentForAppsSetupRef {
    kind: 'agent_for_apps';
    agent_id: string;
    channel_id: string;
    needs: AgentNeed[];
    client?: string | null;
}

/** What a note sets up: an automation, or an agent picked on an agents page. */
export type SetupRef = WorkflowSetupRef | AgentForAppsSetupRef;

/** What a setup is about, for the newest card about it to draw in full: its automation, or its agent. */
export const setupSubject = (setup: SetupRef): string => (setup.kind === 'agent_for_apps' ? `agent:${setup.agent_id}` : setup.workflow_id);

/** One step of a turn as the activity log draws it: what it did, and what it printed or changed. */
export interface Step {
    id: string;
    kind: AgentStepKind;
    tool: string;
    /** `harness` for the harness's own shell, edits and reads; NoClick's own tools have none. */
    source: string | null;
    command: string | null;
    path: string | null;
    query: string | null;
    arguments: JsonObject;
    /** What its command printed, newest last. */
    output: string;
    exitCode: number | null;
    durationMs: number | null;
    isError: boolean;
    result: unknown;
    diffs: AgentStepDiff[];
    /** Still running (only while its turn is, but for a subagent: it can outlive its turn's reply). */
    running: boolean;
    at: number;
    /** A subagent's step: the id of the call (its `Agent` or `Task`) it works for. */
    parent: string | null;
    /** A subagent call's own steps, in the order it took them. */
    children: Step[];
    /** A subagent call's latest words, the moment they came in (a new one starts its next message), and when. */
    said: string;
    saidId: string | null;
    saidAt: number | null;
    /** What a harness's step did, as the platform judged it (none on NoClick's own calls or older history): what kind
     *  of step, its words in its tense, the command as shown, the lines it printed, a test run's counts, a count it
     *  reported, an edit's lines and whether it failed. */
    category: StepCategory | null;
    label: StepLabel | null;
    displayCommand: string | null;
    outputLines: number | null;
    tests: StepTests | null;
    progress: StepProgress | null;
    diffStat: DiffStat | null;
    failed: boolean | null;
}

/** A turn's work and words, in the order they came: a run of steps, what it said between them, a message that joined
 *  it while it worked (steer). */
export type Part = { kind: 'steps'; steps: Step[] } | { kind: 'text'; text: string } | { kind: 'user'; entry: UserEntry };

/** Who wrote a person's message, when it isn't you. */
export interface Author {
    type: string;
    id: string | null;
    name: string;
}

export interface UserEntry {
    kind: 'user';
    key: string;
    /** A message's stable id in its thread (revert and fork from it), once the conversation has it. */
    id: string | null;
    text: string;
    at: number;
    files: Attachment[];
    operationId: string | null;
    /** Someone it was handed off to (`person`), or a teammate who wrote it. */
    author: Author | null;
    via: MessageVia | null;
    trigger: MessageTrigger | null;
    /** The chat it came from, where that isn't the session's own (a WhatsApp chat, `channel:<id>`, `owner`, a shared
     *  page's visitor): where its reply went. */
    chat: string | null;
    command: { name: string; arguments?: string } | null;
    /** Written for one of its harness's subagents, which the main session passes it on to. */
    subagent: MessageSubagent | null;
    /** A channel's turn: the posts it delivered, as the channel has them; `text` is what the agent read. */
    channel: MessageChannel | null;
    /** Sent into the turn under way. */
    steer: boolean;
    /** Sent from this page; the conversation hasn't shown it back yet. */
    pending: boolean;
    /** What it points at (an automation, an account), named in the line its words were sent with. */
    references: ChatReference[];
}

export type TurnStatus = 'running' | 'done' | 'failed' | 'stopped';

/** Why a turn failed when its model connection's provider turned it down: a key it refused (`provider_rejected`) or a
 *  sign-in that ended (`signed_out`), both `credential_disconnected`, an account out of credit
 *  (`provider_out_of_funds`, `payment_required`), or a plan at its usage limit (`plan_limit`, `plan_limit_reached`,
 *  which the line its switch or its wait left says); on which connection, in NoClick's words. */
export interface Failure {
    reason: 'provider_rejected' | 'signed_out' | 'provider_out_of_funds' | 'plan_limit';
    /** The ref the agent names it by (`credential:<id>`, or a connection's name). */
    connection: string | null;
    connectionName: string | null;
    /** The model provider whose account to connect again (`openrouter`, `openai`). */
    integration: string | null;
    provider: string | null;
    message: string;
    /** The provider's own words ("User not found."), when it gave any. */
    providerSaid: string | null;
    nextStep: string | null;
    /** Where its funds are added, for an account out of credit (the provider's billing page). */
    billingUrl: string | null;
}

// Each reason a person can act on, by the error type that carries it.
const FAILURE_TYPES: Record<Failure['reason'], string> = { provider_rejected: 'credential_disconnected', signed_out: 'credential_disconnected', provider_out_of_funds: 'payment_required', plan_limit: 'plan_limit_reached' };

/** Text up to where a reply's older failures went on with the provider's raw answer ("Provider message: …",
 *  "Details: …"), which a person never reads. */
const ownWords = (text: string | null): string | null => text?.split(/\s*(?:Provider message:|Details:)/)[0].trim() || null;

/** A failed reply's `failure` (history), or its operation's error as `{type, message, next_step, ...details}`; null
 *  for any other failure. */
export function failureOf(raw: unknown): Failure | null {
    if (!raw || typeof raw !== 'object') return null;
    const f = raw as JsonObject;
    const reason = typeof f.reason === 'string' && f.reason in FAILURE_TYPES ? (f.reason as Failure['reason']) : null;
    if (!reason || f.type !== FAILURE_TYPES[reason]) return null;
    const s = (v: unknown) => (typeof v === 'string' && v ? v : null);
    return {
        reason,
        connection: s(f.connection),
        connectionName: s(f.connection_name),
        integration: s(f.integration),
        provider: s(f.provider),
        message: ownWords(s(f.message)) ?? '',
        providerSaid: ownWords(s(f.provider_said)),
        nextStep: s(f.next_step),
        billingUrl: s(f.billing_url),
    };
}

/** A machine turn waiting on its harness's image: NoClick's line for it, and how far it's come. */
export interface Download {
    text: string;
    bytes: number | null;
    total: number | null;
}

export interface TurnEntry {
    kind: 'turn';
    key: string;
    operationId: string | null;
    /** The reply's stable id, once the conversation has it. */
    id: string | null;
    parts: Part[];
    /** The whole reply, once it's in. */
    reply: string | null;
    files: Attachment[];
    reasoning: string[];
    status: TurnStatus;
    startedAt: number;
    endedAt: number | null;
    /** The conversation's older history being summarized before the model goes on. */
    compacting: number | null;
    /** Its machine downloading the harness before the turn can start. */
    downloading: Download | null;
    /** Why it failed, where its model connection was refused. */
    failure: Failure | null;
    /** What its stream announced of an approval it held or a long action it started (`kind` `approval` or
     *  `operation`), newest word on each, for their cards where no call's answer names them. */
    announced: JsonObject[];
    /** NoClick turned it down because the account ran out: what its card draws (Add funds, the invite link). */
    outOfFunds: JsonObject | null;
    /** Its harness's reads and searches folded, as the platform folds them (a `group` moment says each change). */
    groups: StepGroup[];
    /** What its harness did, once it ended. */
    summary: TurnSummary | null;
    /** How far it's come as it runs (`paceOf`), for its working line. */
    pace?: TurnPace;
}

/** A running turn's pace, as Claude Code's CLI shows it ("14s · ↑ 12k ↓ 988 tokens · thought for 10s"), from its
 *  `progress` moments (the one shape every harness's turn tells it in): the tokens it has written so far (`estimated`
 *  where its harness reports none yet), what its model calls read (`inputTokens`, once its harness reports them), and
 *  how long it thought, its thinking under way since `thinkingSince`. */
export interface TurnPace {
    tokens: number | null;
    estimated: boolean;
    thinkingMs: number;
    thinkingSince: number | null;
    inputTokens?: number | null;
}

const NO_PACE: TurnPace = { tokens: null, estimated: false, thinkingMs: 0, thinkingSince: null, inputTokens: null };

/** A running turn's pace (none heard: nothing yet). */
export const paceOf = (turn: TurnEntry): TurnPace => turn.pace ?? NO_PACE;

/** Tokens written so far, as its progress last said. */
export const tokensSoFar = (pace: TurnPace): number => pace.tokens ?? 0;

/** How long it thought, by `now` (its thinking under way counts up to then). */
export function thoughtMs(pace: TurnPace, now: number): number {
    return pace.thinkingMs + (pace.thinkingSince === null ? 0 : Math.max(0, now - pace.thinkingSince));
}

/** Its thinking ended at `at`. */
function doneThinking(pace: TurnPace, at: number): TurnPace {
    return pace.thinkingSince === null ? pace : { ...pace, thinkingMs: thoughtMs(pace, at), thinkingSince: null };
}

/** One `progress` moment, said at `at`: its thinking starting or ending, its tokens so far. */
function heardProgress(pace: TurnPace, raw: JsonObject, at: number): TurnPace {
    let next = pace;
    if (raw.thinking === true && next.thinkingSince === null) next = { ...next, thinkingSince: at };
    if (raw.thinking === false) next = doneThinking(next, at);
    if (typeof raw.output_tokens === 'number') next = { ...next, tokens: raw.output_tokens, estimated: raw.estimated === true };
    const usage = raw.usage && typeof raw.usage === 'object' ? (raw.usage as JsonObject) : null;
    if (typeof usage?.input_tokens === 'number' && usage.input_tokens > 0) next = { ...next, inputTokens: usage.input_tokens };
    return next;
}

function paced(turn: TurnEntry, change: (pace: TurnPace) => TurnPace): TurnEntry {
    return { ...turn, pace: change(paceOf(turn)) };
}

export interface NoteEntry {
    kind: 'note';
    key: string;
    text: string;
    at: number;
    /** A note setting up an automation (one picked on a public page): its setup card draws under it. */
    setup: SetupRef | null;
    /** News another NoClick passed on from its space: the space, and the name its NoClick goes by there. */
    space: { id: string; label: string } | null;
    /** A note saying the agent was renamed here (/rename): its new name, drawn as a line of its own. */
    renamedTo?: string;
    /** A note saying the session picks up here, cleared or resumed, and by whom: drawn as a divider. */
    session?: { how: 'cleared' | 'resumed'; by: Author | null };
    /** A note saying app testing went on or off (or the owner allowed it, or said not now): drawn as one quiet line. */
    appTesting?: AppTestingNote;
    /** A note saying the agent moved to another model connection, waits for a plan's reset, or is back on the one it
     *  left: drawn as one quiet line. */
    modelSwitch?: ModelSwitchNote;
    /** A note saying a run of one of the account's workflows waits at its Approval step: its card (Approve, Decline)
     *  draws under it. */
    workflowApproval?: WorkflowApprovalNote;
}

/** The Approval step a note is about: read and answered on /v1 by its card. */
export interface WorkflowApprovalNote {
    id: string;
    workflowId: string;
    workflowName: string;
    title: string | null;
}

function workflowApprovalOf(data: JsonObject | null): WorkflowApprovalNote | undefined {
    const note = data?.workflow_approval as Partial<Record<string, unknown>> | undefined;
    if (!note || typeof note.id !== 'string' || typeof note.workflow_id !== 'string') return undefined;
    return {
        id: note.id,
        workflowId: note.workflow_id,
        workflowName: typeof note.workflow_name === 'string' ? note.workflow_name : 'Your workflow',
        title: typeof note.title === 'string' ? note.title : null,
    };
}

/** What an app testing note says: its state, its line in two parts (the lead in bold, then what it costs), and what the
 *  agent turned it on for. */
export interface AppTestingNote {
    state: 'on' | 'off' | 'allowed' | 'declined';
    lead: string;
    detail: string;
    reason: string | null;
}

const APP_TESTING_STATES: readonly AppTestingNote['state'][] = ['on', 'off', 'allowed', 'declined'];

function appTestingOf(data: JsonObject | null): AppTestingNote | undefined {
    const note = data?.app_testing as Partial<AppTestingNote> | undefined;
    if (!note || !APP_TESTING_STATES.includes(note.state as AppTestingNote['state']) || typeof note.lead !== 'string') return undefined;
    return { state: note.state as AppTestingNote['state'], lead: note.lead, detail: typeof note.detail === 'string' ? note.detail : '', reason: typeof note.reason === 'string' ? note.reason : null };
}

/** Where the owner allowed a switch to a paid key: their words in one of the account's channels or this conversation
 *  (a grant `cited`), or their tap on NoClick's ask. */
export interface SwitchEvidence {
    where: 'channel' | 'conversation' | 'ask' | 'api';
    channelId: string | null;
    channelName: string | null;
    messageId: string | null;
    at: Date | null;
}

/** What a model switch's note says: NoClick's line for it (`lead`, `detail`, in the
 *  agent's clock), and what it's made of, so it reads in the reader's: `switched` from one connection to another
 *  (harness and model on each, who moved it, the owner's say-so for a paid key, and when the plan it left is back);
 *  `waiting` for a plan's reset (`connection`, `resetsAt`, whether the agent picks the work up then); `back_on` the
 *  connection it left. */
export interface ModelSwitchNote {
    state: 'switched' | 'waiting' | 'back_on';
    lead: string;
    detail: string | null;
    from: string | null;
    to: string | null;
    toName: string | null;
    harnessFrom: string | null;
    harnessTo: string | null;
    modelFrom: string | null;
    modelTo: string | null;
    /** Why: `limit` (its plan ran out), `allowed` (the owner's tap), else the words of whoever moved it. */
    reason: string | null;
    by: 'noclick' | 'owner' | 'agent' | null;
    grant: { source: 'cited' | 'asked' | 'owner'; scope: 'once' | 'standing'; evidence: SwitchEvidence | null } | null;
    connection: string | null;
    resetsAt: Date | null;
    picksUp: boolean;
}

const MODEL_SWITCH_STATES: readonly ModelSwitchNote['state'][] = ['switched', 'waiting', 'back_on'];

function modelSwitchOf(data: JsonObject | null): ModelSwitchNote | undefined {
    const note = data?.switch_model as JsonObject | undefined;
    if (!note || !MODEL_SWITCH_STATES.includes(note.state as ModelSwitchNote['state']) || typeof note.lead !== 'string') return undefined;
    const s = (v: unknown) => (typeof v === 'string' && v ? v : null);
    const time = (v: unknown) => (s(v) && !Number.isNaN(Date.parse(v as string)) ? new Date(v as string) : null);
    const one = <T extends string>(v: unknown, of: readonly T[]): T | null => (of.includes(v as T) ? (v as T) : null);
    const by = note.by && typeof note.by === 'object' ? one((note.by as JsonObject).type, ['noclick', 'owner', 'agent'] as const) : null;
    const g = note.grant && typeof note.grant === 'object' ? (note.grant as JsonObject) : null;
    const e = g?.evidence && typeof g.evidence === 'object' ? (g.evidence as JsonObject) : null;
    const where = one(e?.where, ['channel', 'conversation', 'ask', 'api'] as const);
    const source = one(g?.source, ['cited', 'asked', 'owner'] as const);
    return {
        state: note.state as ModelSwitchNote['state'],
        lead: note.lead,
        detail: s(note.detail),
        from: s(note.from),
        to: s(note.to),
        toName: s(note.to_name),
        harnessFrom: s(note.harness_from),
        harnessTo: s(note.harness_to),
        modelFrom: s(note.model_from),
        modelTo: s(note.model_to),
        reason: s(note.reason),
        by,
        grant: source ? { source, scope: g?.scope === 'standing' ? 'standing' : 'once', evidence: e && where ? { where, channelId: s(e.channel_id), channelName: s(e.channel_name), messageId: s(e.message_id), at: time(e.at) } : null } : null,
        connection: s(note.connection),
        resetsAt: time(note.resets_at) ?? time(note.until),
        picksUp: note.picks_up === true,
    };
}

/** A point between turns: the conversation compacted, its sandbox lost moments. */
export interface MarkerEntry {
    kind: 'marker';
    key: string;
    marker: 'compacted' | 'dropped';
    text: string;
    at: number;
}

export type Entry = UserEntry | TurnEntry | NoteEntry | MarkerEntry;

export interface Thread {
    entries: Entry[];
    /** What its coding harness asks a person, by id: approvals and questions, pending until answered. */
    requests: Record<string, HarnessRequest>;
}

export const EMPTY_THREAD: Thread = { entries: [], requests: {} };

const time = (d: Date | null | undefined, fallback: number) => (d ? d.getTime() : fallback);

export function stepOf(s: AgentStep, index: number, turnKey: string, fallbackAt: number): Step {
    return {
        id: s.callId ?? `${turnKey}:${index}`,
        kind: s.kind,
        tool: s.tool,
        source: s.source,
        command: s.command,
        path: s.path,
        query: s.query,
        arguments: s.arguments,
        output: s.output ?? '',
        exitCode: s.exitCode,
        durationMs: s.durationMs,
        isError: s.isError,
        result: s.result,
        diffs: s.diffs,
        running: false,
        at: time(s.createdAt, fallbackAt),
        parent: typeof s.raw?.parent === 'string' ? s.raw.parent : null,
        children: [],
        said: '',
        saidId: null,
        saidAt: null,
        category: s.category,
        label: s.label,
        displayCommand: s.displayCommand,
        outputLines: s.outputLines,
        tests: s.tests,
        progress: s.progress,
        diffStat: s.diffStat,
        failed: s.failed,
    };
}

/** A harness's subagent call: Claude Code's `Agent` (`Task` before), OpenCode's `Task`; or any call steps work for. */
export const isSubagentCall = (s: Step): boolean => s.children.length > 0 || (s.source === 'harness' && /^(agent|task)$/i.test(s.tool));

/** Kept steps, a subagent's under the call it worked for (as history and a reply keep them flat, each naming its
 *  `parent`); one whose call isn't kept stays where it is. */
export function nested(steps: readonly Step[]): Step[] {
    const ids = new Set(steps.map((s) => s.id));
    const under = new Map<string, Step[]>();
    for (const s of steps) if (s.parent && s.parent !== s.id && ids.has(s.parent)) under.set(s.parent, [...(under.get(s.parent) ?? []), s]);
    const withChildren = (s: Step): Step => (under.has(s.id) ? { ...s, children: [...s.children, ...under.get(s.id)!.map(withChildren)] } : s);
    return steps.filter((s) => !(s.parent && s.parent !== s.id && ids.has(s.parent))).map(withChildren);
}

/** Every step, a subagent's too. */
export const flatSteps = (steps: readonly Step[]): Step[] => steps.flatMap((s) => [s, ...flatSteps(s.children)]);

function authorOf(author: Message['author']): Author | null {
    if (!author) return null;
    const fallback = author.type === 'agent' ? 'Another agent' : author.type === 'account' ? 'The account’s owner' : 'A teammate';
    return { type: author.type, id: author.id, name: author.name || fallback };
}

function userEntry(m: Message, at: number, key: string): UserEntry {
    const person = m.role === 'person';
    const read = readMessage(m.text);
    return {
        kind: 'user',
        key,
        id: m.id,
        text: read.text,
        references: read.references,
        at,
        files: m.files,
        operationId: m.operationId,
        author: person ? { type: 'person', id: null, name: String(m.raw.name ?? m.raw.handed_off_to ?? 'Someone') } : authorOf(m.author),
        via: m.via,
        trigger: m.trigger,
        chat: m.chat ?? null,
        command: m.command,
        subagent: m.subagent ?? null,
        channel: m.channel ?? null,
        steer: false,
        pending: false,
    };
}

function settledTurn(m: Message, at: number, startedAt: number, key: string): TurnEntry {
    const steps = nested(m.steps.map((s, i) => stepOf(s, i, key, at)));
    return {
        kind: 'turn',
        key,
        operationId: m.operationId,
        id: m.id,
        parts: steps.length ? [{ kind: 'steps', steps }] : [],
        reply: m.text,
        files: m.files,
        reasoning: m.reasoning.map((r) => r.text),
        status: m.raw.failed === true ? 'failed' : 'done',
        startedAt: Math.min(startedAt, steps[0]?.at ?? startedAt),
        endedAt: at,
        compacting: null,
        downloading: null,
        failure: m.raw.failed === true ? failureOf(m.raw.failure) : null,
        announced: [],
        outOfFunds: outOfFundsOf(m.raw.out_of_funds) ?? null,
        groups: m.groups ?? [],
        summary: m.summary ?? null,
    };
}

function setupOf(data: JsonObject | null): SetupRef | null {
    const setup = data?.setup as Record<string, unknown> | undefined;
    const client = typeof setup?.client === 'string' ? { client: setup.client } : {};
    if (setup?.kind === 'agent_for_apps' && typeof setup.agent_id === 'string' && typeof setup.channel_id === 'string') {
        const needs = (Array.isArray(setup.needs) ? setup.needs : []).flatMap((n) => needOf(n) ?? []);
        return { kind: 'agent_for_apps', agent_id: setup.agent_id, channel_id: setup.channel_id, needs, ...client };
    }
    if (!setup || (setup.kind !== 'mcp' && setup.kind !== 'agent') || typeof setup.workflow_id !== 'string') return null;
    return { kind: setup.kind, workflow_id: setup.workflow_id, ...client };
}

/** The note a message is: one added to the conversation (`note`, maybe setting an automation up), or a space's news
 *  another NoClick passed on (a notification from its space); null for anything else. */
function noteOf(m: { role: string | null; text: string; data: JsonObject | null; notification?: boolean; space?: Message['space'] }, at: number, key: string): NoteEntry | null {
    const space = m.notification && m.space?.label ? { id: m.space.workspaceId, label: m.space.label } : null;
    if (!space && m.role !== 'note') return null;
    const renamedTo = !space && typeof m.data?.renamed_to === 'string' ? m.data.renamed_to : undefined;
    const how = m.data?.session;
    const by = m.data?.by && typeof m.data.by === 'object' ? (m.data.by as unknown as Message['author']) : null;
    const session: NoteEntry['session'] = !space && (how === 'cleared' || how === 'resumed') ? { how, by: authorOf(by) } : undefined;
    const appTesting = space ? undefined : appTestingOf(m.data);
    const modelSwitch = space ? undefined : modelSwitchOf(m.data);
    const workflowApproval = space ? undefined : workflowApprovalOf(m.data);
    return { kind: 'note', key, text: m.text ?? '', at, setup: space ? null : setupOf(m.data), space, ...(renamedTo ? { renamedTo } : {}), ...(session ? { session } : {}), ...(appTesting ? { appTesting } : {}), ...(modelSwitch ? { modelSwitch } : {}), ...(workflowApproval ? { workflowApproval } : {}) };
}

const sameNote = (a: NoteEntry, b: NoteEntry) => a.text === b.text && (a.setup ? setupSubject(a.setup) : null) === (b.setup ? setupSubject(b.setup) : null) && a.setup?.client === b.setup?.client && a.space?.id === b.space?.id;

/** The failed turns whose failure a line beside them already says (a model switch's: it moved on, or waits for the
 *  reset), by key: one between the message the turn answers and the next, on either side of the turn (a line written
 *  as it fails can land before its reply). */
export function failuresTold(entries: readonly Entry[]): Set<string> {
    const told = new Set<string>();
    let failed: string[] = [];
    let said = false;
    const close = () => {
        if (said) failed.forEach((key) => told.add(key));
        failed = [];
        said = false;
    };
    for (const e of entries) {
        if (e.kind === 'user') close();
        else if (e.kind === 'turn' && e.failure) failed.push(e.key);
        else if (e.kind === 'note' && e.modelSwitch && e.modelSwitch.state !== 'back_on') said = true;
    }
    close();
    return told;
}

/** The conversation's history as entries: each reply a settled turn, timed from the message it answers. */
export function fromHistory(messages: readonly Message[], now = Date.now()): Entry[] {
    const entries: Entry[] = [];
    let lastAsk = now;
    messages.forEach((m, i) => {
        const at = time(m.createdAt, now);
        const key = m.id ?? `h${i}`;
        const note = noteOf(m, at, key);
        if (note) {
            entries.push(note);
        } else if (m.role === 'user' || m.role === 'person') {
            lastAsk = at;
            entries.push(userEntry(m, at, key));
        } else if (m.role === 'assistant') {
            entries.push(settledTurn(m, at, lastAsk, key));
        }
    });
    return entries;
}

/** The turn a person's last message started and nothing has answered yet: still running, or it ended without a
 *  reply (stopped), which only its operation can say. */
export function unanswered(entries: readonly Entry[]): UserEntry | null {
    const last = entries[entries.length - 1];
    return last?.kind === 'user' && last.operationId ? last : null;
}

/** A running turn for `operationId`, from `at`. */
export function runningTurn(operationId: string | null, at: number): TurnEntry {
    return {
        kind: 'turn',
        key: `live:${operationId ?? at}`,
        operationId,
        id: null,
        parts: [],
        reply: null,
        files: [],
        reasoning: [],
        status: 'running',
        startedAt: at,
        endedAt: null,
        compacting: null,
        downloading: null,
        failure: null,
        announced: [],
        outOfFunds: null,
        groups: [],
        summary: null,
    };
}

export const isTurn = (e: Entry): e is TurnEntry => e.kind === 'turn';

/** The turn under way, if any. */
export function liveTurn(thread: Thread): TurnEntry | null {
    for (let i = thread.entries.length - 1; i >= 0; i--) {
        const e = thread.entries[i];
        if (e.kind === 'turn' && e.status === 'running') return e;
    }
    return null;
}

function replace(thread: Thread, entry: Entry): Thread {
    return { ...thread, entries: thread.entries.map((e) => (e.key === entry.key ? entry : e)) };
}

/** A turn's own steps, in order (a subagent's are under its call). */
export function stepsOf(turn: TurnEntry): Step[] {
    return turn.parts.flatMap((p) => (p.kind === 'steps' ? p.steps : []));
}

/** Every step of a turn, a subagent's too. */
export const allStepsOf = (turn: TurnEntry): Step[] => flatSteps(stepsOf(turn));

const changed = (steps: Step[], id: string, change: (s: Step) => Step): Step[] => steps.map((s) => (s.id === id ? change(s) : s.children.length ? { ...s, children: changed(s.children, id, change) } : s));

function withStep(turn: TurnEntry, id: string, change: (s: Step) => Step): TurnEntry {
    return {
        ...turn,
        parts: turn.parts.map((p) => (p.kind === 'steps' && flatSteps(p.steps).some((s) => s.id === id) ? { ...p, steps: changed(p.steps, id, change) } : p)),
    };
}

function addStep(turn: TurnEntry, step: Step): TurnEntry {
    // A subagent's step goes under its call.
    if (step.parent && allStepsOf(turn).some((s) => s.id === step.parent)) return withStep(turn, step.parent, (s) => ({ ...s, children: [...s.children, step] }));
    const last = turn.parts[turn.parts.length - 1];
    if (last?.kind === 'steps') return { ...turn, parts: [...turn.parts.slice(0, -1), { kind: 'steps', steps: [...last.steps, step] }] };
    return { ...turn, parts: [...turn.parts, { kind: 'steps', steps: [step] }] };
}

function addText(turn: TurnEntry, text: string): TurnEntry {
    const last = turn.parts[turn.parts.length - 1];
    if (last?.kind === 'text') return { ...turn, parts: [...turn.parts.slice(0, -1), { kind: 'text', text: last.text + text }] };
    return { ...turn, parts: [...turn.parts, { kind: 'text', text }] };
}

/** The running turn an event belongs to: the one under its operation, else the one under way (a turn this page
 *  joined before its operation was known), else a new one. */
function turnFor(thread: Thread, operationId: string | null, at: number): { thread: Thread; turn: TurnEntry } {
    const known = operationId ? thread.entries.find((e): e is TurnEntry => e.kind === 'turn' && e.operationId === operationId) : undefined;
    if (known) return { thread, turn: known };
    const live = liveTurn(thread);
    if (live && (!live.operationId || !operationId)) {
        const adopted = { ...live, operationId: live.operationId ?? operationId };
        return { thread: replace(thread, adopted), turn: adopted };
    }
    const turn = runningTurn(operationId, at);
    return { thread: { ...thread, entries: [...thread.entries, turn] }, turn };
}

/** The step a call id names, else the newest still-running step of the same tool (NoClick's own tools name no call). */
function stepFor(turn: TurnEntry, callId: string | null, tool: string | null): Step | undefined {
    const steps = allStepsOf(turn);
    if (callId) return steps.find((s) => s.id === callId);
    return [...steps].reverse().find((s) => s.running && (!tool || s.tool === tool));
}

/** A person's message the conversation showed: its own row, or the one this page sent, now known. */
function withUserMessage(thread: Thread, event: AgentEvent, at: number): Thread {
    const raw = event.raw;
    const entries = thread.entries;
    const id = event.messageId;
    if (id && entries.some((e) => e.kind === 'user' && e.id === id)) return thread;
    // A message this page sent comes back with its turn's operation, or with the words it was sent with.
    const words = readMessage(event.text ?? '').text;
    const isMine = (e: UserEntry) => e.pending && ((!!event.operationId && e.operationId === event.operationId) || e.text.trim() === words.trim());
    const mine = entries.find((e): e is UserEntry => e.kind === 'user' && isMine(e));
    if (mine) return replace(thread, { ...mine, id, pending: false, operationId: event.operationId ?? mine.operationId });
    const steering = liveTurn(thread);
    const steered = steering?.parts.find((p): p is Extract<Part, { kind: 'user' }> => p.kind === 'user' && isMine(p.entry));
    if (steering && steered) {
        const shown = { ...steered.entry, id, pending: false };
        return replace(thread, { ...steering, parts: steering.parts.map((p) => (p === steered ? { kind: 'user', entry: shown } : p)) });
    }
    // Replayed moments repeat what the history already holds.
    if (event.operationId && entries.some((e) => e.kind === 'user' && e.operationId === event.operationId && e.text === words)) return thread;
    const message: Message = {
        id,
        author: event.author,
        role: event.role ?? 'user',
        text: event.text ?? '',
        createdAt: new Date(at),
        files: event.files,
        toolCalls: [],
        steps: [],
        operationId: event.operationId,
        reasoning: [],
        via: event.via,
        data: event.data,
        trigger: event.trigger,
        command: raw.command && typeof raw.command === 'object' ? { name: String((raw.command as JsonObject).name), arguments: String((raw.command as JsonObject).arguments ?? '') } : null,
        subagent: event.subagent ?? null,
        channel: event.channel ?? null,
        chat: event.chat ?? null,
        raw,
    };
    const entry = userEntry(message, at, id ?? `live:user:${event.operationId ?? at}:${entries.length}`);
    // A channel's posts start their turn as they're shown (their message is kept as it starts): its card says what it's
    // doing from the first moment, and a turn that ends having drawn nothing is gone again, as history reads it.
    const begins = entry.channel && event.operationId && !entries.some((e) => e.kind === 'turn' && e.operationId === event.operationId) ? [runningTurn(event.operationId, at)] : [];
    // A message that joined the turn under way sits in it, where the turn's later work follows it; the turn's own,
    // read after the turn said it's at work (a page watching hears that first), goes before it.
    const live = liveTurn(thread);
    if (live && event.operationId && live.operationId === event.operationId && !live.parts.length && live.reply === null) {
        const turnAt = entries.indexOf(live);
        return { ...thread, entries: [...entries.slice(0, turnAt), entry, ...entries.slice(turnAt)] };
    }
    if (live && event.operationId && live.operationId !== event.operationId && live.operationId) return { ...thread, entries: [...entries, entry, ...begins] };
    if (live && (!event.operationId || live.operationId === event.operationId)) {
        return replace(thread, { ...live, parts: [...live.parts, { kind: 'user', entry: { ...entry, steer: true } }] });
    }
    return { ...thread, entries: [...entries, entry, ...begins] };
}

/** A reply the conversation showed: its turn settles with it. Steps the live events gathered stay when the reply's
 *  own haven't been kept yet (its message can land before the turn's steps are folded in). */
function withReply(thread: Thread, event: AgentEvent, at: number): Thread {
    const id = event.messageId;
    if (id && thread.entries.some((e) => e.kind === 'turn' && e.id === id)) return thread;
    // A turn its operation already ended (its wait can answer before the stream does) takes the message still: its id.
    if (event.operationId && thread.entries.some((e) => e.kind === 'turn' && e.operationId === event.operationId && e.status !== 'running' && e.id)) return thread;
    const { thread: next, turn } = turnFor(thread, event.operationId, at);
    const failed = event.raw.failed === true;
    const status: TurnStatus = failed ? 'failed' : turn.status === 'stopped' ? 'stopped' : 'done';
    const live = stepsOf(turn);
    // Its kept steps, but a subagent still at work as the live stream has it (its call hasn't ended).
    const steps = event.toolCalls.length
        ? nested(event.toolCalls.map((c, i) => stepOf(toStep(c), i, turn.key, at))).map((k) => {
              const l = live.find((s) => s.id === k.id);
              return l?.running && isSubagentCall(l) && status === 'done' ? { ...l, children: [...l.children, ...k.children.filter((c) => !l.children.some((x) => x.id === c.id))] } : k;
          })
        : settledSteps(live, status);
    const settled: TurnEntry = {
        ...turn,
        id,
        parts: steps.length ? [{ kind: 'steps', steps }, ...turn.parts.filter((p): p is Extract<Part, { kind: 'user' }> => p.kind === 'user')] : turn.parts.filter((p) => p.kind === 'user'),
        reply: event.text ?? '',
        // Its message names the files it made; one that names none keeps those the stream said it made.
        files: event.files.length ? event.files : turn.files,
        reasoning: event.reasoning.length ? event.reasoning.map((r) => r.text) : turn.reasoning,
        status,
        endedAt: turn.endedAt ?? at,
        compacting: null,
        downloading: null,
        failure: failed ? (failureOf(event.raw.failure) ?? turn.failure) : null,
        outOfFunds: outOfFundsOf(event.raw.out_of_funds) ?? turn.outOfFunds,
    };
    return replace(next, settled);
}

/** A saved call (`{tool, arguments, result, …}` or a harness step) as an AgentStep, as the SDK reads one. */
function toStep(raw: JsonObject): AgentStep {
    const kinds: AgentStepKind[] = ['command', 'edit', 'read', 'search', 'tool'];
    const kind = typeof raw.kind === 'string' && (kinds as string[]).includes(raw.kind) ? (raw.kind as AgentStepKind) : 'tool';
    const s = (v: unknown) => (typeof v === 'string' ? v : null);
    const n = (v: unknown) => (typeof v === 'number' ? v : null);
    return {
        kind,
        tool: s(raw.tool) ?? '',
        callId: s(raw.id),
        source: s(raw.source),
        arguments: raw.arguments && typeof raw.arguments === 'object' ? (raw.arguments as JsonObject) : {},
        command: s(raw.command),
        path: s(raw.path),
        query: s(raw.query),
        output: s(raw.output),
        exitCode: n(raw.exit_code),
        durationMs: n(raw.duration_ms),
        isError: raw.is_error === true,
        result: raw.result ?? null,
        diffs: Array.isArray(raw.diffs) ? (raw.diffs as JsonObject[]).map((d) => ({ path: s(d.path) ?? '', change: s(d.kind), diff: s(d.diff) ?? '' })) : [],
        createdAt: typeof raw.created_at === 'string' ? new Date(raw.created_at) : null,
        category: s(raw.category) as StepCategory | null,
        label: raw.label && typeof raw.label === 'object' && s((raw.label as JsonObject).text) ? (raw.label as unknown as StepLabel) : null,
        labelSource: s(raw.label_source) as AgentStep['labelSource'],
        displayCommand: s(raw.display_command),
        lines: raw.lines && typeof raw.lines === 'object' ? { from: n((raw.lines as JsonObject).from), to: n((raw.lines as JsonObject).to) } : null,
        outputLines: n(raw.output_lines),
        tests: raw.tests && typeof raw.tests === 'object' ? (raw.tests as unknown as StepTests) : null,
        progress: raw.progress && typeof raw.progress === 'object' && n((raw.progress as JsonObject).total) ? (raw.progress as unknown as StepProgress) : null,
        diffStat: raw.diff_stat && typeof raw.diff_stat === 'object' ? (raw.diff_stat as unknown as DiffStat) : null,
        failed: typeof raw.failed === 'boolean' ? raw.failed : null,
        group: s(raw.group),
        paths: Array.isArray(raw.paths) ? raw.paths.map(String) : [],
        raw,
    };
}

/** The call a subagent's moment works for. */
const parentOf = (event: AgentEvent): string | null => (typeof event.raw.parent === 'string' && event.raw.parent ? event.raw.parent : null);

/** The turn holding a step, whatever its status. */
const turnHolding = (thread: Thread, id: string): TurnEntry | undefined => thread.entries.find((e): e is TurnEntry => e.kind === 'turn' && allStepsOf(e).some((s) => s.id === id));

/** The turn a step's moment goes to: a subagent's, the turn holding its call, settled or not (a background subagent
 *  outlives its turn's reply, and so does its call, until it ends); the turn's own, the running one (none once its
 *  turn settled). */
function stepTurn(thread: Thread, event: AgentEvent, at: number): { thread: Thread; turn: TurnEntry } | null {
    const parent = parentOf(event);
    const holding = parent ? turnHolding(thread, parent) : undefined;
    if (holding) return { thread, turn: holding };
    if (event.type === 'tool_result' && event.callId) {
        const call = turnHolding(thread, event.callId);
        if (call && allStepsOf(call).some((s) => s.id === event.callId && s.running && isSubagentCall(s))) return { thread, turn: call };
    }
    if (settledOp(thread, event.operationId)) return null;
    return turnFor(thread, event.operationId, at);
}

/** A turn's steps as it settles: none running, but for a subagent still at work once the turn was done. */
function settledSteps(steps: Step[], status: TurnStatus): Step[] {
    return steps.map((s) => (status === 'done' && s.running && isSubagentCall(s) ? s : { ...s, running: false, children: settledSteps(s.children, status) }));
}

const NONE: ReadonlySet<string> = new Set();

/** How a turn ended, by its operation's status as `turn_end` says it. */
const TURN_END_STATUS: Partial<Record<string, TurnStatus>> = { succeeded: 'done', failed: 'failed', canceled: 'stopped', expired: 'stopped' };

/** A turn that ended, however it started and whatever it saved (a wake-up that worked and said nothing saves no reply
 *  to settle it), as its operation's `status` and reply `text` say (the stream's turn_end, or the operation read once
 *  the stream is back): closed with its reply, the failure line, or nothing; one that drew nothing is removed, as
 *  history reads it. One this page follows (`following`) closes here only once it succeeded: its operation's wait
 *  says how it failed or stopped. */
export function closed(thread: Thread, operationId: string, status: string | null, text: string | null | undefined, at: number, following = NONE): Thread {
    const as = TURN_END_STATUS[status ?? ''];
    const turn = thread.entries.find((e): e is TurnEntry => e.kind === 'turn' && e.operationId === operationId);
    if (!as || turn?.status !== 'running') return thread;
    const reply = turnEndText(status, text) || undefined;
    if (following.has(operationId)) return as === 'done' ? ended(thread, operationId, { status: as, reply, at }) : thread;
    const drew = reply || turn.parts.length || turn.files.length || Object.values(thread.requests).some((r) => r.operationId === operationId);
    return drew ? ended(thread, operationId, { status: as, reply, at }) : { ...thread, entries: thread.entries.filter((e) => e !== turn) };
}

/** The thread after one live event. `at` is when it arrived; `following`, the turns this page follows to their end. */
export function applyEvent(thread: Thread, event: AgentEvent, at: number, following = NONE): Thread {
    switch (event.type) {
        case 'message': {
            const note = noteOf({ ...event, text: event.text ?? '' }, at, `live:note:${at}:${thread.entries.length}`);
            if (note) return withNote(thread, note);
            if (event.role === 'assistant') return withReply(thread, event, at);
            return withUserMessage(thread, event, at);
        }
        case 'text': {
            if (!event.text) return thread;
            // A subagent's words stay with it, never the turn's own.
            const parent = parentOf(event);
            if (parent) {
                const turn = turnHolding(thread, parent);
                if (!turn) return thread;
                const id = typeof event.raw.id === 'string' ? event.raw.id : null;
                return replace(thread, withStep(turn, parent, (s) => ({ ...s, said: id && id === s.saidId ? s.said + event.text : event.text!, saidId: id, saidAt: at })));
            }
            if (settledOp(thread, event.operationId)) return thread;
            const { thread: next, turn } = turnFor(thread, event.operationId, at);
            return replace(next, addText(turn, event.text));
        }
        case 'reasoning': {
            if (!event.text || parentOf(event) || settledOp(thread, event.operationId)) return thread;
            const { thread: next, turn } = turnFor(thread, event.operationId, at);
            return replace(next, { ...turn, reasoning: [...turn.reasoning, event.text] });
        }
        case 'file': {
            // A file the person sent comes back on their message; one the turn made goes on the turn, as it's made.
            const file = event.file;
            if (!file || event.role === 'user' || parentOf(event) || settledOp(thread, event.operationId)) return thread;
            const { thread: next, turn } = turnFor(thread, event.operationId, at);
            return turn.files.some((f) => f.url === file.url) ? next : replace(next, { ...turn, files: [...turn.files, file] });
        }
        case 'tool_call': {
            const into = stepTurn(thread, event, at);
            if (!into) return thread;
            const { thread: next, turn } = into;
            if (event.callId && allStepsOf(turn).some((s) => s.id === event.callId)) return next;
            const step: Step = {
                id: event.callId ?? `${turn.key}:${stepsOf(turn).length}`,
                kind: event.stepKind ?? 'tool',
                tool: event.tool ?? '',
                source: event.source,
                command: event.command,
                path: event.path,
                query: event.query,
                arguments: event.arguments ?? {},
                output: '',
                exitCode: null,
                durationMs: null,
                isError: false,
                result: null,
                diffs: [],
                running: true,
                at,
                parent: parentOf(event),
                children: [],
                said: '',
                saidId: null,
                saidAt: null,
                category: event.category ?? null,
                label: event.label ?? null,
                displayCommand: event.displayCommand ?? null,
                outputLines: null,
                tests: null,
                progress: null,
                diffStat: null,
                failed: null,
            };
            return replace(next, addStep(turn, step));
        }
        case 'output': {
            const id = event.callId;
            const into = id ? stepTurn(thread, event, at) : null;
            if (!id || !into) return thread;
            const { thread: next, turn } = into;
            if (!stepFor(turn, id, null)) return next;
            return replace(
                next,
                withStep(turn, id, (s) => ({
                    ...s,
                    output: event.whole ? (event.text ?? '') : s.output + (event.text ?? ''),
                    outputLines: event.outputLines ?? s.outputLines,
                    tests: event.tests ?? s.tests,
                    progress: event.progress ?? s.progress,
                }))
            );
        }
        case 'diff': {
            const id = event.callId;
            const into = id ? stepTurn(thread, event, at) : null;
            if (!id || !into) return thread;
            const { thread: next, turn } = into;
            if (!stepFor(turn, id, null)) return next;
            const diff: AgentStepDiff = { path: event.path ?? '', change: event.change, diff: event.diff ?? '' };
            return replace(next, withStep(turn, id, (s) => ({ ...s, diffs: [...s.diffs.filter((d) => d.path !== diff.path), diff] })));
        }
        case 'tool_result': {
            const into = stepTurn(thread, event, at);
            if (!into) return thread;
            const { thread: next, turn } = into;
            const step = stepFor(turn, event.callId, event.tool);
            if (!step) return next;
            return replace(
                next,
                withStep(turn, step.id, (s) => ({
                    ...s,
                    running: false,
                    output: typeof event.raw.output === 'string' && event.raw.output ? event.raw.output : s.output,
                    exitCode: event.exitCode ?? s.exitCode,
                    durationMs: event.durationMs ?? s.durationMs ?? at - s.at,
                    isError: event.isError,
                    result: event.result,
                    category: event.category ?? s.category,
                    label: event.label ?? s.label,
                    outputLines: event.outputLines ?? s.outputLines,
                    tests: event.tests ?? s.tests,
                    progress: event.progress ?? s.progress,
                    diffStat: event.diffStat ?? s.diffStat,
                    failed: event.failed ?? s.failed,
                }))
            );
        }
        case 'progress': {
            // How far the turn has come, the one shape every harness's turn tells it in.
            if (settledOp(thread, event.operationId)) return thread;
            const { thread: next, turn } = turnFor(thread, event.operationId, at);
            if (turn.status !== 'running') return next;
            const when = typeof event.raw.at === 'number' ? event.raw.at : at;
            return replace(next, paced(turn, (p) => heardProgress(p, event.raw, when)));
        }
        case 'status': {
            if (event.status === 'compacting' || event.status === 'compacted') {
                // Compaction names the turn it's in, which can begin with it.
                const into = event.operationId && !settledOp(thread, event.operationId) ? turnFor(thread, event.operationId, at) : null;
                const base = into?.thread ?? thread;
                const live = into?.turn ?? liveTurn(thread);
                if (event.status === 'compacting' && live) return replace(base, { ...live, compacting: at });
                const settled = live ? replace(base, { ...live, compacting: null }) : base;
                return event.status === 'compacted' ? { ...settled, entries: [...settled.entries, { kind: 'marker', key: `live:compacted:${at}`, marker: 'compacted', text: 'Context compacted', at }] } : settled;
            }
            // A machine's harness image: its line while it downloads, gone once it's in.
            if (event.status === 'downloading' || event.status === 'downloaded') {
                const live = liveTurn(thread);
                if (!live) return thread;
                const n = (v: unknown) => (typeof v === 'number' ? v : null);
                return replace(thread, { ...live, downloading: event.status === 'downloading' && event.text ? { text: event.text, bytes: n(event.raw.downloaded_bytes), total: n(event.raw.total_bytes) } : null });
            }
            if (event.status === 'events_dropped') {
                return { ...thread, entries: [...thread.entries, { kind: 'marker', key: `live:dropped:${at}`, marker: 'dropped', text: `${event.count ?? 'Some'} moments of its work didn’t reach this page`, at }] };
            }
            return thread;
        }
        case 'turn_end': {
            if (!event.operationId) return thread;
            const turn = event.summary && thread.entries.find((e): e is TurnEntry => e.kind === 'turn' && e.operationId === event.operationId);
            const told = turn ? replace(thread, { ...turn, summary: event.summary ?? null }) : thread;
            return closed(told, event.operationId, event.status, event.text, at, following);
        }
        case 'group': {
            // A fold of the turn's reads and searches as it stands now; one no longer standing has no steps.
            const group = event.stepGroup;
            const turn = group && ((event.operationId && thread.entries.find((e): e is TurnEntry => e.kind === 'turn' && e.operationId === event.operationId)) || liveTurn(thread));
            if (!group || !turn) return thread;
            const others = turn.groups.filter((g) => g.id !== group.id);
            return replace(thread, { ...turn, groups: group.stepIds.length ? [...others, group] : others });
        }
        case 'request': {
            if (!event.request) return thread;
            const request = toRequest(event.request);
            return { ...thread, requests: { ...thread.requests, [request.id]: request } };
        }
        case 'approval':
        case 'operation': {
            // Said again (an operation's progress), it's the same card: its newest word.
            const said = event.type === 'approval' ? event.approval : event.operation;
            const turn = event.operationId && thread.entries.find((e): e is TurnEntry => e.kind === 'turn' && e.operationId === event.operationId);
            if (!said || typeof said.id !== 'string' || !turn) return thread;
            return replace(thread, { ...turn, announced: [...turn.announced.filter((a) => a.id !== said.id), { ...said, kind: event.type }] });
        }
        default:
            return thread;
    }
}

/** A note the stream says: once (one read back already, or said again, isn't drawn twice; one written since the
 *  person's last message is new), and before a turn at work, where the conversation keeps it. */
function withNote(thread: Thread, note: NoteEntry): Thread {
    const since = thread.entries.slice(thread.entries.map((e) => e.kind).lastIndexOf('user') + 1);
    if (since.some((e) => e.kind === 'note' && sameNote(e, note))) return thread;
    const live = liveTurn(thread);
    const at = live ? thread.entries.indexOf(live) : thread.entries.length;
    return { ...thread, entries: [...thread.entries.slice(0, at), note, ...thread.entries.slice(at)] };
}

function settledOp(thread: Thread, operationId: string | null): boolean {
    return !!operationId && thread.entries.some((e) => e.kind === 'turn' && e.operationId === operationId && e.status !== 'running');
}

/** A request as its live event carries it, in the shape agent.requests lists. */
export function toRequest(raw: JsonObject): HarnessRequest {
    const s = (v: unknown) => (typeof v === 'string' ? v : null);
    const list = (v: unknown) => (Array.isArray(v) ? (v as JsonObject[]) : []);
    const date = (v: unknown) => (typeof v === 'string' ? new Date(v) : null);
    return {
        id: s(raw.id) ?? '',
        kind: (s(raw.kind) ?? 'approval') as HarnessRequest['kind'],
        status: (s(raw.status) ?? 'pending') as HarnessRequest['status'],
        action: s(raw.action),
        title: s(raw.title),
        detail: s(raw.detail),
        plan: s(raw.plan),
        questions: list(raw.questions),
        options: list(raw.options).map((o) => ({ optionId: String(o.option_id), name: String(o.name), kind: String(o.kind) })),
        answer: raw.answer && typeof raw.answer === 'object' ? (raw.answer as JsonObject) : null,
        decision: s(raw.decision),
        answeredAt: date(raw.answered_at),
        canceledReason: s(raw.canceled_reason),
        operationId: s(raw.operation_id),
        createdAt: date(raw.created_at),
        expiresAt: date(raw.expires_at),
        raw,
    };
}

/** A message this page just sent (`key` names it until the conversation shows it back): drawn at once, in the turn
 *  under way when it steers it, else with the turn it starts. */
export function sent(
    thread: Thread,
    key: string,
    text: string,
    files: Attachment[],
    at: number,
    options: { steer?: boolean; command?: { name: string; arguments?: string }; subagent?: MessageSubagent; references?: ChatReference[] } = {}
): Thread {
    const entry: UserEntry = {
        kind: 'user',
        key,
        id: null,
        text,
        at,
        files,
        operationId: null,
        author: null,
        via: null,
        trigger: null,
        chat: null,
        command: options.command ?? null,
        subagent: options.subagent ?? null,
        channel: null,
        steer: !!options.steer,
        pending: true,
        references: options.references ?? [],
    };
    const live = liveTurn(thread);
    if (options.steer && live) return replace(thread, { ...live, parts: [...live.parts, { kind: 'user', entry }] });
    return { ...thread, entries: [...thread.entries, entry, ...(options.steer ? [] : [runningTurn(null, at)])] };
}

/** The send's operation is known: the message and the turn it started carry it. */
export function started(thread: Thread, key: string, operationId: string): Thread {
    let found = false;
    const entries = thread.entries.map((e) => {
        if (e.kind === 'user' && e.key === key) {
            found = true;
            return { ...e, operationId };
        }
        // The turn just after it, not yet named by any event.
        if (found && e.kind === 'turn' && e.status === 'running' && !e.operationId) {
            found = false;
            return { ...e, operationId };
        }
        return e;
    });
    return { ...thread, entries };
}

/** A turn its operation ended, whichever of it and the stream says so first: the reply (and steps) its operation
 *  answered, or a failure (and why, where its connection was refused), or a stop. */
export function ended(thread: Thread, operationId: string, outcome: { status: TurnStatus; reply?: string; steps?: AgentStep[]; failure?: Failure | null; outOfFunds?: JsonObject | null; at: number }): Thread {
    const turn = thread.entries.find((e): e is TurnEntry => e.kind === 'turn' && e.operationId === operationId);
    if (!turn || turn.status !== 'running') return thread;
    const kept = !stepsOf(turn).length && outcome.steps?.length ? [{ kind: 'steps' as const, steps: nested(outcome.steps.map((s, i) => stepOf(s, i, turn.key, outcome.at))) }, ...turn.parts] : turn.parts;
    return replace(thread, {
        ...turn,
        parts: kept.map((p) => (p.kind === 'steps' ? { ...p, steps: settledSteps(p.steps, outcome.status) } : p)),
        // A turn that ended before its reply (stopped, or one that saved none) keeps what it said on the way.
        reply: outcome.reply ?? turn.reply ?? (turn.parts.flatMap((p) => (p.kind === 'text' ? [p.text] : [])).join('').trim() || null),
        status: outcome.status,
        endedAt: outcome.at,
        pace: turn.pace && doneThinking(turn.pace, outcome.at),
        compacting: null,
        downloading: null,
        failure: outcome.failure ?? null,
        outOfFunds: outcome.outOfFunds ?? turn.outOfFunds,
    });
}

/** A send NoClick turned down for lack of money before any turn started: the message stands, and the turn it would
 *  have started ends on the refusal (`reply`), with what its card draws when the account ran out. */
export function refused(thread: Thread, key: string, refusal: { reply: string; outOfFunds: JsonObject | null }, at: number): Thread {
    const i = thread.entries.findIndex((e) => e.key === key);
    if (i < 0) return thread;
    const entries = thread.entries.map((e, k): Entry => {
        if (k === i && e.kind === 'user') return { ...e, pending: false };
        if (k === i + 1 && e.kind === 'turn' && !e.operationId) return { ...e, reply: refusal.reply, outOfFunds: refusal.outOfFunds, status: 'done', endedAt: at };
        return e;
    });
    return { ...thread, entries };
}

/** Why a failed turn failed, read from its operation after the stream settled it (the stream's message doesn't say). */
export function withFailure(thread: Thread, operationId: string, failure: Failure): Thread {
    const turn = thread.entries.find((e): e is TurnEntry => e.kind === 'turn' && e.operationId === operationId);
    return turn && turn.status === 'failed' && !turn.failure ? replace(thread, { ...turn, failure }) : thread;
}

/** A send that failed before any turn started: the message stays, marked, and its turn goes. */
export function unsent(thread: Thread, key: string): Thread {
    const at = thread.entries.findIndex((e) => e.key === key);
    if (at < 0) return thread;
    const next = thread.entries[at + 1];
    return { ...thread, entries: thread.entries.filter((e, i) => i !== at && !(i === at + 1 && next?.kind === 'turn' && !next.operationId)) };
}

/** The turns a thread read from history holds but the one at work: what the stream replays of them is drawn already,
 *  or never drew (one over that saved no reply). */
export function turnsOver(thread: Thread): ReadonlySet<string> {
    const live = liveTurn(thread)?.operationId;
    return new Set(thread.entries.flatMap((e) => ((e.kind === 'user' || e.kind === 'turn') && e.operationId && e.operationId !== live ? [e.operationId] : [])));
}

/** The history read again (after a dropped stream): what it holds stands, and a turn it doesn't hold yet stays. */
export function reread(thread: Thread, entries: Entry[]): Thread {
    const settled = new Set(entries.flatMap((e) => (e.kind === 'turn' && e.operationId ? [e.operationId] : [])));
    const keep = thread.entries.filter((e) => (e.kind === 'turn' && e.status === 'running' && !(e.operationId && settled.has(e.operationId))) || (e.kind === 'user' && e.pending));
    return { ...thread, entries: [...entries, ...keep] };
}

/** Requests still waiting on a person, oldest first. */
export function pendingRequests(thread: Thread): HarnessRequest[] {
    return Object.values(thread.requests)
        .filter((r) => r.status === 'pending')
        .sort((a, b) => time(a.createdAt, 0) - time(b.createdAt, 0));
}

/** Every file a turn changed (its subagents' too), its last diff for each, as the changed-files card counts them. */
export function changedFiles(turn: TurnEntry): AgentStepDiff[] {
    const byPath = new Map<string, AgentStepDiff>();
    for (const s of allStepsOf(turn)) for (const d of s.diffs) byPath.set(d.path, d);
    return [...byPath.values()];
}

/** Subagents working beside the conversation, in the order they were started: their calls still running, in any turn
 *  (one can go on after its turn's reply). */
export function subagentsOf(thread: Thread): Step[] {
    return thread.entries.flatMap((e) => (e.kind === 'turn' ? stepsOf(e).filter((s) => s.running && isSubagentCall(s)) : []));
}
