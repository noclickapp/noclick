// What came in on a turn a trigger started and what the agent did with it, as GET .../conversations/{c}/activity
// reads each one back (the platform's agents.activity items): the chat and who it's with, the message that came in
// (its words, a voice note with its transcript, a file, what it quoted) and what the agent did, in order. Work draws a
// turn a chat app's message started as that chat (ChatTurn); this module reads the wire and says which turns those are.
import { Connection, type Agent, type JsonObject, type NoClick } from 'noclick';
import type { UserEntry } from './thread';

export type ChatKind = 'direct' | 'group' | 'self';

export interface ActivityChat {
    key: string;
    name: string | null;
    kind: ChatKind | null;
    /** E.164. */
    number: string | null;
    /** Their picture on the chat app, where it's known. */
    avatar: string | null;
    /** The trigger's node, which names the app the chat is on. */
    nodeType: string | null;
}

export interface ActivityMedia {
    /** voice, audio, image, video, document, file, location or contact. */
    kind: string;
    url: string | null;
    /** Seconds, for a voice note or audio. */
    duration: number | null;
    transcript: string | null;
}

export interface Inbound {
    senderName: string | null;
    senderId: string | null;
    senderNumber: string | null;
    /** The writer's picture on the chat app, where it's known. */
    senderAvatar: string | null;
    text: string;
    media: ActivityMedia | null;
    quotedText: string | null;
    at: number;
    messageId: string | null;
}

export type DidKind = 'reply' | 'reaction' | 'note' | 'reminder' | 'found' | 'held' | 'failed' | 'quiet';

export interface Did {
    kind: DidKind;
    text: string | null;
    emoji: string | null;
    at: number | null;
    /** The request a held call's owner answers. */
    heldRequestId: string | null;
    messageId: string | null;
    /** The tool it called; none for the turn's own end (quiet, a failed turn). */
    tool: string | null;
    /** A file it sent. */
    media: { kind: string; url: string | null } | null;
    /** When a reminder wakes it. */
    when: string | null;
    /** The memory entry a note saved. */
    name: string | null;
    edited: boolean;
}

export type ActivityStatus = 'running' | 'done' | 'failed';

export interface TurnActivity {
    chat: ActivityChat;
    /** What came in, oldest first: the message that started it, then those that arrived while the agent was busy and
     *  it answered too (none for a turn a wake-up started). */
    inbound: Inbound[];
    did: Did[];
    turn: {
        id: string;
        conversationId: string;
        status: ActivityStatus;
        startedAt: number;
        workedS: number | null;
        /** The trigger whose event started it (its id, as the agent's triggers list it). */
        triggerId: string | null;
        /** Each call it made, with its error where it failed. */
        steps: { tool: string; at: number; error: string | null }[];
    };
}

const s = (v: unknown): string | null => (typeof v === 'string' && v ? v : null);
const n = (v: unknown): number | null => (typeof v === 'number' ? v : null);
const o = (v: unknown): JsonObject => (v && typeof v === 'object' && !Array.isArray(v) ? (v as JsonObject) : {});
const when = (v: unknown, fallback: number): number => (typeof v === 'string' && !Number.isNaN(Date.parse(v)) ? Date.parse(v) : fallback);
const KINDS: readonly string[] = ['direct', 'group', 'self'];
const DID: readonly string[] = ['reply', 'reaction', 'note', 'reminder', 'found', 'held', 'failed', 'quiet'];

function mediaOf(raw: unknown): ActivityMedia | null {
    const m = o(raw);
    return s(m.kind) ? { kind: String(m.kind), url: s(m.url), duration: n(m.duration), transcript: s(m.transcript) } : null;
}

function inboundOf(raw: JsonObject, startedAt: number): Inbound {
    return {
        senderName: s(raw.sender_name),
        senderId: s(raw.sender_id),
        senderNumber: s(raw.sender_number),
        senderAvatar: s(raw.sender_avatar),
        text: typeof raw.text === 'string' ? raw.text : '',
        media: mediaOf(raw.media),
        quotedText: s(raw.quoted_text),
        at: when(raw.at, startedAt),
        messageId: s(raw.message_id),
    };
}

/** One item as the route answers it: `inbound` the message that started the turn, `also_inbound` those it took
 *  along, each `at` when it arrived (else the turn's start). */
export function toTurnActivity(raw: JsonObject): TurnActivity {
    const chat = o(raw.chat);
    const turn = o(raw.turn);
    const startedAt = when(turn.started_at, Date.now());
    const inbound = raw.inbound ? [raw.inbound, ...(Array.isArray(raw.also_inbound) ? raw.also_inbound : [])] : [];
    return {
        chat: { key: String(chat.key ?? ''), name: s(chat.name), kind: KINDS.includes(String(chat.kind)) ? (chat.kind as ChatKind) : null, number: s(chat.number), avatar: s(chat.avatar), nodeType: s(chat.node_type) },
        inbound: inbound.map((m) => inboundOf(o(m), startedAt)),
        did: (Array.isArray(raw.did) ? (raw.did as JsonObject[]) : [])
            .filter((d) => DID.includes(String(d.kind)))
            .map((d) => {
                const media = o(d.media);
                return {
                    kind: d.kind as DidKind,
                    text: s(d.text),
                    emoji: s(d.emoji),
                    at: typeof d.at === 'string' ? when(d.at, startedAt) : null,
                    heldRequestId: s(d.held_request_id),
                    messageId: s(d.message_id),
                    tool: s(d.tool),
                    media: s(media.kind) ? { kind: String(media.kind), url: s(media.url) } : null,
                    when: s(d.when),
                    name: s(d.name),
                    edited: d.edited === true,
                };
            }),
        turn: {
            id: String(turn.id ?? ''),
            conversationId: String(turn.conversation_id ?? ''),
            status: turn.status === 'running' || turn.status === 'failed' ? turn.status : 'done',
            startedAt,
            workedS: n(turn.worked_s),
            triggerId: s(o(turn.started_by).id),
            steps: (Array.isArray(turn.steps) ? (turn.steps as JsonObject[]) : []).map((x) => ({ tool: String(x.tool ?? ''), at: when(x.at, startedAt), error: s(x.error) })),
        },
    };
}

/** A turn a chat app's message started (a person's message on WhatsApp), drawn as that chat; any other trigger's (a
 *  schedule, a webhook) or a wake-up's keeps its own row. */
export const isChatTurn = (a: TurnActivity): boolean => a.inbound.length > 0 && a.chat.kind !== null;

/** A message an app's event started a turn with: one the activity may draw as its chat. A wake-up's, a loop's, a
 *  schedule's or app testing's switch's never is. */
export const fromAnEvent = (e: UserEntry): boolean => !!e.trigger && !e.author && !!e.operationId && !['wakeup', 'loop', 'cron', 'app_testing'].includes(e.trigger.kind);

/** How many of a conversation's latest triggered turns its page reads: more than a thread shows at once. */
export const ACTIVITY_PAGE = 100;

/** A conversation's triggered turns, newest first, the `limit` latest: in the thread its history reads (`agent`, once
 *  its fields are read, names whose). */
export async function readTurnActivity(agent: Agent, conversation: string, limit = ACTIVITY_PAGE): Promise<TurnActivity[]> {
    return (await agent.activity(conversation, { limit })).map((item) => toTurnActivity(item.raw));
}

/** What a chat app keeps of a chat or a person: their picture, and a group's name. */
export interface ChatProfile {
    name: string | null;
    avatar: string | null;
}

/** A WhatsApp chat's pictures and group names, as a WhatsApp connection keeps them (GET
 *  /v1/connections/{ref}/chat_profiles), for turns whose own delivery came before they were kept. */
export const WHATSAPP_NODE = 'automation-whatsapp';
const MAX_PROFILES = 100;

/** The chats and writers `items` don't picture (or a group they don't name), by the connection their trigger
 *  listens on; `connectionOf` names it from a trigger's id. */
export function missingProfiles(items: readonly TurnActivity[], connectionOf: (triggerId: string) => string | null): Map<string, string[]> {
    const wanted = new Map<string, Set<string>>();
    for (const a of items) {
        const ref = a.chat.nodeType === WHATSAPP_NODE && a.turn.triggerId ? connectionOf(a.turn.triggerId) : null;
        if (!ref) continue;
        const jids = wanted.get(ref) ?? new Set<string>();
        if (!a.chat.avatar || (a.chat.kind === 'group' && !a.chat.name)) jids.add(a.chat.key);
        if (a.chat.kind === 'group') for (const m of a.inbound) if (m.senderId && !m.senderAvatar) jids.add(m.senderId);
        wanted.set(ref, jids);
    }
    return new Map([...wanted].filter(([, jids]) => jids.size).map(([ref, jids]) => [ref, [...jids].slice(0, MAX_PROFILES)]));
}

/** Each chat id's profile on a connection `agent`'s trigger listens on, read in the agent's scope. */
export async function readChatProfiles(client: NoClick, agent: Agent, ref: string, jids: readonly string[]): Promise<Map<string, ChatProfile>> {
    const rows = await Connection.fromId(ref, { client }).chatProfiles(jids, { user: agent._talkScope(undefined) });
    return new Map(rows.filter((r) => r.jid).map((r) => [r.jid, { name: r.name, avatar: r.avatarUrl }]));
}

/** `a` with what its connection keeps of its chat and writer, where its own delivery carried none. */
export function withProfiles(a: TurnActivity, profiles: ReadonlyMap<string, ChatProfile>): TurnActivity {
    const chat = profiles.get(a.chat.key);
    const writers = a.inbound.some((m) => m.senderId && profiles.has(m.senderId));
    if (!chat && !writers) return a;
    return {
        ...a,
        chat: { ...a.chat, avatar: a.chat.avatar ?? chat?.avatar ?? null, name: a.chat.name ?? (a.chat.kind === 'group' ? (chat?.name ?? null) : null) },
        inbound: a.inbound.map((m) => ({ ...m, senderAvatar: m.senderAvatar ?? (m.senderId ? profiles.get(m.senderId)?.avatar : null) ?? null })),
    };
}
