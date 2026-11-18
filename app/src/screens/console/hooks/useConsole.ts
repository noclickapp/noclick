// The console's context: what whoever renders the console hands it (its client and who that acts as, where the console
// is mounted, the addresses around it, its clock, its live frames), and the account the shell reads.
import { createContext, useContext, type ReactNode } from 'react';
import type { WorkLive } from '@/sdk/live';
import type { NoClick } from 'noclick';
import type { AccountView } from '@/sdk/owner';
import type { V1State } from '@/sdk/useV1';

export type HrefParams = Record<string, string | null | undefined>;

export interface ConsoleContextValue {
    client: NoClick;
    /** Who the client's calls are made as: the account's `owner`, signed in to NoClick, or one of its API `key`s (a
     *  server that holds one). A key can't do everything an owner can: ownerOnly.ts is the one table of what it can't. */
    actsAs: 'owner' | 'key';
    /** Where the console is mounted, without a trailing slash: every link inside it is built on this. */
    basePath: string;
    /** NoClick's API as code outside this page reaches it (`https://api.noclick.com`), for commands a person copies.
     *  Never the client's own base URL, which may be a server of this app standing in front of the API. */
    apiUrl: string;
    /** NoClick's own site, for links to its docs, pricing, legal pages and billing: its origin without a trailing
     *  slash (`https://noclick.com`), or empty where the console is served from that site itself. */
    site: string;
    /** The app the console is part of, where "back" leads. */
    home: string;
    /** The country to open a country's choice on (buying a number), where the host knows the person's. */
    country?: string;
    user: { id: string; email: string | null };
    /** Wall clock; fixed in the lab so fixtures and screenshots are stable. */
    now: () => number;
    lab: boolean;
    signOut: () => void;
    /** The account's live frames when the host has them (a platform:resource frame makes the reads showing that
     *  resource stale); null when it has none, and reads then refresh on their own slow re-read and on focus. Required,
     *  so every mount says which. */
    live: WorkLive | null;
    /** What stands atop the sidebar beside the search (a host's workspace switcher); nothing by default. */
    workspace?: ReactNode;
}

export const ConsoleContext = createContext<ConsoleContextValue | null>(null);

export function useConsole(): ConsoleContextValue {
    const value = useContext(ConsoleContext);
    if (!value) throw new Error('useConsole() must be used inside <DeveloperConsole>.');
    return value;
}

/** A console URL: `consoleHref('/developers', 'operations', { op: id })` → `/developers/operations?op=…`. */
export function consoleHref(basePath: string, path = '', params: HrefParams = {}): string {
    const search = new URLSearchParams();
    for (const [key, value] of Object.entries(params)) if (value != null && value !== '') search.set(key, value);
    const qs = search.toString();
    const trimmed = path.replace(/^\/+|\/+$/g, '');
    return `${basePath}${trimmed ? `/${trimmed}` : ''}${qs ? `?${qs}` : ''}`;
}

export function useConsoleHref(): (path?: string, params?: HrefParams) => string {
    const { basePath } = useConsole();
    return (path, params) => consoleHref(basePath, path, params);
}

export const AccountContext = createContext<V1State<AccountView> | null>(null);

/** `/v1/account`, refreshed every 60s and on focus by the shell. */
export function useAccount(): V1State<AccountView> {
    const value = useContext(AccountContext);
    if (!value) throw new Error('useAccount() must be used inside <DeveloperConsole>.');
    return value;
}
