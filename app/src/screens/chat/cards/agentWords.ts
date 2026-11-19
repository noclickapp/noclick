// An agent as the person it works for reads it: its job in a line, when it runs and what it uses, in their words
// rather than the platform's (no model, harness or node names). Read from the agent's /v1 view, its own triggers and
// the channels it's in with their schedules.
import { listOf } from '@/ui/chat/primitives';
import { list, obj, str, type JsonObject } from '@/lib/toolCalls';
import { getNodeIconMeta } from '@/lib/nodeIconRegistry';
import { describeCronIn } from '@/lib/scheduleFormat';

/** As long as an automation's description runs (`compiler.DESCRIPTION_MAX`). */
const JOB_MAX = 160;

// Verbs a sentence to the agent ("You …") can't be turned into its job with.
const NOT_A_JOB = new Set(['are', 'am', 'were', 'will', 'would', 'can', 'could', 'should', 'must', 'may', 'might', 'shall', 'need']);
const SAID_AS: Record<string, string> = { have: 'has', do: 'does', go: 'goes' };

/** "research" → "researches", "write" → "writes", "copy" → "copies". */
function thirdPerson(verb: string): string {
    if (SAID_AS[verb]) return SAID_AS[verb];
    if (/(s|sh|ch|x|z)$/.test(verb)) return `${verb}es`;
    if (/[^aeiou]y$/.test(verb)) return `${verb.slice(0, -1)}ies`;
    return `${verb}s`;
}

/** The agent's job in one line: the role its view carries, else its instructions' first sentence said of it ("You
 *  research events…" → "Researches events…"), cut at a word as an automation's description is. */
export function jobOf(agent: JsonObject | undefined): string | undefined {
    const role = str(agent, 'role');
    if (role) return role;
    const line = (str(agent, 'instructions') ?? '').split(/\s+/).join(' ').trim();
    const sentence = /^(.+?[.!?])(?:\s|$)/.exec(line)?.[1] ?? line;
    if (!sentence) return undefined;
    const said = sentence.replace(/^You ([a-z]+)\b/, (whole, verb: string) => (NOT_A_JOB.has(verb) ? whole : thirdPerson(verb).replace(/^./, (c) => c.toUpperCase())));
    return said.length <= JOB_MAX ? said : `${said.slice(0, JOB_MAX - 1).replace(/\s+\S*$/, '')}…`;
}

/** Whether a message names `name` with an @-mention. */
export function mentions(text: string, name: string): boolean {
    return text.toLowerCase().includes(`@${name.toLowerCase()}`);
}

/** A schedule in words, or that it runs on one. */
function scheduleWords(trigger: JsonObject): string {
    const spec = obj(trigger, 'spec');
    return describeCronIn(str(spec, 'cron') ?? '', str(spec, 'tz')) ?? 'On a schedule';
}

/** What each of an agent's own triggers is, as when it runs. */
function triggerWords(trigger: JsonObject): string | undefined {
    switch (str(trigger, 'kind')) {
        case 'cron':
            return scheduleWords(trigger);
        case 'email':
            return 'When an email arrives';
        case 'call':
            return 'When someone calls';
        case 'webhook':
            return 'When another app sends it something';
        case 'event':
            return `When something happens in ${str(obj(trigger, 'spec'), 'connection') ?? 'a connected app'}`;
        case 'platform':
            return 'When NoClick tells it something happened';
        case 'queue':
            return 'For each item on its queue';
        default:
            return undefined;
    }
}

/** A channel it's in, with its schedules. */
export interface ChannelSeat {
    channel: JsonObject;
    triggers: JsonObject[];
}

interface Seated {
    id: string;
    name: string;
}

/** The agents in a channel, by the id a trigger names them with. */
function agentsIn(channel: JsonObject): Seated[] {
    return list(channel, 'members').flatMap((m) => {
        const member = m as JsonObject;
        const type = str(member, 'type');
        return type === 'agent' || type === 'workflow_agent' ? [{ id: str(member, 'agent_id') ?? str(member, 'id') ?? '', name: str(member, 'name') ?? '' }] : [];
    });
}

/** Whom a schedule's post wakes: the agents its trigger says it wakes (`wakes`, agent ids, as the API resolves the
 *  post), else those its message @-mentions, as any post in the room wakes them, or every agent where they read
 *  everything. */
function wokenBy(trigger: JsonObject, channel: JsonObject, agents: readonly Seated[]): Seated[] {
    if (Array.isArray(trigger.wakes)) return agents.filter((a) => (trigger.wakes as unknown[]).includes(a.id));
    if (str(channel, 'mode') === 'all') return [...agents];
    const message = str(obj(trigger, 'spec'), 'message') ?? '';
    return agents.filter((a) => mentions(message, a.name));
}

/** When the agent runs, a line each, from what wakes it: its own schedules and triggers; then in each channel it's
 *  in, the schedules whose post wakes it, the agents such a post tells to hand off to it (named there, not woken),
 *  and how it answers there. A schedule or a hand-off names its channel only when there's more than one. Asked
 *  directly, with none of those. */
export function whenItRuns(agent: JsonObject | undefined, triggers: readonly JsonObject[], seats: readonly ChannelSeat[]): string[] {
    const id = str(agent, 'id');
    const name = str(agent, 'name') ?? '';
    const own = triggers.map(triggerWords).filter((w): w is string => !!w);
    const rooms = seats.flatMap(({ channel, triggers: schedules }) => {
        const room = `#${str(channel, 'name') ?? 'a channel'}`;
        const where = seats.length > 1 ? ` in ${room}` : '';
        const agents = agentsIn(channel);
        const lines: string[] = [];
        const handing = new Set<string>();
        for (const t of schedules.filter((s) => str(s, 'kind') === 'cron')) {
            const woken = wokenBy(t, channel, agents);
            if (woken.some((a) => a.id === id)) lines.push(`${scheduleWords(t)}${where}`);
            else if (mentions(str(obj(t, 'spec'), 'message') ?? '', name)) woken.forEach((a) => handing.add(a.name));
        }
        if (handing.size) lines.push(`When ${listOf([...handing])} ${handing.size > 1 ? 'hand' : 'hands'} off${where}`);
        return [...lines, str(channel, 'mode') === 'all' ? `On every post in ${room}` : `When @-mentioned in ${room}`];
    });
    const lines = [...own, ...rooms];
    return lines.length ? lines : ['When you message it'];
}

/** One thing an agent uses, as its card names it: words, and the app's node type when it's an app. */
export interface Used {
    label: string;
    nodeType?: string;
}

const CAPABILITIES: Record<string, string> = { search: 'web search', fetch: 'web pages', noclick: 'your NoClick account', agents: 'your other agents' };

/** An app's name from its integration (`gmail` → Gmail), as its node is named. */
function appOf(integration: string): Used {
    const nodeType = `automation-${integration.replace(/_/g, '-')}`;
    return { label: getNodeIconMeta(nodeType)?.label || integration.replace(/[_-]/g, ' '), nodeType };
}

function usedOf(entry: unknown): Used | undefined {
    if (entry && typeof entry === 'object' && !Array.isArray(entry)) {
        const tool = str(entry as JsonObject, 'tool');
        if (tool) return usedOf(tool);
        const human = obj(entry as JsonObject, 'human');
        if (human) return { label: human.owner === true ? 'messages to you' : `messages to ${str(human, 'email') ?? str(human, 'phone') ?? 'a person'}` };
        return undefined;
    }
    if (typeof entry !== 'string' || entry === 'code') return undefined;
    const [head] = entry.split(/[.:]/);
    if (CAPABILITIES[head]) return { label: CAPABILITIES[head] };
    if (entry.startsWith('database:')) return { label: 'a database' };
    if (entry.startsWith('bucket:')) return { label: 'stored files' };
    if (entry.startsWith('connection:')) return { label: 'a connected account' };
    return appOf(head);
}

/** What the agent uses, once each, apps by name. */
export function whatItUses(agent: JsonObject | undefined): Used[] {
    const seen = new Set<string>();
    return list(agent, 'tools')
        .map(usedOf)
        .filter((u): u is Used => !!u && !seen.has(u.label) && !!seen.add(u.label));
}

/** "Web search and web pages", or that it uses nothing beyond what it's told. */
export function usesLine(used: readonly Used[]): string {
    const line = listOf(used.map((u) => u.label));
    return line ? line.charAt(0).toUpperCase() + line.slice(1) : 'Nothing beyond what it’s sent';
}
