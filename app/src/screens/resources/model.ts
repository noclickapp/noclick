// What the Resources page lists: every kind the account can own, the items of each, and the payload an item's page
// needs. What workflows keep (files and tables) and the account's own files are read through /v1 (kept.ts); domains,
// email addresses (inboxes), apps, databases, buckets, repos, numbers and Work's kinds (agents, skills, memories,
// machines, secrets) by the reads around the page (reads.tsx), the account's users' (`owner`) beside its own, with
// whatever items a host adds. An automation's published interface is one of its apps, and its tables are a database:
// the one the platform keeps them in, else one per automation here.
import { useCallback, useContext, useMemo, type ReactNode } from 'react';
import { countOf } from '@/ui/primitives';
import { ConsoleContext } from '@/screens/console/hooks/useConsole';
import type { WorkflowRef } from './files';
import { basename } from './fileParts';
import { refreshKept, useKept, type FileRef, type TableRef } from './kept';
import { KINDS, type KindId } from './kinds';
import { usePlatformResources } from './platform';

export { KINDS, kindDef, type KindDef, type KindId } from './kinds';

/** What an item costs, where it has a price of its own (in US dollars). */
export interface ItemPrice {
    usd: number;
    /** `year`: what a year of it renews at; `month`: a monthly charge; `so-far`: what its use has cost this month. */
    per: 'year' | 'month' | 'so-far';
}

/** A platform resource's page: its facts and its live address. */
export interface PlatformDetail {
    facts: [string, ReactNode][];
    /** Where it's served, for Open and Copy link. */
    url?: string;
    /** An app NoClick publishes from an automation's interface: taken down by unpublishing it. */
    unpublish?: boolean;
    /** Its body draws who uses it (with what each may do), so the page doesn't list them twice. */
    usersInBody?: boolean;
}

/** What uses a platform resource: an app that binds it (as `binding`), or an agent with it in its tools. */
export interface ResourceUser {
    kind: 'app' | 'agent';
    id: string;
    name: string;
    binding: string | null;
}

/** One of the account's platform users, whose resource it is (the account's own resources have none). */
export interface ResourceOwner {
    /** Your id for the user. */
    id: string;
    /** Its name, else its id. */
    name: string;
}

export type { FileRef, TableRef } from './kept';

export interface ResourceItem {
    id: string;
    kind: KindId;
    title: string;
    subtitle: string;
    /** When it last changed, for "2h ago". */
    updatedAt?: string | null;
    usedBy: WorkflowRef[];
    /** The apps and agents that use it, for a platform resource (`usedBy` names automations). */
    users?: ResourceUser[];
    /** The automation it came from (an interface published as an app, the database of an automation's tables). */
    origin?: WorkflowRef;
    /** The one of the account's users it belongs to (an app a coding agent made for them, say). */
    owner?: ResourceOwner;
    /** Something about it is broken (a dropped number, a domain that expired). */
    attention?: string;
    /** A step that breaks nothing yet (a DNS record to add, a registration under way). */
    pending?: string;
    /** Its own price; null when it costs nothing (a domain registered elsewhere). */
    price?: ItemPrice | null;
    /** Where it works, beside its line (an agent: the spaces it works in, or your account where it's in none). */
    where?: string;
    /** A mark to lead its row and page with in place of its kind's icon (an agent's, by what it runs on). */
    mark?: string;
    /** Where opening it goes when its page is elsewhere (an agent's, in Work), in place of a page here. */
    open?: () => void;
    file?: FileRef;
    /** A database of an automation's tables: those tables. */
    tables?: TableRef[];
    platform?: PlatformDetail;
}

/** An automation's tables no listed database holds: a database of their own, named for the automation. */
function automationTables(id: string, tables: TableRef[]): ResourceItem {
    const workflow = tables[0].source.workflow;
    const rows = tables.reduce((sum, t) => sum + (t.entry.rows ?? 0), 0);
    return {
        id,
        kind: 'databases',
        title: workflow?.name ?? tables[0].source.label,
        subtitle: [countOf(tables.length, 'table'), countOf(rows, 'row')].join(' · '),
        updatedAt: tables.reduce((latest, t) => (t.entry.mtime > latest ? t.entry.mtime : latest), ''),
        usedBy: [],
        origin: workflow,
        tables,
    };
}

export function useResourceItems() {
    const kept = useKept();
    const platform = usePlatformResources();
    const consoleNow = useContext(ConsoleContext)?.now;

    const items = useMemo(() => {
        const byKind: Record<KindId, ResourceItem[]> = { agents: [], numbers: [], domains: [], email: [], apps: [], databases: [], storage: [], skills: [], memories: [], machines: [], secrets: [], repos: [], files: [] };
        // Each automation's tables, by the database they're kept in (else by automation).
        const tables = new Map<string, TableRef[]>();
        for (const table of kept.tables) {
            const key = table.entry.databaseId ?? `tables:${table.source.workflow?.id ?? table.source.id}`;
            tables.set(key, [...(tables.get(key) ?? []), table]);
        }
        for (const file of kept.files) {
            byKind.files.push({
                id: file.entry.resourceId ?? `${file.source.id}:${file.entry.path}`,
                kind: 'files',
                title: basename(file.entry.path),
                subtitle: file.source.workflow?.name ?? file.source.label,
                updatedAt: file.entry.mtime,
                usedBy: file.source.workflow ? [file.source.workflow] : [],
                file,
            });
        }
        for (const k of KINDS) if (k.id !== 'databases') byKind[k.id].push(...(platform?.items[k.id] ?? []));
        for (const db of platform?.items.databases ?? []) {
            const held = tables.get(db.id);
            tables.delete(db.id);
            byKind.databases.push(held ? { ...db, tables: held } : db);
        }
        for (const [id, list] of tables) byKind.databases.push(automationTables(id, list));
        const newest = (a: ResourceItem, b: ResourceItem) => (b.updatedAt ?? '').localeCompare(a.updatedAt ?? '');
        for (const k of Object.keys(byKind) as KindId[]) byKind[k] = [...byKind[k]].sort(newest);
        return byKind;
    }, [kept.files, kept.tables, platform?.items]);

    const refresh = useCallback(() => {
        refreshKept();
        platform?.refresh();
    }, [platform]);

    // Each kind draws once its own sources answer: /v1 for what workflows keep (files, an automation's tables) and the
    // account's files, the reads around the page for the rest.
    const ownLoading: Partial<Record<KindId, boolean>> = { files: kept.loading.files, databases: kept.loading.tables };
    const kindLoading = Object.fromEntries(KINDS.map((k) => [k.id, !!ownLoading[k.id] || !!platform?.loading[k.id]])) as Record<KindId, boolean>;
    const errors: Partial<Record<KindId, string>> = { ...platform?.errors, ...(kept.errors.files ? { files: kept.errors.files } : {}) };
    if (kept.errors.tables && !errors.databases) errors.databases = kept.errors.tables;

    return {
        items,
        /** By kind: true until what its list is drawn from has answered. */
        loading: kindLoading,
        /** Why a kind couldn't be read. */
        errors,
        now: new Date(consoleNow ? consoleNow() : Date.now()).toISOString(),
        refresh,
    };
}
