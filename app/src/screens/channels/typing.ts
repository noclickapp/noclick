// Who is typing in a channel or DM. Your composer says so through the transport (`typing`) at most every few seconds
// while keys are pressed, and stops on send, blur or clear; the other readers' pages hear it as a `typing` change and
// let a mark lapse a few seconds after its last one. Nothing is kept or polled.
import { useEffect, useMemo, useState } from 'react';
import type { ChannelChange, ChannelsTransport } from './transport';

/** How often a composer renews its "typing" while keys are pressed. */
export const TYPING_BEAT_MS = 3_000;
/** How long a mark lasts without another change: two beats, so one lost one doesn't blink it. */
export const TYPING_TTL_MS = 6_000;

/** Says you're typing (`true`) or stopped; rejects when it couldn't be said. */
export type SendTyping = (channelId: string, typing: boolean) => Promise<void>;

export interface TypingSignal {
    /** The box now holds `text`: typing while it holds anything, renewed each beat; stopped once it's empty. */
    input(text: string): void;
    /** Sent, left the box, or left the channel. */
    stop(): void;
}

/** One composer's signal in one channel. */
export function typingSignal(channelId: string, send: SendTyping, now: () => number = Date.now): TypingSignal {
    let saidAt = -Infinity;
    let typing = false;
    const stop = () => {
        if (!typing) return;
        typing = false;
        saidAt = -Infinity;
        send(channelId, false).catch(() => undefined);
    };
    return {
        input: (text) => {
            if (!text.trim()) return stop();
            const at = now();
            if (typing && at - saidAt < TYPING_BEAT_MS) return;
            typing = true;
            saidAt = at;
            // One that couldn't be said is tried again at the next key.
            send(channelId, true).catch(() => {
                if (saidAt !== at) return;
                typing = false;
                saidAt = -Infinity;
            });
        },
        stop,
    };
}

/** The composer's signal for `channelId`, stopped when the channel changes or the page leaves it. */
export function useTypingSignal(transport: ChannelsTransport, channelId: string): TypingSignal {
    const signal = useMemo(() => typingSignal(channelId, (id, typing) => transport.typing(id, typing)), [channelId, transport]);
    useEffect(() => () => signal.stop(), [signal]);
    return signal;
}

/** Someone typing, as the line draws them: who (their user id in the account, `account` for its owner), their name,
 *  and when the mark lapses. */
export interface Typist {
    id: string;
    name: string;
    until: number;
}

/** The typists after `change`: it marks (or renews) someone until `now + TYPING_TTL_MS`, or clears them. Yours never
 *  shows (`me`: your id as changes name you), nor another channel's, nor any other change. Newest last. */
export function typistsAfter(typists: readonly Typist[], change: ChannelChange, channelId: string, me: string, now: number): Typist[] {
    const typist = change.typist;
    if (change.kind !== 'typing' || !typist || change.channelId !== channelId || typist.id === me) return [...typists];
    const others = typists.filter((t) => t.id !== typist.id);
    return typist.typing ? [...others, { id: typist.id, name: typist.name, until: now + TYPING_TTL_MS }] : others;
}

/** Those still typing at `now`. */
export const typingAt = (typists: readonly Typist[], now: number): Typist[] => typists.filter((t) => t.until > now);

/** Who else is typing in `channelId` right now, from the transport's changes; each mark lapses on its own. */
export function useChannelTypists(transport: ChannelsTransport, channelId: string, me: string): Typist[] {
    const [typists, setTypists] = useState<Typist[]>([]);
    useEffect(() => setTypists([]), [channelId]);
    useEffect(
        () => transport.subscribe((change) => change.kind === 'typing' && setTypists((current) => typistsAfter(current, change, channelId, me, Date.now()))),
        [transport, channelId, me]
    );
    useEffect(() => {
        if (!typists.length) return;
        const next = Math.min(...typists.map((t) => t.until)) - Date.now();
        const timer = setTimeout(() => setTypists((current) => {
            const left = typingAt(current, Date.now());
            return left.length === current.length ? current : left;
        }), Math.max(0, next));
        return () => clearTimeout(timer);
    }, [typists]);
    return typists;
}
