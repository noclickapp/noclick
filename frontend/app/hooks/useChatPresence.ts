// Whether the person is watching their chat right now, told to the server as
// `presence:chat` claims (utils/user_presence.watching_chat). Live means all of:
// the chat is on screen (the hook is mounted), the tab is visible, its window
// has focus, and the person touched the page within the last minute. A message
// the chat shows is also texted unless they are live, so any doubt reads as
// not live: nothing is claimed before the first touch, a claim is renewed
// every 15s and lapses on the server after 35s, and blur, a hidden tab,
// leaving the page, a minute idle or unmounting withdraws it at once.
import { useEffect } from 'react';
import { sendEvent } from '~/lib/socket-sender';
import { PresenceChatRequest } from '~/types/socket-events.generated';

export const CHAT_BEAT_MS = 15_000;
export const CHAT_IDLE_MS = 60_000;
// After a withdrawal the next claim waits this long, so focus flapping stays
// inside the event's rate limit.
const CLAIM_GAP_MS = 3_000;
// A touch only moves the idle deadline, so a second's precision is plenty.
const ACTIVITY_THROTTLE_MS = 1_000;
const ACTIVITY_EVENTS = [
    'pointermove',
    'pointerdown',
    'keydown',
    'wheel',
    'scroll',
    'touchstart',
] as const;
// Capture, because a scroll inside the thread doesn't bubble.
const LISTEN = { capture: true, passive: true } as const;

/** Sends one claim (`live`) or withdrawal; false when it couldn't be sent. */
export type SendChatPresence = (tabId: string, live: boolean) => boolean;

const sendOverSocket: SendChatPresence = (tabId, live) =>
    sendEvent(PresenceChatRequest.create({ tab_id: tabId, live }));

/** Claims the chat for this tab while the person is watching it. Mount where the chat is on screen. */
export function useChatPresence(): void {
    useEffect(() => watchChatPresence(sendOverSocket), []);
}

/** Watches this page for the person and keeps one claim up to date; returns the stop (which withdraws it). */
export function watchChatPresence(send: SendChatPresence): () => void {
    const tabId = crypto.randomUUID();
    let lastActivity = -Infinity;
    let claimed = false;
    let nextClaimAt = -Infinity;
    let timer: ReturnType<typeof setTimeout> | undefined;

    const isLive = (now: number) =>
        document.visibilityState === 'visible' &&
        document.hasFocus() &&
        now - lastActivity < CHAT_IDLE_MS;

    const withdraw = () => {
        clearTimeout(timer);
        timer = undefined;
        if (!claimed) return;
        claimed = false;
        nextClaimAt = Date.now() + CLAIM_GAP_MS;
        send(tabId, false);
    };

    const update = () => {
        const now = Date.now();
        if (!isLive(now)) {
            withdraw();
            return;
        }
        if (now >= nextClaimAt) {
            // A claim that couldn't be sent is tried again at the next beat.
            claimed = send(tabId, true);
            nextClaimAt = now + CHAT_BEAT_MS;
        }
        clearTimeout(timer);
        timer = setTimeout(
            update,
            Math.min(nextClaimAt, lastActivity + CHAT_IDLE_MS) - now
        );
    };

    const onActivity = () => {
        const now = Date.now();
        if (now - lastActivity < ACTIVITY_THROTTLE_MS) return;
        lastActivity = now;
        // While a timer runs it re-reads the new deadline when it fires.
        if (timer === undefined) update();
    };

    for (const type of ACTIVITY_EVENTS)
        window.addEventListener(type, onActivity, LISTEN);
    document.addEventListener('visibilitychange', update);
    window.addEventListener('focus', update);
    window.addEventListener('blur', withdraw);
    window.addEventListener('pagehide', withdraw);

    return () => {
        for (const type of ACTIVITY_EVENTS)
            window.removeEventListener(type, onActivity, LISTEN);
        document.removeEventListener('visibilitychange', update);
        window.removeEventListener('focus', update);
        window.removeEventListener('blur', withdraw);
        window.removeEventListener('pagehide', withdraw);
        withdraw();
    };
}
