// The seam Resources reads the platform's resources through: domains, email
// addresses, apps, databases and repos, which the hosted service serves from its
// platform API for the signed-in account, and puts a website on a domain and an
// email address on one through. A
// deployment registers a Provider (lazy, so
// nothing loads until Resources opens) that renders the context below around
// the page; without one those kinds aren't listed at all.
import { createContext, Suspense, useContext, type ComponentType, type ReactNode } from 'react';
import type { DomainRegistrar } from '~/hooks/useDomainPurchase';
import type { KindId } from './kinds';
import type { ResourceItem } from './model';

/** What a deletion does, as the platform previews it (`POST /v1/delete_previews`'s `impact`). */
export interface DeletionImpact {
    deletes: string;
    /** What has to go first, or stops working with it. */
    depends_on_it: string[];
    data_lost: string[];
    stops_billing: string[];
    reversible: boolean;
    /** How it's taken back, when it can be: "Restorable from the trash for 30 days." */
    undo?: string | null;
}

/** Something of a kind deleted to the trash, restorable until `purgeAfter`. */
export interface TrashEntry {
    id: string;
    name: string;
    trashedAt: string | null;
    purgeAfter: string | null;
}

/** The impact's lists that have something in them, as labelled rows. */
export function impactRows(impact: DeletionImpact): { term: string; items: string[] }[] {
    return (
        [
            ['Depends on it', impact.depends_on_it],
            ['Data lost', impact.data_lost],
            ['Stops billing', impact.stops_billing],
        ] as const
    ).flatMap(([term, items]) => (items?.length ? [{ term, items: [...items] }] : []));
}

/** How a resource's page removes it. */
export interface Removal {
    /** The page's button: "Remove", "Delete", "Let it lapse". */
    label: string;
    /** The confirming button: "Disconnect brother.com". */
    confirm: string;
    /** What it does, read when the person asks. */
    preview(): Promise<DeletionImpact>;
    /** Does it: resolves to what the toast says and whether the resource is gone (the page then leaves), or throws an
     * Error saying why it couldn't. */
    run(): Promise<{ done: string; gone: boolean }>;
}

export interface PlatformResources {
    /** The account's own platform resources, by kind. */
    items: Partial<Record<KindId, ResourceItem[]>>;
    /** True until every kind's first read has answered. */
    loading: boolean;
    /** Why a kind couldn't be read, in a sentence (its list is then empty). */
    errors: Partial<Record<KindId, string>>;
    /** What a kind billed by use has cost so far this month, in US dollars, where its items don't say each. */
    spentThisMonth: Partial<Record<KindId, number>>;
    refresh(): void;
    /** Where Resources searches for and buys domains. */
    registrar: DomainRegistrar;
    /** Shows the website (app) `appId` at `domain` too (a domain's own name brings its www); throws an Error saying why it couldn't. */
    serveApp(appId: string, domain: string): Promise<void>;
    /** The account's domains an email address can be made at (any address works on one): those whose DNS NoClick runs. */
    mailDomains: string[];
    /** Makes the address `localPart`@`domain`, or (`domain` null) one on NoClick's own mail domain; resolves to its
     * item's id, or throws an Error saying why it couldn't. */
    createAddress(localPart: string, domain: string | null): Promise<string>;
    /** A platform item's body on its page: a domain's records, an address's mail, a repo's files, a database's tables, an app's deployments. */
    Body: ComponentType<{ item: ResourceItem; now: string }>;
    /** A live figure a platform item's row shows beside its price (a website's requests this week), or nothing. */
    RowFigure?: ComponentType<{ item: ResourceItem }>;
    /** How `item`'s page removes it, or null where it offers nothing. */
    removal(item: ResourceItem): Removal | null;
    /** What's in the trash, by kind (only kinds whose deletion goes there). */
    trash: Partial<Record<KindId, TrashEntry[]>>;
    /** Puts `entry` back under its name; throws an Error saying why it couldn't (its name was taken again). */
    restore(entry: TrashEntry): Promise<void>;
    /** Deletes `entry` for good now; throws an Error saying why it couldn't. */
    purge(entry: TrashEntry): Promise<void>;
}

/** What the registered Provider renders around Resources. */
export const PlatformResourcesContext = createContext<PlatformResources | null>(null);

let Provider: ComponentType<{ children: ReactNode }> | null = null;

/** The deployment's platform resources: a Provider that renders the context around its children. */
export function registerPlatformResources(provider: ComponentType<{ children: ReactNode }>): void {
    Provider = provider;
}

export function hasPlatformResources(): boolean {
    return Provider !== null;
}

/** The registered platform's resources inside `PlatformResourcesBoundary`, else null. */
export function usePlatformResources(): PlatformResources | null {
    return useContext(PlatformResourcesContext);
}

/** Wraps Resources in the registered Provider, showing `fallback` while it loads. */
export function PlatformResourcesBoundary({ fallback, children }: { fallback: ReactNode; children: ReactNode }) {
    if (!Provider) return <>{children}</>;
    return (
        <Suspense fallback={fallback}>
            <Provider>{children}</Provider>
        </Suspense>
    );
}
