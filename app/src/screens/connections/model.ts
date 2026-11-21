// A connected account as Connections shows it: the app it signs in to, the account itself in words you'd recognise,
// whose it is, what (if anything) keeps it from working, and what can be done with it here. The page's reads build one
// for each account they find (reads.tsx: the platform API's connections, and whatever else a host lists).
import type { Connection } from 'noclick';
import type { WorkflowRef } from '@/screens/resources/files';
import type { ConnectableApp } from '@/ui/slots';
import type { DeletesThrough } from './DeleteDialog';
import type { ProbeAsk } from './probe';
import type { AccountSource } from './views';

/** The account's own facts, in the shape every list of accounts reads (an app account as the platform API reads it, or a
 *  host's own record of one). */
export interface AccountCredential {
    id: string;
    name: string;
    credential_type: string;
    metadata?: Record<string, unknown>;
    created_at: string;
    updated_at?: string;
    /** `owner` for your own, `shared` for one shared with you, `shared_org` for your workspace's. */
    access_type?: string;
    organization_id?: string | null;
    shared_by_email?: string | null;
    shared_by_name?: string | null;
    /** When it stopped working (it can't be used until it's connected again). */
    revoked_at?: string | null;
    /** A linked session's live word: false is dead, null is nothing to ask. */
    connection_healthy?: boolean | null;
    /** How to repair a dead session. */
    connection_hint?: string | null;
}

/** An app in the catalog: its accounts connect here. */
export interface CatalogApp extends ConnectableApp {
    /** The credential type a new account of it is made as. */
    primaryCredentialType: string;
    /** False for a retired app: the catalog leaves it out, an account already connected to it still finds it. */
    listed?: boolean;
}

export interface ConnectedAccount<C extends AccountCredential = AccountCredential, S extends CatalogApp = CatalogApp> {
    credential: C;
    /** The catalog app it signs in to; absent for model sign-ins, environment variables and MCP servers. */
    service?: S;
    /** What the account is, in a word: the app, else the kind of key. */
    app: string;
    /** The account itself: its email or login, its variables, else its name or when it was added. */
    line: string;
    /** The other names search finds its app by ("Anthropic" for a Claude account). */
    aliases?: string[];
    source: AccountSource;
    /** What keeps it from working, when something is known to. */
    problem?: string;
    /** The platform API's connection, where the account was read there. */
    connection?: Connection;
    /** The automations that use it, where the reads know. */
    usedBy?: WorkflowRef[];
    /** Asks its provider about it; absent where nothing can. */
    check?: ProbeAsk;
    /** Renames it; absent where its name is how code finds it. */
    rename?: (name: string) => Promise<void>;
    /** What deleting it leaves without it, and the delete. */
    deletes?: DeletesThrough;
    /** Connects it again, once it stopped working (its owner's to do). */
    reconnect?: () => void;
}

/** Which tab an account lives on, by how it reaches you. */
export function accountSource(credential: Pick<AccountCredential, 'access_type'>): AccountSource {
    if (credential.access_type === 'owner') return 'connected';
    if (credential.access_type === 'shared_org') return 'organization';
    return 'shared';
}

/** The broken ones first, then by app and account. */
export function sortedAccounts<A extends Pick<ConnectedAccount, 'problem' | 'app' | 'line'>>(accounts: readonly A[]): A[] {
    return [...accounts].sort((a, b) => Number(!a.problem) - Number(!b.problem) || a.app.localeCompare(b.app) || a.line.localeCompare(b.line));
}

/** The catalog app each credential type signs in to: the first that takes it. */
export function servicesByType<S extends CatalogApp>(apps: readonly S[]): Map<string, S> {
    const byType = new Map<string, S>();
    for (const app of apps) {
        for (const type of app.acceptedCredentialTypes) if (!byType.has(type)) byType.set(type, app);
    }
    return byType;
}
