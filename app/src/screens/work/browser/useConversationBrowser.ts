// The browser a conversation's agent works in, as the chat beside it shows it: read through the platform client and
// read again on each `platform:resource` frame about its agent's browsers (it started, took a step, waits on a person,
// closed), never on a timer. Both chat pages (Work's conversations, the Chat page) read it once and hand it down in
// context, so the Beside's tile, the turn's card and the big view share one read, one picture socket and one
// take-over. Taking over and handing back go through the SDK's own `takeOver`/`handBack`.
import { createContext, useCallback, useContext, useMemo, useState } from 'react';
import { toast } from 'sonner';
import { invalidateV1 } from '@/sdk/useV1';
import { ALL_USERS, Browser, Operation } from 'noclick';
import { useWorkV1 } from '../agents/reads';
import { useWorkFrames } from '@/sdk/live';
import { stateOf, type BrowserState } from './words';

/** What the big view (laptop) or the full screen (phone) shows: the browser live, or the page an act ended on. */
export type BrowserShown = { mode: 'live' } | { mode: 'still'; frameUrl: string; label: string };

export interface BrowserControl {
    agentId: string;
    conversation: string;
    /** Who waits while a person holds it: "NoClick", an agent's name. */
    agentName: string;
    /** The conversation's newest browser: null before one ever started there. */
    browser: Browser | null;
    state: BrowserState;
    shown: BrowserShown | null;
    show: (view: BrowserShown) => void;
    hide: () => void;
    /** Take it over from the agent and show it live, yours to drive. */
    takeOver: () => Promise<void>;
    /** Hand it back: what you were asked to finish carries on. */
    handBack: () => Promise<void>;
    /** A take-over or hand-back on its way. */
    pending: 'take' | 'back' | null;
}

const BrowserContext = createContext<BrowserControl | null>(null);
export const ConversationBrowserProvider = BrowserContext.Provider;

/** The conversation's browser, inside a chat that reads one; null elsewhere. */
export function useBrowserControl(): BrowserControl | null {
    return useContext(BrowserContext);
}

const keyOf = (agentId: string, conversation: string) => `work:browser:${agentId}:${conversation}`;
const actKey = (operationId: string) => `work:browser-act:${operationId}`;

export function useConversationBrowser(agentId: string | null, conversation: string | null, agentName: string): BrowserControl | null {
    const key = agentId && conversation ? keyOf(agentId, conversation) : null;
    const read = useWorkV1(key, async (client) => (await Browser.list({ client, agent: agentId!, conversation: conversation!, limit: 1, userFilter: ALL_USERS }))[0] ?? null);
    const [shown, setShown] = useState<BrowserShown | null>(null);
    const [pending, setPending] = useState<'take' | 'back' | null>(null);
    const browser = read.data ?? null;
    useWorkFrames('platform:resource', (frame) => {
        if (frame.kind !== 'browser' || !key || frame.parent_id !== agentId) return;
        invalidateV1(key);
        // Its act as it settles: the outcome and last page its turn's receipt shows.
        if (browser?.actId) invalidateV1(actKey(browser.actId));
    });

    const act = useCallback(
        async (which: 'take' | 'back') => {
            if (!browser || !key) return;
            setPending(which);
            try {
                await (which === 'take' ? browser.takeOver() : browser.handBack());
                if (which === 'take') setShown({ mode: 'live' });
            } catch (error) {
                toast(which === 'take' ? 'Couldn’t take over the browser' : 'Couldn’t hand the browser back', {
                    description: error instanceof Error ? error.message : String(error),
                });
            } finally {
                setPending(null);
                invalidateV1(key);
            }
        },
        [browser, key]
    );

    return useMemo(
        () =>
            agentId && conversation
                ? {
                      agentId,
                      conversation,
                      agentName,
                      browser,
                      state: browser ? stateOf(browser) : 'done',
                      shown,
                      show: setShown,
                      hide: () => setShown(null),
                      takeOver: () => act('take'),
                      handBack: () => act('back'),
                      pending,
                  }
                : null,
        [agentId, conversation, agentName, browser, shown, pending, act]
    );
}

/** One act of the browser, as its operation reads now (its steps, its outcome, the page it ended on): read again with
 *  the browser's frames. */
export function useBrowserAct(operationId: string | null) {
    return useWorkV1(operationId ? actKey(operationId) : null, (client) => Operation.fromId(operationId!, { client }).refresh());
}
