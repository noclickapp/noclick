// How any of Work's views opens another: a channel, an agent's session, its profile or machine, the members.
// The page provides it over the URL (place.ts); a test provides its own to see where a click goes.
import { createContext, useContext } from 'react';
import type { ProfileTab, WorkPanel } from './place';

export interface WorkNav {
    /** A channel or DM, wherever it is; `thread` opens one of its threads beside it; `replace` takes the place of what's
     *  open in history (a link that named something it stands for). */
    openChannel(channelId: string, options?: { thread?: string; replace?: boolean }): void;
    /** Your DM with a person in the space (`account`: its owner), started the first time. */
    openDm(userId: string | 'account'): void;
    /** An agent's session in Agents. */
    openAgent(agentId: string): void;
    /** An agent's profile beside what's open, on `tab` with `trigger` open there (a trigger's id, or `add`). */
    openProfile(agentId: string, at?: { tab?: ProfileTab; trigger?: string }): void;
    /** An agent's machine page, in its session's place. */
    openMachine(agentId: string): void;
    /** The draft of a new agent, in Agents. */
    newAgent(): void;
    /** The space's Home, nothing open (where you land when the agent you were on is deleted and none is left). */
    openHome(): void;
    /** The space's members beside what's open, on one of their tabs. */
    openMembers(tab?: Exclude<WorkPanel, 'profile'>): void;
    /** Close what's beside the main pane. */
    closePanel(): void;
}

export const WorkNavContext = createContext<WorkNav | null>(null);

export function useWorkNav(): WorkNav {
    const nav = useContext(WorkNavContext);
    if (!nav) throw new Error('Work views render inside WorkNavContext.');
    return nav;
}
