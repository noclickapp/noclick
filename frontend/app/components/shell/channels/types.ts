// Channels: rooms where your agents talk to each other (and you), in
// workspaces as in Slack. Shapes follow the platform API's channels and
// workspaces (members, mentions-or-all mode, author {type, id, name}, files,
// reactions), as the page draws them.

/** An agent's colour: its avatar, and how its name reads when @-mentioned. */
export type AgentHue = 'sky' | 'violet' | 'pink' | 'amber' | 'emerald';

/** Who is in a channel: you (the account, never a member row), an agent, a person or an agent from elsewhere (A2A). */
export interface ChannelMember {
    id: string;
    kind: 'you' | 'agent' | 'human' | 'outside';
    name: string;
    /** A platform agent member's agent. */
    agentId?: string;
    /** An agent from your Automations: its workflow and agent node, and the workflow's name. */
    workflowId?: string;
    nodeId?: string;
    workflowName?: string;
    /** The agent's harness, as its node type (agent:claude-code, …). */
    markType?: string;
    hue?: AgentHue;
    /** Its avatar's letters, told apart from the room's other agents (`seatMembers`); else its name's first letter. */
    initials?: string;
    /** A platform agent's job in a line, as its agent says it. */
    role?: string;
    /** Taking a turn right now. */
    busy?: boolean;
}

/** Who posted: the account, a person, an agent (a platform agent, or one from your Automations), an agent from elsewhere, NoClick, or an app's event. */
export interface ChannelAuthor {
    type: 'account' | 'user' | 'agent' | 'workflow_agent' | 'a2a' | 'system' | 'app';
    /** An agent's agent id, a person's user id, an Automations agent's or an outside agent's member id; on the
     *  account's post, the agent that posted it for you (null: you did). */
    id: string | null;
    name: string;
}

/** A file on a message: an image shows, a voice clip plays, anything else is a card. */
export interface ChannelAttachment {
    id: string;
    kind: 'image' | 'audio' | 'video' | 'file';
    name: string;
    mimeType: string;
    sizeBytes: number;
    /** Where it opens or plays. */
    url?: string;
    /** A recorded voice clip, with its length and loudness over time (0–1), drawn as its waveform. */
    voice?: boolean;
    durationMs?: number;
    peaks?: number[];
}

/** One emoji on a message: how many, whether you're among them, and who. */
export interface ChannelReaction {
    emoji: string;
    count: number;
    mine: boolean;
    names: string[];
}

export interface ChannelMessage {
    id: string;
    author: ChannelAuthor;
    /** Markdown: bold, italic, strike, code, quotes, lists and links. */
    text: string;
    /** When it was posted (ISO). */
    at: string;
    attachments: ChannelAttachment[];
    reactions: ChannelReaction[];
    /** The members it @-mentions, by name. */
    mentions: string[];
    /** NoClick answering a command: only you see it, and you can dismiss it. */
    ephemeral?: boolean;
    /** Yours, on its way. */
    pending?: boolean;
}

export type ChannelMode = 'mentions' | 'all';

/** A schedule that posts its message in the channel as you: a cron expression on its clock, and when it next posts. */
export interface ChannelSchedule {
    id: string;
    cron: string;
    tz: string | null;
    message: string;
    /** ISO; null while it's paused. */
    nextRun: string | null;
}

export interface Channel {
    id: string;
    name: string;
    topic: string;
    /** Agents answer only when @-mentioned, or every message a person posts. */
    mode: ChannelMode;
    /** Halted: a hard stop tripped, and agents wait until a person posts. */
    status: 'open' | 'halted' | 'closed';
    haltReason: string | null;
    /** The workspace it lives in; null for one in your own channels. */
    workspaceId: string | null;
    members: ChannelMember[];
    /** Messages since you last read it. */
    unread: number;
    createdAt: string;
}

/** A company, a client or a community: its own agents and channels. Yours is the one that holds channels in no workspace. */
export interface ChannelWorkspace {
    /** Null for your own channels. */
    id: string | null;
    name: string;
    /** The logo someone uploaded; without one the workspace shows its initials. */
    logoUrl?: string;
    /** The agents a workspace's channels can hold (they join the workspace first); every agent for your own. */
    agentIds?: string[];
}

interface AgentChoiceBase {
    /** Which agent it is, as `agentKey` names a member: a platform agent's id, an automation's `workflowId:nodeId`. */
    id: string;
    name: string;
    markType?: string;
    /** Its job in a line, where its agent says one. */
    role?: string;
}

/** One of your agents, to add to a channel: one made on the platform, or one in your Automations (an agent node of a workflow). */
export type AgentChoice = (AgentChoiceBase & { source: 'platform' }) | (AgentChoiceBase & { source: 'automation'; workflowId: string; nodeId: string; workflowName: string });
