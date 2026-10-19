// "Ask NoClick" from anywhere: open the chat with a message drafted for the
// user to send (or edit first), and what it points at (an automation, an
// account). A latch like the flow intent's: the chat reads it on mount
// (cross-page) or on the event (already open), whichever is first.
import type { ChatReference } from '~/lib/agentChat';
import { navigateToTab } from '~/lib/navigation';

const ASK_EVENT = 'noclick:coordinator:ask';

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

/** Read and clear the drafted message. */
export function consumePendingAsk(): PendingAsk | null {
    const ask = pendingAsk;
    pendingAsk = null;
    return ask;
}

export function onAskNoClick(listener: () => void): () => void {
    window.addEventListener(ASK_EVENT, listener);
    return () => window.removeEventListener(ASK_EVENT, listener);
}
