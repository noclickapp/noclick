// The Chat page's open asks as its Beside last derived them, for the thread's own cards to show where each happened (a
// hand-off whose agent the account's cap paused draws the cap under it). The chat's provider makes one store, the
// Beside writes it as the asks move, and a card reads it; a card outside the Chat page reads none.
import { createContext, useContext, useSyncExternalStore } from 'react';
import type { NeedsYou } from './model';

export interface Needs {
    needs: readonly NeedsYou[];
    /** Starts a reply in the composer: what an ask with no page of its own does. */
    draft: (text: string) => void;
}

const NONE: Needs = { needs: [], draft: () => undefined };

export class NeedsStore {
    private current: Needs = NONE;
    private readonly listeners = new Set<() => void>();

    set(next: Needs): void {
        this.current = next;
        this.listeners.forEach((listener) => listener());
    }

    get = (): Needs => this.current;

    subscribe = (listener: () => void): (() => void) => {
        this.listeners.add(listener);
        return () => void this.listeners.delete(listener);
    };
}

export const NeedsContext = createContext<NeedsStore | null>(null);

const empty = () => () => undefined;
const none = () => NONE;

export function useNeeds(): Needs {
    const store = useContext(NeedsContext);
    return useSyncExternalStore(store?.subscribe ?? empty, store?.get ?? none, none);
}
