// What came in on a conversation's triggered turns and what the agent did with each (lib/agentThread/turnActivity),
// beside its thread: read once the thread holds a turn an app's event started (a conversation with none reads
// nothing), and read again as the conversation's own live events say such a turn moved (a call it made ended, its
// message landed, it ended), never on a timer. A turn heard before its read lands is `waiting`, which its chat draws
// as already begun. A WhatsApp chat's picture or group name its turns' deliveries didn't carry (older ones) is read
// from what the connection keeps (GET /v1/connections/{ref}/chat_profiles), once per chat.
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import type { Agent, AgentEvent } from 'noclick';
import { peekV1, primeV1, readV1 } from '@/sdk/useV1';
import { useWorkClient } from '../client';
import { triggersKey } from '../profile/reads';
import { fromAnEvent, isChatTurn, missingProfiles, readChatProfiles, readTurnActivity, WHATSAPP_NODE, withProfiles, type ActivityChat, type ChatProfile, type TurnActivity } from '@/lib/agentThread/turnActivity';
import type { Thread } from '@/lib/agentThread/thread';

/** Where a conversation's activity is kept for this session, as its thread is (useAgentThread's `threadKey`). */
export const activityKey = (key: string, conversation: string) => `work:agent:${key}:activity:${conversation}`;

/** How many of the newest turns a live event reads again: the one it moved is among them. */
const RECENT = 5;
/** A turn's burst of events (a call's result, its message, its end) reads once. */
const SETTLE_MS = 250;
// What a triggered turn's moving says (a call ended, its message, its end, what it held or started).
const MOVES: ReadonlySet<AgentEvent['type']> = new Set(['message', 'tool_result', 'turn_end', 'approval', 'operation']);

export interface TurnActivityState {
    /** Each triggered turn read, by its operation's id. */
    byTurn: ReadonlyMap<string, TurnActivity>;
    /** Each chat its turns came from, by key, as its newest turn there names it (a picture any of them had kept). */
    chats: ReadonlyMap<string, ActivityChat>;
    /** Turns its live events named that the read hasn't brought back yet. */
    waiting: ReadonlySet<string>;
    /** Read, or nothing to read: the conversation draws without a later jump. */
    ready: boolean;
    /** Hears each of the conversation's live events. */
    heard: (event: AgentEvent) => void;
}

const merged = (kept: readonly TurnActivity[], fresh: readonly TurnActivity[]) => {
    const ids = new Set(fresh.map((a) => a.turn.id));
    return [...fresh, ...kept.filter((a) => !ids.has(a.turn.id))].sort((a, b) => b.turn.startedAt - a.turn.startedAt);
};

/** `caller`'s conversation's triggered turns (`key` names it in this session's reads, as its thread's does).
 *  `onError` says why a read failed: its turns then keep their own rows. */
export function useTurnActivity(caller: Agent, key: string, conversation: string, thread: Thread, threadReady: boolean, onError: (reason: string) => void): TurnActivityState {
    const client = useWorkClient();
    const cacheKey = activityKey(key, conversation);
    const [items, setItems] = useState<TurnActivity[] | null>(() => peekV1<TurnActivity[]>(client, cacheKey) ?? null);
    const [waiting, setWaiting] = useState<ReadonlySet<string>>(new Set());
    const needed = threadReady && thread.entries.some((e) => e.kind === 'user' && fromAnEvent(e));
    const threadRef = useRef(thread);
    threadRef.current = thread;
    const onErrorRef = useRef(onError);
    onErrorRef.current = onError;
    // The conversation a read answers for: one that lands after another is opened is dropped.
    const shown = useRef(cacheKey);
    shown.current = cacheKey;
    const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
    const heardOps = useRef(new Set<string>());
    const readied = useRef<string | null>(null);
    const [profiles, setProfiles] = useState<ReadonlyMap<string, ChatProfile>>(new Map());
    const askedProfiles = useRef(new Set<string>());

    useEffect(() => {
        setItems(peekV1<TurnActivity[]>(client, cacheKey) ?? null);
        setWaiting(new Set());
        setProfiles(new Map());
        heardOps.current = new Set();
        askedProfiles.current = new Set();
        return () => {
            if (timer.current) clearTimeout(timer.current);
            timer.current = null;
        };
    }, [client, cacheKey]);

    const said = (e: unknown) => onErrorRef.current(`What came in on its chats didn’t load: ${e instanceof Error && e.message ? e.message : 'NoClick didn’t answer.'}`);

    useEffect(() => {
        if (!needed || items !== null) return;
        const asked = cacheKey;
        readV1(client, cacheKey, () => caller.hydrate().then(() => readTurnActivity(caller, conversation))).then(
            (read) => shown.current === asked && setItems(read),
            (e: unknown) => {
                if (shown.current !== asked) return;
                setItems([]);
                said(e);
            }
        );
        // eslint-disable-next-line react-hooks/exhaustive-deps -- `cacheKey` names the agent and conversation
    }, [needed, items === null, client, cacheKey]);

    const reread = useCallback(() => {
        timer.current = null;
        const asked = shown.current;
        const ops = new Set(heardOps.current);
        heardOps.current = new Set();
        readTurnActivity(caller, conversation, RECENT).then(
            (fresh) => {
                if (shown.current !== asked) return;
                setItems((kept) => {
                    const next = merged(kept ?? [], fresh);
                    primeV1(client, asked, next);
                    return next;
                });
                setWaiting((w) => new Set([...w].filter((op) => !ops.has(op))));
            },
            (e: unknown) => {
                if (shown.current !== asked) return;
                setWaiting((w) => new Set([...w].filter((op) => !ops.has(op))));
                said(e);
            }
        );
    }, [client, caller, conversation]);

    const heard = useCallback(
        (event: AgentEvent) => {
            const op = event.operationId;
            if (!op || !MOVES.has(event.type)) return;
            // A message an app's event started a turn with, or a moment of a turn one started.
            const starts = event.type === 'message' && event.role !== 'assistant' && !!event.trigger && !['wakeup', 'loop', 'cron'].includes(event.trigger.kind);
            const triggered = starts || threadRef.current.entries.some((e) => e.kind === 'user' && e.operationId === op && fromAnEvent(e));
            if (!triggered) return;
            heardOps.current.add(op);
            if (starts) setWaiting((w) => (w.has(op) ? w : new Set([...w, op])));
            if (!timer.current) timer.current = setTimeout(reread, SETTLE_MS);
        },
        [reread]
    );

    // Pictures and group names its turns' deliveries didn't carry, as the WhatsApp connection keeps them now.
    useEffect(() => {
        if (!items?.some((a) => a.chat.nodeType === WHATSAPP_NODE)) return;
        const asked = cacheKey;
        readV1(client, triggersKey(key), () => caller.triggers())
            .then(async (triggers) => {
                const refs = new Map(triggers.map((t) => [t.id, typeof t.spec.connection === 'string' ? t.spec.connection : null]));
                for (const [ref, jids] of missingProfiles(items, (id) => refs.get(id) ?? null)) {
                    const fresh = jids.filter((j) => !askedProfiles.current.has(j));
                    if (!fresh.length) continue;
                    fresh.forEach((j) => askedProfiles.current.add(j));
                    const read = await readChatProfiles(client, caller, ref, fresh);
                    if (shown.current === asked) setProfiles((p) => new Map([...p, ...read]));
                }
            })
            // A chat without its picture shows its initials, as one with none does.
            .catch((e: unknown) => console.warn('[work] the chats’ pictures didn’t read:', e));
        // eslint-disable-next-line react-hooks/exhaustive-deps -- `cacheKey` names the agent and conversation
    }, [items, client, cacheKey]);

    const byTurn = useMemo(() => new Map((items ?? []).map((a) => [a.turn.id, withProfiles(a, profiles)])), [items, profiles]);
    const chats = useMemo(() => {
        const out = new Map<string, ActivityChat>();
        for (const a of [...byTurn.values()].filter(isChatTurn).sort((x, y) => y.turn.startedAt - x.turn.startedAt)) {
            const kept = out.get(a.chat.key);
            out.set(a.chat.key, kept ? { ...kept, avatar: kept.avatar ?? a.chat.avatar } : a.chat);
        }
        return out;
    }, [byTurn]);
    // Ready once, it stays so: a turn heard later reads beside what's drawn.
    const settled = !needed || items !== null;
    if (settled) readied.current = cacheKey;
    return { byTurn, chats, waiting, ready: settled || readied.current === cacheKey, heard };
}
