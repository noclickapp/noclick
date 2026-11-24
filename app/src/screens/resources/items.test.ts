// The platform's resources as Resources lists them, read over a fake
// transport: what each row and page says, what each costs, where the console
// manages it, where a website's name at a domain stands, how a repo is
// read (a binary file is never fetched), what uses a bucket, and which of the
// account's users an item belongs to.
import { describe, expect, it } from 'vitest';
import { ALL_USERS, Bucket, Conflict, Database, Domain, NO_USER, NoClick, NotAvailable, NotFound, PaymentRequired, Project, Repo, type TrashItem } from 'noclick';
import { RECORDED, RECORDED_REPO_ID } from '@/screens/console/fixtures/repoWire';
import { servedNames } from '@/screens/console/pages/resources/appDomains';
import {
    appItem,
    awaitingCertificate,
    bucketItem,
    databaseItem,
    domainItem,
    domainRecords,
    freeForWebsite,
    mailDomains,
    refusalText,
    removalOf,
    repoItem,
    repoReader,
    repoSummary,
    servingRefusal,
    servingState,
    trashByKind,
    withOwner,
} from './items';

function client(rows: Record<string, unknown[]>, files: Record<string, string> = {}, objects: Record<string, object> = {}) {
    const paths: string[] = [];
    const fetch: typeof globalThis.fetch = async (input) => {
        const url = new URL(typeof input === 'string' ? input : input instanceof URL ? input.href : input.url);
        paths.push(`${url.pathname}${url.search}`);
        const file = url.searchParams.get('path');
        if (file !== null) return new Response(files[file] ?? '', { status: 200, headers: { 'Content-Type': 'application/octet-stream' } });
        if (objects[url.pathname]) return new Response(JSON.stringify(objects[url.pathname]), { status: 200, headers: { 'Content-Type': 'application/json' } });
        return new Response(JSON.stringify({ object: 'list', data: rows[url.pathname] ?? [], next_cursor: null }), { status: 200, headers: { 'Content-Type': 'application/json' } });
    };
    return { client: new NoClick({ apiKey: 'test-token', baseUrl: 'https://api.test', fetch, maxRetries: 0 }), paths };
}

const DOMAIN = {
    object: 'domain', id: 'dom_1', name: 'acmebooking.com', source: 'bought', noclick_dns: true, status: 'active', expires_at: '2027-03-14T00:00:00Z', auto_renew: true,
    renewal_usd: 18, renewal_years: 1, serves: [{ kind: 'project', id: 'prj_1', name: 'booking', hostname: 'acmebooking.com' }],
    records: [
        { type: 'ALIAS', name: '@', value: 'apps.noclick.site', status: 'verified', required: true, managed: true },
        { type: 'TXT', name: '_acme', value: 'x', status: 'pending', required: true, managed: true },
    ],
    user_id: null, created_at: '2026-09-01T00:00:00Z',
};

async function domains(...rows: object[]) {
    const { client: c } = client({ '/v1/domains': rows });
    return (await Domain.listPage({ client: c, userFilter: NO_USER })).data;
}

describe('a domain', () => {
    it('reads its status and what it serves, renews at a yearly price, and opens its console drawer', async () => {
        const [d] = await domains(DOMAIN);
        const item = domainItem(d);
        expect(item).toMatchObject({ id: 'dom_1', kind: 'domains', title: 'acmebooking.com', subtitle: 'Active · Serves booking', price: { usd: 18, per: 'year' } });
        expect(item.platform?.facts).toEqual([
            ['Status', 'Active'],
            ['Renews', 'Mar 14, 2027'],
            ['Source', 'Bought'],
            ['Serves', 'booking'],
        ]);
        expect(item.platform?.url).toBe('https://acmebooking.com');
        expect(Object.keys(item.platform!)).toEqual(['facts', 'url']);
        expect(domainRecords(d).map((r) => r.status)).toEqual(['found', 'waiting']);
    });

    it('says what a purchase in progress waits on, and costs nothing when it is registered elsewhere', async () => {
        const [registering, connected, failed] = await domains(
            { ...DOMAIN, id: 'dom_2', status: 'registering', serves: [] },
            { ...DOMAIN, id: 'dom_3', source: 'connected', noclick_dns: false, status: 'pending_dns', expires_at: null, auto_renew: null, renewal_usd: null, renewal_years: null, serves: [] },
            { ...DOMAIN, id: 'dom_4', status: 'failed', serves: [] }
        );
        expect(domainItem(registering)).toMatchObject({ subtitle: 'Registering · Not in use yet', pending: expect.stringContaining('charged once the registry confirms') });
        expect(domainItem(registering).platform?.url).toBeUndefined();
        const outside = domainItem(connected);
        expect(outside).toMatchObject({ subtitle: 'Waiting for DNS · Not in use yet', price: null, pending: expect.stringContaining('Add the records below') });
        expect(outside.platform?.facts.map(([label]) => label)).toEqual(['Status', 'Source', 'Serves']);
        expect(domainItem(failed).attention).toBe('Registering it failed, and nothing was charged.');
    });
});

describe("a website's name at a domain", () => {
    const at = (hostname: string) => ({ kind: 'project', id: 'prj_1', name: 'booking', hostname });
    const APP = {
        object: 'project', id: 'prj_1', name: 'booking', url: 'https://acmebooking.com', hostname: 'booking.noclick.site', repo_id: null, runtime: 'edge',
        production_branch: 'published', domain_names: ['acmebooking.com', 'www.acmebooking.com'], deploy_on_push: 'off', user_id: null, created_at: '2026-09-01T00:00:00Z',
    };

    /** The domains `rows`, and the apps: booking, then any others given as [id, the names it's live at]. */
    async function read(rows: object[], apps: [string, string[]][] = [['prj_1', APP.domain_names]]) {
        const { client: c } = client({ '/v1/domains': rows, '/v1/projects': apps.map(([id, live]) => ({ ...APP, id, domain_names: live })) });
        const projects = (await Project.listPage({ client: c, userFilter: NO_USER })).data;
        return { project: projects[0], projects, found: (await Domain.listPage({ client: c, userFilter: NO_USER })).data };
    }

    it('waits on its domain, then on its certificate, and is live once its app lists it', async () => {
        const both = (name: string) => [at(name), at(`www.${name}`)];
        const { project, found } = await read([
            { ...DOMAIN, serves: both('acmebooking.com') },
            { ...DOMAIN, id: 'dom_2', name: 'cakes.com', serves: both('cakes.com') },
            { ...DOMAIN, id: 'dom_3', name: 'pies.com', status: 'registering', serves: both('pies.com') },
            { ...DOMAIN, id: 'dom_4', name: 'tarts.com', status: 'expired', serves: both('tarts.com') },
        ]);
        const names = servedNames(found, project.id);
        expect(names.map((n) => [n.hostname, n.stops])).toEqual([
            ['acmebooking.com', ['acmebooking.com', 'www.acmebooking.com']],
            ['cakes.com', ['cakes.com', 'www.cakes.com']],
            ['pies.com', ['pies.com', 'www.pies.com']],
            ['tarts.com', ['tarts.com', 'www.tarts.com']],
        ]);
        expect(names.map((n) => servingState(n, project))).toEqual([
            { step: 'live', words: 'Live', detail: 'Your site is live at acmebooking.com and www.acmebooking.com.' },
            { step: 'certificate', words: 'Getting a certificate', detail: 'Waiting for its certificate, usually a few minutes.' },
            { step: 'waiting', words: 'Registering', detail: 'Registering pies.com, usually within a minute.' },
            { step: 'attention', words: 'Expired', detail: 'It expired on Mar 14, 2027.' },
        ]);
        // Only a settled domain's name still waits on its certificate, and only that keeps the apps read again.
        expect(awaitingCertificate(found, [project])).toBe(true);
        expect(awaitingCertificate([found[0], found[2], found[3]], [project])).toBe(false);
        expect(found.map(freeForWebsite)).toEqual([false, false, false, false]);
        expect(freeForWebsite((await read([{ ...DOMAIN, serves: [] }])).found[0])).toBe(true);
    });

    const connected = { source: 'connected', noclick_dns: false, expires_at: null, auto_renew: null, renewal_usd: null, renewal_years: null };

    it("is live at www alone when a bare connected domain's optional apex record is never added, and nothing waits on it", async () => {
        // As the API orders a connected domain's names: its www (primary) before its apex.
        const domain = { ...DOMAIN, ...connected, name: 'bakery.com', serves: [at('www.bakery.com'), at('bakery.com')], records: [] };
        const { project, found } = await read([domain], [['prj_1', ['www.bakery.com']]]);
        const [name] = servedNames(found, project.id);
        expect(name.stops).toEqual(['www.bakery.com', 'bakery.com']);
        expect(servingState(name, project)).toEqual({ step: 'live', words: 'Live', detail: 'Your site is live at www.bakery.com.' });
        expect(awaitingCertificate(found, [project])).toBe(false);
        // Until www is live, it waits on its certificate, and the app is read again.
        const waiting = await read([domain], [['prj_1', []]]);
        expect(awaitingCertificate(waiting.found, [waiting.project])).toBe(true);
    });

    it('stays live while its connected domain waits on another name added under it', async () => {
        const menu = { kind: 'project', id: 'prj_2', name: 'menu', hostname: 'menu.shop.example.org' };
        const domain = {
            ...DOMAIN,
            ...connected,
            name: 'shop.example.org',
            wildcard: true,
            status: 'pending_dns',
            serves: [at('shop.example.org'), menu],
            // The wildcard covers the new name: no record of its own to add.
            records: [{ type: 'CNAME', name: '*.shop', value: 'cname.noclick.site', status: 'verified', required: true, managed: false }],
        };
        const { projects, found } = await read([domain], [
            ['prj_1', ['shop.example.org']],
            ['prj_2', []],
        ]);
        const [booking, other] = projects;
        expect(servingState(servedNames(found, booking.id)[0], booking)).toEqual({ step: 'live', words: 'Live', detail: 'Your site is live at shop.example.org.' });
        expect(servingState(servedNames(found, other.id)[0], other)).toEqual(
            { step: 'certificate', words: 'Getting a certificate', detail: 'Waiting for its certificate, usually a few minutes.' }
        );
        expect(awaitingCertificate(found, [booking])).toBe(false);
        expect(awaitingCertificate(found, [booking, other])).toBe(true);
    });
});

describe('a domain waiting on DNS', () => {
    it('waits on NoClick setting its DNS up, on records to add where its DNS is hosted, or with them in place on its certificate', async () => {
        const verified = DOMAIN.records.map((r) => ({ ...r, managed: false, status: 'verified' }));
        const [transferred, outside, inPlace] = await domains(
            { ...DOMAIN, id: 'dom_5', source: 'transferred', status: 'pending_dns', serves: [] },
            { ...DOMAIN, id: 'dom_6', source: 'connected', noclick_dns: false, status: 'pending_dns', records: DOMAIN.records.map((r) => ({ ...r, managed: false })), serves: [] },
            { ...DOMAIN, id: 'dom_7', source: 'connected', noclick_dns: false, status: 'pending_dns', records: verified, serves: [] }
        );
        expect(domainItem(transferred)).toMatchObject({ subtitle: 'Setting up DNS · Not in use yet', pending: 'NoClick is setting up its DNS. It works in a few minutes.' });
        expect(domainItem(outside)).toMatchObject({ subtitle: 'Waiting for DNS · Not in use yet', pending: expect.stringContaining('Add the records below') });
        expect(domainItem(inPlace)).toMatchObject({ subtitle: 'Getting a certificate · Not in use yet', pending: expect.stringContaining('Its records are in place') });
    });
});

describe('a refusal to put a website on a name', () => {
    it('reads in plain words, leaving out next steps that name API calls', () => {
        const unregistered = new NotAvailable("bakery.cmo isn't registered, so there's nothing to connect.", {
            nextStep: 'Buy it (POST /v1/domains), or check the spelling.',
            details: { field: 'name' },
        });
        expect(servingRefusal(unregistered)).toBe("bakery.cmo isn't registered, so there's nothing to connect. Check the spelling, or buy it under Domains.");
        expect(servingRefusal(new NotFound("The app isn't served at bakery.com.", { nextStep: "List the app's domains with GET /v1/projects/{id}/domains." }))).toBe(
            "The app isn't served at bakery.com."
        );
        expect(servingRefusal(new Conflict('bakery.com is connected to another NoClick account.', { nextStep: 'Its owner disconnects it there first.' }))).toBe(
            'bakery.com is connected to another NoClick account. Its owner disconnects it there first.'
        );
        expect(servingRefusal(new PaymentRequired('Your account can’t pay for this: $0.10 left, $1.00 needed. Add funds in the console.'))).toBe(
            'Your balance can’t cover it right now. Top up, then try again.'
        );
    });

    it('reads any refusal the same way, a next step written with a shortened path included', () => {
        expect(refusalText(new NotFound("No such version of 'menu.txt': versions are kept 30 days.", { nextStep: 'List them with GET .../objects/versions?key=.' }))).toBe(
            "No such version of 'menu.txt': versions are kept 30 days."
        );
        expect(refusalText(new Conflict('The bucket is in the tools of concierge.', { nextStep: "Take it out of those agents' tools first." }))).toBe(
            "The bucket is in the tools of concierge. Take it out of those agents' tools first."
        );
        expect(refusalText(new Error('Network down'))).toBe('Network down');
    });
});

describe('an app, a database and a repo', () => {
    it("lists an app at its address with its production deploy and this month's spend", async () => {
        const { client: c } = client({
            '/v1/projects': [
                {
                    object: 'project', id: 'prj_1', name: 'booking', url: 'https://booking.noclick.site', hostname: 'booking.noclick.site', repo_id: 'repo_1', runtime: 'edge',
                    production_branch: 'main', domain_names: ['acmebooking.com'], deploy_on_push: 'production', user_id: null, created_at: '2026-09-01T00:00:00Z',
                    production: { object: 'deployment', id: 'dep_1', project_id: 'prj_1', branch: 'main', status: 'ready', production: true, created_at: '2026-10-08T00:00:00Z' },
                },
            ],
        });
        const [p] = (await Project.listPage({ client: c, userFilter: NO_USER })).data;
        const item = appItem(p, 3.42);
        expect(item).toMatchObject({ title: 'booking', subtitle: 'booking.noclick.site · Live', price: { usd: 3.42, per: 'so-far' }, updatedAt: '2026-10-08T00:00:00.000Z' });
        expect(item.platform?.url).toBe('https://booking.noclick.site');
        expect(item.platform?.facts).toContainEqual(['Domains', 'acmebooking.com']);
        expect(appItem(p, undefined).price).toBeUndefined();
    });

    it('lists a database by engine, tables and size, billed by use', async () => {
        const { client: c } = client({
            '/v1/databases': [{ object: 'database', id: 'db_1', name: 'bookings', engine: 'postgres', status: 'ready', size_bytes: 2048, table_count: 3, used_by: [{ kind: 'project', id: 'prj_1', name: 'booking', binding: 'DB' }], region: 'us-east', created_at: '2026-09-01T00:00:00Z' }],
        });
        const [db] = (await Database.listPage({ client: c, userFilter: NO_USER })).data;
        const item = databaseItem(db);
        expect(item).toMatchObject({ subtitle: 'Postgres · 3 tables · 2.0 KB' });
        expect(item.price).toBeUndefined();
        expect(item.platform?.facts).toContainEqual(['Used by', 'booking']);
    });

    it('lists a bucket as public or private with its files and size, and names the apps that bind it and the agents with it in their tools', async () => {
        const { client: c } = client({
            '/v1/buckets': [
                {
                    object: 'bucket', id: 'bkt_1', name: 'uploads', public: false, size_bytes: 44_204_032, object_count: 18_204, public_base_url: null, region: 'eu-west', user_id: null, created_at: '2026-09-01T00:00:00Z',
                    used_by: [
                        { kind: 'project', id: 'prj_1', name: 'booking', binding: 'FILES' },
                        { kind: 'agent', id: 'agt_1', name: 'concierge', binding: null },
                    ],
                },
                { object: 'bucket', id: 'bkt_2', name: 'fresh', public: true, size_bytes: null, object_count: null, public_base_url: 'https://api.noclick.com/api/public/buckets/bkt_2', used_by: [], region: null, created_at: '2026-10-01T00:00:00Z' },
            ],
        });
        const [uploads, fresh] = (await Bucket.listPage({ client: c, userFilter: NO_USER })).data;
        const item = bucketItem(uploads);
        expect(item).toMatchObject({ kind: 'storage', title: 'uploads', subtitle: 'Private · 18.2K files · 42.2 MB', usedBy: [], updatedAt: '2026-09-01T00:00:00.000Z' });
        expect(item.users).toEqual([
            { kind: 'app', id: 'prj_1', name: 'booking', binding: 'FILES' },
            { kind: 'agent', id: 'agt_1', name: 'concierge', binding: null },
        ]);
        expect(item.platform?.facts).toEqual([
            ['Access', 'Private'],
            ['Files', '18,204'],
            ['Size', '42.2 MB'],
            ['Region', 'eu-west'],
            ['Created', 'Sep 1, 2026'],
        ]);
        // Billed by what it stores, between them all: no price of its own.
        expect(item.price).toBeUndefined();
        // Not measured yet: it says only what it is.
        expect(bucketItem(fresh)).toMatchObject({ subtitle: 'Public', users: [] });
    });

    it("names the automation a published interface was built in, unpublishes it rather than deploying, and prices it as the account's own use", async () => {
        const { client: c } = client({
            '/v1/projects': [
                {
                    object: 'project', id: 'prj_2', name: 'booking-form', url: 'https://booking-form.noclick.site', hostname: 'booking-form.noclick.site', repo_id: null, runtime: 'edge',
                    production_branch: 'published', domain_names: [], deploy_on_push: 'off', user_id: null, created_at: '2026-09-01T00:00:00Z', published: true,
                    workflow: { id: 'wf_2', name: 'Booking' },
                    production: { object: 'deployment', id: 'dep_2', project_id: 'prj_2', branch: 'published', status: 'ready', production: true, created_at: '2026-10-08T00:00:00Z' },
                },
            ],
        });
        const [p] = (await Project.listPage({ client: c, userFilter: NO_USER })).data;
        const item = appItem(p, 0.5);
        expect(item).toMatchObject({ title: 'booking-form', origin: { id: 'wf_2', name: 'Booking', marks: [] }, platform: { unpublish: true } });
        expect(item.price).toBeUndefined();
        expect(item.platform?.facts.map(([label]) => label)).toEqual(['Address', 'Production', 'Published', 'Domains']);
    });

    it("names an automation's tables' database for the automation, and lists its tables on its page", async () => {
        const { client: c } = client({
            '/v1/databases': [
                { object: 'database', id: 'db_2', name: 'booking-1a2b3c4d', engine: 'sqlite', status: 'ready', size_bytes: 4096, table_count: 1, used_by: [], region: null, created_at: '2026-09-01T00:00:00Z', workflow: { id: 'wf_2', name: 'Booking' } },
                { object: 'database', id: 'db_3', name: 'gone-5e6f7a8b', engine: 'sqlite', status: 'ready', size_bytes: 0, table_count: 0, used_by: [], region: null, created_at: '2026-09-01T00:00:00Z', workflow: { id: 'wf_3', name: null } },
            ],
        });
        const [kept, orphaned] = (await Database.listPage({ client: c, userFilter: NO_USER })).data;
        expect(databaseItem(kept)).toMatchObject({ title: 'Booking', origin: { id: 'wf_2', name: 'Booking' }, tables: [] });
        // An automation that's gone names nothing: the database keeps its own name.
        expect(databaseItem(orphaned)).toMatchObject({ title: 'gone-5e6f7a8b', origin: undefined, tables: [] });
    });

    it('lists a link someone committed as a link, one entry whatever it points to, and reads where it points', async () => {
        const { client: c, paths } = client(
            {
                '/v1/repos': [RECORDED.repo],
                [`/v1/repos/${RECORDED_REPO_ID}/files`]: [
                    { object: 'repo_file', path: 'public/assets', type: 'dir', size: null, sha: null },
                    { object: 'repo_file', path: 'public/index.html', type: 'file', size: 12, sha: 'a1' },
                    { object: 'repo_file', path: 'public/shared', type: 'link', size: null, sha: null },
                ],
            },
            { 'public/shared': '../shared' }
        );
        const [repo] = (await Repo.listPage({ client: c, userFilter: NO_USER })).data;
        const reader = repoReader(repo);
        expect(await reader.list('public/', 'main')).toEqual([
            { path: 'public/assets', dir: true, size: null, link: false },
            { path: 'public/index.html', dir: false, size: 12, link: false },
            { path: 'public/shared', dir: false, size: null, link: true },
        ]);
        // Opened, it's read as any path is: the answer is where it points, never the folder or file there.
        expect(await reader.read('public/shared', 'main')).toBe('../shared');
        expect(paths.at(-1)).toBe(`/v1/repos/${RECORDED_REPO_ID}/files?path=public%2Fshared`);
    });

    it("reads a repo's files at a ref, its default branch unnamed, and never fetches a file that can't be text", async () => {
        const [latest] = RECORDED.featureHistory.data;
        const patch = 'diff --git a/README.md b/README.md\n--- a/README.md\n+++ b/README.md\n@@ -1 +1 @@\n-# Audit\n+# Audit tools\n';
        const { client: c, paths } = client(
            { '/v1/repos': [RECORDED.repo], [`/v1/repos/${RECORDED_REPO_ID}/commits`]: [...RECORDED.featureHistory.data] },
            { 'README.md': RECORDED.readme },
            {
                [`/v1/repos/${RECORDED_REPO_ID}/commits/${latest.sha}`]: {
                    ...latest,
                    parents: ['2ce72c6adab0e7bb71f2b16961ffe94c387cfab0'],
                    additions: 1,
                    deletions: 1,
                    files: [{ object: 'commit_file', path: 'README.md', old_path: null, status: 'modified', additions: 1, deletions: 1, size: 14, patch }],
                },
            }
        );
        const [repo] = (await Repo.listPage({ client: c, userFilter: NO_USER })).data;
        expect(repoItem(repo)).toMatchObject({ subtitle: 'main · Tidy', platform: { facts: [] } });
        expect(repoSummary(repo)).toEqual({ defaultBranch: 'main', sizeBytes: 300437, usedBy: [{ id: RECORDED.repo.used_by[0].id, name: 'zz-audit-0e7fbd' }], createdAt: '2026-10-09T18:23:51.814Z' });
        const reader = repoReader(repo);
        expect(await reader.read('README.md', 'feature/audit')).toBe(RECORDED.readme);
        expect(paths.at(-1)).toBe(`/v1/repos/${RECORDED_REPO_ID}/files?path=README.md&ref=feature%2Faudit`);
        // Named, a default branch with no commit yet is "not found" where unnamed it lists empty: it goes unnamed.
        await reader.list('', 'main');
        expect(paths.at(-1)).toBe(`/v1/repos/${RECORDED_REPO_ID}/files?prefix=`);
        expect(await reader.history('main', null, 100)).toEqual({
            commits: [
                { sha: '96d6a1b805099e479380764125a5da470d3a06d2', message: 'Feature work', author: 'Ana Audit', at: '2026-10-09T18:23:53.000Z' },
                { sha: '2ce72c6adab0e7bb71f2b16961ffe94c387cfab0', message: 'Start the audit', author: 'NoClick', at: '2026-10-09T18:23:52.000Z' },
            ],
            next: null,
        });
        expect(paths.at(-1)).toBe(`/v1/repos/${RECORDED_REPO_ID}/commits?limit=100`);
        await reader.history('feature/audit', 'c2', 100);
        expect(paths.at(-1)).toBe(`/v1/repos/${RECORDED_REPO_ID}/commits?branch=feature%2Faudit&cursor=c2&limit=100`);
        expect(await reader.commit(latest.sha)).toEqual({
            sha: latest.sha,
            message: 'Feature work',
            author: 'Ana Audit',
            at: '2026-10-09T18:23:53.000Z',
            parents: ['2ce72c6adab0e7bb71f2b16961ffe94c387cfab0'],
            additions: 1,
            deletions: 1,
            files: [{ path: 'README.md', oldPath: null, status: 'modified', additions: 1, deletions: 1, size: 14, patch }],
        });
        const before = paths.length;
        expect(await reader.read('public/logo.png', 'main')).toBeNull();
        expect(paths).toHaveLength(before);
    });
});

describe("one of the account's users' resources", () => {
    it('names the user an item belongs to, by name where it has one, and leaves the account’s own as they read', async () => {
        const repo = (id: string, userId: string | null) => ({ object: 'repo', id, name: `site-${id}`, default_branch: 'main', used_by: [], user_id: userId, created_at: '2026-10-26T00:00:00Z' });
        const { client: c } = client({ '/v1/repos': [repo('r1', 'wa-100200300400500600'), repo('r2', 'user_42'), repo('r3', null)] });
        const [unnamed, named, own] = (await Repo.listPage({ client: c, userFilter: ALL_USERS })).data;
        const names = new Map([['user_42', 'Ana Silva']]);
        expect(withOwner(repoItem(named), named.userId, names).owner).toEqual({ id: 'user_42', name: 'Ana Silva' });
        expect(withOwner(repoItem(unnamed), unnamed.userId, names).owner).toEqual({ id: 'wa-100200300400500600', name: 'wa-100200300400500600' });
        expect(withOwner(repoItem(own), own.userId, names)).toEqual(repoItem(own));
        expect('owner' in withOwner(repoItem(own), own.userId, names)).toBe(false);
    });

    it("takes any address on a user's domain whose DNS NoClick runs, as on the account's own", async () => {
        const list = await domains(DOMAIN, { ...DOMAIN, id: 'dom_2', name: 'pilot-hub.com', user_id: 'wa-100200300400500600' }, { ...DOMAIN, id: 'dom_3', name: 'pending.com', status: 'registering' });
        expect(mailDomains(list)).toEqual(['acmebooking.com', 'pilot-hub.com']);
    });
});

describe('removing a resource from its page', () => {
    // Answers each write as the platform would: a domain's PATCH with the domain, a DELETE with what it deleted. A
    // write acting for one of the account's users is noted with them.
    function writes(rows: Record<string, unknown[]>) {
        const calls: string[] = [];
        const fetch: typeof globalThis.fetch = async (input, init) => {
            const url = new URL(typeof input === 'string' ? input : input instanceof URL ? input.href : input.url);
            const method = init?.method ?? 'GET';
            const user = new Headers(init?.headers).get('NoClick-User');
            if (method !== 'GET') calls.push(`${method} ${url.pathname}${user ? ` as ${user}` : ''}`);
            const kind = url.pathname.split('/')[2];
            const body =
                method === 'PATCH'
                    ? { ...DOMAIN, auto_renew: false }
                    : method === 'DELETE'
                      ? {
                            id: url.pathname.split('/')[3],
                            deleted: true,
                            // A kind that goes to the trash answers with its item there.
                            trash: { object: 'trash_item', id: 'tr_1', kind, resource_id: url.pathname.split('/')[3], name: 'bakery-site', user_id: null },
                            operation_id: 'op_1',
                        }
                      : { object: 'list', data: rows[`/v1/${kind}`] ?? [], next_cursor: null };
            return new Response(JSON.stringify(body), { status: 200, headers: { 'Content-Type': 'application/json' } });
        };
        return { client: new NoClick({ apiKey: 'test-token', baseUrl: 'https://api.test', fetch, maxRetries: 0 }), calls };
    }
    const said = { deletes: 'What the platform says it does.', depends_on_it: [], data_lost: [], stops_billing: [], reversible: false };
    const previewed: string[] = [];
    const preview = async (path: string, user: string | null) => {
        previewed.push(user ? `${path} as ${user}` : path);
        return said;
    };

    it('disconnects a connected domain, previewing the delete the platform runs', async () => {
        const { client: c, calls } = writes({ '/v1/domains': [{ ...DOMAIN, id: 'dom_3', name: 'brother.com', source: 'connected', auto_renew: null, serves: [] }] });
        const [d] = (await Domain.listPage({ client: c, userFilter: NO_USER })).data;
        const removal = removalOf('domains', d, preview)!;
        expect([removal.label, removal.confirm]).toEqual(['Remove', 'Disconnect brother.com']);
        expect(await removal.preview()).toBe(said);
        expect(previewed.at(-1)).toBe('/v1/domains/dom_3');
        expect(await removal.run()).toEqual({ done: 'Disconnected brother.com', gone: true });
        expect(calls).toEqual(['DELETE /v1/domains/dom_3']);
    });

    it('lets a domain registered here lapse instead (turning auto-renew back on undoes it), and offers nothing once it will', async () => {
        const { client: c, calls } = writes({ '/v1/domains': [DOMAIN, { ...DOMAIN, id: 'dom_2', auto_renew: false }] });
        const [renewing, lapsing] = (await Domain.listPage({ client: c, userFilter: NO_USER })).data;
        const removal = removalOf('domains', renewing, preview)!;
        expect([removal.label, removal.confirm]).toEqual(['Let it lapse', 'Turn off auto-renew']);
        expect(await removal.preview()).toEqual({ ...said, reversible: true });
        expect(await removal.run()).toEqual({ done: 'acmebooking.com won’t renew: it stays yours until Mar 14, 2027', gone: false });
        expect(calls).toEqual(['PATCH /v1/domains/dom_1']);
        expect(removalOf('domains', lapsing, preview)).toBeNull();
    });

    it('moves a repo or an app to the trash, and offers nothing for an app NoClick publishes or an automation’s database', async () => {
        const { client: c, calls } = writes({
            '/v1/repos': [{ object: 'repo', id: 'repo_1', name: 'bakery-site', default_branch: 'main', used_by: [], created_at: '2026-09-01T00:00:00Z' }],
            '/v1/projects': [
                { object: 'project', id: 'prj_2', name: 'booking-form', published: true, repo_id: null, created_at: '2026-09-01T00:00:00Z' },
                { object: 'project', id: 'prj_3', name: 'bakery', published: false, repo_id: 'repo_1', created_at: '2026-09-01T00:00:00Z' },
            ],
            '/v1/databases': [{ object: 'database', id: 'db_1', name: 'tables', engine: 'sqlite', status: 'ready', workflow: { id: 'wf_1', name: 'Booking' }, used_by: [], created_at: '2026-09-01T00:00:00Z' }],
        });
        const [repo] = (await Repo.listPage({ client: c, userFilter: NO_USER })).data;
        const removal = removalOf('repos', repo, preview)!;
        expect([removal.label, removal.confirm]).toEqual(['Move to trash', 'Move bakery-site to the trash']);
        expect(await removal.run()).toEqual({ done: 'Moved bakery-site to the trash', gone: true });
        expect(calls).toEqual(['DELETE /v1/repos/repo_1']);
        const [published, site] = (await Project.listPage({ client: c, userFilter: NO_USER })).data;
        const app = removalOf('apps', site, preview)!;
        expect([app.label, app.confirm]).toEqual(['Move to trash', 'Move bakery to the trash']);
        expect(await app.run()).toEqual({ done: 'Moved bakery to the trash', gone: true });
        expect(calls).toEqual(['DELETE /v1/repos/repo_1', 'DELETE /v1/projects/prj_3']);
        const [tables] = (await Database.listPage({ client: c, userFilter: NO_USER })).data;
        expect(removalOf('apps', published, preview)).toBeNull();
        expect(removalOf('databases', tables, preview)).toBeNull();
    });

    it('moves a bucket to the trash with its files, which the platform refuses unless forced', async () => {
        const { client: c } = writes({ '/v1/buckets': [{ object: 'bucket', id: 'bkt_1', name: 'uploads', public: false, object_count: 3, used_by: [], created_at: '2026-09-01T00:00:00Z' }] });
        const sent: string[] = [];
        const [bucket] = (await Bucket.listPage({ client: c, userFilter: NO_USER })).data;
        const deleting = bucket.delete.bind(bucket);
        bucket.delete = async (options) => {
            sent.push(JSON.stringify(options));
            return deleting(options);
        };
        const removal = removalOf('storage', bucket, preview)!;
        expect([removal.label, removal.confirm]).toEqual(['Move to trash', 'Move uploads to the trash']);
        await removal.preview();
        expect(previewed.at(-1)).toBe('/v1/buckets/bkt_1?force=true');
        expect(await removal.run()).toEqual({ done: 'Moved uploads to the trash', gone: true });
        expect(sent).toEqual(['{"force":true}']);
    });

    it('previews and removes one of the account’s users’ resources acting for that user, whose call alone reaches it', async () => {
        const { client: c, calls } = writes({
            '/v1/repos': [{ object: 'repo', id: 'repo_9', name: 'pilot-hub', default_branch: 'main', used_by: [], user_id: 'wa-100200300400500600', created_at: '2026-10-26T00:00:00Z' }],
        });
        const [repo] = (await Repo.listPage({ client: c, userFilter: ALL_USERS })).data;
        const removal = removalOf('repos', repo, preview)!;
        await removal.preview();
        expect(previewed.at(-1)).toBe('/v1/repos/repo_9 as wa-100200300400500600');
        expect(await removal.run()).toEqual({ done: 'Moved pilot-hub to the trash', gone: true });
        expect(calls).toEqual(['DELETE /v1/repos/repo_9 as wa-100200300400500600']);
    });

    it('sorts the trash, its users’ included, into the kinds it comes back to, leaving kinds Resources doesn’t list', async () => {
        // The fields trashByKind reads, as a listed TrashItem carries them.
        const item = (kind: string, id: string, userId: string | null = null) =>
            ({ id, kind, name: `${kind}-${id}`, resourceId: `r-${id}`, userId, trashedAt: new Date('2026-10-07T12:00:00Z'), purgeAfter: new Date('2026-11-06T12:00:00Z') }) as unknown as TrashItem;
        const names = new Map([['user_42', 'Ana Silva']]);
        const sorted = trashByKind(
            [
                item('database', 'tr_1'),
                item('inbox', 'tr_2'),
                item('repo', 'tr_3'),
                item('dict', 'tr_4'),
                item('database', 'tr_5', 'user_42'),
                item('project', 'tr_6'),
                item('bucket', 'tr_7', 'wa-1'),
                item('durable_object_class', 'tr_8'),
                item('database_copy', 'tr_9'),
            ],
            names
        );
        expect(Object.keys(sorted).sort()).toEqual(['apps', 'databases', 'email', 'repos', 'storage']);
        expect(sorted.storage).toEqual([{ id: 'tr_7', name: 'bucket-tr_7', trashedAt: '2026-10-07T12:00:00.000Z', purgeAfter: '2026-11-06T12:00:00.000Z', owner: { id: 'wa-1', name: 'wa-1' } }]);
        // An app's Durable Object class comes back to the websites, beside the apps.
        expect(sorted.apps?.map((e) => e.name)).toEqual(['project-tr_6', 'durable_object_class-tr_8']);
        // What a database's restore rewound goes back to the databases.
        expect(sorted.databases).toEqual([
            { id: 'tr_1', name: 'database-tr_1', trashedAt: '2026-10-07T12:00:00.000Z', purgeAfter: '2026-11-06T12:00:00.000Z' },
            { id: 'tr_5', name: 'database-tr_5', trashedAt: '2026-10-07T12:00:00.000Z', purgeAfter: '2026-11-06T12:00:00.000Z', owner: { id: 'user_42', name: 'Ana Silva' } },
            { id: 'tr_9', name: 'database_copy-tr_9', trashedAt: '2026-10-07T12:00:00.000Z', purgeAfter: '2026-11-06T12:00:00.000Z' },
        ]);
    });
});
