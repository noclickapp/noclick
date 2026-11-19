// "Ask NoClick" from anywhere: a message drafted for the chat, for the person to send (or edit first), with what it
// points at (an automation, an account). A latch: the chat takes it on mount (asked from another page) or on the event
// (asked while it's open), whichever is first. Going to the chat is the asker's. A page of a site that a visitor leaves
// for sign-up stages its draft in storage instead (`STAGED_KEY`), where the tab an emailed sign-up link opens can read
// it too, and the chat takes that the same way once they're in.
import type { ChatReference } from '@/lib/agentThread/messages';

const ASK_EVENT = 'noclick:coordinator:ask';
/** In localStorage: `{ text, ts }`, a draft a page of a site left for the chat. */
export const STAGED_KEY = 'noclick:chat-draft';
// Long enough to sign up and confirm an email; a draft older than that isn't this visit's.
const STAGED_FRESH_MS = 30 * 60 * 1000;

export interface PendingAsk {
    text: string;
    references?: ChatReference[];
}

let pendingAsk: PendingAsk | null = null;

/** Drafts `text` for the chat, which takes it now if it's open, else when it opens. */
export function stageAsk(text: string, references?: ChatReference[]): void {
    pendingAsk = { text, references };
    window.dispatchEvent(new Event(ASK_EVENT));
}

function freshDraft(raw: string): string | null {
    try {
        const { text, ts } = JSON.parse(raw);
        return typeof text === 'string' && text.trim() && typeof ts === 'number' && Date.now() - ts < STAGED_FRESH_MS ? text : null;
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
