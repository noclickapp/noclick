// What Resources reads of the platform, for the page and every item's page: domains, email addresses, apps, databases,
// buckets, repos and numbers (reads.tsx), with what a host adds (slots.ts), and the ways it changes them: puts a website
// on a domain, makes an email address, removes, restores.
import { createContext, useContext, type ComponentType } from 'react';
import type { NumberPurchaseTransport } from '@/screens/numbers/usePhoneNumberPurchase';
import type { DomainRegistrar } from '@/screens/domains/useDomainPurchase';
import type { DeletionImpact as PreviewedImpact } from 'noclick';
import type { KindId } from './kinds';
import type { ResourceItem, ResourceOwner } from './model';

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

/** What `previewDelete` (the SDK's) says a deletion does, as Resources reads it. */
export function impactOf(impact: PreviewedImpact): DeletionImpact {
    return {
        deletes: impact.deletes,
        depends_on_it: impact.dependsOnIt,
        data_lost: impact.dataLost,
        stops_billing: impact.stopsBilling,
        reversible: impact.reversible,
        undo: impact.undo,
    };
}

/** Something of a kind deleted to the trash, restorable until `purgeAfter`. */
export interface TrashEntry {
    id: string;
    name: string;
    trashedAt: string | null;
    purgeAfter: string | null;
    /** The one of the account's users it belonged to. */
    owner?: ResourceOwner;
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
    /** Every platform resource the account holds, by kind: its own, and its users' (each with its `owner`). */
    items: Partial<Record<KindId, ResourceItem[]>>;
    /** By kind: true until the reads its list is drawn from first answer. Each kind draws on its own, never waiting on another's. */
    loading: Partial<Record<KindId, boolean>>;
    /** Why a kind couldn't be read, in a sentence (its list is then empty). */
    errors: Partial<Record<KindId, string>>;
    /** What a kind billed by use has cost so far this month, in US dollars, where its items don't say each. */
    spentThisMonth: Partial<Record<KindId, number>>;
    /** What a number costs a month, in US dollars, by its id, where its item carries no price of its own. */
    numberPrices: ReadonlyMap<string, number>;
    /** How the page for buying a number buys it. */
    numberTransport: NumberPurchaseTransport;
    refresh(): void;
    /** Where Resources searches for and buys domains. */
    registrar: DomainRegistrar;
    /** Shows the website (app) `appId` at `domain` too (a domain's own name brings its www); throws an Error saying why it couldn't. */
    serveApp(appId: string, domain: string): Promise<void>;
    /** The domains any email address works on, the account's and its users': those whose DNS NoClick runs. */
    mailDomains: string[];
    /** Makes the address `localPart`@`domain`, or (`domain` null) one on NoClick's own mail domain; resolves to its
     * item's id, or throws an Error saying why it couldn't. */
    createAddress(localPart: string, domain: string | null): Promise<string>;
    /** A platform item's body on its page: a domain's records, an address's mail, a repo's files, a database's tables, an app's deployments. */
    Body: ComponentType<{ item: ResourceItem; now: string }>;
    /** A platform item's own actions in its page's header, beside the removal (a skill's Attach to and ⋯). */
    Actions?: ComponentType<{ item: ResourceItem }>;
    /** Why a kind's own way of getting one can't be used on this deployment yet, in a sentence: its button is greyed
     *  out with these words (a computer of yours while agents don't run on machines here). */
    unavailable?: Partial<Record<KindId, string>>;
    /** Making one of a kind here (?kind=&new=1, over its list), started on `way` where one was picked (?way=): `onDone`
     *  takes the new item's id, or null when it was left. */
    Create?: Partial<Record<KindId, ComponentType<{ onDone: (id: string | null) => void; way?: string }>>>;
    /** The ways to get one, drawn in an empty kind's place of its button (a machine: renting one, or a computer of
     *  yours, each with its price). A pick opens that kind's Create on it, so its dialog outlives the list filling in. */
    Empty?: Partial<Record<KindId, ComponentType<{ onPick: (way: string) => void }>>>;
    /** A notice above a kind's list, where something about the whole kind waits (machines: NoClick's company check). */
    Notice?: Partial<Record<KindId, ComponentType>>;
    /** A live figure a platform item's row shows beside its price (a website's requests this week), or nothing. */
    RowFigure?: ComponentType<{ item: ResourceItem }>;
    /** A kind whose rows lead with the platform's own mark in place of the kind's icon (an agent's face and ring). */
    Lead?: Partial<Record<KindId, ComponentType<{ item: ResourceItem }>>>;
    /** A kind whose item's page is the platform's own (an agent's: its files, spend and sessions), framed as every
     *  resource's page is (`ResourcePageFrame`), in place of the shared anatomy. */
    Page?: Partial<Record<KindId, ComponentType<{ item: ResourceItem; now: string; onBack: (to: 'all' | 'kind') => void }>>>;
    /** A kind whose rows end in a ⋯ menu of the platform's own (an agent's Rename), beside the row it acts on. */
    RowMenu?: Partial<Record<KindId, ComponentType<{ item: ResourceItem }>>>;
    /** Whether `item` is drawn by parts of its own: one of Work's kinds (workKinds.tsx), or what a host adds (slots.ts
     *  MORE_KINDS). Its lead, page and row menu above are for those alone. */
    hasOwnParts(item: ResourceItem): boolean;
    /** How `item`'s page removes it, or null where it offers nothing. */
    removal(item: ResourceItem): Removal | null;
    /** What's in the trash, by kind (only kinds whose deletion goes there). */
    trash: Partial<Record<KindId, TrashEntry[]>>;
    /** Puts `entry` back under its name; throws an Error saying why it couldn't (its name was taken again). */
    restore(entry: TrashEntry): Promise<void>;
    /** Deletes `entry` for good now; throws an Error saying why it couldn't. */
    purge(entry: TrashEntry): Promise<void>;
}

/** Resources' reads, around the page (reads.tsx). */
export const PlatformResourcesContext = createContext<PlatformResources | null>(null);

/** Resources' reads, inside them; null outside. */
export function usePlatformResources(): PlatformResources | null {
    return useContext(PlatformResourcesContext);
}
