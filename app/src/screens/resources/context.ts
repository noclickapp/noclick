// What whoever shows Resources hands it: values, where a slot (slots.ts) is a piece of the page. The client, the site
// and the live frames come from the console's context it's drawn inside (useConsole).
import { createContext, useContext, type ReactNode } from 'react';
import type { LucideIcon } from 'lucide-react';
import type { KindId } from './kinds';

/** One of the page's items, for a command palette to open later by name. */
export interface RememberedItem {
    id: string;
    label: string;
    /** Its kind's name. */
    context: string;
    icon: LucideIcon;
    about: string;
    kind: KindId;
    resource: string;
    /** Where opening it goes when its page is elsewhere. */
    open?: () => void;
}

export interface ResourcesContextValue {
    /** The workspace whose workflows' files and tables are listed, as `organization_id` names it (a team workspace's
     *  id, or `none`); absent, every workflow the account reads. */
    workspace?: string;
    /** Whether the account is billed here: without it no prices show and nothing sold is offered. */
    billing: boolean;
    /** The visitor's country, where whoever shows Resources knows it: what buying a number opens on. */
    country?: string;
    /** Hands a request to an assistant (an empty kind's "Ask NoClick"); absent, no such button shows. */
    ask?: (text: string) => void;
    /** Opens a workflow (a file's "Used by", a database's "Built in"); absent, its name is plain text. */
    openWorkflow?: (workflow: { id: string; name: string }) => void;
    /** Hands the page's items to a command palette. */
    remember?: (items: RememberedItem[]) => void;
    /** Opens a kind on a page of the host's own instead (the developer console's, with its user filter and actions),
     *  returning whether it did; absent, or false, the kind opens here. */
    openKind?: (kind: KindId) => boolean;
    /** More the account holds, under the overview's tiles: the developer console's kinds only code makes. */
    more?: ReactNode;
}

export const ResourcesContext = createContext<ResourcesContextValue>({ billing: true });

export function useResources(): ResourcesContextValue {
    return useContext(ResourcesContext);
}
