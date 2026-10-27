// What the Channels page works out from its data: which workspace a channel
// sits in, what's unread, who wrote a message, which agent a member is, and
// how a workspace's name becomes its tile.
import type { AgentChoice, AgentHue, Channel, ChannelAuthor, ChannelMember, ChannelWorkspace } from './types';

/** You (the account) as a channel shows you: in every channel, though never a member row. */
export const YOU_ID = 'you';
/** NoClick itself: the room's own notes, and its answers to your commands. */
export const NOCLICK_ID = 'noclick';

export const YOU: ChannelMember = { id: YOU_ID, kind: 'you', name: 'You' };

/** The agents' colours, every pair of which stays apart in both themes and for colour-blind readers (avatars.tsx has
 *  the steps and the validator's verdict). */
export const AGENT_HUES: AgentHue[] = ['sky', 'violet', 'pink', 'amber', 'emerald'];

/** An agent's own colour, read from its id: the one it wears wherever no other agent beside it already does. */
export function hueFor(id: string): AgentHue {
    let hash = 0;
    for (const ch of id) hash = (hash * 31 + ch.charCodeAt(0)) >>> 0;
    return AGENT_HUES[hash % AGENT_HUES.length];
}

/** A name's words as a person reads them ("Paws & Pace" is two). */
function wordsOf(name: string): string[] {
    return name.split(/\s+/).filter((w) => /[\p{L}\p{N}]/u.test(w));
}

const initial = (word = '') => (Array.from(word.replace(/^[^\p{L}\p{N}]+/u, ''))[0] ?? '?').toUpperCase();

/** Words `a` and `b` share at their start (`end`: at their end), at most `limit`. */
function sharedWords(a: readonly string[], b: readonly string[], limit: number, end = false): number {
    let n = 0;
    while (n < limit && n < b.length && a[end ? a.length - 1 - n : n] === b[end ? b.length - 1 - n : n]) n++;
    return n;
}

/** The letters each name wears beside the others: where names share words ("Paws & Pace Austin Events Researcher",
 *  "Paws & Pace Newsletter Writer"), the last word of what sets it apart (R, W); else its first letter. Two that would
 *  still match take the initials of their last two such words (ER, NW), or a single word's first two letters. */
export function initialsAmong(names: readonly string[]): string[] {
    const words = names.map(wordsOf);
    const lower = words.map((ws) => ws.map((w) => w.toLowerCase()));
    const apart = words.map((ws, i) => {
        const others = lower.filter((_, j) => j !== i);
        const start = Math.max(0, ...others.map((o) => sharedWords(lower[i], o, ws.length - 1)));
        const end = Math.max(0, ...others.map((o) => sharedWords(lower[i], o, ws.length - 1 - start, true)));
        return ws.slice(start, ws.length - end);
    });
    const one = apart.map((ws, i) => (ws.length < words[i].length ? initial(ws.at(-1)) : initial(names[i])));
    return one.map((letters, i) => {
        if (!one.some((other, j) => j !== i && other === letters)) return letters;
        const ws = apart[i];
        return ws.length > 1 ? initial(ws.at(-2)) + initial(ws.at(-1)) : Array.from(ws[0] ?? names[i]).slice(0, 2).join('');
    });
}

/** A room's members as it draws them: each agent in its own colour unless an agent before it in the room wears that
 *  one, then in the first one free, and with the letters that tell it from the room's other agents. */
export function seatMembers(members: readonly ChannelMember[]): ChannelMember[] {
    const agents = members.filter((m) => m.kind === 'agent');
    const letters = initialsAmong(agents.map((a) => a.name));
    const worn = new Set<AgentHue>();
    const seated = new Map(
        agents.map((agent, i) => {
            const own = hueFor(agentKey(agent) ?? agent.id);
            const hue = worn.has(own) ? (AGENT_HUES.find((h) => !worn.has(h)) ?? own) : own;
            worn.add(hue);
            return [agent.id, { ...agent, hue, initials: letters[i] }];
        })
    );
    return members.map((m) => seated.get(m.id) ?? m);
}

/** Who answers in a channel: agents read everything, or wait to be @-mentioned. `named: false` says it of "They" (or
 *  "It"), where the agents are listed just before it. */
export function modeLine(mode: Channel['mode'], agents: Pick<ChannelMember, 'name'>[], { named = true }: { named?: boolean } = {}): string {
    const one = agents.length === 1;
    const listed = agents.length ? new Intl.ListFormat('en', { type: 'conjunction' }).format(agents.map((a) => a.name)) : 'Agents';
    const who = named ? listed : one ? 'It' : 'They';
    return mode === 'all' ? `${who} ${one ? 'reads' : 'read'} every message` : `${who} ${one ? 'answers' : 'answer'} when @-mentioned`;
}

/** A workspace's open channels, oldest first, as a sidebar lists them. */
export function channelsIn(workspace: ChannelWorkspace, channels: Channel[]): Channel[] {
    return channels.filter((c) => c.workspaceId === workspace.id).sort((a, b) => a.createdAt.localeCompare(b.createdAt));
}

/** A workspace's channel by id, else its first. */
export function channelIn(workspace: ChannelWorkspace, channels: Channel[], channelId?: string | null): Channel | null {
    const mine = channelsIn(workspace, channels);
    return mine.find((c) => c.id === channelId) ?? mine[0] ?? null;
}

export function unreadIn(workspace: ChannelWorkspace, channels: Channel[]): number {
    return channelsIn(workspace, channels).reduce((sum, c) => sum + c.unread, 0);
}

/** An agent posting for you: the account's post an agent made (your assistant setting a channel going), never yours. */
export function postedForYou(author: ChannelAuthor): boolean {
    return author.type === 'account' && !!author.id;
}

/** NoClick's own name in a channel: its notes there, and your assistant's posts for you, wear its mark. */
export const NOCLICK_NAME = 'NoClick';

/** Whether NoClick wrote it: a note of its own in the room, or its assistant posting for you. */
export function byNoClick(author: ChannelAuthor): boolean {
    return author.type === 'system' || (postedForYou(author) && author.name === NOCLICK_NAME);
}

/** Who wrote a message, drawn as a member: you, a member of the room, or (one who left, or one posting for you) the
 *  name it posted under. */
export function authorMember(author: ChannelAuthor, members: ChannelMember[]): ChannelMember | null {
    switch (author.type) {
        case 'account':
        case 'agent':
            if (author.type === 'account' && !postedForYou(author)) return YOU;
            return members.find((m) => m.agentId === author.id) ?? { id: `agent:${author.id}`, kind: 'agent', name: author.name, hue: hueFor(author.id ?? author.name) };
        case 'workflow_agent':
            return members.find((m) => m.id === author.id) ?? { id: `workflow_agent:${author.id}`, kind: 'agent', name: author.name, hue: hueFor(author.id ?? author.name) };
        case 'a2a':
            return members.find((m) => m.id === author.id) ?? { id: `a2a:${author.id}`, kind: 'outside', name: author.name };
        case 'user':
            return members.find((m) => m.kind === 'human' && m.name === author.name) ?? { id: `user:${author.id}`, kind: 'human', name: author.name };
        default:
            return null;
    }
}

/** The agents an agent's message hands the work to: those it @-mentions. */
export function handoffsOf(author: ChannelAuthor, mentions: string[], members: ChannelMember[]): ChannelMember[] {
    if (author.type !== 'agent' && author.type !== 'workflow_agent' && author.type !== 'a2a') return [];
    return mentions.map((name) => members.find((m) => m.name === name && m.kind !== 'you')).filter((m): m is ChannelMember => !!m);
}

/** An agent in your Automations: its workflow's agent node. */
export function automationKey(workflowId: string, nodeId: string): string {
    return `${workflowId}:${nodeId}`;
}

/** Which agent a member is, as an `AgentChoice` names it: a platform agent's id, an automation's `automationKey`. */
export function agentKey(member: Pick<ChannelMember, 'agentId' | 'workflowId' | 'nodeId'>): string | undefined {
    if (member.agentId) return member.agentId;
    return member.workflowId && member.nodeId ? automationKey(member.workflowId, member.nodeId) : undefined;
}

/** Your agents as the pickers group them: those in your Automations, then the platform's. */
export function agentGroups(agents: AgentChoice[]): { label: string; agents: AgentChoice[] }[] {
    return [
        { label: 'Your agents', agents: agents.filter((a) => a.source === 'automation') },
        { label: 'Platform agents', agents: agents.filter((a) => a.source === 'platform') },
    ].filter((group) => group.agents.length > 0);
}

/** Slack's rule: the first letters of the first two words ("HH"), or one word's first letter ("L"). */
export function initialsFor(name: string): string {
    const words = name.trim().split(/\s+/).filter(Boolean);
    const first = (word = '') => Array.from(word)[0] ?? '';
    return (words.length > 1 ? first(words[0]) + first(words[1]) : first(words[0])).toUpperCase() || '?';
}

/** A channel name as Slack keeps them: lowercase words joined by dashes. */
export function channelSlug(name: string): string {
    return name
        .trim()
        .toLowerCase()
        .replace(/^#/, '')
        .replace(/[^a-z0-9_-]+/g, '-')
        .replace(/-{2,}/g, '-')
        .replace(/^-|-$/g, '')
        .slice(0, 80);
}
