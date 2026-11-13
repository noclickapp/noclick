// "Ask NoClick" from anywhere: open the chat with a message drafted for the
// user to send (or edit first), and what it points at (an automation, an
// account). A latch like the flow intent's: the chat reads it on mount
// (cross-page) or on the event (already open), whichever is first. A page of
// the site that a visitor leaves for sign-up stages its draft in storage
// instead (`useLandingCta`, which writes `STAGED_KEY`), and the chat takes that
// the same way once they're in.
import type { ChatReference } from '~/lib/agentChat';
import { navigateToTab } from '~/lib/navigation';

const ASK_EVENT = 'noclick:coordinator:ask';
// In localStorage: the tab an emailed sign-up link opens is another tab.
export const STAGED_KEY = 'noclick:chat-draft';
// Long enough to sign up and confirm an email; a draft older than that isn't this visit's.
const STAGED_FRESH_MS = 30 * 60 * 1000;

export interface PendingAsk {
    text: string;
    references?: ChatReference[];
}

let pendingAsk: PendingAsk | null = null;

export function askNoClick(text: string, references?: ChatReference[]): void {
    pendingAsk = { text, references };
    window.dispatchEvent(new Event(ASK_EVENT));
    navigateToTab('chat');
}

function freshDraft(raw: string): string | null {
    try {
        const { text, ts } = JSON.parse(raw);
        return typeof text === 'string' && text.trim() && typeof ts === 'number' && Date.now() - ts < STAGED_FRESH_MS
            ? text
            : null;
    } catch {
        return null;
    }
}

/** Take the draft a page of the site staged, while fresh (a stale or unreadable one goes anyway). */
function takeStaged(): string | null {
    try {
        const raw = window.localStorage.getItem(STAGED_KEY);
        if (raw === null) return null;
        window.localStorage.removeItem(STAGED_KEY);
        return freshDraft(raw);
    } catch {
        return null; // storage is off (a private window): nothing was staged
    }
}

/** Read and clear the drafted message. */
export function consumePendingAsk(): PendingAsk | null {
    const ask = pendingAsk;
    pendingAsk = null;
    if (ask) return ask;
    const text = takeStaged();
    return text ? { text } : null;
}

export function onAskNoClick(listener: () => void): () => void {
    window.addEventListener(ASK_EVENT, listener);
    return () => window.removeEventListener(ASK_EVENT, listener);
}
