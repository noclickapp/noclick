// The channels transport on the platform API, through the TypeScript SDK: the account's own workspaces and channels
// (not its users'), or one space someone joined from another account. Every read maps the platform's objects into
// the page's shapes; every failure becomes the sentence to show. Live changes are whatever the host hands `deliver`
// (the account's changes, as it follows them); without any, the page's own re-reads keep it current. An agent from
// your Automations a channel already holds reads like any member; only the platform's agents are offered to add.
import { ChannelNameTaken, type ChannelChange, type ChannelHistoryPage, type ChannelsTransport, type VoiceClipInfo } from './transport';
import { automationKey, hueFor } from './model';
import type { SendTyping } from './typing';
import type { AgentChoice, Channel, ChannelAttachment, ChannelAuthor, ChannelMember, ChannelMembership, ChannelMessage, ChannelReaction, ChannelSchedule, ChannelWorkspace } from './types';
import { agentMarkType } from '@/ui/primitives';
import type { PlatformChannelEvent, PlatformChannelTypingEvent } from '@/sdk/frames';
import { errorText } from '@/screens/console/pages/resources/shared';
import { heldCallOf } from '@/sdk/held';
import { needOf } from '@/lib/agentNeeds';
import { turnAsksOf } from '@/lib/turnAsks';
import {
    Agent,
    Channel as PlatformChannel,
    Conflict,
    NO_USER,
    TrashItem,
    User,
    Workspace,
    type AgentTrigger,
    type ChannelAttachment as PlatformAttachment,
    type ChannelMember as PlatformMember,
    type ChannelMessage as PlatformMessage,
    type ChannelReaction as PlatformReaction,
    type NoClick,
} from 'noclick';

/** One page holds every channel and workspace the page lists. */
const LIST_LIMIT = 100;
/** Messages per page of history. */
const HISTORY_LIMIT = 50;

const AUTHORS = new Set<ChannelAuthor['type']>(['account', 'user', 'agent', 'workflow_agent', 'a2a', 'system', 'app']);

export function memberOf(member: PlatformMember): ChannelMember {
    const busy = member.raw.busy === true;
    const turn = busy
        ? { ...(typeof member.raw.busy_since === 'string' ? { busySince: member.raw.busy_since } : {}), ...(typeof member.raw.busy_thread_id === 'string' ? { busyThread: member.raw.busy_thread_id } : {}) }
        : {};
    if (member.type === 'agent') {
        // The names its agent went by before a rename: an @mention of one still names it.
        const former = Array.isArray(member.raw.former_names) ? member.raw.former_names.filter((n): n is string => typeof n === 'string') : [];
        return { id: member.id, kind: 'agent', name: member.name ?? 'agent', agentId: member.agentId ?? undefined, hue: hueFor(member.agentId ?? member.id), busy, ...turn, ...(member.raw.noclick === true ? { noclick: true } : {}), ...(former.length ? { formerNames: former } : {}) };
    }
    if (member.type === 'workflow_agent') {
        const workflowId = String(member.raw.workflow_id);
        const nodeId = String(member.raw.node_id);
        const workflowName = typeof member.raw.workflow_name === 'string' ? member.raw.workflow_name : undefined;
        return { id: member.id, kind: 'agent', name: member.name ?? 'agent', workflowId, nodeId, workflowName, hue: hueFor(automationKey(workflowId, nodeId)), busy, ...turn };
    }
    return { id: member.id, kind: member.type === 'a2a' ? 'outside' : 'human', name: member.name ?? member.type ?? 'member', ...(member.userId ? { userId: member.userId } : {}), busy };
}

/**
 * Whose eyes a channel is read through. Your own account's: you are the account. A space you joined in another
 * account (`me` your user id there): you are that user, and the account is its owner, someone else.
 */
export interface Perspective {
    me: string;
    /** The account's owner, as their posts are signed. */
    ownerName: string;
}

/** An author as you read it: the account's posts are yours in your own account, the owner's in one you joined. */
export function seenBy(author: ChannelAuthor, who?: Perspective): ChannelAuthor {
    if (!who) return author;
    if (author.type === 'user' && author.id === who.me) return { type: 'account', id: null, name: 'You' };
    if (author.type === 'account' && !author.id) return { type: 'user', id: 'account', name: author.name || who.ownerName };
    return author;
}

export function channelOf(channel: PlatformChannel, who?: Perspective): Channel {
    const status = channel.status;
    return {
        id: channel.id,
        kind: channel.raw.kind === 'dm' ? 'dm' : 'channel',
        name: channel.name,
        topic: channel.topic,
        mode: channel.mode === 'all' ? 'all' : 'mentions',
        status: status === 'halted' || status === 'closed' ? status : 'open',
        haltReason: channel.haltReason,
        workspaceId: channel.workspaceId,
        // You are never one of its member rows: the page adds you.
        members: channel.members.filter((m) => !who || m.userId !== who.me).map(memberOf),
        unread: channel.unreadCount,
        starred: channel.starred,
        muted: channel.muted,
        ...(typeof channel.raw.mention_count === 'number' ? { mentions: channel.raw.mention_count } : {}),
        ...(who ? { joined: channel.members.some((m) => m.userId === who.me) } : {}),
        createdAt: channel.createdAt?.toISOString() ?? '',
        lastMessage: lastMessageOf(channel.raw.last_message, who),
    };
}

function lastMessageOf(raw: unknown, who?: Perspective): Channel['lastMessage'] {
    if (!raw || typeof raw !== 'object') return null;
    const m = raw as Raw;
    return { text: rawText(m.text) ?? '', at: rawText(m.created_at) ?? '', author: seenBy(authorOf((m.author as Raw | undefined) ?? {}), who) };
}

export function workspaceOf(workspace: Workspace): ChannelWorkspace {
    return {
        id: workspace.id,
        name: workspace.name,
        logoUrl: workspace.logoUrl ?? undefined,
        agentIds: workspace.members.flatMap((m) => (m.type === 'agent' && m.agentId ? [m.agentId] : [])),
    };
}

export function agentOf(agent: Agent): AgentChoice {
    const role = typeof agent.raw.role === 'string' && agent.raw.role ? agent.raw.role : undefined;
    const harness = agent.harness ?? 'sdk';
    return { id: agent.id, name: agent.name, markType: agentMarkType(harness.replace('_', '-')), harness, model: agent.model, ...(role ? { role } : {}), ...(agent.noclick ? { noclick: true } : {}) };
}

export function attachmentOf(file: PlatformAttachment): ChannelAttachment {
    return {
        // The SDK's Attachment also covers a file as a turn's history shows it; a channel's has both.
        id: file.id ?? file.url,
        kind: file.kind,
        name: file.name,
        mimeType: file.mimeType,
        sizeBytes: file.sizeBytes ?? 0,
        url: file.url || undefined,
        voice: file.voice,
        durationMs: file.durationMs ?? undefined,
        peaks: file.peaks ?? undefined,
    };
}

/** Your reaction is yours (the account's, or your user's in a space you joined); everyone else is named as they reacted. */
export function reactionOf(reaction: PlatformReaction, who?: Perspective): ChannelReaction {
    const by = reaction.by.map((b) => seenBy(authorOf(b), who));
    return {
        emoji: reaction.emoji,
        count: reaction.count,
        mine: by.some((b) => b.type === 'account' && !b.id),
        names: by.map((b) => (b.type === 'account' && !b.id ? 'You' : b.name || 'someone')),
    };
}

type Raw = Record<string, unknown>;
const rawText = (v: unknown) => (typeof v === 'string' ? v : null);
const rawCount = (v: unknown) => (typeof v === 'number' && Number.isFinite(v) ? v : 0);

function authorOf(raw: { type?: unknown; id?: unknown; name?: unknown }): ChannelAuthor {
    const type = AUTHORS.has(raw.type as ChannelAuthor['type']) ? (raw.type as ChannelAuthor['type']) : 'system';
    return { type, id: rawText(raw.id), name: rawText(raw.name) ?? '' };
}

/** Who joined or left, from a system message's `membership` event; you by "You" where you're among them. */
function membershipOf(event: Raw, who?: Perspective): ChannelMembership {
    const members = Array.isArray(event.members) ? (event.members as Raw[]) : [];
    const by = event.by && typeof event.by === 'object' ? (event.by as Raw) : null;
    const isBy = (m: Raw) => !!by && ((by.type === 'user' && by.id === m.user_id) || (by.type === 'agent' && by.id === m.agent_id));
    return {
        action: event.action === 'removed' ? 'removed' : 'added',
        // The account signs these "owner": you in your own account, its owner by name in one you joined.
        by: by ? seenBy(authorOf(by.type === 'account' ? { ...by, name: '' } : by), who) : null,
        self: members.length > 0 && members.every(isBy),
        members: members.map((m) => ({ id: String(m.id), name: who && m.user_id === who.me ? 'You' : (rawText(m.name) ?? 'Someone') })),
    };
}

/** A message's thread and pin, as the platform keeps them beside it (Work's channels), what a system message says
 *  of the channel itself (a pin, who joined), and an agent's question's answers to tap. */
/** An agent's question's answers, from its message's `question` event: each a label and the reply a tap posts. */
function questionOf(event: Raw): NonNullable<ChannelMessage['question']> {
    const options = Array.isArray(event.options) ? (event.options as Raw[]) : [];
    return { options: options.flatMap((o) => (typeof o.label === 'string' && typeof o.reply === 'string' ? [{ label: o.label, reply: o.reply }] : [])) };
}

/** What an agent still needs, from its message's `connect` event: each of its apps' accounts, and its model. */
function asksOf(event: Raw): NonNullable<ChannelMessage['asks']> {
    return { needs: (Array.isArray(event.needs) ? event.needs : []).flatMap((n) => needOf(n) ?? []) };
}

function threadOf(raw: Raw, who?: Perspective): Pick<ChannelMessage, 'thread' | 'threadId' | 'alsoInChannel' | 'pinned' | 'event' | 'membership' | 'question' | 'asks' | 'turnAsks' | 'automation'> {
    const count = rawCount(raw.reply_count);
    const pinned = raw.pinned && typeof raw.pinned === 'object' ? (raw.pinned as Raw) : null;
    const event = raw.event && typeof raw.event === 'object' ? (raw.event as Raw) : null;
    return {
        ...(count
            ? {
                  thread: {
                      count,
                      lastAt: rawText(raw.last_reply_at),
                      authors: (Array.isArray(raw.reply_authors) ? (raw.reply_authors as Raw[]) : []).map((a) => seenBy(authorOf(a), who)),
                      unread: rawCount(raw.unread_replies),
                      following: raw.following === true,
                  },
              }
            : {}),
        threadId: rawText(raw.thread_id),
        alsoInChannel: raw.also_in_channel === true,
        pinned: pinned ? { by: seenBy(authorOf((pinned.by as Raw | undefined) ?? {}), who), at: rawText(pinned.at) } : null,
        ...(event?.type === 'pinned' && typeof event.message_id === 'string' ? { event: { type: 'pinned' as const, messageId: event.message_id } } : {}),
        ...(event?.type === 'membership' ? { membership: membershipOf(event, who) } : {}),
        ...(event?.type === 'question' ? { question: questionOf(event) } : {}),
        ...(event?.type === 'connect' ? { asks: asksOf(event) } : {}),
        ...(event?.type === 'asks' ? { turnAsks: turnAsksOf(event, (by) => seenBy(authorOf(by), who)) ?? undefined } : {}),
        ...(event?.type === 'automation' ? { automation: { workflowId: rawText(event.workflow_id) } } : {}),
    };
}

export function messageOf(message: PlatformMessage, who?: Perspective): ChannelMessage {
    return {
        id: message.id,
        author: seenBy(authorOf(message.author), who),
        text: message.text,
        at: typeof message.raw.created_at === 'string' ? message.raw.created_at : (message.createdAt?.toISOString() ?? new Date(0).toISOString()),
        attachments: message.attachments.map(attachmentOf),
        reactions: message.reactions.map((r) => reactionOf(r, who)),
        mentions: message.mentions.filter((m): m is string => typeof m === 'string'),
        ...threadOf(message.raw, who),
    };
}

/** A channel's trigger as a schedule that posts in it; a channel's triggers are all schedules (`Cron`s). */
export function scheduleOf(trigger: AgentTrigger): ChannelSchedule[] {
    const { cron, tz, message } = trigger.spec;
    if (trigger.kind !== 'cron' || typeof cron !== 'string') return [];
    return [{ id: trigger.id, cron, tz: typeof tz === 'string' ? tz : null, message: typeof message === 'string' ? message : '', nextRun: trigger.nextRun?.toISOString() ?? null }];
}

export function changeOf(frame: PlatformChannelEvent): ChannelChange {
    return {
        kind: frame.kind,
        channelId: frame.channel_id ?? undefined,
        workspaceId: frame.workspace_id ?? undefined,
        messageId: frame.message_id ?? undefined,
        threadId: (frame as { thread_id?: string | null }).thread_id ?? undefined,
    };
}

/** Someone typing in a channel, or stopping, as a change. */
export function typingChangeOf(frame: PlatformChannelTypingEvent): ChannelChange {
    return {
        kind: 'typing',
        channelId: frame.channel_id,
        workspaceId: frame.workspace_id ?? undefined,
        typist: { id: frame.user_id, name: frame.name, typing: frame.typing },
    };
}

/** Says you're typing through the API (`Channel.typing`). */
export function sdkTyping(client: NoClick): SendTyping {
    return (channelId, typing) => PlatformChannel.fromId(channelId, { client, user: null }).typing(typing);
}

/** Run a platform call; its failure becomes an Error whose message is the sentence to show, but for a call held for
 *  the account's owner, which stays itself for the screen to follow (src/sdk/held.ts). */
async function said<T>(call: () => Promise<T>): Promise<T> {
    try {
        return await call();
    } catch (e) {
        if (heldCallOf(e)) throw e;
        throw new Error(errorText(e));
    }
}

export interface PlatformTransport extends ChannelsTransport {
    /** Hand a change to whoever follows the channels. */
    deliver(change: ChannelChange): void;
}

export interface TransportOptions {
    /** How you say you're typing: through the API (`sdkTyping`), or however the host says it. */
    sendTyping: SendTyping;
    /** One space someone joined from another account, read through their eyes (below). */
    person?: Perspective & { workspaceId: string };
}

/**
 * The account's own channels and workspaces through `client`; or, with `person`, one space someone joined from
 * another account, through their session's client: its channels only, read through their eyes.
 */
export function platformTransport(client: NoClick, { sendTyping, person }: TransportOptions): PlatformTransport {
    const listeners = new Set<(change: ChannelChange) => void>();
    // The agents not yet in `workspace` join it; a personal space's agents are the ones in its channels, never added.
    const joinWorkspace = async (workspace: Workspace, agentIds: string[]) => {
        if (workspace.raw.personal === true) return;
        const inside = new Set(workspace.members.flatMap((m) => (m.agentId ? [m.agentId] : [])));
        for (const id of agentIds.filter((a) => !inside.has(a))) await workspace.add(Agent.fromId(id, { client, user: null }));
    };
    const channel = (id: string) => PlatformChannel.fromId(id, { client, user: null });
    const message = (m: PlatformMessage) => messageOf(m, person);
    const room = (c: PlatformChannel) => channelOf(c, person);
    const read = async (id: string) => room(await PlatformChannel.get(id, { client, user: null }));
    const historyPage = (page: { data: PlatformMessage[]; nextCursor: string | null }): ChannelHistoryPage => ({ messages: page.data.map(message), older: page.nextCursor });
    // An account reads its own (no user's); a person reads what their session reaches.
    const scope = person ? { workspace: person.workspaceId } : { userFilter: NO_USER };

    return {
        deliver: (change) => listeners.forEach((listener) => listener(change)),
        subscribe: (listener) => {
            listeners.add(listener);
            return () => {
                listeners.delete(listener);
            };
        },
        workspaces: () => said(async () => (person ? [] : (await Workspace.listPage({ client, userFilter: NO_USER, status: 'active', limit: LIST_LIMIT })).data.map(workspaceOf))),
        // Open and closed: a closed one stays in its list, read-only.
        channels: () => said(async () => (await PlatformChannel.listPage({ client, ...scope, limit: LIST_LIMIT })).data.map(room)),
        agents: () =>
            said(async () => {
                const platform = await Agent.listPage({ client, ...(person ? {} : { userFilter: NO_USER }), limit: LIST_LIMIT });
                // NoClick's helpers work for it, not you: none is offered for a channel.
                return platform.data.filter((a) => a.status !== 'expired' && !a.helper).map(agentOf);
            }),
        history: (channelId, before) =>
            said(async () => historyPage(await channel(channelId).messagesPage(before ? { before, limit: HISTORY_LIMIT } : { newest: true, limit: HISTORY_LIMIT }))),
        after: (channelId, afterId) => said(async () => (await channel(channelId).messages({ after: afterId, limit: 200 })).map(message)),
        message: (channelId, messageId) => said(async () => message(await channel(channelId).message(messageId))),
        upload: (channelId, file: File, clip?: VoiceClipInfo) =>
            said(async () => attachmentOf(await channel(channelId).upload(file, { name: file.name, mimeType: file.type || undefined, voice: !!clip, peaks: clip?.peaks }))),
        post: (channelId, text, attachmentIds) => said(async () => message(await channel(channelId).post(text, { files: attachmentIds }))),
        react: (channelId, messageId, emoji, on) => said(async () => message(await (on ? channel(channelId).react(messageId, emoji) : channel(channelId).unreact(messageId, emoji)))),
        askConnected: (channelId, messageId, askId) => said(async () => void (await channel(channelId).askConnected(messageId, askId))),
        createWorkspace: (name, logo) =>
            said(async () => {
                const made = await Workspace.create(name, { client, user: null });
                if (logo) await made.setLogo(logo);
                return workspaceOf(made);
            }),
        createChannel: ({ workspaceId, name, topic, agents, people = [] }) =>
            said(async () => {
                const agentIds = agents.map((a) => a.id);
                if (workspaceId) {
                    // A workspace's channel takes its platform agents from the workspace: those not yet in it join it first.
                    const workspace = await Workspace.get(workspaceId, { client, user: null });
                    await joinWorkspace(workspace, agentIds);
                }
                const made = await PlatformChannel.create(name, {
                    client,
                    user: null,
                    workspace: workspaceId ?? undefined,
                    topic: topic || undefined,
                    // Agents in a new channel answer every message; mention-only is only a channel made that way before.
                    mode: 'all',
                    // A space's people by their user ids; the personal space holds none.
                    members: [...agentIds.map((agentId) => ({ agentId })), ...(workspaceId ? people.map((id) => User.fromId(id, { client })) : [])],
                });
                return room(made);
            }),
        updateChannel: (channelId, changes) => said(async () => room(await channel(channelId).update(changes))),
        schedules: (channelId) => said(async () => (await channel(channelId).triggers()).flatMap(scheduleOf)),
        addAgent: (room, agent) =>
            said(async () => {
                if (room.workspaceId) await joinWorkspace(await Workspace.get(room.workspaceId, { client, user: null }), [agent.id]);
                await channel(room.id).add({ agentId: agent.id });
                return read(room.id);
            }),
        removeMember: (channelId, memberId) =>
            said(async () => {
                await channel(channelId).remove(memberId);
                return read(channelId);
            }),
        close: (channelId) => said(async () => void (await channel(channelId).close())),
        reopen: async (channelId, name) => {
            try {
                return room(await channel(channelId).reopen({ name }));
            } catch (e) {
                throw e instanceof Conflict ? new ChannelNameTaken(errorText(e)) : new Error(errorText(e));
            }
        },
        setPreference: (channelId, preference, on) =>
            said(async () => {
                const c = channel(channelId);
                return room(await (preference === 'starred' ? (on ? c.star() : c.unstar()) : on ? c.mute() : c.unmute()));
            }),
        leave: (channelId) => said(() => channel(channelId).leave()),
        join: (channelId) => said(async () => room(await channel(channelId).join())),
        deleteChannel: (channelId) => said(async () => ({ trashId: (await channel(channelId).delete()).id })),
        restoreChannel: (trashId) => said(async () => void (await TrashItem.fromId(trashId, { client }).restore())),
        markRead: (channelId) => said(async () => void (await channel(channelId).markRead())),
        typing: (channelId, typing) => sendTyping(channelId, typing),
    };
}
