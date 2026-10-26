// What the Resources page lists: every kind the account can own, the items of
// each, and the payload an item's page needs. Numbers, files and tables come
// from the dashboard overview (numbers are phone_number credentials; files and
// tables are workflow resources, workspaces agent volumes). Domains, email
// addresses (inboxes), apps, databases, buckets and repos are the platform's, read by the
// registered platform (platform.tsx) for the signed-in account, its platform users'
// (`owner`) beside its own: an automation's
// published interface is one of its apps. An automation's tables are a
// database: the one a platform keeps them in, else one per automation here.
import { useCallback, useMemo } from 'react';
import { countOf } from '~/components/dashboard/primitives';
import type { CredentialEntry, FileEntry, FileSource, WorkflowRef } from '~/components/dashboard/types';
import { fetchDashboardOverview, useDashboardOverview, type WorkspaceRef } from '~/hooks/useDashboardOverview';
import { basename } from './fileParts';
import { KINDS, visibleKinds, type KindId } from './kinds';
import { hasPlatformResources, usePlatformResources } from './platform';

export { KINDS, kindDef, type KindDef, type KindId } from './kinds';

/** What an item costs, where it has a price of its own (in US dollars). */
export interface ItemPrice {
    usd: number;
    /** `year`: what a year of it renews at; `month`: a monthly charge; `so-far`: what its use has cost this month. */
    per: 'year' | 'month' | 'so-far';
}

/** A platform resource's page: its facts and its live address. */
export interface PlatformDetail {
    facts: [string, string][];
    /** Where it's served, for Open and Copy link. */
    url?: string;
    /** An app NoClick publishes from an automation's interface: taken down by unpublishing it. */
    unpublish?: boolean;
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

/** A file or table, as the overview lists it. */
export interface FileRef {
    entry: FileEntry;
    source: FileSource;
}

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
    credential?: CredentialEntry;
    file?: FileRef;
    /** A database of an automation's tables: those tables. */
    tables?: FileRef[];
    workspace?: WorkspaceRef;
    platform?: PlatformDetail;
}

/** An automation's tables no listed database holds: a database of their own, named for the automation. */
function automationTables(id: string, tables: FileRef[]): ResourceItem {
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
    const { overview, loading } = useDashboardOverview();
    const platform = usePlatformResources();

    const items = useMemo(() => {
        const byKind: Record<KindId, ResourceItem[]> = { numbers: [], domains: [], email: [], apps: [], databases: [], storage: [], repos: [], files: [] };
        for (const c of overview?.credentials ?? []) {
            if (c.credentialType !== 'phone_number') continue;
            const dropped = c.health === 'disconnected' || c.health === 'revoked';
            byKind.numbers.push({
                id: c.id,
                kind: 'numbers',
                title: c.name,
                subtitle: dropped ? (c.healthDetail ?? 'Not reachable') : 'Calls and texts',
                updatedAt: c.lastRefreshAt ?? c.createdAt,
                usedBy: c.usedBy,
                attention: dropped ? (c.healthDetail ?? 'This number is not reachable.') : undefined,
                credential: c,
            });
        }
        // Each automation's tables, by the database they're kept in (else by automation).
        const tables = new Map<string, FileRef[]>();
        for (const source of overview?.files ?? []) {
            for (const entry of source.files) {
                if (entry.resourceType === 'dataset') {
                    const key = entry.databaseId ?? `tables:${source.workflow?.id ?? source.id}`;
                    tables.set(key, [...(tables.get(key) ?? []), { entry, source }]);
                    continue;
                }
                byKind.files.push({
                    id: entry.resourceId ?? `${source.id}:${entry.path}`,
                    kind: 'files',
                    title: basename(entry.path),
                    subtitle: source.workflow?.name ?? source.label,
                    updatedAt: entry.mtime,
                    usedBy: source.workflow ? [source.workflow] : [],
                    file: { entry, source },
                });
            }
        }
        for (const w of overview?.workspaces ?? []) {
            byKind.files.push({
                id: `workspace:${w.id}`,
                kind: 'files',
                title: `${w.agent.label} workspace`,
                subtitle: w.conversationTitle || w.conversationKey,
                updatedAt: w.lastActivity,
                usedBy: [w.workflow],
                workspace: w,
            });
        }
        for (const k of KINDS) if (k.platform) byKind[k.id] = platform?.items[k.id] ?? [];
        for (const db of platform?.items.databases ?? []) {
            const held = tables.get(db.id);
            tables.delete(db.id);
            byKind.databases.push(held ? { ...db, tables: held } : db);
        }
        for (const [id, list] of tables) byKind.databases.push(automationTables(id, list));
        const newest = (a: ResourceItem, b: ResourceItem) => (b.updatedAt ?? '').localeCompare(a.updatedAt ?? '');
        for (const k of Object.keys(byKind) as KindId[]) byKind[k] = [...byKind[k]].sort(newest);
        return byKind;
    }, [overview, platform?.items]);

    const refresh = useCallback(() => {
        void fetchDashboardOverview();
        platform?.refresh();
    }, [platform]);
    // A platform registers before anything renders, so the kinds are fixed for the page's life.
    const kinds = useMemo(() => visibleKinds({ platform: hasPlatformResources() }), []);

    return {
        items,
        kinds,
        loading: (!overview && loading) || !!platform?.loading,
        /** Why a platform kind couldn't be read. */
        errors: platform?.errors ?? {},
        now: overview?.generatedAt ?? new Date().toISOString(),
        refresh,
    };
}
