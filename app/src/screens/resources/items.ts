// The platform's resources as Resources lists them: each domain, email address,
// app, database, bucket and repo the account holds, its users' included, with the
// words its row and page show, what it costs where it has a price of its own, and
// where each name an app is served at stands. An app NoClick published from an
// automation's interface and the database an automation keeps its tables in name
// that automation; an item of one of the account's users names that user. A
// repo also gets the reader its page browses it with, and every kind the way its
// page removes it.
import type { KindId } from './kinds';
import type { DeletionImpact, Removal, TrashEntry } from './platform';
import type { RepoReader, RepoSummary } from './RepoBrowser';
import type { DnsRecordRow } from './ResourceDetail';
import type { ResourceItem, ResourceOwner, ResourceUser } from './model';
import type { WorkflowRef } from './files';
import { countOf, fmtBytes } from '@/ui/primitives';
import { servedNames, type ServedName } from '@/screens/console/pages/resources/appDomains';
import { dayLabel, registeredHere, sourceLabel } from '@/screens/console/pages/resources/DomainsParts';
import { NoClickError, type Bucket, type NoClick, type Database, type DnsRecord, type Domain, type Inbox, type Project, type Repo, type TrashItem, type UsedBy } from 'noclick';
import { authorName, decodeText, isBinaryPath, refFor } from '@/lib/repoText';


const iso = (date: Date | null | undefined) => date?.toISOString() ?? null;

/** The automation an app or database came from, while it still has one. */
function origin(workflow: { id: string; name: string | null } | null): WorkflowRef | undefined {
    return workflow?.name ? { id: workflow.id, name: workflow.name, marks: [] } : undefined;
}

/** The one of the account's users `userId` names: by its name where `names` (the users read) has one, else by your id
 * for it. None for the account's own. */
export function ownerOf(userId: string | null, names: ReadonlyMap<string, string>): ResourceOwner | undefined {
    return userId ? { id: userId, name: names.get(userId) ?? userId } : undefined;
}

/** `item`, marked with the user its object belongs to; the account's own stays as it is. */
export function withOwner(item: ResourceItem, userId: string | null, names: ReadonlyMap<string, string>): ResourceItem {
    const owner = ownerOf(userId, names);
    return owner ? { ...item, owner } : item;
}

/** NoClick keeps its DNS: a bought domain (from before its zone is made), or one moved to NoClick's DNS. */
const dnsHere = (d: Domain) => d.noClickDns || d.source === 'bought';

/** A record it needs that its DNS host doesn't answer with yet. */
const awaitsRecords = (d: Domain) => d.records.some((r) => r.required && r.status !== 'verified');

/** What a domain is doing, in a few words, and what its page says about it. */
export function domainState(d: Domain): { words: string; attention?: string; pending?: string } {
    const day = dayLabel(d.expiresAt);
    switch (d.status) {
        case 'awaiting_human':
            return { words: 'Waiting for approval', pending: 'Your account’s policy holds purchases for a person to approve. It’s charged once they do.' };
        case 'registering':
            return { words: 'Registering', pending: 'Registering it with the registry. It’s charged once the registry confirms, usually within a minute.' };
        case 'transferring_in':
            return { words: 'Transferring in', pending: 'Moving it from its current registrar, which can take up to five days.' };
        case 'pending_dns':
            if (dnsHere(d)) return { words: 'Setting up DNS', pending: 'NoClick is setting up its DNS. It works in a few minutes.' };
            return awaitsRecords(d)
                ? { words: 'Waiting for DNS', pending: 'Add the records below where its DNS is hosted. It goes live a few minutes after.' }
                : { words: 'Getting a certificate', pending: 'Its records are in place. It goes live once its certificate is issued, usually within a few minutes.' };
        case 'registrant_unverified': {
            const by = d.registrantVerifyBy ? ` by ${dayLabel(d.registrantVerifyBy)}, or the domain stops working` : '';
            return { words: 'Confirm the registrant', pending: `${d.registrantEmail ?? 'The registrant'} was sent a link to confirm their address. Confirm it${by}.` };
        }
        case 'expiring':
            return { words: `Expires ${day}`, pending: `It expires on ${day} unless it’s renewed.` };
        case 'expired':
            return { words: 'Expired', attention: `It expired on ${day}.` };
        case 'transferring_out':
            return { words: 'Transferring out' };
        case 'failed':
            return { words: 'Failed', attention: 'Registering it failed, and nothing was charged.' };
        default:
            return { words: 'Active' };
    }
}

/** Statuses that settle by themselves: frames say when they move, and a list holding one is re-read as a backstop. */
export const SETTLING_DOMAIN_STATUSES: ReadonlySet<string> = new Set(['awaiting_human', 'registering', 'transferring_in', 'pending_dns', 'transferring_out']);

export interface ServingState {
    /** `live`; `certificate`: its records are in place and the name waits on its certificate; `waiting` on its domain; `attention`: its domain is gone. */
    step: 'live' | 'certificate' | 'waiting' | 'attention';
    /** A few words for its status. */
    words: string;
    /** What it waits on, or that it's live, in a sentence. */
    detail: string;
}

const CERTIFICATE: ServingState = { step: 'certificate', words: 'Getting a certificate', detail: 'Waiting for its certificate, usually a few minutes.' };

/**
 * Where an app's name stands. It's live once the app lists one of its names as live, whatever its domain does
 * meanwhile (a connected domain waits again while another name under it is set up), unless the domain is gone; until
 * then its domain's own state says what it waits on, and once that's settled, it waits on its certificate.
 */
export function servingState(served: ServedName, project: Pick<Project, 'domainNames'>): ServingState {
    const d = served.domain;
    const state = domainState(d);
    if (state.attention) return { step: 'attention', words: state.words, detail: state.attention };
    const live = served.stops.filter((h) => project.domainNames.includes(h));
    if (live.length) return { step: 'live', words: 'Live', detail: `Your site is live at ${live.join(' and ')}.` };
    switch (d.status) {
        case 'registering':
            return { step: 'waiting', words: state.words, detail: `Registering ${d.name}, usually within a minute.` };
        case 'awaiting_human':
        case 'transferring_in':
            return { step: 'waiting', words: state.words, detail: state.pending ?? '' };
        case 'pending_dns':
            if (dnsHere(d)) return { step: 'waiting', words: state.words, detail: state.pending ?? '' };
            if (awaitsRecords(d)) return { step: 'waiting', words: state.words, detail: `Add its DNS records where ${d.name}'s DNS is hosted. It goes live a few minutes after.` };
            return CERTIFICATE;
        default:
            return CERTIFICATE;
    }
}

/** Whether a domain's own name could show a website: it isn't gone, and shows none there yet. */
export function freeForWebsite(d: Domain): boolean {
    return !['failed', 'expired', 'transferring_out'].includes(d.status) && !d.serves.some((s) => s.kind === 'project' && s.hostname === d.name);
}

/**
 * Whether a name some app is served at waits on its certificate: its domain may say nothing more about it, so the apps
 * are read again as the backstop. A domain's own name and its www are one: a bare connected domain serves at www
 * alone when its optional apex record is never added.
 */
export function awaitingCertificate(domains: readonly Domain[], projects: readonly Project[]): boolean {
    return projects.some((p) => servedNames(domains, p.id).some((name) => servingState(name, p).step === 'certificate'));
}

/** An API call's own steps ("Buy it (POST /v1/domains)", "List them with GET .../objects") mean nothing on these pages. */
const API_CALL = /\b(GET|POST|PUT|PATCH|DELETE) (\/|\.\.\.)|\/v1\//;

/** Why the platform refused, in Resources' words: its next step only where it names no API call. */
export function refusalText(error: unknown): string {
    if (!(error instanceof NoClickError)) return error instanceof Error ? error.message : String(error);
    return error.nextStep && !API_CALL.test(error.nextStep) ? `${error.message} ${error.nextStep}` : error.message;
}

/** Why a website couldn't go on a name or come off it, in Resources' words. */
export function servingRefusal(error: unknown): string {
    if (error instanceof NoClickError && error.type === 'payment_required') return 'Your balance can’t cover it right now. Top up, then try again.';
    // A name nobody holds is connected, and one that isn't registered can't be.
    if (error instanceof NoClickError && error.type === 'not_available' && error.details.field === 'name') return `${error.message} Check the spelling, or buy it under Domains.`;
    return refusalText(error);
}

function servesLine(d: Domain): string | null {
    const names = [...new Set(d.serves.map((s) => s.name))];
    return names.length ? names.join(', ') : null;
}

export function domainItem(d: Domain): ResourceItem {
    const state = domainState(d);
    const serves = servesLine(d);
    const here = registeredHere(d);
    const yearly = here && d.renewalUsd != null && d.renewalYears ? d.renewalUsd / d.renewalYears : undefined;
    return {
        id: d.id,
        kind: 'domains',
        title: d.name,
        subtitle: [state.words, serves ? `Serves ${serves}` : 'Not in use yet'].join(' · '),
        updatedAt: iso(d.createdAt),
        usedBy: [],
        ...(state.attention ? { attention: state.attention } : {}),
        ...(state.pending ? { pending: state.pending } : {}),
        // A connected domain renews where it's registered: NoClick charges nothing for it.
        ...(here ? (yearly !== undefined ? { price: { usd: yearly, per: 'year' as const } } : {}) : { price: null }),
        platform: {
            facts: [
                ['Status', state.words],
                ...(here ? ([[d.autoRenew ? 'Renews' : 'Expires', dayLabel(d.expiresAt)]] as [string, string][]) : []),
                ['Source', sourceLabel(d)],
                ['Serves', serves ?? 'Nothing yet'],
            ],
            ...(serves ? { url: `https://${d.name}` } : {}),
        },
    };
}

/** A domain's records as its page lists them: kept by NoClick for a bought one, to add where its DNS is for a connected one. */
export function domainRecords(d: Domain): DnsRecordRow[] {
    return d.records.map((r: DnsRecord) => ({
        type: r.type,
        name: r.name,
        value: r.value,
        status: r.status === 'verified' ? 'found' : r.status === 'conflict' ? 'conflict' : 'waiting',
    }));
}

const DEPLOY_WORDS: Record<string, string> = { queued: 'Queued', building: 'Building', ready: 'Live', failed: 'Failed', canceled: 'Canceled' };

export function appItem(p: Project, spentUsd: number | undefined): ResourceItem {
    const production = p.production;
    const words = production ? (DEPLOY_WORDS[production.status] ?? production.status) : 'Not deployed';
    const domains: [string, string] = ['Domains', p.domainNames.length ? p.domainNames.join(', ') : 'None'];
    return {
        id: p.id,
        kind: 'apps',
        title: p.name,
        subtitle: `${p.hostname} · ${words}`,
        updatedAt: iso(production?.createdAt ?? p.createdAt),
        usedBy: [],
        origin: origin(p.workflow),
        ...(production?.status === 'failed' ? { attention: `Its last production deploy failed${production.error ? `: ${production.error}` : '.'}` } : {}),
        // What a published interface uses is the account's own usage, not the platform's.
        ...(spentUsd !== undefined && !p.published ? { price: { usd: spentUsd, per: 'so-far' as const } } : {}),
        platform: {
            facts: p.published
                ? [
                      ['Address', p.hostname],
                      ['Production', words],
                      ['Published', production?.createdAt ? dayLabel(production.createdAt) : '—'],
                      domains,
                  ]
                : [
                      ['Address', p.hostname],
                      ['Production', words],
                      ['Deployed', production?.createdAt ? dayLabel(production.createdAt) : '—'],
                      ['Branch', p.productionBranch],
                      ['Runtime', p.runtime === 'edge' ? 'Edge' : 'Container'],
                      domains,
                  ],
            url: p.url,
            ...(p.published ? { unpublish: true } : {}),
        },
    };
}

/** The domains any email address works on: active ones whose DNS NoClick keeps, the account's and its users'. */
export function mailDomains(domains: readonly Domain[]): string[] {
    return domains.filter((d) => d.status === 'active' && dnsHere(d)).map((d) => d.name);
}

/** An inbox, as the email address it is. Its mail is its page's body. */
export function inboxItem(i: Inbox): ResourceItem {
    return {
        id: i.id,
        kind: 'email',
        title: i.address,
        subtitle: i.agentId ? 'An agent answers its mail' : 'Mail sent to it arrives here',
        updatedAt: iso(i.createdAt),
        usedBy: [],
        platform: {
            facts: [
                ['Answered by', i.agentId ? 'An agent' : 'You'],
                ['Created', dayLabel(i.createdAt)],
            ],
        },
    };
}

const ENGINES: Record<string, string> = { postgres: 'Postgres', sqlite: 'SQLite' };

export function databaseItem(db: Database): ResourceItem {
    const engine = ENGINES[db.engine] ?? db.engine;
    const used = db.usedBy.map((u) => u.name);
    const from = origin(db.workflow);
    return {
        id: db.id,
        kind: 'databases',
        // An automation's tables are kept in a database named for it.
        title: from?.name ?? db.name,
        subtitle: [engine, db.tableCount != null ? countOf(db.tableCount, 'table') : null, db.sizeBytes != null ? fmtBytes(db.sizeBytes) : null].filter(Boolean).join(' · '),
        updatedAt: iso(db.createdAt),
        usedBy: [],
        origin: from,
        // Its page lists the automation's tables (Resources adds them from the overview).
        ...(db.workflow ? { tables: [] } : {}),
        ...(db.status === 'restoring' ? { pending: 'Restoring to an earlier time. It answers again once that’s done.' } : {}),
        ...(db.status === 'branching' ? { pending: 'Making a branch of it. It answers as usual meanwhile.' } : {}),
        platform: {
            facts: [
                ['Engine', engine],
                ['Region', db.region ?? 'Any'],
                ['Size', db.sizeBytes != null ? fmtBytes(db.sizeBytes) : '—'],
                ['Created', db.createdAt ? dayLabel(db.createdAt) : '—'],
                ['Used by', used.length ? used.join(', ') : 'Nothing yet'],
            ],
        },
    };
}

/** What the platform says uses a resource, as Resources names it: the apps that bind it and the agents with it in their tools. */
function usersOf(usedBy: readonly UsedBy[]): ResourceUser[] {
    return usedBy.map((u) => ({ kind: u.kind === 'agent' ? 'agent' : 'app', id: u.id, name: u.name, binding: u.binding }));
}

/** A bucket: whether it's public, what it holds, and the apps and agents that use it. Its files are its page's body. */
export function bucketItem(b: Bucket): ResourceItem {
    const access = b.public ? 'Public' : 'Private';
    const files = b.objectCount != null ? countOf(b.objectCount, 'file') : null;
    const size = b.sizeBytes != null ? fmtBytes(b.sizeBytes) : null;
    return {
        id: b.id,
        kind: 'storage',
        title: b.name,
        subtitle: [access, files, size].filter(Boolean).join(' · '),
        updatedAt: iso(b.createdAt),
        usedBy: [],
        users: usersOf(b.usedBy),
        platform: {
            facts: [
                ['Access', access],
                ['Files', b.objectCount != null ? b.objectCount.toLocaleString('en-US') : '—'],
                ['Size', size ?? '—'],
                ['Region', b.region ?? 'Any'],
                ['Created', b.createdAt ? dayLabel(b.createdAt) : '—'],
            ],
        },
    };
}

export function repoItem(r: Repo): ResourceItem {
    const last = r.lastCommit;
    return {
        id: r.id,
        kind: 'repos',
        title: r.name,
        subtitle: `${r.defaultBranch} · ${last?.message ?? 'Nothing committed yet'}`,
        updatedAt: iso(last?.createdAt ?? r.createdAt),
        usedBy: [],
        // A repo is its browser: its facts live beside the files.
        platform: { facts: [] },
    };
}

export function repoSummary(r: Repo): RepoSummary {
    return { defaultBranch: r.defaultBranch, sizeBytes: r.sizeBytes, usedBy: r.usedBy.map((u) => ({ id: u.id, name: u.name })), createdAt: iso(r.createdAt) };
}

/** Reads a repo through the platform API: names that are never text aren't fetched, nor is its default branch named. */
export function repoReader(r: Repo): RepoReader {
    const at = (ref: string) => refFor(ref, r.defaultBranch);
    const commit = (c: { sha: string; message: string; author: string | null; createdAt: Date | null }) => ({
        sha: c.sha,
        message: c.message,
        author: c.author && authorName(c.author),
        at: iso(c.createdAt),
    });
    return {
        branches: async () => (await r.branches()).map((b) => b.name),
        list: async (dir, ref) => (await r.files(dir, { ref: at(ref) })).map((f) => ({ path: f.path, dir: f.type === 'dir', size: f.size, link: f.type === 'link' })),
        read: async (path, ref) => (isBinaryPath(path) ? null : decodeText(await r.read(path, { ref: at(ref) }))),
        history: async (ref, cursor, limit) => {
            const page = await r.commitsPage({ branch: at(ref), cursor: cursor ?? undefined, limit });
            return { commits: page.data.map(commit), next: page.nextCursor };
        },
        commit: async (sha) => {
            const d = await r.diff(sha);
            return {
                ...commit(d.commit),
                parents: d.parents,
                additions: d.additions,
                deletions: d.deletions,
                files: d.files.map((f) => ({ path: f.path, oldPath: f.oldPath, status: f.status, additions: f.additions, deletions: f.deletions, size: f.size, patch: f.patch })),
            };
        },
    };
}

/** The trash's kinds as Resources lists them: an app's Durable Object class (`app/Class`) under the websites, and
 * what a database's restore rewound (a database copy, which restoring puts back into it) under the databases. */
const TRASH_KINDS: Partial<Record<string, KindId>> = {
    project: 'apps',
    durable_object_class: 'apps',
    inbox: 'email',
    database: 'databases',
    database_copy: 'databases',
    bucket: 'storage',
    repo: 'repos',
    skill: 'skills',
    memory: 'memories',
};

/** What's in the trash, the account's users' included, by the Resources kind it comes back to. */
export function trashByKind(items: TrashItem[], names: ReadonlyMap<string, string>): Partial<Record<KindId, TrashEntry[]>> {
    const out: Partial<Record<KindId, TrashEntry[]>> = {};
    for (const item of items) {
        const kind = TRASH_KINDS[item.kind];
        if (!kind) continue;
        const owner = ownerOf(item.userId, names);
        (out[kind] ??= []).push({ id: item.id, name: item.name ?? item.resourceId, trashedAt: iso(item.trashedAt), purgeAfter: iso(item.purgeAfter), ...(owner ? { owner } : {}) });
    }
    return out;
}

/** What the platform says `DELETE path` would do (`POST /v1/delete_previews`), asked as `user` (null: the account): a
 * user's resource is reached only by a call acting for that user. */
export type DeletePreviewer = (path: string, user: string | null) => Promise<DeletionImpact>;

/** The platform's own deletion preview, through `client`. */
export function deletePreviewer(client: NoClick): DeletePreviewer {
    return async (path, user) => (await client.request<{ impact: DeletionImpact }>('POST', '/v1/delete_previews', { json: { method: 'DELETE', path }, user })).impact;
}

/** How a kind's page removes it, the way the platform API does: a connected domain is disconnected (it stays
 * registered wherever it is), a domain registered here only lapses (auto-renew off), an app, an address, a database, a
 * bucket (its files with it) or a repo goes to the trash (restorable for 30 days). Null where the page offers nothing: a registered
 * domain already set to lapse, an app NoClick publishes (it's unpublished instead), an automation's database (it goes
 * with the automation). */
export function removalOf(kind: KindId, object: Domain | Inbox | Project | Database | Bucket | Repo, preview: DeletePreviewer): Removal | null {
    const previewOf = (path: string) => preview(path, object.userId);
    const trashing = (path: string, name: string, remove: () => Promise<TrashItem>): Removal => ({
        label: 'Move to trash',
        confirm: `Move ${name} to the trash`,
        preview: () => previewOf(path),
        run: async () => {
            await remove();
            return { done: `Moved ${name} to the trash`, gone: true };
        },
    });
    switch (kind) {
        case 'domains': {
            const d = object as Domain;
            const path = `/v1/domains/${d.id}`;
            if (!registeredHere(d)) {
                return {
                    label: 'Remove',
                    confirm: `Disconnect ${d.name}`,
                    preview: () => previewOf(path),
                    run: async () => {
                        await d.delete();
                        return { done: `Disconnected ${d.name}`, gone: true };
                    },
                };
            }
            if (!d.autoRenew) return null;
            return {
                label: 'Let it lapse',
                confirm: 'Turn off auto-renew',
                // The platform's words for why it can only lapse; turning auto-renew back on before then undoes it.
                preview: async () => ({ ...(await previewOf(path)), reversible: true }),
                run: async () => {
                    await d.update({ autoRenew: false });
                    return { done: `${d.name} won’t renew: it stays yours until ${dayLabel(d.expiresAt)}`, gone: false };
                },
            };
        }
        case 'email': {
            const inbox = object as Inbox;
            return trashing(`/v1/inboxes/${inbox.id}`, inbox.address, () => inbox.delete());
        }
        case 'apps': {
            const app = object as Project;
            return app.published ? null : trashing(`/v1/projects/${app.id}`, app.name, () => app.delete());
        }
        case 'databases': {
            const db = object as Database;
            return db.workflow ? null : trashing(`/v1/databases/${db.id}`, db.name, () => db.delete());
        }
        case 'storage': {
            const bucket = object as Bucket;
            // Previewed and deleted forced: its files go to the trash with it (the API refuses a bucket holding any).
            const forced = `/v1/buckets/${bucket.id}?force=true`;
            return trashing(forced, bucket.name, () => bucket.delete({ force: true }));
        }
        case 'repos': {
            const repo = object as Repo;
            return trashing(`/v1/repos/${repo.id}`, repo.name, () => repo.delete());
        }
        default:
            return null;
    }
}
