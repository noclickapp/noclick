// The platform API's answers for what the canvas shows of a workflow's runs: its runs and their counts, one run with
// what each step did, starting and stopping a run (its operation and the operation's wait), a step's outputs across runs
// and in one, each step's latest output, and what a step type outputs. Everything else is the graph fixtures' (the
// workflow's graph, its edits, its step types). The server's outputs hold a secret (a request's Authorization header)
// that no read carries, as the API withholds it (`withheld`).
import { refusedToAccountKey } from '@/screens/console/ownerOnly';
import { graphFetch, WORKFLOW, type Observe } from '../graph/fixtures';

type Json = Record<string, unknown>;

/** A value a step's stored output holds that no read carries. */
export const OUTPUT_SECRET = 'the bearer value an output held';

const AT = '2026-10-16T15:00:00.000Z';
const run = (id: string, status: string, source: string, started: string, finished: string | null, more: Json = {}): Json => ({
    object: 'workflow_run', id, workflow_id: WORKFLOW, status, waiting_on: null, inputs: {}, outputs: {}, error: null, source, trigger: null,
    user_id: null, operation_id: null, started_at: started, finished_at: finished, ...more,
});

/** The workflow's runs, newest first: one from the app that succeeded, a phone call's that failed, a schedule's still
 *  running, one from code, one from its endpoint. */
export const RUNS: Json[] = [
    run('run_5', 'succeeded', 'app', AT, '2026-10-16T15:00:04.250Z'),
    run('run_4', 'failed', 'trigger', '2026-10-16T09:20:00.000Z', '2026-10-16T09:21:12.000Z', {
        trigger: 'call',
        error: { type: 'run_failed', message: "Step 'Slack' failed: channel_not_found", run_id: 'run_4', step: 'Slack' },
    }),
    run('run_3', 'running', 'schedule', '2026-10-15T08:00:00.000Z', null),
    run('run_2', 'succeeded', 'api', '2026-10-14T08:00:00.000Z', '2026-10-14T08:00:01.000Z', { operation_id: 'op_2' }),
    run('run_1', 'succeeded', 'endpoint', '2026-10-13T08:00:00.000Z', '2026-10-13T08:00:00.640Z'),
];

/** What each step did in a run, as one run's read gives it: bounded outputs, a secret left out and named. */
export function stepsOf(runId: string): Json[] {
    const failed = runId === 'run_4';
    return [
        { id: 'hook', name: 'Webhook', status: 'succeeded', error: null, output: { body: { order: 'ord_81' }, headers: { 'content-type': 'application/json' } }, withheld: ['headers.Authorization'] },
        { id: 'agent', name: 'Agent', status: 'succeeded', error: null, output: { reply: 'Sorted: priority.' }, withheld: [] },
        failed
            ? { id: 'slack', name: 'Slack', status: 'failed', error: 'channel_not_found', output: null, withheld: [] }
            : { id: 'slack', name: 'Slack', status: runId === 'run_3' ? 'running' : 'succeeded', error: null, output: runId === 'run_3' ? null : { ok: true, ts: '1.2' }, withheld: [] },
    ];
}

/** Each step's stored outputs, newest first, as the server holds them: the webhook's with the secret it never reads back. */
const STORED: Record<string, Array<{ run_id: string; created_at: string; output: Json }>> = {
    hook: [
        { run_id: 'run_5', created_at: AT, output: { body: { order: 'ord_81' }, headers: { 'content-type': 'application/json', Authorization: OUTPUT_SECRET } } },
        { run_id: 'run_4', created_at: '2026-10-16T09:20:00.000Z', output: { body: { order: 'ord_80' }, headers: { Authorization: OUTPUT_SECRET } } },
    ],
    agent: [{ run_id: 'run_5', created_at: AT, output: { reply: 'Sorted: priority.' } }],
    slack: [{ run_id: 'run_5', created_at: AT, output: { ok: true, ts: '1.2' } }],
};

/** An output as a read gives it: the Authorization header left out and named. */
function shown(output: Json): { output: Json; withheld: string[] } {
    const headers = output.headers as Json | undefined;
    if (!headers || !('Authorization' in headers)) return { output, withheld: [] };
    const { Authorization: _held, ...rest } = headers;
    return { output: { ...output, headers: rest }, withheld: ['headers.Authorization'] };
}

function refused(status: number, type: string, message: string): Response {
    return Response.json({ error: { type, message } }, { status });
}

export interface RunsFetchOptions {
    actsAs?: 'owner' | 'key';
    observe?: Observe;
    /** The runs listed (RUNS by default). */
    runs?: () => Json[];
    /** How many a page of them holds (2, so the log pages). */
    pageSize?: number;
    /** A run started here: the run its operation settles with (`run_new`, succeeded, by default), or the error it
     *  fails with. */
    started?: () => { run: Json } | { error: Json };
    /** One run as it reads now (a run of RUNS with its steps by default). */
    oneRun?: (runId: string) => Json | null;
    /** How the graph fixtures answer the rest: the workflow as the server holds it, its version and each edit. */
    graph?: Pick<Parameters<typeof graphFetch>[0], 'server' | 'version' | 'edit'>;
}

/** The platform API's answers for the canvas's runs and results, the graph fixtures answering the rest. Acting as one
 *  of the account's keys (`key`), what the API refuses a key is refused here too. */
export function runsFetch(options: RunsFetchOptions = {}): typeof fetch {
    const graph = graphFetch({ ...options.graph, actsAs: options.actsAs, observe: options.observe });
    const runs = options.runs ?? (() => RUNS);
    const pageSize = options.pageSize ?? 2;
    const started = options.started ?? (() => ({ run: run('run_new', 'succeeded', 'api', AT, '2026-10-16T15:00:02.000Z', { operation_id: 'op_new' }) }));
    const oneRun = options.oneRun ?? ((runId: string) => {
        const found = [...runs(), 'run' in started() ? (started() as { run: Json }).run : null].find((r) => r && r.id === runId);
        return found ? { ...found, steps: stepsOf(runId) } : null;
    });
    const operation = (status: string): Json => {
        const settled = started();
        const base = { object: 'operation', id: 'op_new', kind: 'workflow.run', status, summary: 'Orders', created_at: AT, updated_at: AT, result: null, error: null };
        if (status === 'running' || status === 'canceled') return base;
        return 'run' in settled ? { ...base, status: 'succeeded', result: settled.run } : { ...base, status: 'failed', error: settled.error };
    };

    const answer = async (method: string, url: URL): Promise<Response | null> => {
        const path = decodeURIComponent(url.pathname);
        if (options.actsAs === 'key' && refusedToAccountKey(method, url.pathname)) {
            return refused(403, 'permission_denied', 'A key can’t do this: only the account’s signed-in owner can.');
        }
        const workflow = `/v1/workflows/${WORKFLOW}`;
        if (method === 'GET' && path === `${workflow}/runs`) {
            // Narrowed as the API narrows them: by status, how each started, the kind of event that started it, whether
            // it waits, and text in its error.
            const listed = (name: string) => url.searchParams.get(name)?.split(',');
            const waits = url.searchParams.get('waiting');
            const search = url.searchParams.get('search')?.toLowerCase();
            const rows = runs().filter(
                (r) =>
                    (!listed('status') || listed('status')!.includes(String(r.status))) &&
                    (!listed('source') || listed('source')!.includes(String(r.source))) &&
                    (!listed('trigger') || listed('trigger')!.includes(String(r.trigger))) &&
                    (waits === null || String(Boolean(r.waiting_on)) === waits) &&
                    (!search || String((r.error as Json | null)?.message ?? '').toLowerCase().includes(search))
            );
            const from = url.searchParams.get('cursor') ? rows.findIndex((r) => r.id === url.searchParams.get('cursor')) + 1 : 0;
            const size = Math.min(pageSize, Number(url.searchParams.get('limit') ?? pageSize));
            const page = rows.slice(from, from + size);
            return Response.json({ object: 'list', data: page, next_cursor: from + size < rows.length ? page[page.length - 1].id : null });
        }
        if (method === 'GET' && path === `${workflow}/runs/counts`) {
            const by = (key: string) => runs().reduce<Record<string, number>>((n, r) => ({ ...n, [String(r[key])]: (n[String(r[key])] ?? 0) + 1 }), {});
            const { null: _noTrigger, ...byTrigger } = by('trigger');
            return Response.json({
                object: 'run_counts', workflow_id: WORKFLOW, total: runs().length, by_status: { running: 0, succeeded: 0, failed: 0, ...by('status') },
                waiting: runs().filter((r) => r.waiting_on).length, by_source: by('source'), by_trigger: byTrigger,
            });
        }
        if (method === 'POST' && path === `${workflow}/runs`) return Response.json(operation('running'), { status: 202 });
        if (method === 'GET' && path === '/v1/operations/op_new/wait') return Response.json(operation('settled'));
        if (method === 'GET' && path === '/v1/operations/op_new') return Response.json(operation('settled'));
        if (method === 'POST' && path === '/v1/operations/op_new/cancel') return Response.json(operation('canceled'));
        const stop = path.match(new RegExp(`^${workflow}/runs/([^/]+)/stop$`));
        if (method === 'POST' && stop) {
            const found = oneRun(stop[1]);
            return found ? Response.json({ ...found, status: 'failed', finished_at: AT }) : refused(404, 'not_found', `No run '${stop[1]}' of this workflow.`);
        }
        const one = path.match(new RegExp(`^${workflow}/runs/([^/]+)$`));
        if (method === 'GET' && one) {
            const found = oneRun(one[1]);
            return found ? Response.json(found) : refused(404, 'not_found', `No run '${one[1]}' of this workflow.`);
        }
        const listed = path.match(new RegExp(`^${workflow}/steps/([^/]+)/outputs$`));
        if (method === 'GET' && listed) {
            const rows = (STORED[listed[1]] ?? []).slice(0, Number(url.searchParams.get('limit') ?? 10));
            return Response.json({
                object: 'list',
                next_cursor: null,
                data: rows.map((row) => ({
                    object: 'step_output', step_id: listed[1], run_id: row.run_id, workflow_id: WORKFLOW, iteration: null, source: 'app', status: 'succeeded',
                    error: null, created_at: row.created_at, no_event: false, preview: Object.keys(row.output).join(', '), withheld: shown(row.output).withheld,
                })),
            });
        }
        const output = path.match(new RegExp(`^${workflow}/steps/([^/]+)/outputs/([^/]+)$`));
        if (method === 'GET' && output) {
            const row = (STORED[output[1]] ?? []).find((r) => r.run_id === output[2]);
            if (!row) return refused(404, 'not_found', `The step stored nothing in run '${output[2]}'.`);
            return Response.json({
                object: 'step_output', step_id: output[1], run_id: row.run_id, workflow_id: WORKFLOW, iteration: null, source: 'app', status: 'succeeded',
                error: null, created_at: row.created_at, no_event: false, path: null, full: url.searchParams.get('full') === 'true', truncated: false, ...shown(row.output),
            });
        }
        if (method === 'GET' && path === `${workflow}/outputs`) {
            const wanted = url.searchParams.get('steps')?.split(',') ?? Object.keys(STORED);
            const latest = wanted.filter((id) => STORED[id]?.length).map((id) => [id, shown(STORED[id][0].output)] as const);
            return Response.json({
                object: 'step_outputs', workflow_id: WORKFLOW, full: url.searchParams.get('full') === 'true', truncated: [],
                outputs: Object.fromEntries(latest.map(([id, read]) => [id, read.output])),
                withheld: Object.fromEntries(latest.filter(([, read]) => read.withheld.length).map(([id, read]) => [id, read.withheld])),
            });
        }
        const shape = path.match(/^\/v1\/step_types\/([^/]+)\/output_shape$/);
        if (method === 'GET' && shape) {
            const known = shape[1] === 'automation-slack';
            return Response.json({
                object: 'step_output_shape', type: shape[1], operation: url.searchParams.get('operation') ?? 'default',
                shape: known ? { ok: 'boolean', ts: 'string' } : null,
                suggested_refs: known ? [{ path: 'ts', label: 'Message time', description: 'When Slack stored the message.' }] : null,
            });
        }
        return null;
    };
    return async (input, init) => {
        const request = new Request(input, init);
        const url = new URL(request.url);
        const answered = answer(request.method, url);
        const mine = await answered;
        if (!mine) return graph(input, init);
        const text = request.method === 'GET' ? '' : await request.text();
        options.observe?.(request.method, url.pathname, Promise.resolve(mine), text ? (JSON.parse(text) as Json) : {}, init);
        return mine;
    };
}
