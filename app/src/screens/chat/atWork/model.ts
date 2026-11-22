// What the tab of what's at work shows, derived once from what /v1 says. A row is the thing being worked on (an app,
// an automation, an agent of its own, a held purchase or deletion, the account's cap), never the agent: its name, the
// task in it, where it stands, its one link, and what it needs from the person. The agents doing the work are its
// parts, shown only when it's opened.
//
// Where each row comes from: an app's coding agent (the listing's `app`); a build's child, through its checkout (the
// agent's `repos`) to the app whose `repo_id` that is; a run, its automation (the operation's `summary`); a coding
// agent with neither, itself. A held call names no project, so it stands as its own row, named by what it does.
// Work is named by its title, as whoever handed it over gave it; work started before titles by its text's first clause.
// The chat's own agent is never a row: on a coding harness it's listed beside the account's other coding agents, but
// it's the conversation the tab sits under, and its turn is the chat's.
import { agentMarkType } from '@/ui/primitives';
import { standing } from '@/slots';
import { CONNECTION_MARK } from '@/ui/slots';
import type { AgentSlice, CodingAgent, CodingAgentsPage, CodingCredential, EditFeedback, FollowedOperation, HeldApproval, LiveRead, PauseReason, ProjectSlice, ToolCallEntry } from './types';

/** Where the rows' links go: the account's billing (its cap, its funds), a held call's approval page, and a commit of
 *  an app's code. */
export interface AtWorkLinks {
    billing: string;
    approval: (approvalId: string) => string;
    commit: (repoId: string, sha: string) => string;
}

/** Everything the tab is derived from. */
export interface AtWorkSources {
    links: AtWorkLinks;
    /** The chat's own agent (NoClick's, the coordinator), by id: never at work in its own tab. */
    own: string | null;
    coding: CodingAgentsPage | null;
    projects: ProjectSlice[];
    /** The work the chat's turns started, as the chat follows it. */
    operations: FollowedOperation[];
    /** The agents behind the tasks, by id. */
    agents: Record<string, AgentSlice>;
    approvals: HeldApproval[];
    /** Each app's live session and its newest edits, by app. */
    live: Record<string, LiveRead>;
    /** What the person asked in the message the turn that started each task answered, by task. */
    requests: Record<string, string>;
}

// ── Words ───────────────────────────────────────────────────────────────────

const HARNESS: Record<string, string> = { claude_code: 'Claude Code', codex: 'Codex', opencode: 'OpenCode', hermes: 'Hermes', openclaw: 'OpenClaw', sdk: 'NoClick agent' };
const MODEL_WORDS: [RegExp, string][] = [
    [/gpt-?luna|gpt-6-luna/i, 'GPT-Luna'],
    [/(^|\/)sonnet|claude-sonnet/i, 'Sonnet'],
    [/(^|\/)opus|claude-opus/i, 'Opus'],
    [/(^|\/)haiku|claude-haiku/i, 'Haiku'],
    [/gpt-5-codex/i, 'GPT-5 Codex'],
];

/** "Codex · GPT-Luna": what runs it and on which model, in words. */
export function runsOn(harness: string, model: string): string {
    const words = MODEL_WORDS.find(([pattern]) => pattern.test(model))?.[1] ?? model.split('/').pop() ?? model;
    return model ? `${HARNESS[harness] ?? harness} · ${words}` : (HARNESS[harness] ?? harness);
}

export function harnessMark(harness: string): string {
    return harness === 'sdk' ? 'agent' : agentMarkType(harness.replace('_', '-'));
}

// The AI plans an agent signs in with, by the account type they sign in as.
const PLAN_NAMES: Readonly<Record<string, string>> = {
    agent_claude_code_oauth: 'Claude',
    agent_codex_oauth: 'ChatGPT',
    agent_github_copilot_oauth: 'Copilot',
    agent_xai_oauth: 'SuperGrok',
};

/** "your Claude plan", "your ChatGPT key": a plan by its name, a key by its company's, as Connections lists them. */
export function paidBy(credential: CodingCredential): string {
    if (credential.kind === 'noclick') return 'NoClick’s key';
    if (credential.kind === 'pending' || !credential.connected) return 'its key isn’t connected';
    const type = credential.credential_type ?? '';
    const plan = PLAN_NAMES[type];
    return plan ? `your ${plan} plan` : `your ${standing(CONNECTION_MARK).aiCompany(type) ?? credential.connection} key`;
}

const WHERE: Record<string, string> = { live: 'on the live site', sandbox: 'in a sandbox', machine: 'on your machine' };

// Verbs a task opens with, so "Speed up the menu page" reads as what it's doing: "Speeding up the menu page".
const VERBS = /^(speed|make|add|move|write|turn|prepare|change|fix|put|build|update|remove|set|create|connect|rename|replace|show|use|give|let|offer|swap|resize|redo|check|finish|start|send|draft|clean|tidy)\b/i;

function ing(verb: string): string {
    const v = verb.toLowerCase();
    if (/[^aeiou]e$/.test(v) && !/ee$/.test(v)) return v.slice(0, -1) + 'ing';
    if (/^(put|set|let|swap|stop|get|run|cut|shop)$/.test(v)) return v + v.at(-1) + 'ing';
    return v + 'ing';
}

/** A task as what's being done: its first clause, its verb as doing ("Speed up the menu page on phones: …" →
 *  "Speeding up the menu page on phones"). A title is used as it was given. */
export function doingOf(text: string): string {
    // A person's own message may open with a word that isn't the task ("Also build …", "Can you put …").
    const clause = text
        .split(/[:.;!?]\s|[:.;!?]$|\n|\s\(|,\s(?:then|and then)\s/i)[0]
        .trim()
        .replace(/^(also|and|now|please|can you|could you|would you)\s+/i, '');
    const match = clause.match(VERBS);
    if (!match) return clause;
    const word = ing(match[0]);
    return word[0].toUpperCase() + word.slice(1) + clause.slice(match[0].length);
}

/** The work's own title, else (work started before titles) its text's first clause. */
export function taskOf(title: string | null | undefined, text: string | null | undefined): string {
    return title?.trim() || doingOf(text ?? '');
}

function firstSentence(text: string): string {
    // Up to the first stop a space follows; no lookbehind, which Safari before 16.4 can't parse.
    return (text.match(/^[\s\S]*?[.!?](?=\s)/)?.[0] ?? text).replace(/[.]$/, '');
}

export function base(path: string): string {
    return path.split('/').pop() ?? path;
}

/** A step of an agent's work as a person reads it. */
export function stepLine(entry: ToolCallEntry): string {
    const path = (entry.arguments.file_path ?? entry.arguments.path) as string | undefined;
    const command = entry.arguments.command as string | undefined;
    switch (entry.tool) {
        case 'Read':
        case 'files__read':
            return `Read ${base(path ?? '')}`;
        case 'Write':
            return `Wrote ${base(path ?? '')}`;
        case 'Edit':
            return `Edited ${base(path ?? '')}`;
        case 'files__write':
            return `Saved ${base(path ?? '')}`;
        case 'shell':
        case 'Bash':
            return `Ran ${command ?? 'a command'}`;
        default:
            return entry.tool.replace(/__/g, ' ').replace(/_/g, ' ');
    }
}

const OUTCOME: Record<EditFeedback['outcome'], string> = { hot: 'Saved', reload: 'Saved', none: 'Saved', error: 'Couldn’t build' };

export function editLine(edit: EditFeedback): string {
    return `${OUTCOME[edit.outcome]} ${base(edit.files[0] ?? '')}`;
}

/** Dollars as the tab says them: cents under $10, whole dollars above. */
export function money(usd: number): string {
    return usd < 10 ? `$${usd.toFixed(2)}` : `$${Math.round(usd)}`;
}

// ── A held ask: a purchase, a deletion or another call waiting on the owner's OK ──

/** What a held call does: a deletion (it says what it takes along, or runs a `*_delete`), a purchase (it has a price),
 *  or another change the account's policy holds. */
export type HeldKind = 'purchase' | 'deletion' | 'change';

/** What names a held call: its approval, as listed or read, or as the tool that asked answered before then. */
export type HeldNaming = Pick<HeldApproval, 'price'> & Partial<Pick<HeldApproval, 'action' | 'summary' | 'operation' | 'impact' | 'arguments' | 'subject'>>;

export interface HeldAsk {
    kind: HeldKind;
    /** The verb it's asked with: "Delete", "Buy", else its title's own ("Start"). */
    verb: string;
    /** Its verb and the thing, as every place names it: "Delete tiktok?", "Buy morrowbakehouse.com?". */
    title: string;
    /** The thing: "tiktok", "morrowbakehouse.com". */
    name: string;
    /** Under the title: a purchase's price ("$11.25 a year"), the account a deletion takes ("@morrowbakehouse"), else
     *  the kind of thing it is ("Connection"). */
    line: string | null;
    /** It said whole: "Deleting tiktok needs your OK". */
    sentence: string;
}

/** How many of the words after a deletion's verb are its resource ("connection" of `connections_delete`, "phone
 *  number" of `phone_numbers_delete`), before the one it names. */
function nounWords(words: readonly string[], operation: string | null | undefined): number {
    const resource = operation?.replace(/_delete$/, '').split('_').filter(Boolean) ?? [];
    const one = (word: string, plural: string) => {
        const w = word.toLowerCase();
        return w.length > 2 && (plural.startsWith(w) || (w.endsWith('y') && plural.startsWith(`${w.slice(0, -1)}i`)));
    };
    return resource.length && words.length >= resource.length && resource.every((plural, i) => one(words[i], plural)) ? resource.length : 0;
}

const usd = (amount: number) => `$${amount.toFixed(2)}`;

/** A price in a row's few words: "$11.25 a year", "$1.50 a month"; a first charge that renews, with what it renews
 *  at where that differs ("$11.25, then $21.99 a year"). */
function priceLine({ amount_usd, recurrence, renewal }: NonNullable<HeldApproval['price']>): string {
    if (recurrence !== 'once' || !renewal) return `${usd(amount_usd)}${recurrence === 'yearly' ? ' a year' : recurrence === 'monthly' ? ' a month' : ''}`;
    const per = renewal.months === 12 ? 'a year' : renewal.months === 1 ? 'a month' : `every ${renewal.months} months`;
    if (renewal.amount_usd === amount_usd) return `${usd(amount_usd)} ${per}`;
    return renewal.amount_usd == null ? `${usd(amount_usd)} now` : `${usd(amount_usd)}, then ${usd(renewal.amount_usd)} ${per}`;
}

// The start of a NoClick id, which a title never shows.
const AN_ID = /^[0-9a-f]{8}-[0-9a-f]{4}/i;

/** A held call as every place names it (the Beside's row, its rail, the thread's card, the review): the verb, read off
 *  the approval, and the thing: by the app its subject is on, over the account it reaches ("Delete TikTok?" over
 *  "@morrowbakehouse"), else as the approval's own title names it ("Delete connection tiktok" → "Delete tiktok?" over
 *  "Connection"; "Buy morrowbakehouse.com for 1 year" → "Buy morrowbakehouse.com?" over its price). A title in another
 *  verb ("Start machine web") is asked as it is. */
export function heldAskOf(approval: HeldNaming): HeldAsk {
    const said = (approval.action || approval.summary || '').trim().replace(/[.?]$/, '');
    const [verb = '', ...rest] = said.split(/\s+/);
    const named = typeof approval.arguments?.name === 'string' ? approval.arguments.name : null;
    const asked = (kind: HeldKind, line: string | null): HeldAsk => ({ kind, verb, title: `${said}?`, name: said, line, sentence: `${doingOf(said)} needs your OK` });
    if (approval.impact || /_delete$/.test(approval.operation ?? '')) {
        const { subject } = approval;
        if (subject?.app && /^delete$/i.test(verb)) {
            return { kind: 'deletion', verb: 'Delete', title: `Delete ${subject.app}?`, name: subject.app, line: subject.account || subject.name, sentence: `Deleting ${subject.app} needs your OK` };
        }
        if (said && !/^delete$/i.test(verb)) return asked('deletion', null);
        const n = nounWords(rest, approval.operation);
        const noun = rest.slice(0, n).join(' ');
        const thing = rest.slice(n).join(' ');
        const name = !thing ? noun || named || 'it' : AN_ID.test(thing) ? `this ${noun || 'one'}` : thing;
        return { kind: 'deletion', verb: 'Delete', title: `Delete ${name}?`, name, line: noun ? noun[0].toUpperCase() + noun.slice(1) : null, sentence: `Deleting ${name} needs your OK` };
    }
    if (approval.price) {
        const line = priceLine(approval.price);
        if (said && !/^buy$/i.test(verb)) return asked('purchase', line);
        const name = rest.join(' ').replace(/ for \d+ years?$/, '') || named || 'it';
        return { kind: 'purchase', verb: 'Buy', title: `Buy ${name}?`, name, line, sentence: `Buying ${name} needs your OK` };
    }
    return said ? asked('change', null) : { kind: 'change', verb: 'Approve', title: 'Approve this?', name: 'this', line: null, sentence: 'This needs your OK' };
}

function at(iso: string | null | undefined): number | undefined {
    const ms = iso ? Date.parse(iso) : NaN;
    return Number.isFinite(ms) ? ms : undefined;
}

// ── Parts: the agents behind a row ──────────────────────────────────────────

export type PartState = 'working' | 'waiting' | 'paused' | 'failed' | 'ready' | 'done' | 'idle';

export interface Ask {
    label: string;
    href?: string;
    /** No link: it drafts a reply to NoClick, which does it. */
    draft?: string;
}

export interface Part {
    key: string;
    /** The agent, for its steps and its terminal. */
    agentId: string;
    agent: string;
    harness: string;
    /** "Codex · GPT-Luna". */
    runsOn: string;
    /** "NoClick's key · on the live site · $4.86 this month". */
    machinery: string;
    state: PartState;
    /** What it's doing, in a few words: its task. */
    doing: string;
    /** Where it stands, in a line: its newest word or step. */
    status: string;
    since?: number;
    /** Its newest edits as steps, newest first, when it edits a live site; else read from its conversation. */
    steps?: string[];
    /** The conversation it works in: its terminal shows it, and its steps are read from it when they aren't edits. */
    conversation?: string;
    /** Watch opens its terminal: the one way in of an agent the site doesn't show, the second beside a live site. */
    watch: boolean;
    ask?: Ask;
    /** The raw words behind a failure, kept behind Details. */
    detail?: string;
    spent: number;
    /** The turn or task to stop. */
    stop?: string;
    change?: { sha: string; href: string };
    /** The workstream its task belongs to, by name, where one was named. */
    workstream?: string | null;
}

/** Why an agent is paused, and the one thing that starts it again. */
const PAUSED = (links: AtWorkLinks): Record<PauseReason, { line: string; ask?: Ask }> => ({
    spend_cap: { line: 'Paused at your monthly cap', ask: { label: 'Raise cap', href: links.billing } },
    out_of_funds: { line: 'Paused: out of funds', ask: { label: 'Add funds', href: links.billing } },
    spending_paused: { line: 'Paused: spending is paused' },
    budget: { line: 'Its monthly budget ran out', ask: { label: 'Raise budget', draft: 'Raise its monthly budget.' } },
    disconnected: { line: 'Its model key isn’t connected', ask: { label: 'Connect', draft: 'Connect its model key again.' } },
    expired: { line: 'Expired' },
    failed_start: { line: 'Didn’t start: its sandbox stopped', ask: { label: 'Try again', draft: 'Try that again.' } },
    paused: { line: 'Paused by you', ask: { label: 'Resume', draft: 'Resume it.' } },
});

function codingState(agent: CodingAgent): PartState {
    if (agent.state === 'paused') return agent.paused?.reason === 'failed_start' ? 'failed' : 'paused';
    if (agent.state === 'warm') return 'ready';
    if (agent.state === 'stopped') return 'idle';
    return agent.state;
}

function codingPart(agent: CodingAgent, sources: AtWorkSources, name: string): Part {
    // What it was last handed, when no turn of its is in flight (one that failed to start, say).
    const handed = sources.operations.filter((op) => op.kind === 'agent.message' && op.agent_id === agent.agent_id).at(-1);
    const appId = agent.app?.project_id;
    const live = appId ? sources.live[appId] : undefined;
    const repo = sources.projects.find((p) => p.id === appId)?.repo_id;
    const pause = agent.paused ? PAUSED(sources.links)[agent.paused.reason] : undefined;
    const state = codingState(agent);
    const edits = live?.edits ?? [];
    const own = agent.credential.kind === 'key' || agent.credential.kind === 'plan';
    const cost = [agent.spent_usd_this_month > 0 && `${money(agent.spent_usd_this_month)} this month`, own && agent.model_usage_this_month.usd > 0 && `${money(agent.model_usage_this_month.usd)} on ${paidBy(agent.credential)}`].filter(Boolean);
    const editing = agent.place === 'live' && !!live;
    // The turn it's on, else the conversation it last ran in (its terminal shows that turn, in a live container too).
    const conversation = agent.job?.conversation ?? agent.runs.find((r) => r.conversation)?.conversation ?? undefined;
    const head = live?.session?.git?.head;
    const ask = state === 'paused' || state === 'failed' ? pause?.ask : undefined;
    return {
        key: agent.agent_id,
        agentId: agent.agent_id,
        agent: agent.name,
        harness: agent.harness,
        runsOn: runsOn(agent.harness, agent.model),
        machinery: [paidBy(agent.credential), WHERE[agent.place], ...cost].join(' · '),
        state,
        doing: agent.job ? taskOf(agent.job.title, agent.job.text) : handed ? taskOf(handed.title, handed.summary) : state === 'ready' ? 'Answering its messages' : `${name}’s coding agent`,
        status:
            state === 'working' && edits.length
                ? `${editLine(edits.at(-1)!)} · ${live!.session?.edits.last_seq ?? edits.length} changes so far`
                : state === 'working'
                  ? 'Working on it'
                  : state === 'waiting'
                    ? 'Waiting for your answer'
                    : state === 'ready'
                      ? 'Ready for its next message'
                      : (pause?.line ?? ''),
        since: at(agent.job?.since) ?? at(agent.runs[0]?.since),
        steps: editing ? edits.slice(-3).reverse().map(editLine) : undefined,
        conversation,
        // Editing a live site, the site shows its work first and its terminal second: Watch needs its conversation.
        watch: !editing || !!conversation,
        // A retry or a resume names what it's for: the reply goes to NoClick, which hears it in the chat.
        ask: ask?.draft ? { ...ask, draft: `${ask.draft.replace(/\.$/, '')} (${name}).` } : ask,
        detail: state === 'failed' ? agent.paused?.message : undefined,
        spent: agent.spent_usd_this_month,
        stop: state === 'working' || state === 'waiting' ? agent.job?.operation_id : undefined,
        change: head && repo && editing ? { sha: head.slice(0, 7), href: sources.links.commit(repo, head) } : undefined,
        workstream: (agent.job ?? handed)?.workstream?.name ?? null,
    };
}

/** The account named in a connection hold's line ("Waiting for its user to connect Stripe ('stripe')."). */
function connectionOf(what: string | null | undefined): string | undefined {
    return what?.match(/connect (.+?) \(/)?.[1];
}

function childPart(op: FollowedOperation, sources: AtWorkSources): Part {
    const agent = op.agent_id ? sources.agents[op.agent_id] : undefined;
    const coding = sources.coding?.data.find((c) => c.agent_id === op.agent_id);
    const state: PartState = op.status === 'waiting' ? 'waiting' : op.status === 'completed' ? 'done' : op.status === 'running' ? 'working' : 'failed';
    const update = op.latest_update;
    const hold = update?.kind === 'blocked' ? update.waiting_on : null;
    const account = connectionOf(update?.text);
    const harness = agent?.harness ?? coding?.harness ?? 'sdk';
    return {
        key: op.id,
        agentId: op.agent_id ?? op.id,
        agent: agent?.name ?? coding?.name ?? 'A helper agent',
        harness,
        runsOn: runsOn(harness, agent?.model ?? coding?.model ?? ''),
        machinery: [coding ? paidBy(coding.credential) : 'NoClick’s key', coding ? WHERE[coding.place] : 'in NoClick'].join(' · '),
        state,
        doing: taskOf(op.title, op.summary),
        status: hold?.kind === 'connection' ? `Waiting for you to connect ${account ?? 'an account'}` : firstSentence(update?.text ?? (state === 'failed' ? 'Stopped before it finished' : 'Starting')),
        since: at(op.created_at),
        conversation: 'task',
        watch: true,
        ask: hold?.url ? { label: `Connect ${account ?? 'it'}`, href: hold.url } : undefined,
        spent: coding?.spent_usd_this_month ?? 0,
        stop: state === 'working' || state === 'waiting' ? op.id : undefined,
        workstream: op.workstream?.name ?? null,
    };
}

// ── Rows: what's being worked on ────────────────────────────────────────────

export type RowState = 'needs' | 'working' | 'ready' | 'done';

export type WayIn = { label: 'Open site'; projectId: string; url: string; live: boolean } | { label: 'Watch'; part: Part };

export interface Row {
    key: string;
    kind: 'app' | 'automation' | 'agent' | HeldKind | 'account';
    name: string;
    /** What's being done in it, in a few words. */
    task: string;
    /** Where it stands now, in a line. */
    status: string;
    state: RowState;
    since?: number;
    /** Its one link: the site (the live view while an agent edits it, else production), or the terminal of the one agent
     *  at it while that agent works where the site doesn't show it (a sandbox), or of an agent with no site. */
    link?: WayIn;
    /** The second way in, shown once the row is opened: the site, when the terminal took the link, or the terminal of
     *  the one agent editing the live site. */
    also?: WayIn;
    /** What it needs from the person, when one thing does. */
    ask?: Ask;
    parts: Part[];
    /** The held approval itself, which Review opens. */
    approval?: HeldApproval;
    /** What the account's cap or balance holds, by name. */
    holds?: string[];
}

function partsLine(parts: Part[]): string {
    const done = parts.filter((p) => p.state === 'done').length;
    const working = parts.filter((p) => p.state === 'working').length;
    const waiting = parts.filter((p) => p.state === 'waiting').length;
    return [working && `${working} working`, waiting && `${waiting} waiting on you`, done && `${done} done`].filter(Boolean).join(', ');
}

const NEEDS: PartState[] = ['waiting', 'paused', 'failed'];

function stateOf(parts: Part[]): RowState {
    if (parts.some((p) => NEEDS.includes(p.state))) return 'needs';
    if (parts.some((p) => p.state === 'working')) return 'working';
    if (parts.some((p) => p.state === 'ready')) return 'ready';
    return 'done';
}

function approvalRow(approval: HeldApproval, links: AtWorkLinks): Row {
    const held = heldAskOf(approval);
    return {
        key: approval.id,
        kind: held.kind,
        name: held.name,
        task: held.sentence,
        status: held.line ? `Waiting for your OK · ${held.line}` : 'Waiting for your OK',
        state: 'needs',
        since: at(approval.created_at),
        ask: { label: 'Review', href: links.approval(approval.id) },
        approval,
        parts: [],
    };
}

function resetsOn(message: string | undefined): string | undefined {
    return message?.match(/resets on ([A-Z][a-z]+ \d+)/)?.[1];
}

function capOf(message: string | undefined): string | undefined {
    return message?.match(/your (\$[\d,.]+) monthly cap/)?.[1];
}

/** An app's name as a person reads it: its title, as the listing or the app gives it. */
function titleOf(agent: CodingAgent | undefined, project: ProjectSlice | undefined): string {
    return project?.title ?? agent?.app?.title ?? agent?.app?.name ?? agent?.name ?? 'An app';
}

export interface AtWork {
    rows: Row[];
    needs: Row[];
    working: Row[];
    /** Anything to show: work going, or something that needs the owner. An agent that is only ready (warm, idle) is
     *  listed while the tab is open for other work, and never opens it alone. */
    active: boolean;
    /** What the account's coding agents cost this month. */
    spent: number;
}

const ORDER: Record<RowState, number> = { needs: 0, working: 1, ready: 2, done: 3 };
const LIVE_STATES = new Set(['running', 'waiting']);

export function atWork(sources: AtWorkSources): AtWork {
    const coding = (sources.coding?.data ?? []).filter((a) => a.agent_id !== sources.own);
    const tasks = sources.operations.filter((op) => op.kind === 'agent.task');
    const childIds = new Set(tasks.map((op) => op.agent_id));
    const rows: Row[] = [];

    // The account's cap or balance holds every agent alike: one row, naming what it holds.
    const held = coding.filter((a) => a.paused && (a.paused.reason === 'spend_cap' || a.paused.reason === 'out_of_funds'));
    if (held.length) {
        const pause = held[0].paused!;
        const names = held.map((a) => titleOf(a, sources.projects.find((p) => p.id === a.app?.project_id)));
        rows.push({
            key: `account:${pause.reason}`,
            kind: 'account',
            name: pause.reason === 'spend_cap' ? (capOf(pause.message) ? `Your ${capOf(pause.message)} monthly cap` : 'Your monthly cap') : 'Your balance',
            task: `${names.length === 1 ? names[0] : `${names.length} projects`} paused`,
            status: `${names.join(' and ')} ${names.length === 1 ? 'waits' : 'wait'} ${resetsOn(pause.message) ? `until ${resetsOn(pause.message)}` : 'for funds'}`,
            state: 'needs',
            ask: PAUSED(sources.links)[pause.reason].ask,
            parts: held.map((a, i) => codingPart(a, sources, names[i])),
            holds: names,
        });
    }

    // Each app: its own coding agent, and a build's children working in its repo.
    const appIds = new Set([...coding.flatMap((a) => (a.app && !held.includes(a) ? [a.app.project_id] : [])), ...sources.projects.map((p) => p.id)]);
    for (const appId of appIds) {
        const project = sources.projects.find((p) => p.id === appId);
        const coder = coding.find((a) => a.app?.project_id === appId && !held.includes(a));
        const name = titleOf(coder, project);
        const kids = tasks.filter((op) => project?.repo_id && sources.agents[op.agent_id ?? '']?.repos.some((r) => r.repo_id === project.repo_id));
        const parts = [...(coder ? [codingPart(coder, sources, name)] : []), ...kids.map((op) => childPart(op, sources))].filter((p) => p.state !== 'idle');
        // Work that's all done shows no row, unless it's a build some of whose parts still go.
        if (!parts.length || parts.every((p) => p.state === 'done')) continue;
        const editing = coder?.place === 'live' && (coder.state === 'working' || coder.state === 'waiting');
        const needing = parts.filter((p) => NEEDS.includes(p.state));
        const lead = needing[0] ?? parts.find((p) => p.state === 'working') ?? parts[0];
        const request = kids.map((k) => sources.requests[k.id]).find(Boolean);
        const site: WayIn | undefined = editing ? { label: 'Open site', projectId: appId, url: project?.url ?? '', live: true } : project?.production ? { label: 'Open site', projectId: appId, url: project.url, live: false } : undefined;
        // Its one agent at work out of the site's sight: its terminal is where the work shows until it's published. One
        // editing the live site: the site first, its terminal second. A build's several parts keep a Watch each.
        const one = parts.length === 1 ? parts[0] : undefined;
        const going = one?.watch && (one.state === 'working' || one.state === 'waiting') ? one : undefined;
        const watched = editing ? undefined : going;
        rows.push({
            key: appId,
            kind: 'app',
            name,
            task: kids.length && request ? doingOf(request) : lead.doing,
            status: needing.length ? needing[0].status : parts.length > 1 ? `${parts.length} parts: ${partsLine(parts)}` : lead.status,
            state: stateOf(parts),
            since: Math.min(...parts.map((p) => p.since ?? Date.now())),
            link: watched ? { label: 'Watch', part: watched } : site,
            also: watched ? site : editing && going ? { label: 'Watch', part: going } : undefined,
            ask: needing.length === 1 ? needing[0].ask : undefined,
            parts,
        });
    }

    // An automation's run: the automation is the row.
    for (const op of sources.operations) {
        if (op.kind !== 'workflow.run' || !LIVE_STATES.has(op.status)) continue;
        rows.push({
            key: op.id,
            kind: 'automation',
            name: op.summary ?? 'An automation',
            task: 'Running',
            status: op.status === 'waiting' ? 'Waiting for an approval' : op.step === 'agent_turn' ? 'Its agent is taking its turn' : 'Running its steps',
            state: op.status === 'waiting' ? 'needs' : 'working',
            since: at(op.created_at),
            parts: [],
        });
    }

    // A coding agent of its own (no app, not a child): the agent is what's being worked on.
    for (const agent of coding) {
        if (agent.app || childIds.has(agent.agent_id) || held.includes(agent) || agent.state === 'stopped') continue;
        const part = codingPart(agent, sources, agent.name);
        rows.push({
            key: agent.agent_id,
            kind: 'agent',
            name: agent.name,
            task: part.doing,
            status: part.status,
            state: stateOf([part]),
            since: part.since,
            link: { label: 'Watch', part },
            ask: part.ask,
            parts: [part],
        });
    }

    // A child with no app to work on: its task is the row.
    for (const op of tasks) {
        if (!LIVE_STATES.has(op.status) || rows.some((r) => r.parts.some((p) => p.key === op.id))) continue;
        const part = childPart(op, sources);
        rows.push({ key: op.id, kind: 'agent', name: part.agent, task: part.doing, status: part.status, state: stateOf([part]), since: part.since, link: { label: 'Watch', part }, ask: part.ask, parts: [part] });
    }

    for (const approval of sources.approvals) if (approval.status === 'pending') rows.push(approvalRow(approval, sources.links));

    rows.sort((a, b) => ORDER[a.state] - ORDER[b.state]);
    return {
        rows,
        needs: rows.filter((r) => r.state === 'needs'),
        working: rows.filter((r) => r.state === 'working'),
        active: rows.some((r) => r.state === 'needs' || r.state === 'working'),
        spent: coding.reduce((sum, a) => sum + a.spent_usd_this_month, 0),
    };
}

/** What one row needs, as the line on the composer says it, long and short (beside its action on a phone). */
export function needsSentence(row: Row): { long: string; short: string } {
    if (row.approval) {
        const held = heldAskOf(row.approval);
        return { long: held.sentence, short: held.title };
    }
    if (row.kind === 'account') return { long: `${row.name} paused ${(row.holds ?? []).join(' and ')}`, short: row.name === 'Your balance' ? 'Out of funds' : 'Monthly cap reached' };
    if (row.kind === 'automation') return { long: `${row.name} needs your OK`, short: row.name };
    const part = row.parts.find((p) => NEEDS.includes(p.state));
    const words = part?.state === 'failed' ? 'didn’t start' : part?.state === 'paused' ? 'is paused' : 'needs you';
    // On a phone the action beside it says what's needed; the name is enough.
    return { long: `${row.name} ${words}`, short: row.name };
}
