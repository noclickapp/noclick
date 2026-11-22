// @vitest-environment happy-dom
// What the canvas shows of a workflow's runs where no host fills its run slots, over the platform API: the run log
// (its pages and counts, narrowed by how runs ended and saying what else isn't offered), a step's output panel (its
// stored outputs, each read whole and never a secret; the shape a step type outputs; pinning the one shown as the
// step's mock, nothing saved under a name), a failed step's error (no builder to ask; funds and the spending cap
// opened on NoClick), one run's results (what each step did, read again as it moves), and running: the whole workflow,
// from a step, one step alone, and stopping a run, each after the canvas's pending save lands.
import { act, cleanup, fireEvent, render, renderHook, screen, waitFor } from '@testing-library/react';
import type { Node } from '@xyflow/react';
import { NoClick } from 'noclick';
import { useState, type ReactNode } from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { ClientProvider } from '@/sdk/client';
import { createWorkLive, WorkLiveContext, type WorkLive } from '@/sdk/live';
import { standing } from '@/slots';
import { addFundsUrl, billingSettingsUrl, NOCLICK_SITE } from '@/screens/console/lib/site';
import { WORKFLOW } from '../graph/fixtures';
import { graphRecords, markGraphDirty, recordGraphSnapshot, setCanvasEditsClient, setCanvasMounted, setGraphLoaded } from '../graph/liveGraphStore';
import { RUN_FIXES, RUN_READS, RUN_RESULTS, SAVED_OUTPUTS } from '../slots';
import { ErrorActionButton } from './ErrorActionButton';
import { OUTPUT_SECRET, RUNS, runsFetch, stepsOf, type RunsFetchOptions } from './fixtures';
import { NodeExecutionErrorBanner } from './NodeExecutionErrorBanner';
import { OutputPanel } from './OutputPanel';
import { WorkflowExecutionLogs, type LogsFilters, type WorkflowExecutionLog } from './RunLog';
import { logOfRun } from './standards';
import { useRunLog } from './useRunLog';
import { useWorkflowRuns } from './useRun';

type Json = Record<string, unknown>;

afterEach(() => {
    cleanup();
    setCanvasEditsClient(null);
    for (const id of Object.keys(graphRecords)) delete graphRecords[id];
});

/** A client over the fixtures, every call kept as `METHOD path?query` with its body. */
function world(options: RunsFetchOptions = {}) {
    const sent: { line: string; body: Json }[] = [];
    const answers = runsFetch(options);
    const client = new NoClick({
        apiKey: 'held-by-this-app-server',
        baseUrl: 'https://api.test',
        maxRetries: 0,
        fetch: async (input, init) => {
            const url = new URL(String(input instanceof Request ? input.url : input));
            sent.push({ line: `${init?.method ?? 'GET'} ${decodeURIComponent(url.pathname)}${url.search}`, body: init?.body ? (JSON.parse(String(init.body)) as Json) : {} });
            return answers(input, init);
        },
    });
    return { client, sent, lines: () => sent.map((call) => call.line) };
}

const within = (client: NoClick, live?: WorkLive) =>
    function Around({ children }: { children: ReactNode }) {
        return (
            <ClientProvider client={client}>
                <WorkLiveContext.Provider value={live ?? null}>{children}</WorkLiveContext.Provider>
            </ClientProvider>
        );
    };

beforeEach(() => {
    if (!('ResizeObserver' in globalThis)) {
        (globalThis as Record<string, unknown>).ResizeObserver = class {
            observe() {}
            unobserve() {}
            disconnect() {}
        };
    }
    if (!('IntersectionObserver' in globalThis)) {
        (globalThis as Record<string, unknown>).IntersectionObserver = class {
            observe() {}
            unobserve() {}
            disconnect() {}
        };
    }
});

// ── the run log ──────────────────────────────────────────────────────────────

describe('the run log on the API', () => {
    function useLog() {
        const reads = standing(RUN_READS).useRunReads();
        const [logs, setLogs] = useState<WorkflowExecutionLog[]>([]);
        return { reads, logs, log: useRunLog({ workflowId: WORKFLOW, reads, setLogs }) };
    }

    it('reads a page and the counts, pages on, and narrows by how runs ended', async () => {
        const { client, lines } = world();
        const { result } = renderHook(useLog, { wrapper: within(client) });
        await waitFor(() => expect(result.current.logs).toHaveLength(2));
        await waitFor(() => expect(result.current.log.counts.total).toBe(5));
        expect(lines().sort()).toEqual([`GET /v1/workflows/${WORKFLOW}/runs/counts`, `GET /v1/workflows/${WORKFLOW}/runs?limit=50`]);
        // Each run as a row: how it ended, how it started, what it said, how long it took.
        expect(result.current.logs.map((log) => [log.id, log.status, log.trigger, log.message, log.duration])).toEqual([
            ['run_5', 'success', 'manual', 'Completed.', 4250],
            ['run_4', 'error', 'event', "Step 'Slack' failed: channel_not_found", 72_000],
        ]);
        // A run from code and one from the workflow's endpoint are both the API's; an event the log has no name of its
        // own for (a phone call) is an event.
        expect(result.current.log.counts).toEqual({ total: 5, byStatus: { success: 3, error: 1, running: 1, waiting: 0 }, byTrigger: { manual: 1, event: 1, cron: 1, run: 2 } });
        expect(result.current.log.hasMore).toBe(true);

        act(() => result.current.log.onLoadMore());
        await waitFor(() => expect(result.current.logs).toHaveLength(4));
        expect(lines().at(-1)).toBe(`GET /v1/workflows/${WORKFLOW}/runs?limit=50&cursor=run_4`);
        expect(result.current.logs[2]).toMatchObject({ id: 'run_3', status: 'running', trigger: 'cron', message: 'Running…', duration: undefined });

        act(() => result.current.log.onFiltersChange({ status: 'error', trigger: 'all', query: '' }));
        await waitFor(() => expect(result.current.logs.map((log) => log.id)).toEqual(['run_4']));
        expect(lines().at(-1)).toBe(`GET /v1/workflows/${WORKFLOW}/runs?limit=50&status=failed`);
        expect(result.current.log.hasMore).toBe(false);
        // The same filters again read nothing.
        const before = lines().length;
        act(() => result.current.log.onFiltersChange({ status: 'error', trigger: 'all', query: '' }));
        expect(lines()).toHaveLength(before);
    });

    it('narrows by everything the log offers: a search, how a run started, and the runs that wait apart from those that run', async () => {
        const run = (id: string, more: Json): Json => ({ ...RUNS[2], id, ...more });
        const runs = [
            run('run_9', { source: 'trigger', trigger: 'email', waiting_on: 'approval' }),
            run('run_8', { source: 'trigger', trigger: 'webhook', waiting_on: 'delay' }),
            run('run_7', { source: 'api', waiting_on: 'agent_turn' }),
            run('run_6', { source: 'trigger', trigger: 'webhook' }),
            ...RUNS,
        ];
        const { client, lines } = world({ runs: () => runs, pageSize: 50 });
        const { result } = renderHook(useLog, { wrapper: within(client) });
        await waitFor(() => expect(result.current.logs).toHaveLength(9));
        expect(result.current.reads.narrows).toEqual({ waiting: true, source: true, search: true });
        // A run that waits is the log's waiting, whatever it waits on; an email's and a webhook's wear their own marks.
        expect(result.current.logs.slice(0, 4).map((log) => [log.id, log.status, log.trigger])).toEqual([
            ['run_9', 'waiting', 'email'], ['run_8', 'waiting', 'webhook'], ['run_7', 'waiting', 'run'], ['run_6', 'running', 'webhook'],
        ]);
        await waitFor(() => expect(result.current.log.counts.total).toBe(9));
        expect(result.current.log.counts).toEqual({
            total: 9,
            byStatus: { success: 3, error: 1, running: 2, waiting: 3 },
            byTrigger: { manual: 1, cron: 1, run: 3, email: 1, webhook: 2, event: 1 },
        });
        const read = `GET /v1/workflows/${WORKFLOW}/runs?limit=50`;
        for (const [filters, query, ids] of [
            [{ status: 'all', trigger: 'all', query: 'CHANNEL_not' }, '&search=CHANNEL_not', ['run_4']],
            [{ status: 'all', trigger: 'webhook', query: '' }, '&trigger=webhook', ['run_8', 'run_6']],
            [{ status: 'all', trigger: 'email', query: '' }, '&trigger=email', ['run_9']],
            [{ status: 'all', trigger: 'manual', query: '' }, '&source=app', ['run_5']],
            [{ status: 'all', trigger: 'cron', query: '' }, '&source=schedule', ['run_3']],
            [{ status: 'all', trigger: 'run', query: '' }, '&source=api%2Cendpoint', ['run_7', 'run_2', 'run_1']],
            [{ status: 'waiting', trigger: 'all', query: '' }, '&status=running&waiting=true', ['run_9', 'run_8', 'run_7']],
            [{ status: 'running', trigger: 'all', query: '' }, '&status=running&waiting=false', ['run_6', 'run_3']],
        ] as [LogsFilters, string, string[]][]) {
            act(() => result.current.log.onFiltersChange(filters));
            await waitFor(() => expect(lines().at(-1)).toBe(read + query));
            await waitFor(() => expect(result.current.logs.map((log) => log.id)).toEqual(ids));
        }
        // A way of starting the API has no word for (a form's) lists nothing, and reads nothing.
        const before = lines().length;
        act(() => result.current.log.onFiltersChange({ status: 'all', trigger: 'form', query: '' }));
        await waitFor(() => expect(result.current.logs).toEqual([]));
        expect([lines().length, result.current.log.error]).toEqual([before, null]);
    });

    it('offers only what its reads narrow by, and says what it doesn’t', async () => {
        const logs = RUNS.map(logOfRun);
        const counts = { total: 5, byStatus: { success: 3, error: 1, running: 1, waiting: 0 }, byTrigger: {} };
        const said: LogsFilters[] = [];
        const draw = (narrows?: { waiting: boolean; source: boolean; search: boolean }) =>
            render(<WorkflowExecutionLogs logs={logs} counts={counts} hasMore={false} loading={false} onFiltersChange={(f) => said.push(f)} onLoadMore={() => undefined} narrows={narrows} />);

        const narrowed = draw({ waiting: false, source: false, search: false });
        const chips = () => [...narrowed.container.querySelectorAll('button')].map((b) => b.textContent?.replace(/\d+$/, ''));
        expect(chips()).toEqual(['All', 'Success', 'Error', 'Running']);
        expect(narrowed.container.querySelector('input')).toBeNull();
        expect(screen.getByTestId('run-log-not-offered').textContent).toBe(
            'The list narrows by how runs ended. Searching their errors, narrowing them by how they started and telling a run that waits (on an approval or a delay) from one that runs aren’t on the API yet: NoClick’s app does them.'
        );
        // A run an event started wears its own mark, never a webhook's.
        expect(narrowed.container.textContent).toContain('Event');
        fireEvent.click(screen.getByRole('button', { name: /Error/ }));
        expect(said.at(-1)).toEqual({ status: 'error', trigger: 'all', query: '' });
        narrowed.unmount();

        // Everything, where nothing says otherwise: every chip and the search, and no note.
        const whole = draw();
        expect([...whole.container.querySelectorAll('button')].map((b) => b.textContent?.replace(/\d+$/, ''))).toEqual([
            'All', 'Success', 'Error', 'Running', 'Waiting', 'Any', 'Manual', 'Schedule', 'Webhook', 'Email', 'Form', 'API',
        ]);
        expect(whole.container.querySelector('input')).not.toBeNull();
        expect(screen.queryByTestId('run-log-not-offered')).toBeNull();
        whole.unmount();

        const noSearch = draw({ waiting: true, source: true, search: false });
        expect(screen.getByTestId('run-log-not-offered').textContent).toBe('The list narrows by how runs ended. Searching their errors isn’t on the API yet: NoClick’s app does it.');
        noSearch.unmount();
    });
});

// ── a step's output ──────────────────────────────────────────────────────────

const step = (id: string, type: string, data: Json = {}): Node => ({ id, type, position: { x: 0, y: 0 }, data: { label: id, ...data } });

describe('a step’s output on the API', () => {
    it('reads the step’s stored outputs whole, never a secret, and walks back through them', async () => {
        const { client, sent, lines } = world();
        const picked: unknown[] = [];
        const view = render(<OutputPanel selectedNode={step('hook', 'trigger-webhook')} workflowId={WORKFLOW} onHistoryIndexChange={(...args) => picked.push(args)} />, { wrapper: within(client) });
        // The newest of two is shown.
        await waitFor(() => expect(view.container.textContent).toContain('2 of 2'));
        expect(view.container.textContent).toContain('ord_81');
        expect(lines().filter((line) => line.includes('/steps/')).sort()).toEqual([
            `GET /v1/workflows/${WORKFLOW}/steps/hook/outputs/run_4?full=true`,
            `GET /v1/workflows/${WORKFLOW}/steps/hook/outputs/run_5?full=true`,
            `GET /v1/workflows/${WORKFLOW}/steps/hook/outputs?limit=20`,
        ]);
        // The older one, and the canvas is told which is shown.
        fireEvent.click(view.container.querySelector('.-ml-1 button')!);
        await waitFor(() => expect(view.container.textContent).toContain('1 of 2'));
        expect(view.container.textContent).toContain('ord_80');
        expect(picked.at(-1)).toEqual(['hook', 1, { body: { order: 'ord_80' }, headers: {} }]);
        expect(view.container.innerHTML).not.toContain(OUTPUT_SECRET);
        expect(JSON.stringify(sent)).not.toContain(OUTPUT_SECRET);
    });

    it('shows what a step type outputs before the step has run, read once', async () => {
        const { client, lines } = world();
        const view = render(<OutputPanel selectedNode={step('slack', 'automation-slack', { operation: 'send_message' })} workflowId="wf_none" />, { wrapper: within(client) });
        await waitFor(() => expect(view.container.textContent).toContain('Expected Output'));
        await waitFor(() => expect(view.container.textContent).toContain('ts'));
        const shape = 'GET /v1/step_types/automation-slack/output_shape?operation=send_message';
        expect(lines().filter((line) => line.includes('output_shape'))).toEqual([shape]);
        view.unmount();
        // Kept for the session by type and operation.
        const again = render(<OutputPanel selectedNode={step('slack-2', 'automation-slack', { operation: 'send_message' })} workflowId="wf_none" />, { wrapper: within(client) });
        await waitFor(() => expect(again.container.textContent).toContain('Expected Output'));
        expect(lines().filter((line) => line.includes('output_shape'))).toEqual([shape]);
        // A type nothing is known of yet: nothing to show.
        again.unmount();
        const none = render(<OutputPanel selectedNode={step('log', 'log')} workflowId="wf_none" />, { wrapper: within(client) });
        await waitFor(() => expect(none.container.textContent).toContain('No output yet'));
        // Nothing is saved under a name here, so the hint offers no saved output to load.
        expect(none.container.textContent).toContain('Run the step to see what it outputs');
    });

    it('pins the output shown as the step’s mock, and saves nothing under a name', async () => {
        const { client, lines } = world();
        const mocked: unknown[] = [];
        const view = render(<OutputPanel selectedNode={step('agent', 'agent', { output: { reply: 'Sorted: priority.' } })} workflowId={WORKFLOW} onMockToggle={(...args) => mocked.push(args)} />, {
            wrapper: within(client),
        });
        await waitFor(() => expect(lines().some((line) => line.includes('/steps/agent/outputs/run_5'))).toBe(true));
        expect(standing(SAVED_OUTPUTS).useSaved('agent')).toMatchObject({ saved: [], save: null, share: null });
        expect(view.container.querySelector('button[title="Save this output for later use"]')).toBeNull();
        expect(view.container.textContent).not.toContain('Load from saved outputs');
        fireEvent.click(view.container.querySelector('button[title="Use this output as mock data"]')!);
        expect(mocked).toEqual([['agent', true, { reply: 'Sorted: priority.' }]]);
    });
});

// ── a failed step ────────────────────────────────────────────────────────────

describe('a failed step on the API', () => {
    it('asks no builder, opens funds and the spending cap on NoClick, and keeps a link a link', () => {
        const { client } = world();
        expect(standing(RUN_FIXES).ask).toBeNull();
        const failed = step('slack', 'automation-slack', { error: 'Slack: channel_not_found' });
        const banner = render(<NodeExecutionErrorBanner node={failed} />, { wrapper: within(client) });
        expect(banner.container.textContent).toContain('channel_not_found');
        expect(banner.container.querySelector('button')).toBeNull();
        banner.unmount();

        const drawn = (action: { type: string; label: string; url?: string }) => render(<ErrorActionButton action={action} nodeId="slack" />, { wrapper: within(client) }).container;
        expect(drawn({ type: 'open_topup', label: 'Add funds' }).querySelector('a')?.getAttribute('href')).toBe(addFundsUrl(NOCLICK_SITE));
        expect(drawn({ type: 'open_billing', label: 'Raise the cap' }).querySelector('a')?.getAttribute('href')).toBe(billingSettingsUrl(NOCLICK_SITE));
        expect(drawn({ type: 'open_url', label: 'Open billing', url: 'https://provider.test/billing' }).querySelector('a')?.getAttribute('href')).toBe('https://provider.test/billing');
        // The step's accounts are on the step: no jump is offered where nothing takes it.
        expect(drawn({ type: 'open_credentials', label: 'Reconnect' }).innerHTML).toBe('');
        expect(drawn({ type: 'something_new', label: 'Do it' }).innerHTML).toBe('');
    });
});

// ── one run's results ────────────────────────────────────────────────────────

describe('a run’s results on the API', () => {
    it('lists what each step did, says what stays on NoClick, and reads again as the run moves', async () => {
        let slack = 'running';
        const { client, lines } = world({
            oneRun: (id) => ({ ...RUNS.find((r) => r.id === 'run_3')!, id, status: slack === 'running' ? 'running' : 'succeeded', steps: stepsOf(slack === 'running' ? 'run_3' : 'run_5') }),
        });
        const live = createWorkLive();
        const Results = standing(RUN_RESULTS);
        const opened: string[] = [];
        const onClose = vi.fn();
        render(<Results workflowId={WORKFLOW} runId="run_3" onClose={onClose} onOpenStep={(id) => opened.push(id)} />, { wrapper: within(client, live) });
        await screen.findByTestId('run-step-slack');
        expect(screen.getByTestId('run-steps').textContent).toContain('Running');
        expect(screen.getByTestId('run-step-hook').textContent).toContain('Left out, as a secret: headers.Authorization.');
        expect(screen.getByTestId('run-step-slack').textContent).toContain('Running');
        expect(screen.getByTestId('run-steps').textContent).toContain('A run replayed on the canvas, and the calls its agents made, are in NoClick’s app');
        expect(lines()).toEqual([`GET /v1/workflows/${WORKFLOW}/runs/run_3`]);

        // Another run's move reads nothing; this run's reads it again.
        act(() => live.deliver('platform:resource', { kind: 'workflow_run', id: 'run_9', parent_id: WORKFLOW }));
        expect(lines()).toHaveLength(1);
        slack = 'succeeded';
        act(() => live.deliver('platform:resource', { kind: 'workflow_run', id: 'run_3', parent_id: WORKFLOW }));
        await waitFor(() => expect(screen.getByTestId('run-step-slack').textContent).toContain('Succeeded'));
        expect(lines()).toHaveLength(2);

        fireEvent.click(screen.getByRole('button', { name: 'Slack' }));
        expect(opened).toEqual(['slack']);
        fireEvent.click(screen.getByRole('button', { name: 'Close' }));
        expect(onClose).toHaveBeenCalled();
    });

    it('draws nothing while no run is open, and a failed run with its error', async () => {
        const { client, lines } = world();
        const Results = standing(RUN_RESULTS);
        const closed = render(<Results workflowId={WORKFLOW} runId={null} onClose={() => undefined} />, { wrapper: within(client) });
        expect(closed.baseElement.querySelector('[data-testid="run-steps"]')).toBeNull();
        expect(lines()).toEqual([]);
        closed.unmount();
        render(<Results workflowId={WORKFLOW} runId="run_4" onClose={() => undefined} />, { wrapper: within(client) });
        await screen.findByTestId('run-step-slack');
        expect(screen.getByTestId('run-steps').textContent).toContain("Step 'Slack' failed: channel_not_found");
        expect(screen.getByTestId('run-step-slack').textContent).toContain('Failed');
    });
});

// ── running ──────────────────────────────────────────────────────────────────

describe('running a workflow on the API', () => {
    const NODES: Node[] = [step('hook', 'trigger-webhook'), step('agent', 'agent'), step('slack', 'automation-slack')];

    function useRuns(client: NoClick, onRunMoved?: () => void) {
        const [nodes, setNodes] = useState<Node[]>(NODES);
        return { nodes, runs: useWorkflowRuns({ client, workflowId: WORKFLOW, setNodes, onRunMoved }) };
    }
    const states = (nodes: Node[]) => nodes.map((n) => [n.id, n.data.executionState ?? null, n.data._lastRunStatus ?? null]);

    it('runs the whole workflow, from a step and one step alone, and gives each step its output whole', async () => {
        const { client, sent, lines } = world();
        const moved = vi.fn();
        const { result } = renderHook(() => useRuns(client, moved), { wrapper: within(client, createWorkLive()) });

        await act(() => result.current.runs.run());
        expect(sent.find((call) => call.line === `POST /v1/workflows/${WORKFLOW}/runs`)?.body).toEqual({ inputs: {} });
        expect(lines()).toEqual([
            `POST /v1/workflows/${WORKFLOW}/runs`,
            expect.stringMatching(/^GET \/v1\/operations\/op_new\/wait/),
            `GET /v1/workflows/${WORKFLOW}/runs/run_new`,
            `GET /v1/workflows/${WORKFLOW}/outputs?steps=hook%2Cagent%2Cslack&full=true`,
        ]);
        // Each step rests with how its run went and what it output, never the secret its stored output holds.
        expect(states(result.current.nodes)).toEqual([['hook', 'idle', 'completed'], ['agent', 'idle', 'completed'], ['slack', 'idle', 'completed']]);
        expect(result.current.nodes[0].data.output).toEqual({ body: { order: 'ord_81' }, headers: { 'content-type': 'application/json' } });
        expect(JSON.stringify(result.current.nodes)).not.toContain(OUTPUT_SECRET);
        expect(result.current.runs).toMatchObject({ busy: false, running: [], error: null });
        expect(moved).toHaveBeenCalledTimes(1);

        await act(() => result.current.runs.run({ fromStep: 'agent' }));
        await act(() => result.current.runs.run({ fromStep: 'slack', only: true }));
        expect(sent.filter((call) => call.line === `POST /v1/workflows/${WORKFLOW}/runs`).map((call) => call.body)).toEqual([
            { inputs: {} },
            { inputs: {}, from_step: 'agent' },
            { inputs: {}, from_step: 'slack', only: true },
        ]);
    });

    it('shows a failed run’s steps and says why it failed', async () => {
        const failed = { ...RUNS[1], id: 'run_bad' };
        const { client } = world({
            started: () => ({ error: { type: 'run_failed', message: "Step 'Slack' failed: channel_not_found", run_id: 'run_bad', step: 'Slack' } }),
            oneRun: (id) => ({ ...failed, id, steps: stepsOf('run_4') }),
        });
        const { result } = renderHook(() => useRuns(client), { wrapper: within(client, createWorkLive()) });
        await act(() => result.current.runs.run());
        expect(result.current.runs.error).toContain("Step 'Slack' failed: channel_not_found");
        expect(states(result.current.nodes)).toEqual([['hook', 'idle', 'completed'], ['agent', 'idle', 'completed'], ['slack', 'idle', 'error']]);
        expect(result.current.nodes[2].data.error).toBe('channel_not_found');
    });

    it('follows a run someone else started as its steps move, and stops it', async () => {
        let ended = false;
        const { client, lines } = world({
            oneRun: (id) => ({ ...RUNS[2], id, status: ended ? 'failed' : 'running', finished_at: ended ? '2026-10-15T08:01:00.000Z' : null, steps: stepsOf('run_3') }),
        });
        const live = createWorkLive();
        const { result } = renderHook(() => useRuns(client), { wrapper: within(client, live) });
        // A run of another workflow moves nothing here.
        act(() => live.deliver('platform:resource', { kind: 'workflow_run', id: 'run_x', parent_id: 'wf_other' }));
        expect(lines()).toEqual([]);
        act(() => live.deliver('platform:resource', { kind: 'workflow_run', id: 'run_3', parent_id: WORKFLOW }));
        await waitFor(() => expect(result.current.runs.running).toEqual(['run_3']));
        expect(states(result.current.nodes)).toEqual([['hook', 'completed', 'completed'], ['agent', 'completed', 'completed'], ['slack', 'running', null]]);

        ended = true;
        await act(() => result.current.runs.stop());
        expect(lines()).toContain(`POST /v1/workflows/${WORKFLOW}/runs/run_3/stop`);
        await waitFor(() => expect(result.current.runs.running).toEqual([]));
        expect(result.current.nodes[2].data.executionState).toBe('idle');
    });

    it('lands the canvas’s pending save before it runs, and never runs a workflow it couldn’t save', async () => {
        const { client, lines } = world();
        setCanvasEditsClient(client);
        recordGraphSnapshot(WORKFLOW, false, { nodes: NODES, edges: [] }, false);
        setCanvasMounted(WORKFLOW, false, true);
        setGraphLoaded(WORKFLOW, true);
        const rec = graphRecords[WORKFLOW];
        rec.nodes = [...rec.nodes, step('mine', 'log')];
        markGraphDirty(WORKFLOW);
        const { result } = renderHook(() => useRuns(client), { wrapper: within(client, createWorkLive()) });
        await act(() => result.current.runs.run());
        const order = lines().map((line) => line.replace(/\?.*$/, ''));
        expect(order.indexOf(`POST /v1/workflows/${WORKFLOW}/edits`)).toBeGreaterThan(-1);
        expect(order.indexOf(`POST /v1/workflows/${WORKFLOW}/edits`)).toBeLessThan(order.indexOf(`POST /v1/workflows/${WORKFLOW}/runs`));

        // A viewer's canvas saves nothing: what it changed can't land, so nothing runs.
        rec.readOnly = true;
        rec.nodes = [...rec.nodes, step('more', 'log')];
        rec.dirty = true;
        const before = lines().length;
        await act(() => result.current.runs.run());
        expect(result.current.runs.error).toBe('This didn’t run: the workflow’s last changes couldn’t be saved, and a run reads the saved workflow.');
        expect(lines()).toHaveLength(before);
    });
});
