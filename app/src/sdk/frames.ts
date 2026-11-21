// The platform's frames a screen follows (src/sdk/live.ts): each says what moved in the account, never what it is now,
// so the screen reads that again through the platform client.

/** One of the account's agents moved: the pages listing agents read their states again. */
export interface PlatformAgentEvent {
    agent_id: string;
    /** turn: a turn of its started, moved on (waiting on a person included) or settled; step: it reported a tool call;
     *  tool_servers: one conversation's tool servers moved; wakeups: a loop of one conversation was set, came round,
     *  changed or stopped; definition: it was changed (renamed, say); session: everyone talking to it now shares
     *  another conversation, cleared or resumed. */
    change: 'turn' | 'step' | 'tool_servers' | 'wakeups' | 'definition' | 'session';
    /** The conversation a tool_servers or wakeups change is about, and a turn's, when it is one of the account's own
     *  threads. */
    conversation?: string | null;
}

/** Something in the account's own channels moved (a message posted, its reactions, a channel's members or settings, a
 *  workspace): the pages showing it read it again. */
export interface PlatformChannelEvent {
    /** message: the main timeline moved (new messages, or who's busy); thread: one thread (thread_id) moved, a reply
     *  posted (message_id) or your read point or following in it; reaction: one message's reactions; pin: a message
     *  pinned or unpinned; bookmark: the channel's bookmarks; channel: the channel itself (members, topic, mode, status,
     *  deleted or restored); workspace: a workspace and its channels; sections: your own sections of a workspace's
     *  channels (workspace_id; none: those in no workspace). */
    kind: 'message' | 'thread' | 'reaction' | 'pin' | 'bookmark' | 'channel' | 'workspace' | 'sections';
    channel_id?: string | null;
    workspace_id?: string | null;
    /** The message whose reactions or pin changed, or the reply posted in a thread. */
    message_id?: string | null;
    /** The thread (its first message's id) the change is in. */
    thread_id?: string | null;
}

/** Someone is typing in a channel (or DM) the reader reads, or stopped, never kept: a page shows it until `typing` is
 *  false, or a few seconds pass without another. */
export interface PlatformChannelTypingEvent {
    channel_id: string;
    workspace_id?: string | null;
    /** Who: a person's user id in the account, or `account` for its owner. */
    user_id: string;
    /** Their name as the channel shows it. */
    name: string;
    typing: boolean;
}

/** One of the account's coding agents moved: the pages showing coding agents read them again. */
export interface PlatformCodingAgentEvent {
    /** The agent that moved; none when any of the account's may have (its spending cap reached, its balance run out). */
    agent_id?: string | null;
    /** turn: a turn of its started, moved on or settled; place: where it runs came up or went away; pause: a limit or
     *  pause now holds it or no longer does; definition: it was made, changed or deleted. */
    change: 'turn' | 'place' | 'pause' | 'definition';
}

/** The account was charged, or given a charge back: one frame a burst of charges, naming nothing about them (no
 *  amount, service or charge). A page showing what the account spent reads it again. */
export interface PlatformUsageEvent {
    /** When it was said; none where the host doesn't know. */
    at: string | null;
}

/** A platform resource the account owns moved (a domain registered, a deployment went ready, a repo's branch moved, a
 *  call answered or ended, a call held for approval or the approval answered, and so on): the pages showing it read
 *  it again. */
export interface PlatformResourceEvent {
    /** The resource's object type in the platform API. */
    kind:
        | 'domain'
        | 'deployment'
        | 'repo'
        | 'mcp_server'
        | 'live_session'
        | 'phone_call'
        | 'workflow'
        | 'durable_object_class'
        | 'skill'
        | 'memory'
        | 'machine'
        | 'sandbox'
        | 'agent_move'
        | 'connection'
        | 'plan_usage'
        | 'workspace_resource'
        | 'space_question'
        | 'trigger'
        | 'approval'
        | 'browser';
    id: string;
    /** Its status as its API view now gives it (one that has none: active); none once it's gone. */
    status?: string | null;
    /** What it belongs to, when it belongs to something (a deployment's or a live session's app, a call's number, a
     *  trigger's agent). */
    parent_id?: string | null;
    /** A workflow's graph version now (GET /v1/workflows/{id}/graph). */
    version?: number | null;
}
