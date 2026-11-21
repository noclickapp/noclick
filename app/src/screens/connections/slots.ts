// Connections' slots (src/slots.ts): where a host puts its own pieces on the page, each with what stands there when none
// does (slotStandards.tsx). The marks and names of accounts, and connecting one where it's needed, are slots several
// screens draw (`connection.mark`, `connect.app`, `connect.model` in @/ui/slots).
import type { ComponentType, ReactNode } from 'react';
import type { NoClick } from 'noclick';
import { slot } from '@/slots';
import type { CatalogApp, ConnectedAccount } from './model';
import { ApiReads, connectInNewTab, ModelCompanyConnect, ReadOnlyAccess, useModelCompanies, useV1CatalogApps } from './slotStandards';

/** Where the page reads the accounts it lists: a Provider around it that gives them (`ConnectionsAccountsContext` in
 *  reads.tsx). The standard reads every connection the platform API lists in the workspace the page shows. */
export const READS = slot<ComponentType<{ children: ReactNode }>>('connections.reads', ApiReads);

export interface ConnectionsApps {
    /** Every app whose accounts connect here (the retired ones too, marked), read once and kept; empty until read. */
    useApps(): CatalogApp[];
}

/** The apps the catalog lists and accounts are matched to. The standard reads the integrations the platform API lists. */
export const APPS = slot<ConnectionsApps>('connections.apps', { useApps: useV1CatalogApps });

/** Connects another account of `app` from the catalog, with the client the page reads with. The standard makes a
 *  connection and opens its connect page on NoClick in a new tab, then reads the accounts again once it lands. */
export const CONNECT = slot<(app: CatalogApp, client: NoClick) => void>('connections.connect', connectInNewTab);

/** An AI company in the catalog, among the apps. */
export interface AiCompanyEntry {
    /** What it's known by in the catalog's ranking (`ai:<id>`). */
    id: string;
    title: string;
    /** The line under its name before anything is connected (the subscription it signs in with). */
    line?: string;
    /** Every credential type that counts as one of its accounts. */
    credentialTypes: string[];
    /** What search finds it by. */
    searchFields: string[];
    mark: ReactNode;
}

/** Connecting an account with `company`, opened while it's set: `accounts` is every account you can use (it lists the
 *  company's), and `onOpenAccount` opens one of them on its page. */
export interface AiConnectProps {
    company: AiCompanyEntry | null;
    accounts: ConnectedAccount[];
    onOpenChange: (open: boolean) => void;
    onOpenAccount: (accountId: string) => void;
}

export interface ConnectionsAi {
    /** The AI companies the catalog lists. */
    useCompanies(): AiCompanyEntry[];
    Connect: ComponentType<AiConnectProps>;
}

/** The AI companies agents run on, in the catalog among the apps. The standard lists each model provider the platform
 *  API knows and connects it at its connect page on NoClick (through the shared `connect.model` slot). */
export const AI = slot<ConnectionsAi>('connections.ai', { useCompanies: useModelCompanies, Connect: ModelCompanyConnect });

/** An account's Access section: who else may use it. `onLeft` runs once an account shared with you is taken off your
 *  list. The standard says whose it is and that sharing is done on NoClick. */
export const ACCOUNT_ACCESS = slot<ComponentType<{ account: ConnectedAccount; onLeft: () => void }>>('connections.account.access', ReadOnlyAccess);

/** More of an account's page, after its proof (a WhatsApp number's agent, say). The standard has nothing to add. */
export const ACCOUNT_MORE = slot<ComponentType<{ account: ConnectedAccount }>>('connections.account.more', () => null);
