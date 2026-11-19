// A fake of a machine's own page over Work's fixtures: its view as `GET /v1/machines/{id}` reads it now (this month's
// spend, uptime, who's working, its last check-in's health), the company check before a first machine, its shell's
// token, its home folder's files, and the verbs its page sends (rename, resize, stop, start, restart, ports, delete,
// which moves its agents back to their sandboxes). The routes answer as the platform does; anything else is left to
// the fixture that called them.
type Json = Record<string, unknown>;

const MIN = 60_000;
const reply = (body: unknown, status = 200) =>
    new Response(JSON.stringify(body), {
        status,
        headers: { 'Content-Type': 'application/json' },
    });
const refuse = (
    status: number,
    type: string,
    message: string,
    extra: Json = {}
) => reply({ error: { type, message, ...extra } }, status);

/** Where the account's company check stands (`GET /v1/machines/vetting`). */
export type VettingStatus =
    | 'not_submitted'
    | 'pending'
    | 'approved'
    | 'rejected';

/** A file or folder on a machine's disk, by its absolute path. */
export interface DiskEntry {
    dir?: boolean;
    content?: string;
    size?: number;
    at: string;
}

export interface MachineWorld {
    machines: Json[];
    agents: Json[];
    vetting: { value: Json };
    disks: Map<string, Map<string, DiskEntry>>;
    now: () => number;
}

export const HOME = '/home/noclick';

/** What a NoClick machine's view adds once it runs: its spend, uptime, who works on it and how busy it is. */
export function runningNoClick(now: number, over: Json = {}): Json {
    return {
        host: 'digitalocean',
        max_monthly_usd: 40,
        status_reason: null,
        conversations_at_once: 2,
        spent_usd_this_month: 16.64,
        started_at: new Date(now - 12 * 24 * 60 * MIN).toISOString(),
        last_seen_at: new Date(now - 12_000).toISOString(),
        working_count: 0,
        agent_states: [],
        health: {
            cpus: 2,
            load_1m: 0.76,
            cpu_percent: 38,
            memory_used_gb: 2.6,
            memory_total_gb: 4,
            disk_used_gb: 31,
            disk_total_gb: 80,
        },
        pending: null,
        ports: [],
        app_testing: 'never',
        ...over,
    };
}

/** Your own Mac with NoClick on it, three quarters of it for agents. */
export function ownMac(now: number, over: Json = {}): Json {
    return {
        object: 'machine',
        id: 'm-own-mbp',
        name: 'rowan-mbp',
        kind: 'own',
        status: 'running',
        status_reason: null,
        size: null,
        region: null,
        host: null,
        os: 'Ubuntu 24.04.3 LTS (VM on macOS 15.1)',
        hostname: 'rowan-mbp',
        cpu: 10,
        memory_gb: 16,
        disk_gb: 64,
        monthly_usd: 0,
        max_monthly_usd: null,
        conversations_at_once: 4,
        agent_share: 0.75,
        agent_share_fixed: true,
        pairing: null,
        spent_usd_this_month: 0,
        started_at: new Date(now - 3 * 24 * 60 * MIN).toISOString(),
        last_seen_at: new Date(now - 8_000).toISOString(),
        working_count: 0,
        agent_states: [],
        health: {
            cpus: 10,
            load_1m: 2.2,
            cpu_percent: 22,
            memory_used_gb: 3.1,
            memory_total_gb: 16,
            disk_used_gb: 18,
            disk_total_gb: 64,
        },
        pending: null,
        ports: [],
        app_testing: 'ask_first',
        created_at: new Date(now - 30 * 24 * 60 * MIN).toISOString(),
        ...over,
    };
}

/** A home folder with what agents and people leave on a machine: an app, logs, a note and a backup too big to fetch. */
export function sampleDisk(now: number): Map<string, DiskEntry> {
    const at = (ms: number) => new Date(now - ms).toISOString();
    return new Map<string, DiskEntry>([
        [HOME, { dir: true, at: at(MIN) }],
        [`${HOME}/apps`, { dir: true, at: at(5 * 24 * 60 * MIN) }],
        [`${HOME}/logs`, { dir: true, at: at(MIN) }],
        [
            `${HOME}/notes.txt`,
            {
                content:
                    'Restart the test database after the Postgres upgrade.\nThe support agent replies from support@example.com.\n',
                at: at(2 * 24 * 60 * MIN),
            },
        ],
        [
            `${HOME}/apps/storefront-preview`,
            { dir: true, at: at(5 * 24 * 60 * MIN) },
        ],
        [
            `${HOME}/apps/storefront-preview/package.json`,
            {
                content:
                    '{\n  "name": "storefront-preview",\n  "scripts": { "start": "node server.js" }\n}\n',
                at: at(5 * 24 * 60 * MIN),
            },
        ],
        [
            `${HOME}/apps/storefront-preview/server.js`,
            {
                content:
                    'import http from "node:http";\n\nhttp.createServer((req, res) => res.end("Storefront preview")).listen(3000);\n',
                at: at(5 * 24 * 60 * MIN),
            },
        ],
        [
            `${HOME}/logs/support-2026-11-10.log`,
            {
                content:
                    '09:58:12 replied to #1123 (refund approved)\n09:47:03 drafted a reply to #1122\n',
                at: at(2 * MIN),
            },
        ],
        [
            `${HOME}/logs/backup-2026-11-09.tar.gz`,
            { size: 41_200_000, at: at(24 * 60 * MIN) },
        ],
    ]);
}

const parent = (path: string) => path.slice(0, path.lastIndexOf('/')) || '/';
const resolve = (path: string | null) => {
    const p = !path ? HOME : path.startsWith('/') ? path : `${HOME}/${path}`;
    return p.replace(/\/+$/, '') || '/';
};
const sizeOf = (e: DiskEntry) =>
    e.size ?? new TextEncoder().encode(e.content ?? '').byteLength;

function entryView(path: string, e: DiskEntry): Json {
    return {
        object: 'machine_entry',
        path,
        type: e.dir ? 'directory' : 'file',
        size: e.dir ? null : sizeOf(e),
        updated_at: e.at,
    };
}

/** The company check, a held machine (bought before NoClick approved the company) and the page's verbs; undefined for
 *  any other request. */
export function machineWorldRoutes(
    world: MachineWorld,
    method: string,
    path: string,
    query: URLSearchParams,
    body: Json,
    raw?: unknown
): Response | undefined {
    // What runs now, as Resources' Machines lists it: NoClick's machines (yours are listed apart), priced as charged.
    if (method === 'GET' && path === '/v1/compute') {
        const data = world.machines
            .filter((m) => m.kind !== 'own')
            .map((m) => ({
                object: 'compute',
                kind: 'machine',
                id: m.id,
                name: m.name,
                status: m.status,
                user_id: null,
                region: m.region,
                cpu: m.cpu,
                memory_gb: m.memory_gb,
                started_at: m.created_at,
                usd_per_hour:
                    Math.round((Number(m.monthly_usd) / 730) * 1e6) / 1e6,
                usd_per_month: m.monthly_usd,
                spent_usd_today: null,
                running: world.agents
                    .filter((a) => a.machine_id === m.id)
                    .map((a) => ({
                        agent_id: a.id,
                        agent_name: a.name,
                        conversation: 'main',
                        harness: a.harness,
                        state: 'live',
                    })),
            }));
        return reply({ object: 'list', data, next_cursor: null });
    }
    if (path === '/v1/machines/vetting') {
        if (method === 'GET') return reply(world.vetting.value);
        if (method === 'POST') {
            if (world.vetting.value.status === 'approved')
                return refuse(
                    409,
                    'conflict',
                    'Your company is already approved for machines.'
                );
            world.vetting.value = {
                object: 'machine_vetting',
                status: 'pending',
                company_name: body.company_name,
                website: body.website,
                country: body.country,
                use_case: body.use_case,
                policy_version: '2026-10-08',
                submitted_at: new Date(world.now()).toISOString(),
                decided_at: null,
                reason: null,
            };
            return reply(world.vetting.value);
        }
    }
    const at = path.match(/^\/v1\/machines\/([^/]+)(\/.*)?$/);
    if (!at || at[1] === 'sizes' || at[1] === 'own') return undefined;
    const [, id, rest = ''] = at;
    const m = world.machines.find((x) => x.id === id);
    if (!m) return undefined;
    const notRunning = () =>
        refuse(503, 'not_available', `The machine is ${m.status}.`, {
            next_step: 'Retry once it’s running (GET /v1/machines/{id}).',
        });
    const ownRefused = (what: string) =>
        refuse(
            400,
            'invalid_request',
            `Your own machine isn’t NoClick’s to reach: ${what} is refused.`
        );

    if (rest === '' && method === 'DELETE') {
        // Its agents go back to their own sandboxes, then it's gone (the charge stops today).
        for (const a of world.agents)
            if (a.machine_id === id) a.machine_id = null;
        world.machines.splice(world.machines.indexOf(m), 1);
        return new Response(null, { status: 204 });
    }
    if (rest === '' && method === 'PATCH') {
        if (m.kind === 'own' && body.size)
            return refuse(
                400,
                'invalid_request',
                'Your own machine has no size: it’s sized by the box and free.',
                { field: 'size' }
            );
        if (typeof body.name === 'string') m.name = body.name;
        if ('agent_share' in body) m.agent_share = body.agent_share ?? 0.75;
        if (typeof body.app_testing === 'string')
            m.app_testing = body.app_testing;
        if (typeof body.size === 'string' && body.size !== m.size) {
            m.pending = { size: body.size, move: false };
            m.status = 'updating';
        }
        return reply({
            ...m,
            pairing: m.pairing
                ? {
                      ...(m.pairing as Json),
                      code: null,
                      command: null,
                      commands: null,
                  }
                : null,
        });
    }
    if (rest === '/stop' && method === 'POST') {
        if (m.kind === 'own') return ownRefused('stopping it');
        Object.assign(m, {
            status: 'stopped',
            status_reason: 'stopped',
            working_count: 0,
            started_at: null,
        });
        return reply(m);
    }
    if (rest === '/start' && method === 'POST') {
        if (m.kind === 'own') return ownRefused('starting it');
        Object.assign(m, { status: 'provisioning', status_reason: null });
        return reply(m);
    }
    if (rest === '/restart' && method === 'POST') {
        if (m.kind === 'own') return ownRefused('a restart');
        m.status = 'restarting';
        return reply(
            {
                object: 'operation',
                id: `op-restart-${id}`,
                kind: 'machine.restart',
                status: 'running',
                result: null,
                error: null,
            },
            202
        );
    }
    if (rest === '/shell' && method === 'POST') {
        if (m.status !== 'running') return notRunning();
        return reply({
            object: 'machine_shell',
            machine_id: id,
            url: 'wss://api.noclick.test/v1/terminals/attach',
            token: `machine-shell-${id}`,
            token_expires_at: new Date(world.now() + 2 * MIN).toISOString(),
            idle_limit_s: 900,
        });
    }
    if (rest === '/ports' && method === 'POST') {
        const port = Number(body.port);
        const host = `${String(m.name)}-${port}.noclick.test`;
        m.ports = [
            ...((m.ports as Json[] | undefined) ?? []).filter(
                (p) => p.port !== port
            ),
            {
                object: 'machine_port',
                port,
                url: `https://${host}`,
                public: body.public === true,
            },
        ];
        return reply(
            (m.ports as Json[]).find((p) => p.port === port),
            201
        );
    }
    const closing = rest.match(/^\/ports\/(\d+)$/);
    if (closing && method === 'DELETE') {
        m.ports = ((m.ports as Json[] | undefined) ?? []).filter(
            (p) => p.port !== Number(closing[1])
        );
        return new Response(null, { status: 204 });
    }
    if (rest === '/files') {
        if (m.status !== 'running') return notRunning();
        const disk = world.disks.get(id) ?? new Map<string, DiskEntry>();
        world.disks.set(id, disk);
        const target = resolve(query.get('path'));
        if (method === 'GET' && query.get('view') === 'list') {
            const folder = disk.get(target);
            if (!folder)
                return refuse(404, 'not_found', `Nothing is at ${target}.`);
            if (!folder.dir)
                return refuse(400, 'invalid_request', `${target} is a file.`);
            const data = [...disk.entries()]
                .filter(([p]) => p !== target && parent(p) === target)
                .sort(([a], [b]) => a.localeCompare(b))
                .map(([p, e]) => entryView(p, e));
            return reply({
                object: 'list',
                path: target,
                data,
                next_cursor: null,
            });
        }
        if (method === 'GET') {
            const file = disk.get(target);
            if (!file || file.dir)
                return refuse(404, 'not_found', `No file at ${target}.`);
            if (sizeOf(file) > 16 * 1024 * 1024)
                return refuse(
                    400,
                    'invalid_request',
                    `${target} is ${sizeOf(file)} bytes; downloads are capped at 16777216.`
                );
            return new Response(new TextEncoder().encode(file.content ?? ''), {
                status: 200,
                headers: { 'Content-Type': 'application/octet-stream' },
            });
        }
        if (method === 'PUT') {
            const size =
                raw instanceof Uint8Array
                    ? raw.byteLength
                    : typeof raw === 'string'
                      ? raw.length
                      : raw instanceof Blob
                        ? raw.size
                        : Number(body.size_bytes ?? 0);
            const content = typeof raw === 'string' ? raw : undefined;
            disk.set(target, {
                content,
                size: content === undefined ? size : undefined,
                at: new Date(world.now()).toISOString(),
            });
            return reply({
                object: 'machine_file',
                machine_id: id,
                path: target,
                size,
            });
        }
    }
    return undefined;
}

/** `POST /v1/machines` while the company isn't approved: refused until it's sent, then a held machine that starts once
 *  NoClick approves it, never charged before. Undefined once it's approved (buying goes on as usual). */
export function heldPurchase(
    world: Pick<MachineWorld, 'vetting'>
): Response | 'held' | undefined {
    const status = world.vetting.value.status as VettingStatus;
    if (status === 'approved') return undefined;
    if (status === 'pending') return 'held';
    return refuse(
        403,
        'action_required',
        status === 'rejected'
            ? `NoClick didn’t approve your company for machines: ${String(world.vetting.value.reason)}`
            : 'Machines need your company vetted by NoClick first, under the machines usage policy.',
        {
            vetting: status,
        }
    );
}
