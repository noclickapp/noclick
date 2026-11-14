// Channels: rooms where your agents talk to each other (and you), in
// workspaces as in Slack. Shapes follow the platform API's channels and
// workspaces (members, mentions-or-all mode, author {type, id, name}, files,
// reactions), as the page draws them.

/** An agent's colour: its avatar, and how its name reads when @-mentioned. */
export type AgentHue = 'sky' | 'violet' | 'pink' | 'fuchsia' | 'emerald' | 'blue' | 'purple' | 'teal';

/** Who is in a channel: you (the account, never a member row), an agent, a person or an agent from elsewhere (A2A). */
export interface ChannelMember {
    id: string;
    kind: 'you' | 'agent' | 'human' | 'outside';
    name: string;
    /** A platform agent member's agent. */
    agentId?: string;
    /** A person's user id (in a space, the one their DM and role name them by). */
    userId?: string;
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
    /** Taking a turn right now: since when (ISO), and the thread it answers in (none: the channel itself). */
    busy?: boolean;
    busySince?: string;
    busyThread?: string;
    /** Its triggers are paused: it wakes only when someone messages it. */
    paused?: boolean;
    /** A NoClick, the account's own or a space's, as the platform flags it: drawn with NoClick's mark and named as
     *  NoClick, never by the name it was made with. */
    noclick?: boolean;
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
    /** Its thread, once anyone replied: how many, when the last came, who (newest first), and what you haven't read. */
    thread?: ChannelThreadSummary;
    /** A reply: the message whose thread it's in. */
    threadId?: string | null;
    /** A reply sent to the channel too. */
    alsoInChannel?: boolean;
    pinned?: { by: ChannelAuthor; at: string | null } | null;
    /** NoClick's quiet line about the channel itself: someone pinned a message. */
    event?: { type: 'pinned'; messageId: string };
    /** Who joined or left, as the channel keeps it: a quiet line as Slack draws joins, a run of them one line. */
    membership?: ChannelMembership;
    /** An agent's question with answers to tap: a tap posts its `reply` as yours. */
    question?: { options: ChannelQuestionOption[] };
}

/** One answer to an agent's question: what its button says, and what a tap posts as you. */
export interface ChannelQuestionOption {
    label: string;
    reply: string;
}

/** `by` added or removed `members`. `by` is null when NoClick did it (a member left the space, its automation's step
 *  went), and `self` when the members came or went by themselves (a person joining by posting). */
export interface ChannelMembership {
    action: 'added' | 'removed';
    by: ChannelAuthor | null;
    self: boolean;
    /** Each by its channel member id, and its name as the channel knows it. */
    members: { id: string; name: string }[];
}

export interface ChannelThreadSummary {
    count: number;
    lastAt: string | null;
    authors: ChannelAuthor[];
    /** Replies since you last read it, counted for threads you follow. */
    unread: number;
    following: boolean;
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
    /** A channel, or a DM between two people. */
    kind?: 'channel' | 'dm';
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
    /** Messages since you last read it (none while you've muted it). */
    unread: number;
    /** Yours alone: starred, it leads your list; muted, it's never unread or bold for you. */
    starred?: boolean;
    muted?: boolean;
    /** Messages since you last read it that @-mention you (while muted, all it counts as unread); unset where the
     *  platform doesn't count them yet. */
    mentions?: number;
    /** A person in a space's channel: whether they're in it (they star, mute and leave only one they're in). The
     *  account reads every one of its own, so it's never set for it. */
    joined?: boolean;
    createdAt: string;
    /** A DM's newest message, for its row in a list. */
    lastMessage?: { text: string; at: string; author: ChannelAuthor } | null;
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
    /** A platform agent's harness and model ids (`sdk`; null model: the harness's default). */
    harness?: string;
    model?: string | null;
    /** Its model and harness as a picker names them ("Sonnet 5.5 on Claude Code"), once read. */
    modelLine?: string;
    /** A NoClick, the account's own or a space's, as the platform flags it: never offered as one of your agents; the
     *  pickers list the one that answers here first, in its mark. */
    noclick?: boolean;
}

/** One of your agents, to add to a channel: one made on the platform, or one in your Automations (an agent node of a workflow). */
export type AgentChoice = (AgentChoiceBase & { source: 'platform' }) | (AgentChoiceBase & { source: 'automation'; workflowId: string; nodeId: string; workflowName: string });

/** A person of the space, to add to a channel: their user id, their name, and a line under it (when they were last on). */
export interface PersonChoice {
    id: string;
    name: string;
    detail?: string | null;
}
