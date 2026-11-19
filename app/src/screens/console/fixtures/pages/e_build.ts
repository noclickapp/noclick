// Fixtures for Build and host (Apps answer `not_available` until NoClick holds their vendor
// credentials, so they're lab only): the Apps and Code repos resource kinds, answering what
// the API answers. The lab story: `booking` (the account's, deploying
// main on push, with a production deploy, a preview, bindings including the support agent,
// secrets, schedules and the domain acmebooking.com, and its $25 monthly budget used up, so its
// log shows paid calls refused and its latest push couldn't deploy) and `status-page` (Acme's,
// deploying every branch on push, whose pushed preview failed to build), deployed from the
// repos `booking` and `status-page`, next to `agent-tools`, a repo an agent commits to.
import {
    AGENTS,
    DAY,
    FIXTURE_NOW_MS,
    HOUR,
    MIN,
    USERS,
    ago,
    apiError,
    fixtureId,
    list,
    ok,
    pageList,
    type FixtureReply,
    type FixtureRequest,
    type FixtureRoute,
} from '../core';
import { CONNECTIONS } from './a';
import { userMatches } from './c';
import { BUCKETS, DATABASES } from './d_data';
import { DOMAINS, type DomainRow } from './g_domains';
import { SECRETS as ACCOUNT_SECRETS } from './k_files';
import { DICTS, QUEUES } from './l_state';
import { REPO_ERRORS, branchWire, cloneUrlWire, commitWire, deletedWire, fileWire, repoWire } from '../repoWire';

const ACME = USERS[0].id;

/** This file's ids: repos 1xx, apps 2xx (but booking), deployments 3xx, schedules 4xx, operations 5xx, a domain added in the lab 904. */
export const buildId = (n: number) => `e0000000-0000-4000-8000-${String(n).padStart(12, '0')}`;

/** The story's apps and repos, by id, for the other kinds' fixtures to point at. The booking
 *  app keeps the id the Domains and Data fixtures gave it first. */
export const BOOKING_APP_ID = fixtureId(7, 70_901);
export const STATUS_PAGE_APP_ID = buildId(202);
export const BOOKING_REPO_ID = buildId(101);
export const STATUS_PAGE_REPO_ID = buildId(102);
export const AGENT_TOOLS_REPO_ID = buildId(103);
const NOW = new Date(FIXTURE_NOW_MS).toISOString();
const later = (ms: number) => new Date(FIXTURE_NOW_MS + ms).toISOString();
const plus = (iso: string, ms: number) => new Date(Date.parse(iso) + ms).toISOString();

type Json = Record<string, unknown>;

// ── repos ────────────────────────────────────────────────────────────────

const DEV = 'Dana Reyes <dev@acme.test>';
const CONCIERGE = 'concierge <concierge@agents.noclick.app>';
const SUPPORT_BOT = 'support-bot <support-bot@agents.noclick.app>';

interface CommitRow {
    sha: string;
    message: string;
    author: string;
    branch: string;
    created_at: string;
    files_changed: number;
}

const commit = (sha: string, message: string, author: string, branch: string, when: number, files: number): CommitRow => ({
    sha,
    message,
    author,
    branch,
    created_at: ago(when),
    files_changed: files,
});

export const REPO_COMMITS: Record<string, CommitRow[]> = {
    [BOOKING_REPO_ID]: [
        commit('b5e60d2a9c41', 'Show the deposit on the confirmation page', CONCIERGE, 'main', 20 * MIN, 1),
        commit('a1b2c3d94e7f', 'Try a one-page booking form', CONCIERGE, 'new-form', 45 * MIN, 2),
        commit('9f2c1ab4d8e0', 'Take a deposit when a party is over six', CONCIERGE, 'main', 2 * HOUR + 10 * MIN, 3),
        commit('3e8d0f27b1c5', 'Send reminder emails the morning of a booking', DEV, 'main', 2 * DAY, 4),
        commit('71b0c9e5a2d3', 'Store bookings in the database', DEV, 'main', 5 * DAY, 6),
        commit('0a4f2d18c6b9', 'Start the booking site', DEV, 'main', 8 * DAY, 11),
    ],
    [STATUS_PAGE_REPO_ID]: [
        commit('5c1e9a0f3b27', 'Add a 90-day uptime chart', DEV, 'uptime-chart', 30 * MIN, 2),
        commit('c7d2e41a90f6', 'Show incident history', DEV, 'main', 1 * DAY, 3),
        commit('2b9e7d0c4a18', 'Start the status page', DEV, 'main', 12 * DAY, 9),
    ],
    [AGENT_TOOLS_REPO_ID]: [
        commit('e41f0b8a7c23', 'Handle refunds over $500 with an approval', SUPPORT_BOT, 'main', 3 * HOUR, 2),
        commit('8d7c6b5a4f31', 'Add the order lookup tool', SUPPORT_BOT, 'main', 1 * DAY + 4 * HOUR, 3),
        commit('1c2d3e4f5a6b', 'Start the repo', DEV, 'main', 6 * DAY, 4),
    ],
};

const BOOKING_PACKAGE = `{
  "name": "booking",
  "private": true,
  "type": "module",
  "scripts": {
    "build": "remix vite:build",
    "start": "remix-serve ./build/server/index.js"
  },
  "dependencies": {
    "@remix-run/node": "^2.15.0",
    "@remix-run/react": "^2.15.0",
    "react": "^18.3.1",
    "react-dom": "^18.3.1"
  }
}
`;

export const REPO_FILES: Record<string, Record<string, string | Uint8Array>> = {
    [BOOKING_REPO_ID]: {
        'README.md': "# Booking\n\nAcme's table booking site, deployed by NoClick at https://booking.noclick.site.\n\nThe app reads its database as `DB` and its uploads as `FILES`.\n",
        'package.json': BOOKING_PACKAGE,
        'app/root.tsx': 'import { Links, Meta, Outlet, Scripts } from "@remix-run/react";\n\nexport default function App() {\n  return (\n    <html lang="en">\n      <head>\n        <Meta />\n        <Links />\n      </head>\n      <body>\n        <Outlet />\n        <Scripts />\n      </body>\n    </html>\n  );\n}\n',
        'app/routes/_index.tsx': 'export default function Index() {\n  return <h1>Book a table at Acme</h1>;\n}\n',
        'app/routes/book.tsx': 'import { Form } from "@remix-run/react";\n\nexport default function Book() {\n  return (\n    <Form method="post">\n      <input name="name" placeholder="Your name" />\n      <input name="party" type="number" min={1} />\n      <button type="submit">Book</button>\n    </Form>\n  );\n}\n',
        'app/routes/jobs.reminders.tsx': 'import { bookingsToday } from "~/lib/bookings.server";\n\n// Called by the /jobs/reminders schedule every weekday at 9am.\nexport async function action() {\n  const today = await bookingsToday();\n  return Response.json({ reminded: today.length });\n}\n',
        'app/lib/bookings.server.ts': '// Bookings live in the DB binding (the booking-db database).\nexport async function bookingsToday() {\n  return [];\n}\n',
        'migrations/0001_init.sql': 'create table bookings (\n  id text primary key,\n  name text not null,\n  party integer not null,\n  date text not null,\n  deposit_cents integer\n);\n',
        'public/favicon.ico': new Uint8Array([0, 0, 1, 0, 1, 0, 16, 16, 0, 0, 1, 0, 32, 0, 104, 4]),
    },
    [STATUS_PAGE_REPO_ID]: {
        'README.md': "# Status page\n\nAcme's public status page, built with Astro.\n",
        'package.json': '{\n  "name": "status-page",\n  "scripts": { "build": "astro build" },\n  "dependencies": { "astro": "^4.16.0" }\n}\n',
        'astro.config.mjs': 'import { defineConfig } from "astro/config";\n\nexport default defineConfig({ output: "static" });\n',
        'src/pages/index.astro': '---\nimport Incidents from "../components/Incidents.astro";\n---\n<h1>All systems operational</h1>\n<Incidents />\n',
        'src/components/Incidents.astro': '---\nconst incidents = await fetch("https://status.acme.test/incidents.json").then((r) => r.json());\n---\n<ul>{incidents.map((i) => <li>{i.title}</li>)}</ul>\n',
    },
    [AGENT_TOOLS_REPO_ID]: {
        'README.md': '# Agent tools\n\nTools support-bot writes for itself: order lookups and refunds.\n',
        'package.json': '{\n  "name": "agent-tools",\n  "type": "module",\n  "scripts": { "test": "node --test" }\n}\n',
        'src/index.ts': 'export { lookupOrder } from "./lookup.ts";\nexport { refund } from "./refunds.ts";\n',
        'src/lookup.ts': 'export async function lookupOrder(id: string) {\n  const res = await fetch(`https://api.acme.test/orders/${id}`);\n  return await res.json();\n}\n',
        'src/refunds.ts': '// Refunds over $500 wait for a person to approve them.\nexport async function refund(orderId: string, amountUsd: number) {\n  return { orderId, amountUsd, needsApproval: amountUsd > 500 };\n}\n',
        'test/lookup.test.ts': 'import { test } from "node:test";\n\ntest("looks an order up", async () => {});\n',
    },
};

/** What a branch other than main changed, over main's files: the tree its commits made. */
export const REPO_BRANCH_FILES: Record<string, Record<string, Record<string, string>>> = {
    [BOOKING_REPO_ID]: {
        'new-form': {
            'app/routes/book.tsx': 'import { OnePageForm } from "~/components/OnePageForm";\n\nexport default function Book() {\n  return <OnePageForm />;\n}\n',
            'app/components/OnePageForm.tsx': 'export function OnePageForm() {\n  return <form method="post">{/* name, party, date and deposit on one page */}</form>;\n}\n',
        },
    },
    [STATUS_PAGE_REPO_ID]: {
        'uptime-chart': {
            'src/components/UptimeChart.astro': '---\nconst days = 90;\n---\n<svg aria-label={`Uptime over ${days} days`} />\n',
        },
    },
};

/** A repo's files on a branch: main's, with the branch's own over them; undefined for a branch it doesn't have. */
function treeAt(repoId: string, branch: string): Record<string, string | Uint8Array> | undefined {
    if (branch === 'main') return REPO_FILES[repoId];
    if (!BRANCHES[repoId]?.some((b) => b.name === branch)) return undefined;
    return { ...REPO_FILES[repoId], ...REPO_BRANCH_FILES[repoId]?.[branch] };
}

const BRANCHES: Record<string, { name: string; head: string; updated_at: string }[]> = Object.fromEntries(
    Object.entries(REPO_COMMITS).map(([repoId, commits]) => {
        const heads = new Map<string, CommitRow>();
        for (const c of commits) if (!heads.has(c.branch)) heads.set(c.branch, c);
        const rows = [...heads.values()].map((c) => branchWire(c.branch, c.sha, c.created_at) as { name: string; head: string; updated_at: string });
        return [repoId, rows.sort((a, b) => (a.name === 'main' ? -1 : b.name === 'main' ? 1 : a.name.localeCompare(b.name)))];
    })
);

/** A branch's history as GET .../commits lists it: its own commits, then main's from before it forked, each under the branch asked for. */
function history(repoId: string, branch: string): Json[] {
    const commits = REPO_COMMITS[repoId] ?? [];
    const own = commits.filter((c) => c.branch === branch);
    const forked = own.length ? Date.parse(own[own.length - 1].created_at) : Infinity;
    const base = branch === 'main' ? [] : commits.filter((c) => c.branch === 'main' && Date.parse(c.created_at) < forked);
    return [...own, ...base].map((c) => commitWire(c, branch));
}

const repoSize = (repoId: string) => Object.values(REPO_FILES[repoId]).reduce((n, f) => n + (typeof f === 'string' ? f.length : f.length), 0) * 380;

/** A fixed 40-hex stand-in for git's blob id of a file's content. */
function blobId(content: string | Uint8Array): string {
    const bytes = typeof content === 'string' ? new TextEncoder().encode(content) : content;
    let hash = 0x811c9dc5;
    for (const b of bytes) hash = Math.imul(hash ^ b, 0x01000193) >>> 0;
    return hash.toString(16).padStart(8, '0').repeat(5);
}

function repo(n: number, name: string, userId: string | null, usedBy: { id: string; name: string }[], createdAgo: number) {
    const id = buildId(n);
    return repoWire({
        id,
        name,
        size_bytes: repoSize(id),
        last_commit: REPO_COMMITS[id].find((c) => c.branch === 'main') ?? null,
        used_by: usedBy,
        user_id: userId,
        created_at: ago(createdAgo),
    }) as {
        object: 'repo';
        id: string;
        name: string;
        default_branch: string;
        size_bytes: number;
        last_commit: Json | null;
        used_by: { kind: string; id: string; name: string }[];
        user_id: string | null;
        created_at: string;
    };
}

export const REPOS = [
    repo(101, 'booking', null, [{ id: BOOKING_APP_ID, name: 'booking' }], 8 * DAY),
    repo(102, 'status-page', ACME, [{ id: STATUS_PAGE_APP_ID, name: 'status-page' }], 12 * DAY),
    repo(103, 'agent-tools', null, [], 6 * DAY),
];

// ── apps ─────────────────────────────────────────────────────────────────

const BOOKING = BOOKING_APP_ID;
const STATUS_PAGE = STATUS_PAGE_APP_ID;
/** The user-sites domain apps' own hostnames are under, and where a connected domain points. */
const SITES = 'noclick.site';
const SITES_TARGET = 'cname.noclick.site';

/** Designed: booking has spent its budget (mostly on AI and its support agent), so its paid calls fail. */
export const BOOKING_BUDGET_USD = 25;
const BOOKING_SPENT_USD = 25.04;
const RESETS_AT = '2026-10-01T00:00:00+00:00';

/** The app budget's refusal, as `core/spend.py` words it: a deploy is paid work too. */
const budgetSpent = (cap: number, spent: number) => `The app's budget of $${cap} this month is used up ($${spent.toFixed(4)} spent).`;

function deployment(n: number, projectId: string, fields: Json & { branch: string; commit: string; status: string; created: number }) {
    const { created, ...rest } = fields;
    const createdAt = ago(created);
    const message = Object.values(REPO_COMMITS)
        .flat()
        .find((c) => c.sha === fields.commit)?.message;
    return {
        object: 'deployment',
        id: buildId(n),
        project_id: projectId,
        commit_message: message ?? null,
        url: null,
        production: false,
        // A deploy of the production branch is built with production's secrets; any other with previews'.
        environment: fields.branch === 'main' ? 'production' : 'preview',
        started_by: 'deploy',
        error: null,
        created_at: createdAt,
        ready_at: fields.status === 'ready' ? plus(createdAt, 92_000) : null,
        ...rest,
    };
}

export const DEPLOYMENTS = [
    // The concierge's push to main, refused by the used-up budget: a failed deployment saying why, never built.
    deployment(305, BOOKING, {
        branch: 'main',
        commit: 'b5e60d2a9c41',
        status: 'failed',
        started_by: 'push',
        commit_message: '',
        error: budgetSpent(BOOKING_BUDGET_USD, BOOKING_SPENT_USD),
        created: 18 * MIN,
    }),
    deployment(302, BOOKING, { branch: 'new-form', commit: 'a1b2c3d94e7f', status: 'ready', url: 'https://new-form--booking.noclick.site', created: 40 * MIN }),
    deployment(301, BOOKING, { branch: 'main', commit: '9f2c1ab4d8e0', status: 'ready', production: true, url: 'https://booking.noclick.site', created: 2 * HOUR + 5 * MIN }),
    // An earlier production release, kept for rollback: it serves nowhere until it's promoted again.
    deployment(303, BOOKING, { branch: 'main', commit: '3e8d0f27b1c5', status: 'ready', created: 2 * DAY - 10 * MIN }),
    deployment(304, BOOKING, { branch: 'main', commit: '71b0c9e5a2d3', status: 'canceled', created: 5 * DAY - 20 * MIN }),
    deployment(312, STATUS_PAGE, {
        branch: 'uptime-chart',
        commit: '5c1e9a0f3b27',
        status: 'failed',
        started_by: 'push',
        error: "Cannot find module 'chart.js' imported from src/components/UptimeChart.astro",
        created: 25 * MIN,
    }),
    deployment(311, STATUS_PAGE, { branch: 'main', commit: 'c7d2e41a90f6', status: 'ready', production: true, url: 'https://status-page.noclick.site', created: 1 * DAY - 5 * MIN }),
];

type Line = [offsetMs: number, level: 'info' | 'warn' | 'error', message: string];

function lines(deploymentId: string, start: string, rows: Line[]) {
    return rows.map(([offset, level, message]) => ({ object: 'log_line', at: plus(start, offset), level, message, deployment_id: deploymentId }));
}

/** A build that shipped to `url`, where it served when it was ready. */
const okBuild = (d: (typeof DEPLOYMENTS)[number], framework: string, command: string, url: string): Line[] => [
    [0, 'info', `Cloning ${d.project_id === BOOKING ? 'booking' : 'status-page'} at ${d.commit.slice(0, 7)} (${d.branch})`],
    [1_800, 'info', `Detected framework: ${framework}`],
    [2_400, 'info', 'Installing dependencies with npm ci'],
    [21_000, 'info', 'added 412 packages in 18s'],
    [21_500, 'info', `Running ${command}`],
    [74_000, 'info', 'Built in 52.4s'],
    [86_000, 'info', 'Uploading 38 files (1.9 MB)'],
    [92_000, 'info', `Ready at ${url}`],
];

const byId = (id: string) => DEPLOYMENTS.find((d) => d.id === id)!;
const remix = (n: number, url: string) => lines(buildId(n), byId(buildId(n)).created_at, okBuild(byId(buildId(n)), 'remix', 'remix vite:build', url));

export const BUILD_LOGS: Record<string, ReturnType<typeof lines>> = {
    [buildId(301)]: remix(301, 'https://booking.noclick.site'),
    [buildId(302)]: remix(302, 'https://new-form--booking.noclick.site'),
    [buildId(303)]: remix(303, 'https://booking.noclick.site'),
    [buildId(304)]: lines(buildId(304), byId(buildId(304)).created_at, [
        [0, 'info', 'Cloning booking at 71b0c9e (main)'],
        [1_700, 'info', 'Detected framework: remix'],
        [2_300, 'info', 'Installing dependencies with npm ci'],
        [9_000, 'warn', 'Canceled: a newer commit on main started its own deployment'],
    ]),
    [buildId(311)]: lines(buildId(311), byId(buildId(311)).created_at, okBuild(byId(buildId(311)), 'astro', 'astro build', 'https://status-page.noclick.site')),
    [buildId(312)]: lines(buildId(312), byId(buildId(312)).created_at, [
        [0, 'info', 'Cloning status-page at 5c1e9a0 (uptime-chart)'],
        [1_600, 'info', 'Detected framework: astro'],
        [2_100, 'info', 'Installing dependencies with npm ci'],
        [14_000, 'info', 'added 318 packages in 12s'],
        [14_400, 'info', 'Running astro build'],
        [19_800, 'info', '[build] Collecting build info...'],
        [23_100, 'error', "Cannot find module 'chart.js' imported from src/components/UptimeChart.astro"],
        [23_200, 'error', 'chart.js is imported but not in package.json. Run npm install chart.js and commit package.json and package-lock.json.'],
        [23_900, 'error', 'Build failed: astro build exited with code 1'],
    ]),
};

const NO_REQUESTS = { requests: 0, errors: 0, error_rate: null, by_status: {}, slowest_routes: [] };

/** How the requests each serving deployment answered went over the last day (`GET /v1/deployments/{id}/requests`). */
export const REQUESTS: Record<string, Record<string, unknown>> = {
    [buildId(301)]: {
        requests: 18_402,
        errors: 37,
        error_rate: 0.002,
        by_status: { '200': 17_110, '201': 412, '304': 640, '404': 203, '500': 31, none: 6 },
        slowest_routes: [
            { method: 'POST', path: '/api/book', requests: 412, errors: 9, p50_ms: 184, p95_ms: 912, max_ms: 2_410 },
            { method: 'GET', path: '/venues/:id', requests: 3_208, errors: 4, p50_ms: 96, p95_ms: 388, max_ms: 1_204 },
            { method: 'GET', path: '/api/slots', requests: 5_930, errors: 18, p50_ms: 41, p95_ms: 210, max_ms: 960 },
            { method: 'GET', path: '/', requests: 8_852, errors: 6, p50_ms: 18, p95_ms: 74, max_ms: 402 },
        ],
    },
    [buildId(302)]: {
        requests: 64,
        errors: 0,
        error_rate: 0,
        by_status: { '200': 61, '304': 3 },
        slowest_routes: [{ method: 'GET', path: '/book', requests: 22, errors: 0, p50_ms: 88, p95_ms: 240, max_ms: 301 }],
    },
};

/** Each app's production traffic: a day's requests by hour (heaviest in the afternoon), and the share of them each status, path and day takes. */
const TRAFFIC: Record<string, { day: number; before: number; byStatus: Record<string, number>; paths: [string, number, number, number][]; p50: number; p95: number }> = {
    [BOOKING]: {
        day: 18_402,
        before: 0.84,
        byStatus: { '200': 0.93, '201': 0.022, '304': 0.035, '404': 0.011, '500': 0.0017, none: 0.0003 },
        // Path, share of requests, share of them failed, p95 ms.
        paths: [
            ['/', 0.48, 0.0007, 74],
            ['/api/slots', 0.32, 0.003, 210],
            ['/venues/7', 0.17, 0.0012, 388],
            ['/api/book', 0.022, 0.022, 912],
        ],
        p50: 24,
        p95: 310,
    },
    [STATUS_PAGE]: { day: 2_210, before: 1.1, byStatus: { '200': 0.97, '304': 0.03 }, paths: [['/', 0.9, 0, 40], ['/history', 0.1, 0, 95]], p50: 12, p95: 61 },
};
const HOURLY_SHAPE = [2, 1, 1, 1, 1, 2, 3, 5, 6, 6, 7, 7, 8, 8, 8, 7, 7, 6, 5, 4, 3, 3, 2, 2];
const DAILY_SHAPE = [0.92, 1.05, 1.1, 0.98, 1.02, 0.71, 0.66];

/** An app's traffic over a period (`GET /v1/projects/{id}/analytics`): its production site's unless asked; previews' are a trickle. */
export function trafficOf(projectId: string, period: string, environment: string): Record<string, unknown> {
    const t = TRAFFIC[projectId];
    const hourly = period === '24h';
    const count = hourly ? 24 : period === '30d' ? 30 : 7;
    const step = hourly ? HOUR : DAY;
    const start = Math.floor(FIXTURE_NOW_MS / step) * step - (count - 1) * step;
    const shape = Array.from({ length: count }, (_, i) => (hourly ? HOURLY_SHAPE[i] / 4 : DAILY_SHAPE[i % 7]));
    const scale = !t ? 0 : environment === 'preview' ? 0.004 : environment === 'all' ? 1.004 : 1;
    const perInterval = shape.map((w) => Math.round(((t?.day ?? 0) * scale * w) / (hourly ? 6 : 1)));
    const requests = perInterval.reduce((a, b) => a + b, 0);
    const failedShare = t ? (t.byStatus['500'] ?? 0) + (t.byStatus.none ?? 0) : 0;
    const series = perInterval.map((n, i) => ({ at: new Date(start + i * step).toISOString(), requests: n, errors: Math.round(n * failedShare) }));
    const errors = series.reduce((a, b) => a + b.errors, 0);
    return {
        object: 'project_analytics', project_id: projectId, period, environment, interval: hourly ? 'hour' : 'day', tz: 'UTC',
        since: series[0].at, until: NOW, requests, errors, error_rate: requests ? Number((errors / requests).toFixed(4)) : null,
        by_status: Object.fromEntries(Object.entries(t?.byStatus ?? {}).map(([status, share]) => [status, Math.round(requests * share)]).filter(([, n]) => n)),
        p50_ms: requests ? t!.p50 : null, p95_ms: requests ? t!.p95 : null, series,
        top_paths: requests ? t!.paths.map(([path, share, failed, p95]) => ({ path, requests: Math.round(requests * share), errors: Math.round(requests * share * failed), p95_ms: p95 })) : [],
        previous_requests: Math.round(requests * (t?.before ?? 0)), previous_errors: Math.round(errors * (t?.before ?? 0)), sampled: false,
    };
}

export const RUNTIME_LOGS: Record<string, ReturnType<typeof lines>> = {
    [BOOKING]: lines(buildId(301), ago(70 * MIN), [
        [0, 'info', 'GET / 200 in 18ms'],
        [42_000, 'info', 'GET /book 200 in 36ms'],
        [95_000, 'info', 'POST /book 201 in 118ms'],
        [96_000, 'info', 'Deposit of $40.00 requested for a party of 8'],
        [610_000, 'warn', 'Slow query (812ms): select * from bookings where date = ?'],
        [1_220_000, 'info', 'GET /book 200 in 29ms'],
        [1_800_000, 'error', 'SQLITE_BUSY: database is locked (retried once, then succeeded)'],
        [2_400_000, 'info', 'POST /jobs/sync-calendar 502 in 30012ms'],
        [2_401_000, 'error', 'Calendar sync timed out after 30s'],
        [3_000_000, 'info', 'GET / 200 in 16ms'],
        [3_600_000, 'info', 'POST /book 201 in 104ms'],
        [3_900_000, 'info', 'GET /book 200 in 31ms'],
        // Designed: NoClick's own line for each kind of paid call it refuses, at most one a minute.
        [3_960_000, 'error', `NoClick refused app.ai.chat: booking's $${BOOKING_BUDGET_USD}.00 monthly budget is used up (SpendCapExceeded). Paid calls fail until Oct 1.`],
        [3_961_000, 'info', 'GET /reviews 200 in 22ms (served without the summary)'],
        [4_020_000, 'error', `NoClick refused SUPPORT.message: booking's $${BOOKING_BUDGET_USD}.00 monthly budget is used up (SpendCapExceeded). Paid calls fail until Oct 1.`],
        [4_021_000, 'info', 'POST /chat 200 in 14ms (offered email instead)'],
    ]),
    [STATUS_PAGE]: lines(buildId(311), ago(3 * HOUR), [
        [0, 'info', 'GET / 200 in 4ms'],
        [1_600_000, 'info', 'GET / 200 in 3ms'],
        [4_800_000, 'info', 'GET /incidents 200 in 6ms'],
    ]),
};

/**
 * What the booking app binds and the domain that serves it, by the ids the Data and Domains
 * fixtures give them; Build.test.tsx checks the two agree.
 */
export const BOUND = {
    bookingDb: { id: fixtureId(7, 5001), name: 'booking-db' },
    uploads: { id: fixtureId(7, 6001), name: 'uploads' },
    acmebooking: { id: fixtureId(7, 70_001), name: 'acmebooking.com' },
};

const SEEN = DICTS.find((d) => d.name === 'processed-orders')!;
const JOBS = QUEUES.find((q) => q.name === 'webhook-buffer')!;
const SHIPPING = ACCOUNT_SECRETS.find((s) => s.name === 'shipping')!;

const binding = (name: string, kind: string, resource: { id: string; name: string }, createdAgo: number) => ({
    object: 'binding',
    name,
    kind,
    resource_id: resource.id,
    resource_name: resource.name,
    created_at: ago(createdAgo),
});

export const BINDINGS: Record<string, Json[]> = {
    [BOOKING]: [
        binding('DB', 'database', BOUND.bookingDb, 5 * DAY),
        binding('FILES', 'bucket', BOUND.uploads, 5 * DAY),
        binding('SEEN', 'dict', SEEN, 4 * DAY),
        binding('JOBS', 'queue', JOBS, 4 * DAY),
        binding('SHIPPING', 'secret', SHIPPING, 3 * DAY),
        binding('SUPPORT', 'agent', AGENTS[0], 2 * DAY),
    ],
    [STATUS_PAGE]: [],
};

/** What a binding can name, by kind; a secret or an agent of the account's binds to a user's app too. */
const BINDABLE: Record<string, { rows: readonly { id: string; name: string; user_id: string | null }[]; accountWide?: boolean }> = {
    database: { rows: DATABASES },
    bucket: { rows: BUCKETS },
    dict: { rows: DICTS },
    queue: { rows: QUEUES },
    secret: { rows: ACCOUNT_SECRETS, accountWide: true },
    connection: { rows: CONNECTIONS },
    agent: { rows: AGENTS, accountWide: true },
};

/** Designed: plain (non-secret) settings, readable back. */
export const SETTINGS: Record<string, { name: string; value: string; updated_at: string }[]> = {
    [BOOKING]: [
        { name: 'BOOKING_TIMEZONE', value: 'America/New_York', updated_at: ago(8 * DAY) },
        { name: 'SUPPORT_EMAIL', value: 'help@acmebooking.com', updated_at: ago(6 * DAY) },
    ],
};

const BOTH = ['production', 'preview'];

/** Each secret's name, the deployments that read it and when its value was set; never the value. */
export const SECRETS: Record<string, { name: string; environments: string[]; updated_at: string }[]> = {
    [BOOKING]: [
        // Payments and sign-in set theirs when they're turned on (the App services fixtures).
        { name: 'PAYMENTS_SECRET_KEY', environments: BOTH, updated_at: ago(3 * DAY) },
        { name: 'PAYMENTS_PUBLISHABLE_KEY', environments: BOTH, updated_at: ago(3 * DAY) },
        { name: 'PAYMENTS_WEBHOOK_SECRET', environments: BOTH, updated_at: ago(3 * DAY) },
        { name: 'GOOGLE_CLIENT_ID', environments: BOTH, updated_at: ago(2 * DAY) },
        { name: 'GOOGLE_CLIENT_SECRET', environments: BOTH, updated_at: ago(2 * DAY) },
        { name: 'MAPS_API_KEY', environments: BOTH, updated_at: ago(6 * DAY) },
        { name: 'SESSION_SECRET', environments: ['production'], updated_at: ago(8 * DAY) },
    ],
    [STATUS_PAGE]: [{ name: 'UPTIME_API_KEY', environments: BOTH, updated_at: ago(12 * DAY) }],
};

interface ScheduleFields extends Json {
    name: string;
    cron: string;
    tz: string;
    path: string;
    next_run?: string | null;
}

const schedule = (n: number, projectId: string, fields: ScheduleFields) => ({
    object: 'schedule',
    id: buildId(n),
    project_id: projectId,
    status: 'active',
    paused_reason: null as string | null,
    last_run: null as string | null,
    last_status: null as string | null,
    last_error: null as string | null,
    created_at: ago(5 * DAY),
    ...fields,
});

export const SCHEDULES = [
    schedule(401, BOOKING, {
        name: '/jobs/reminders',
        cron: '0 9 * * 1-5',
        tz: 'America/New_York',
        path: '/jobs/reminders',
        next_run: '2026-09-28T13:00:00.000Z',
        last_run: '2026-09-25T13:00:02.000Z',
        last_status: 'succeeded',
    }),
    // Paused by the breaker: five runs in a row failed the same way over more than 30 minutes.
    schedule(402, BOOKING, {
        name: 'calendar-sync',
        cron: '*/15 * * * *',
        tz: 'UTC',
        path: '/jobs/sync-calendar',
        status: 'paused',
        paused_reason: 'Its last 5 runs failed: Answered 502.',
        next_run: null,
        last_run: ago(3 * HOUR),
        last_status: 'failed',
        last_error: 'Answered 502.',
    }),
    // Still active: the repo has no /jobs/cleanup route, so its one weekly run failed.
    schedule(403, BOOKING, {
        name: '/jobs/cleanup',
        cron: '0 3 * * 0',
        tz: 'UTC',
        path: '/jobs/cleanup',
        next_run: '2026-09-27T03:00:00.000Z',
        last_run: '2026-09-20T03:00:01.000Z',
        last_status: 'failed',
        last_error: 'Answered 404.',
    }),
];

/** calendar-sync's next tick once resumed: the next quarter hour. */
const NEXT_QUARTER_HOUR = new Date(Math.ceil(FIXTURE_NOW_MS / (15 * MIN)) * 15 * MIN).toISOString();

const ACMEBOOKING = DOMAINS.find((d) => d.id === BOUND.acmebooking.id)!;

/** The domains serving each app: the Domains fixtures' own rows. */
export const PROJECT_DOMAINS: Record<string, readonly DomainRow[]> = {
    [BOOKING]: [ACMEBOOKING],
    [STATUS_PAGE]: [],
};

/** The booking app's Durable Objects (GET /v1/projects/{id}/durable_objects): production's Room live, a preview's Room
 *  stopped at its spending limit, and a Lobby class in the trash. Every other app declares none. */
export const BOOKING_OBJECT_CLASSES: Json[] = [
    {
        object: 'durable_object_class', id: fixtureId(7, 71_001), project_id: BOOKING_APP_ID, name: 'Room', binding: 'ROOM',
        environment: 'production', branch: null, status: 'live', stopped_for: null, objects: 12, objects_more: false,
        stored_bytes: 48_640, added_by_deployment_id: null, created_at: ago(9 * DAY), parked_at: null, trashed_at: null,
        trash_id: null, restorable_until: null,
    },
    {
        object: 'durable_object_class', id: fixtureId(7, 71_002), project_id: BOOKING_APP_ID, name: 'Room', binding: 'ROOM',
        environment: 'preview', branch: 'new-seating', status: 'stopped', stopped_for: 'budget', objects: 2, objects_more: false,
        stored_bytes: 2_048, added_by_deployment_id: null, created_at: ago(2 * DAY), parked_at: null, trashed_at: null,
        trash_id: null, restorable_until: null,
    },
    {
        object: 'durable_object_class', id: fixtureId(7, 71_003), project_id: BOOKING_APP_ID, name: 'Lobby', binding: 'LOBBY',
        environment: 'production', branch: null, status: 'trashed', stopped_for: null, objects: 3, objects_more: false,
        stored_bytes: 1_024, added_by_deployment_id: null, created_at: ago(9 * DAY), parked_at: null, trashed_at: ago(DAY),
        trash_id: fixtureId(7, 71_103), restorable_until: '2026-10-25T16:20:05.000Z',
    },
];
export const BOOKING_OBJECTS_USD = 0.42;

export const USAGE: Record<string, Json> = {
    [BOOKING]: {
        object: 'project_usage',
        requests: 18342,
        cpu_ms: 912_000,
        usd: BOOKING_SPENT_USD,
        period_start: '2026-09-01T00:00:00+00:00',
        budget_usd: BOOKING_BUDGET_USD,
        limited_by: 'project',
        by_type: { apps: 1.84, ai: 14.2, model_tokens: 6.9, tool_runs: 1.1, databases: 0.6, app_email: 0.4 },
    },
    [STATUS_PAGE]: {
        object: 'project_usage',
        requests: 2210,
        cpu_ms: 40_300,
        usd: 0.12,
        period_start: '2026-09-01T00:00:00+00:00',
        budget_usd: null,
        limited_by: null,
        by_type: { apps: 0.12 },
    },
};

/** An app's view. Its URL is the first domain serving it, else its own hostname. */
function project(n: number, fields: Json & { id?: string; name: string; repo_id: string; user_id: string | null; domain_names?: string[] }) {
    const id = fields.id ?? buildId(n);
    const hostname = `${fields.name}.${SITES}`;
    const domainNames = fields.domain_names ?? [];
    return {
        object: 'project',
        id,
        url: `https://${domainNames[0] ?? hostname}`,
        hostname,
        runtime: 'edge',
        framework: null as string | null,
        production_branch: 'main',
        domain_names: domainNames,
        budget_usd_per_month: null as number | null,
        deploy_on_push: 'off',
        preview_access: 'public',
        preview_public_paths: [] as string[],
        region: 'us-east',
        production: DEPLOYMENTS.find((d) => d.project_id === id && d.production) ?? null,
        created_at: ago(8 * DAY),
        ...fields,
    };
}

export const PROJECTS = [
    project(201, {
        id: BOOKING,
        name: 'booking',
        repo_id: BOOKING_REPO_ID,
        framework: 'remix',
        budget_usd_per_month: BOOKING_BUDGET_USD,
        deploy_on_push: 'production',
        // acmebooking.com, bought through NoClick, serves it at its name and www.
        domain_names: ['acmebooking.com', 'www.acmebooking.com'],
        user_id: null,
    }),
    project(202, { name: 'status-page', repo_id: STATUS_PAGE_REPO_ID, framework: 'astro', deploy_on_push: 'all', user_id: ACME, created_at: ago(12 * DAY) }),
];

// ── routes ───────────────────────────────────────────────────────────────

function listed<T extends { user_id: string | null; name?: string }>(r: FixtureRequest, rows: readonly T[]): FixtureReply {
    const name = r.query.get('name');
    return pageList(r, rows.filter((row) => userMatches(r.query, row.user_id) && (name === null || row.name === name)));
}

function trashItem(id: string, resourceId: string, name: string, userId: string | null) {
    const at = Date.parse(NOW);
    return {
        object: 'trash_item',
        id,
        kind: 'project',
        resource_id: resourceId,
        name,
        user_id: userId,
        trashed_at: new Date(at - 2 * 86_400_000).toISOString(),
        purge_after: new Date(at + 28 * 86_400_000).toISOString(),
    };
}

/** An app deleted two days ago, restorable for 28 more. */
export const TRASHED_APPS = [trashItem(buildId(903), buildId(211), 'old-landing', null)];

/** The booking app's Lobby class, deleted to the trash (its row in BOOKING_OBJECT_CLASSES). */
export const TRASHED_CLASSES = [
    { ...trashItem(fixtureId(7, 71_103), fixtureId(7, 71_003), 'booking/Lobby', null), kind: 'durable_object_class', purge_after: '2026-10-25T16:20:05.000Z' },
];

function found<T>(row: T | undefined, what: string): FixtureReply {
    return row ? ok(row) : apiError(404, 'not_found', `No such ${what}.`);
}

/** A sub-resource read: served in every set but `error`, where the drawer shows the failure. */
function sub(r: FixtureRequest, rows: readonly unknown[]): FixtureReply {
    return r.set === 'error' ? apiError(500, 'server_error', 'The platform API failed to answer.') : list(rows);
}

/** The acting user: the `NoClick-User` header, your id for them as it is. */
const actingUser = (r: FixtureRequest): string | null => r.headers.get('NoClick-User');

/** An operation's view as `core/operations_store.view` shows a queued one to the owner, with its kind's own fields. */
function operation(n: number, kind: string, summary: string, userId: string | null, fields: Json = {}) {
    return {
        status: 202,
        body: {
            object: 'operation',
            id: buildId(n),
            kind,
            status: 'queued',
            step: null,
            result: null,
            error: null,
            created_at: NOW,
            updated_at: NOW,
            user_id: userId,
            key_id: null,
            agent_id: null,
            started_at: null,
            finished_at: null,
            wait_ms: null,
            run_ms: null,
            held_ms: null,
            events: [],
            summary,
            ...fields,
        },
    };
}

/** A repos API error (`repoWire.REPO_ERRORS`) as the fixture answers it. */
function repoError({ status, error }: { status: number; error: Json }): FixtureReply {
    return { status, body: { error } };
}

/** A directory listing (`prefix`) or a file's bytes (`path`) at `ref` (main when absent), as the route answers them. */
function files(r: FixtureRequest): FixtureReply {
    const ref = r.query.get('ref');
    if (CREATED.has(r.params.id)) {
        // Nothing committed: unnamed, the default branch lists empty; named, it doesn't exist yet.
        if (ref !== null) return repoError(REPO_ERRORS.noRef(ref));
        return r.query.has('path') ? repoError(REPO_ERRORS.noFile(r.query.get('path')!, String(CREATED.get(r.params.id)!.default_branch))) : list([]);
    }
    if (!REPO_FILES[r.params.id]) return repoError(REPO_ERRORS.noRepo());
    const tree = treeAt(r.params.id, ref ?? 'main');
    if (!tree) return repoError(REPO_ERRORS.noRef(ref!));
    const path = r.query.get('path');
    if (path !== null) {
        const file = tree[path];
        if (file === undefined) return repoError(REPO_ERRORS.noFile(path, ref ?? 'main'));
        return { status: 200, raw: typeof file === 'string' ? file : new Uint8Array(file) };
    }
    const prefix = (r.query.get('prefix') ?? '').replace(/\/?$/, '/').replace(/^\/$/, '');
    const under = Object.entries(tree).filter(([p]) => p.startsWith(prefix));
    const entry = (p: string, f: string | Uint8Array) => fileWire(p, { size: typeof f === 'string' ? new TextEncoder().encode(f).length : f.length, sha: blobId(f) });
    // Git's order, as the API keeps it: by code point, so README.md comes before big.txt.
    const byPath = (a: Json, b: Json) => (String(a.path) < String(b.path) ? -1 : String(a.path) > String(b.path) ? 1 : 0);
    if (r.query.get('recursive') === 'true') return list(under.map(([p, f]) => entry(p, f)).sort(byPath));
    const dirs = new Set<string>();
    const entries: Json[] = [];
    for (const [p, f] of under) {
        const rest = p.slice(prefix.length);
        const slash = rest.indexOf('/');
        if (slash === -1) entries.push(entry(p, f));
        else dirs.add(prefix + rest.slice(0, slash));
    }
    return list([...[...dirs].sort().map((d) => fileWire(d, null)), ...entries.sort(byPath)]);
}

/** Repos made in the lab (or a test), empty: found by id, listing empty until something is committed. */
const CREATED = new Map<string, Json>();

const repoRoutes: FixtureRoute[] = [
    { method: 'GET', path: '/v1/repos', reply: (r) => listed(r, REPOS) },
    {
        method: 'GET',
        path: '/v1/repos/:id',
        reply: (r) => {
            const row = REPOS.find((x) => x.id === r.params.id) ?? CREATED.get(r.params.id);
            return row ? found(row, 'repo') : repoError(REPO_ERRORS.noRepo());
        },
    },
    {
        method: 'POST',
        path: '/v1/repos',
        reply: (r) => {
            const body = (r.body ?? {}) as { name?: string; default_branch?: string };
            const name = String(body.name ?? 'repo');
            const taken = REPOS.find((x) => x.name === name);
            if (taken) return repoError(REPO_ERRORS.taken(name, taken.id));
            const made = repoWire({ id: buildId(109), name, default_branch: body.default_branch, user_id: actingUser(r), created_at: NOW });
            CREATED.set(String(made.id), made);
            return { status: 201, body: made };
        },
    },
    {
        method: 'DELETE',
        path: '/v1/repos/:id',
        reply: (r) => {
            const row = REPOS.find((x) => x.id === r.params.id);
            if (row?.used_by.length) return repoError(REPO_ERRORS.deployed(row.used_by));
            if (!row && !CREATED.delete(r.params.id)) return repoError(REPO_ERRORS.noRepo());
            return ok(deletedWire(r.params.id));
        },
    },
    {
        method: 'POST',
        path: '/v1/repos/:id/clone_url',
        reply: (r) => {
            const body = (r.body ?? {}) as { write?: boolean; ttl_s?: number };
            const token = body.write ? 'eyJ.write.7Hq2mX9vLp4R' : 'eyJ.read.3Kd8sB1nYt6W';
            return ok(cloneUrlWire(r.params.id, token, !!body.write, later((body.ttl_s ?? 3600) * 1000)));
        },
    },
    {
        method: 'GET',
        path: '/v1/repos/:id/commits',
        reply: (r) => {
            const branch = r.query.get('branch') ?? 'main';
            const branches = BRANCHES[r.params.id] ?? [];
            // A repo with no commits answers an empty history, whatever the branch, as production does.
            if (branches.length && !branches.some((b) => b.name === branch)) return repoError(REPO_ERRORS.noRef(branch));
            return sub(r, history(r.params.id, branch).slice(0, Number(r.query.get('limit') ?? 20)));
        },
    },
    { method: 'GET', path: '/v1/repos/:id/branches', reply: (r) => sub(r, BRANCHES[r.params.id] ?? []) },
    { method: 'GET', path: '/v1/repos/:id/files', reply: files },
    {
        method: 'POST',
        path: '/v1/repos/:id/export',
        reply: (r) => {
            const body = (r.body ?? {}) as { to?: string; connection?: string; owner?: string; name?: string };
            const row = REPOS.find((x) => x.id === r.params.id);
            if (body.to === 'github') {
                const github = CONNECTIONS.find((c) => (c.id === body.connection || c.name === body.connection) && (c.user_id === null || c.user_id === row?.user_id));
                if (github?.integration !== 'github') {
                    return apiError(400, 'invalid_request', 'connection names a GitHub connection, by name or id.', 'List them with GET /v1/connections?integration=github.', { field: 'connection' });
                }
                if (github.status === 'pending') {
                    return apiError(424, 'needs_connection', `The '${github.name}' connection has no github account connected yet.`, 'Send the user connect_url; retry once the connect operation succeeds.', {
                        connection: github.name,
                        integration: 'github',
                        connect_url: github.connect_link?.url ?? null,
                    });
                }
            }
            return body.to === 'github'
                ? operation(501, 'repo.export_to_github', `github.com/${body.owner}/${body.name ?? row?.name}`, row?.user_id ?? null)
                : operation(502, 'repo.export', row?.name ?? '', row?.user_id ?? null);
        },
    },
];

type App = (typeof PROJECTS)[number];

const NO_APP = apiError(404, 'not_found', 'No such app.', 'List apps with GET /v1/projects.');

/** A route on one app: 404 for an id the account has no app at. */
const onApp =
    (reply: (r: FixtureRequest, app: App) => FixtureReply) =>
    (r: FixtureRequest): FixtureReply => {
        const app = PROJECTS.find((p) => p.id === r.params.id);
        return app ? reply(r, app) : NO_APP;
    };

const invalid = (message: string, field: string) => apiError(400, 'invalid_request', message, undefined, { field });

const FRAMEWORKS: Record<string, readonly string[]> = { edge: ['nextjs', 'remix', 'astro', 'vite', 'static'], container: ['python', 'node', 'docker'] };

/** What create and PATCH refuse in a body, as `projects/service.py` words it. */
function projectRefusal(runtime: string, body: Json): FixtureReply | null {
    if (body.framework != null && !FRAMEWORKS[runtime].includes(String(body.framework))) {
        return invalid(`On the ${runtime} runtime, framework is one of ${FRAMEWORKS[runtime].join(', ')} (omitted: detected from the repo at each build).`, 'framework');
    }
    if (body.deploy_on_push !== undefined && !['off', 'production', 'all'].includes(String(body.deploy_on_push))) {
        return invalid('deploy_on_push is off, production (a push to the production branch deploys it) or all (a push to any other branch deploys a preview too).', 'deploy_on_push');
    }
    if (body.preview_access !== undefined && !['public', 'link'].includes(String(body.preview_access))) {
        return invalid('preview_access is public (anyone with a preview’s URL opens it) or link (only a link NoClick signs opens it).', 'preview_access');
    }
    return null;
}

/** A link opening the newest serving preview of `app` (or `branch`'s), as POST /v1/projects/{id}/previews/link answers one. */
function previewLink(r: FixtureRequest, app: App): FixtureReply {
    const branch = ((r.body ?? {}) as Json).branch as string | undefined;
    if (branch === app.production_branch) {
        return invalid(`${branch} is the production branch, which is always public at the app’s URL; a link opens a preview.`, 'branch');
    }
    const serving = DEPLOYMENTS.find((d) => d.project_id === app.id && d.status === 'ready' && d.branch !== app.production_branch && (branch === undefined || d.branch === branch));
    if (!serving) {
        return apiError(404, 'not_found', `${branch ? `No preview of ${branch}` : 'No preview of this app'} is serving: a link opens one that is.`, `Deploy a branch other than ${app.production_branch} as a preview first (POST /v1/projects/${app.id}/deployments with its branch); its deploy answers its link.`);
    }
    const host = `${serving.branch}--${app.hostname}`;
    return ok({
        object: 'preview_link',
        project_id: app.id,
        branch: serving.branch,
        url: `https://${host}/?preview=p1~${Math.floor(Date.now() / 1000) + 7 * 86_400}~${app.id}~${host}~${'0'.repeat(64)}`,
        preview_url: `https://${host}`,
        preview_access: app.preview_access,
        expires_at: plus(new Date().toISOString(), 7 * DAY),
    });
}

/** A deploy refused because the app's budget is used up: paid work, like every build. */
function budgetRefusal(app: App): FixtureReply | null {
    const usage = USAGE[app.id];
    if (usage?.limited_by !== 'project') return null;
    const cap = Number(usage.budget_usd);
    return apiError(402, 'spend_cap_exceeded', budgetSpent(cap, Number(usage.usd)), `Raise the app's budget with PATCH /v1/projects/${app.id} {"budget_usd_per_month": ...}, or wait until the cap resets at ${RESETS_AT}.`, {
        cap,
        spent: usage.usd,
        scope: 'project',
        scope_id: app.id,
        resets_at: RESETS_AT,
        project: app.name,
        project_id: app.id,
    });
}

/** Where a deploy of `branch` serves: the app's own hostname for production, else the branch's preview. */
const deployUrl = (app: App, branch: string) => (branch === app.production_branch ? `https://${app.hostname}` : `https://${branch}--${app.hostname}`);

const VAR = /^[A-Za-z][A-Za-z0-9_]{0,127}$/;

/** A setting's or secret's name, checked as `check_var` checks it. */
function varRefusal(name: string): FixtureReply | null {
    if (!VAR.test(name)) return invalid(`'${name}' isn't a name the app reads: letters, digits and _, starting with a letter.`, 'name');
    if (name.startsWith('NOCLICK_')) return invalid("Names starting with NOCLICK_ are NoClick's own.", 'name');
    return null;
}

const environmentsOf = (value: unknown): string[] => (value == null || value === 'all' ? BOTH : [String(value)]);
const settingsOf = (id: string) => SETTINGS[id] ?? [];
const secretsOf = (id: string) => SECRETS[id] ?? [];

/** A schedule's reads and writes by id. */
const onSchedule =
    (reply: (r: FixtureRequest, s: (typeof SCHEDULES)[number]) => FixtureReply) =>
    (r: FixtureRequest): FixtureReply => {
        const s = SCHEDULES.find((x) => x.id === r.params.id);
        return s ? reply(r, s) : apiError(404, 'not_found', 'No such schedule.', "List an app's with GET /v1/projects/{id}/schedules.");
    };

/** The domain holding `name` (it, or a name under it), of the account's. */
const holding = (name: string) => DOMAINS.find((d) => name === d.name || name.endsWith(`.${d.name}`));

/** A name nobody holds, connected for the app: `pending_dns` with what its owner adds at its DNS host. */
function connectedDomain(name: string, app: App): Json {
    const labels = name.split('.');
    const apex = labels.length === 2;
    const host = apex ? 'www' : labels.slice(0, -2).join('.');
    const records = [
        { type: 'CNAME', name: host, value: SITES_TARGET, purpose: 'Sends it to NoClick', required: true, managed: false, status: 'pending' },
        { type: 'TXT', name: `_cf-custom-hostname.${host}`, value: '4f9a2c71-0b8e-4d3a-9e65-1c7b2d8f0a34', purpose: 'Proves the domain is yours', required: true, managed: false, status: 'pending' },
        { type: 'TXT', name: `_acme-challenge.${host}`, value: 'Zq8xN3vR1kLm5pT7wY2bC9dF4gH6jK0s', purpose: 'Lets its certificate be issued before traffic moves', required: false, managed: false, status: 'pending' },
        ...(apex ? [{ type: 'ALIAS', name: '@', value: SITES_TARGET, purpose: 'Serves the bare name (or forward it to www instead)', required: false, managed: false, status: 'pending' }] : []),
    ];
    return {
        object: 'domain',
        id: buildId(904),
        name,
        source: 'connected',
        noclick_dns: false,
        wildcard: false,
        status: 'pending_dns',
        expires_at: null,
        renewable_until: null,
        auto_renew: null,
        renewal_usd: null,
        renewal_years: null,
        records,
        setup_url: null,
        serves: [{ kind: 'project', id: app.id, name: app.name, hostname: name }],
        registrant: null,
        registrant_email: null,
        registrant_verify_by: null,
        transfer_locked_until: null,
        user_id: app.user_id,
        created_at: NOW,
    };
}

/** Serve the app at `name` too: a held domain answers as it is, serving the app; any other is connected. */
function addDomain(r: FixtureRequest, app: App): FixtureReply {
    const name = String((r.body as { name?: string } | null)?.name ?? '')
        .trim()
        .toLowerCase();
    if (!/^([a-z0-9-]+\.)+[a-z]{2,}$/.test(name)) return invalid(`${name || 'That'} isn't a domain name.`, 'name');
    if (name === app.hostname || name.endsWith(`.${SITES}`)) return invalid('NoClick already serves the app at its own hostname.', 'name');
    const held = holding(name);
    if (!held) return { status: 201, body: connectedDomain(name, app) };
    if (held.user_id !== null && held.user_id !== app.user_id) return apiError(403, 'permission_denied', `${held.name} belongs to one of your users, so it serves only their apps.`, undefined, { field: 'name' });
    if (held.user_id === null && app.user_id !== null && held.name === name) {
        return apiError(403, 'permission_denied', `${name} is the account's own: a user's app takes a name under it.`, `Add a subdomain instead, like ${app.name}.${name}.`, { field: 'name' });
    }
    // A domain itself serves at its name and www; a name under it at that name.
    const hostnames = held.name === name ? [name, `www.${name}`] : [name];
    const fresh = hostnames.filter((h) => !held.serves.some((s) => s.kind === 'project' && s.id === app.id && s.hostname === h));
    const serves = [...held.serves, ...fresh.map((hostname) => ({ kind: 'project' as const, id: app.id, name: app.name, hostname }))];
    return { status: 201, body: { ...held, status: held.source === 'connected' ? 'pending_dns' : held.status, serves } };
}

function removeDomain(r: FixtureRequest, app: App): FixtureReply {
    const name = r.params.name.toLowerCase();
    const serving = (PROJECT_DOMAINS[app.id] ?? []).some((d) => d.serves.some((s) => s.kind === 'project' && s.id === app.id && s.hostname === name));
    if (!serving) return apiError(404, 'not_found', `The app isn't served at ${name}.`, "List the app's domains with GET /v1/projects/{id}/domains.", { field: 'name' });
    return ok({ object: 'project_domain', name, deleted: true });
}

const projectRoutes: FixtureRoute[] = [
    { method: 'GET', path: '/v1/projects', reply: (r) => listed(r, PROJECTS) },
    { method: 'GET', path: '/v1/projects/:id', reply: (r) => found(PROJECTS.find((p) => p.id === r.params.id), 'app') },
    {
        method: 'POST',
        path: '/v1/projects',
        reply: (r) => {
            const body = (r.body ?? {}) as Json;
            const name = String(body.name ?? '');
            const runtime = String(body.runtime ?? 'edge');
            if (!(runtime in FRAMEWORKS)) return invalid('runtime is edge or container.', 'runtime');
            const refused = projectRefusal(runtime, body);
            if (refused) return refused;
            const taken = PROJECTS.find((p) => p.name === name && p.user_id === actingUser(r));
            if (taken) return apiError(409, 'conflict', `A project named '${name}' already exists.`, 'Use that one (Project.from_name), or pick another name.', { existing_id: taken.id });
            return {
                status: 201,
                body: project(209, {
                    name,
                    repo_id: String(body.repo_id ?? buildId(109)),
                    runtime,
                    framework: (body.framework as string | undefined) ?? null,
                    production_branch: (body.production_branch as string | undefined) ?? 'main',
                    // Every app made through the API has a budget: its maker's, else $10 (projects.service).
                    budget_usd_per_month: (body.budget_usd_per_month as number | undefined) ?? 10,
                    deploy_on_push: (body.deploy_on_push as string | undefined) ?? 'off',
                    region: (body.region as string | undefined) ?? 'us-east',
                    user_id: actingUser(r),
                    created_at: NOW,
                }),
            };
        },
    },
    {
        method: 'DELETE',
        path: '/v1/projects/:id',
        reply: onApp((_, app) => {
            const trash = trashItem(buildId(901), app.id, app.name, app.user_id);
            return ok({ object: 'project', id: app.id, deleted: true, trash, restorable_until: trash.purge_after, operation_id: buildId(902) });
        }),
    },
    {
        method: 'GET',
        path: '/v1/trash',
        reply: (r) => {
            const kind = r.query.get('kind');
            return list([...(!kind || kind === 'project' ? TRASHED_APPS : []), ...(!kind || kind === 'durable_object_class' ? TRASHED_CLASSES : [])]);
        },
    },
    {
        method: 'POST',
        path: '/v1/trash/:id/restore',
        reply: (r) => {
            const cls = TRASHED_CLASSES.find((t) => t.id === r.params.id);
            if (cls) {
                // As the class's own view answers, out of the trash.
                const row = BOOKING_OBJECT_CLASSES.find((c) => (c as { id: string }).id === cls.resource_id) as Json;
                return ok({ ...row, status: 'live', trashed_at: null, trash_id: null, restorable_until: null, restored: true });
            }
            const item = TRASHED_APPS.find((t) => t.id === r.params.id);
            if (!item) return apiError(404, 'not_found', 'Nothing in the trash has that id.');
            return ok({ ...project(210, { id: item.resource_id, name: item.name, repo_id: buildId(212), user_id: item.user_id }), restored: true, domains_not_restored: [] });
        },
    },
    {
        method: 'DELETE',
        path: '/v1/trash/:id',
        reply: (r) => ok({ object: 'trash_item', id: r.params.id, kind: 'project', purged: true }),
    },
    { method: 'POST', path: '/v1/projects/:id/previews/link', reply: onApp(previewLink) },
    {
        method: 'PATCH',
        path: '/v1/projects/:id',
        reply: onApp((r, app) => {
            const body = (r.body ?? {}) as Json;
            if (body.region != null && body.region !== app.region) {
                return apiError(409, 'conflict', `The app runs in ${app.region}, fixed when it was created.`, 'Create another app in that region, or leave region out.', { region: app.region });
            }
            return projectRefusal(app.runtime, body) ?? ok({ ...app, ...body });
        }),
    },
    {
        method: 'GET',
        path: '/v1/projects/:id/deployments',
        reply: (r) => {
            const branch = r.query.get('branch');
            return sub(r, DEPLOYMENTS.filter((d) => d.project_id === r.params.id && (!branch || d.branch === branch)));
        },
    },
    {
        method: 'POST',
        path: '/v1/projects/:id/deployments',
        reply: onApp((r, app) => {
            const branch = (r.body as { branch?: string } | null)?.branch ?? app.production_branch;
            return budgetRefusal(app) ?? operation(503, 'project.deploy', `Deploy ${branch} of ${app.name}`, app.user_id, { deployment_id: buildId(306), url: deployUrl(app, branch) });
        }),
    },
    { method: 'GET', path: '/v1/deployments/:id', reply: (r) => found(DEPLOYMENTS.find((d) => d.id === r.params.id), 'deployment') },
    {
        method: 'GET',
        path: '/v1/deployments/:id/logs',
        reply: (r) => {
            const d = DEPLOYMENTS.find((x) => x.id === r.params.id);
            if (!d) return apiError(404, 'not_found', 'No such deployment.');
            const rows = r.query.get('kind') === 'runtime' ? (RUNTIME_LOGS[d.project_id] ?? []).filter((l) => l.deployment_id === d.id) : (BUILD_LOGS[d.id] ?? []);
            return sub(r, rows);
        },
    },
    {
        method: 'GET',
        path: '/v1/deployments/:id/requests',
        reply: (r) => {
            const d = DEPLOYMENTS.find((x) => x.id === r.params.id);
            if (!d) return apiError(404, 'not_found', 'No such deployment.');
            return ok({ object: 'request_outcomes', deployment_id: d.id, since: ago(DAY), until: ago(0), sampled: false, ...(REQUESTS[d.id] ?? NO_REQUESTS) });
        },
    },
    {
        method: 'POST',
        path: '/v1/deployments/:id/cancel',
        reply: (r) => found(DEPLOYMENTS.map((d) => ({ ...d, status: d.status === 'queued' || d.status === 'building' ? 'canceled' : d.status })).find((d) => d.id === r.params.id), 'deployment'),
    },
    {
        method: 'POST',
        path: '/v1/deployments/:id/promote',
        reply: (r) => {
            const d = DEPLOYMENTS.find((x) => x.id === r.params.id);
            const app = d && PROJECTS.find((p) => p.id === d.project_id);
            if (!d || !app) return apiError(404, 'not_found', 'No such deployment.');
            if (d.status !== 'ready') return apiError(409, 'conflict', `The deployment is ${d.status}; only a ready one serves.`, undefined, { status: d.status });
            return operation(504, 'deployment.promote', `Promote a deployment of ${app.name}`, app.user_id, { deployment_id: d.id, url: `https://${app.hostname}` });
        },
    },
    { method: 'GET', path: '/v1/projects/:id/bindings', reply: (r) => sub(r, BINDINGS[r.params.id] ?? []) },
    {
        method: 'POST',
        path: '/v1/projects/:id/bindings',
        reply: onApp((r, app) => {
            const body = (r.body ?? {}) as { name?: string; kind?: string; id?: string };
            const name = body.name ?? '';
            if (!/^[A-Za-z][A-Za-z0-9_]{0,63}$/.test(name)) {
                return invalid(`A binding's name is the variable the app reads: letters, digits and _, starting with a letter, up to 64 characters; '${name}' isn't.`, 'name');
            }
            if (name.startsWith('NOCLICK_')) return invalid("Names starting with NOCLICK_ are NoClick's own.", 'name');
            const kind = BINDABLE[body.kind ?? ''];
            if (!kind) return invalid(`kind is one of ${Object.keys(BINDABLE).join(', ')}.`, 'kind');
            const resource = kind.rows.find((x) => x.id === body.id && (x.user_id === app.user_id || (kind.accountWide && x.user_id === null)));
            if (!resource) {
                const whose = app.user_id ? `its user's${kind.accountWide ? " or the account's" : ''}` : "the account's";
                return apiError(404, 'not_found', `No ${body.kind} ${body.id} the app can be given: it binds ${whose}.`, `Pass the id of one from GET /v1/${body.kind}s.`, { field: 'id' });
            }
            return { status: 201, body: { object: 'binding', name, kind: body.kind, resource_id: resource.id, resource_name: resource.name, created_at: NOW } };
        }),
    },
    {
        method: 'DELETE',
        path: '/v1/projects/:id/bindings/:name',
        reply: onApp((r, app) =>
            (BINDINGS[app.id] ?? []).some((b) => b.name === r.params.name)
                ? ok({ object: 'binding', name: r.params.name, deleted: true })
                : apiError(404, 'not_found', `Nothing is bound to the app as '${r.params.name}'.`, 'List its bindings with GET /v1/projects/{id}/bindings.', { field: 'name' })
        ),
    },
    {
        method: 'GET',
        path: '/v1/projects/:id/secrets',
        reply: (r) => {
            const env = r.query.get('environment');
            const rows = secretsOf(r.params.id).filter((s) => !env || env === 'all' || s.environments.includes(env));
            return sub(r, rows.map((s) => ({ object: 'project_secret', ...s })));
        },
    },
    {
        method: 'PUT',
        path: '/v1/projects/:id/secrets/:name',
        reply: onApp((r, app) => {
            const name = r.params.name;
            const refused = varRefusal(name);
            if (refused) return refused;
            if (settingsOf(app.id).some((s) => s.name === name)) return apiError(409, 'conflict', `${name} is one of the app's settings.`, 'Delete the setting first, or pick another name.');
            return ok({ object: 'project_secret', name, environments: environmentsOf((r.body as { environment?: string } | null)?.environment) });
        }),
    },
    {
        method: 'DELETE',
        path: '/v1/projects/:id/secrets/:name',
        reply: onApp((r, app) => {
            const env = r.query.get('environment');
            const set = secretsOf(app.id).some((s) => s.name === r.params.name && environmentsOf(env).some((e) => s.environments.includes(e)));
            if (!set) return apiError(404, 'not_found', `The app has no secret '${r.params.name}'${env && env !== 'all' ? ` for ${env}` : ''}.`, 'List them with GET /v1/projects/{id}/secrets.');
            return ok({ object: 'project_secret', name: r.params.name, deleted: true });
        }),
    },
    { method: 'GET', path: '/v1/projects/:id/settings', reply: (r) => sub(r, settingsOf(r.params.id).map((s) => ({ object: 'project_setting', ...s }))) },
    {
        method: 'PUT',
        path: '/v1/projects/:id/settings/:name',
        reply: onApp((r, app) => {
            const name = r.params.name;
            const value = (r.body as { value?: unknown } | null)?.value;
            const refused = varRefusal(name);
            if (refused) return refused;
            if (typeof value !== 'string' || new TextEncoder().encode(value).length > 4096) return invalid("A setting's value is a string of at most 4,096 bytes.", 'value');
            if (secretsOf(app.id).some((s) => s.name === name)) return apiError(409, 'conflict', `${name} is one of the app's secrets.`, 'Delete the secret first, or pick another name.');
            return ok({ object: 'project_setting', name, value });
        }),
    },
    {
        method: 'DELETE',
        path: '/v1/projects/:id/settings/:name',
        reply: onApp((r, app) =>
            settingsOf(app.id).some((s) => s.name === r.params.name)
                ? ok({ object: 'project_setting', name: r.params.name, deleted: true })
                : apiError(404, 'not_found', `The app has no setting '${r.params.name}'.`, 'List them with GET /v1/projects/{id}/settings.')
        ),
    },
    { method: 'GET', path: '/v1/projects/:id/schedules', reply: (r) => sub(r, SCHEDULES.filter((s) => s.project_id === r.params.id)) },
    { method: 'GET', path: '/v1/schedules/:id', reply: onSchedule((_, s) => ok(s)) },
    // Pausing by hand clears any reason; resuming clears it and fires from the next tick; a run
    // records what it did (a paused schedule stays paused, and a manual failure never pauses one).
    { method: 'POST', path: '/v1/schedules/:id/pause', reply: onSchedule((_, s) => ok(s.status === 'active' ? { ...s, status: 'paused', paused_reason: null, next_run: null } : s)) },
    {
        method: 'POST',
        path: '/v1/schedules/:id/resume',
        reply: onSchedule((_, s) => ok(s.status === 'paused' ? { ...s, status: 'active', paused_reason: null, next_run: s.next_run ?? NEXT_QUARTER_HOUR } : s)),
    },
    {
        method: 'POST',
        path: '/v1/schedules/:id/run',
        reply: onSchedule((_, s) => {
            const error = s.path === '/jobs/sync-calendar' ? 'Answered 502.' : s.path === '/jobs/cleanup' ? 'Answered 404.' : null;
            return ok({ ...s, last_run: NOW, last_status: error ? 'failed' : 'succeeded', last_error: error });
        }),
    },
    { method: 'DELETE', path: '/v1/schedules/:id', reply: onSchedule((_, s) => ok({ object: 'schedule', id: s.id, deleted: true })) },
    { method: 'GET', path: '/v1/projects/:id/domains', reply: (r) => sub(r, PROJECT_DOMAINS[r.params.id] ?? []) },
    { method: 'POST', path: '/v1/projects/:id/domains', reply: onApp(addDomain) },
    { method: 'DELETE', path: '/v1/projects/:id/domains/:name', reply: onApp(removeDomain) },
    {
        method: 'GET',
        path: '/v1/projects/:id/logs',
        reply: (r) => {
            const level = r.query.get('level');
            const deploymentId = r.query.get('deployment_id');
            // A level reads that level and above.
            const rank = (l: string) => ['info', 'warn', 'error'].indexOf(l);
            const rows = (RUNTIME_LOGS[r.params.id] ?? []).filter((l) => (!level || rank(l.level) >= rank(level)) && (!deploymentId || l.deployment_id === deploymentId));
            return sub(r, rows.slice(-Number(r.query.get('limit') ?? 100)));
        },
    },
    {
        method: 'GET',
        path: '/v1/projects/analytics/summary',
        reply: (r) => {
            const period = r.query.get('period') ?? '7d';
            const apps = PROJECTS.filter((p) => userMatches(r.query, p.user_id));
            const weeks = apps.map((p) => trafficOf(p.id, period, 'production'));
            return ok({
                object: 'project_analytics_summary', period, tz: r.query.get('tz') ?? 'UTC', since: weeks[0]?.since ?? NOW, until: NOW, sampled: false,
                data: weeks.map((w, i) => ({ project_id: apps[i].id, requests: w.requests, errors: w.errors })),
            });
        },
    },
    {
        method: 'GET',
        path: '/v1/projects/:id/analytics',
        reply: (r) =>
            PROJECTS.some((p) => p.id === r.params.id)
                ? ok(trafficOf(r.params.id, r.query.get('period') ?? '7d', r.query.get('environment') ?? 'production'))
                : found(undefined, 'app'),
    },
    {
        method: 'GET',
        path: '/v1/projects/:id/usage',
        reply: (r) => (r.set === 'error' ? apiError(500, 'server_error', 'The platform API failed to answer.') : found(USAGE[r.params.id], 'app')),
    },
    {
        method: 'GET',
        path: '/v1/projects/:id/durable_objects',
        // Every other app (a test's own included) declares none.
        reply: (r) =>
            r.params.id === BOOKING_APP_ID
                ? ok({ object: 'list', data: BOOKING_OBJECT_CLASSES, unread: [], cost: { usd: BOOKING_OBJECTS_USD, period_start: '2026-09-01T00:00:00+00:00' } })
                : ok({ object: 'list', data: [], unread: [], cost: null }),
    },
    {
        method: 'DELETE',
        path: '/v1/projects/:id/durable_objects/:cls',
        reply: (r) => {
            const cls = BOOKING_OBJECT_CLASSES.find((c) => (c as { id: string }).id === r.params.cls) as { id: string; name: string } | undefined;
            return cls
                ? ok({
                      // As trash.deleted answers: the class gone from its list, its trash entry, and the operation that takes it back.
                      object: 'durable_object_class',
                      id: cls.id,
                      deleted: true,
                      trash: { object: 'trash_item', id: fixtureId(7, 71_200), kind: 'durable_object_class', resource_id: cls.id, name: `booking/${cls.name}`, user_id: null, trashed_at: new Date(FIXTURE_NOW_MS).toISOString(), purge_after: '2026-10-26T16:20:05.000Z' },
                      restorable_until: '2026-10-26T16:20:05.000Z',
                      operation_id: fixtureId(7, 71_300),
                  })
                : apiError(404, 'not_found', 'The app has no such Durable Object class.');
        },
    },
    {
        method: 'POST',
        path: '/v1/projects/:id/export',
        reply: (r) => operation(505, 'project.export', PROJECTS.find((p) => p.id === r.params.id)?.name ?? '', PROJECTS.find((p) => p.id === r.params.id)?.user_id ?? null),
    },
];

export const routes: FixtureRoute[] = [...repoRoutes, ...projectRoutes];
