// What the Channels page works out from its data: which workspace a channel
// sits in, what's unread, who wrote a message, which agent a member is, and
// how a workspace's name becomes its tile.
import type { AgentChoice, AgentHue, Channel, ChannelAuthor, ChannelMember, ChannelWorkspace } from './types';

/** You (the account) as a channel shows you: in every channel, though never a member row. */
export const YOU_ID = 'you';
/** NoClick itself: the room's own notes, and its answers to your commands. */
export const NOCLICK_ID = 'noclick';

export const YOU: ChannelMember = { id: YOU_ID, kind: 'you', name: 'You' };

const HUES: AgentHue[] = ['indigo', 'violet', 'teal', 'sky', 'emerald', 'rose', 'orange'];

/** An agent keeps one colour everywhere, read from its id. */
export function hueFor(id: string): AgentHue {
    let hash = 0;
    for (const ch of id) hash = (hash * 31 + ch.charCodeAt(0)) >>> 0;
    return HUES[hash % HUES.length];
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

/** Who wrote a message, drawn as a member: you, a member of the room, or (one who left) the name it posted under. */
export function authorMember(author: ChannelAuthor, members: ChannelMember[]): ChannelMember | null {
    switch (author.type) {
        case 'account':
            return YOU;
        case 'agent':
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
