// What whoever shows Work hands it: values, where a slot (slots.ts) is a piece of the page. The client and the live
// frames come through Work's own providers (client.ts, `@/sdk/live`), and who the client acts as, the site and the
// visitor's country from the console's context Work is drawn inside (useConsole).
import { createContext, useContext } from 'react';
import type { LucideIcon } from 'lucide-react';

/** One of Work's places, for a command palette to open later by name. */
export interface PaletteEntry {
    id: string;
    label: string;
    /** Where it is (its space's name, "Agent", "Space"). */
    context?: string;
    icon: LucideIcon;
    /** More it answers to (a channel's topic). */
    about?: string;
    run: () => void;
}

/** A page of the app outside Work: Resources (at a kind, an item or buying something, as its address names it), or
 *  the connected accounts. */
export type OtherPage = 'resources' | 'connections';

export interface WorkContextValue {
    /** Hands a request to the account's assistant on its own page (`/remind`, `/automate`, "Change how it works", a
     *  space's "Ask NoClick"); absent, none of those is offered. */
    ask?: (text: string) => void;
    /** Opens another page of the app with its own address params (a null clears one); absent, what would open one
     *  isn't offered. */
    openPage?: (page: OtherPage, params?: Record<string, string | null>) => void;
    /** Opens one step of a workflow on its canvas (a trigger's "Open step"); absent, it isn't offered. */
    openWorkflowStep?: (workflowId: string, stepId: string) => void;
    /** A command palette: Work hands it its places, and Home's Find opens it; absent, there's no Find. */
    palette?: { remember: (entries: PaletteEntry[]) => void; open: () => void };
}

export const WorkContext = createContext<WorkContextValue>({});

export function useWork(): WorkContextValue {
    return useContext(WorkContext);
}
