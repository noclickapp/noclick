// What stands in the Test Run screen's slot (reads.ts) when no host fills it, over the platform API alone with the
// client a `ClientProvider` above gives:
//
// - what the workflow can stage: `GET /v1/workflows/{id}/test_runs`, each offered situation with its trigger and its
//   staged message. The runs the workflow added itself come from its settings (below), so only the offered ones are
//   taken from the list;
// - a run: `POST /v1/workflows/{id}/rehearsals` with the run's name among the workflow's test runs, a
//   `workflow.rehearse` operation. The API reports a test run when it ends, not step by step: the screen shows it
//   thinking, then every step at once (each call with what it was given, what the simulated world answered and what
//   it would have sent) and the agent's closing words. It plays the test runs the workflow holds, so the screen's
//   changes are written first (`runsSaved`);
// - the workflow's own test runs, names, edits and removals: its `rehearsal_authoring` setting, read with its graph
//   (`GET /v1/workflows/{id}/graph`) and written as an `update_workflow` edit (only its owner's key may);
// - what still needs connecting: the workflow's steps as `GET /v1/workflows/{id}` reads them (a step whose account
//   isn't attached), each type by its name in the step catalog.
//
// A finished run isn't shared from here (a shared run's page is NoClick's app's). The SDK loads with the first read
// (../standardsSdk.ts).
import { useCallback, useEffect, useMemo, useState, useSyncExternalStore } from 'react';
import type { Edge, Node } from '@xyflow/react';
import type { NoClick } from 'noclick';
import { proxy, useSnapshot } from 'valtio';
import { useProvidedClient } from '@/sdk/client';
import { deriveUnmetConnections, type UnmetConnection } from '../readiness';
import type { RehearsalAuthoring } from './authoring';
import type { MockRun } from './scenarios';
import { deriveArtifacts, toReplayRows, type LiveRow, type LiveRunState } from './liveRows';
import type { PickedRun, StagedSituations } from './reads';
import { triggersOfStaged, type StagedTrigger } from './staged';

type Json = Record<string, unknown>;

const sdk = () => import('../standardsSdk');

/** An error as a line a person reads. */
async function said(error: unknown): Promise<string> {
    return (await sdk()).errorText(error);
}

const NO_CLIENT = 'The Test Run needs a client to reach the API with (a ClientProvider above it).';

// ── what the workflow can stage ─────────────────────────────────────────────

/** A step type's name where the catalog didn't give one: its type, spaced. */
const spaced = (nodeType: string) =>
    nodeType
        .replace(/^(automation|trigger)-/, '')
        .replace(/[-_]/g, ' ')
        .replace(/\b[a-z]/g, (c) => c.toUpperCase());

/** The API's list of test runs as the screen's staged list: the offered situations by trigger type, in the list's
 *  order. A run the workflow added is left to its settings, where the screen keeps (and changes) it. */
export function stagedOfTestRuns(offered: readonly Json[]): { staged: StagedTrigger[]; names: Record<string, string> } {
    const byType = new Map<string, StagedTrigger>();
    const names: Record<string, string> = {};
    for (const run of offered) {
        const trigger = (run.trigger ?? {}) as Json;
        const type = String(trigger.type ?? '');
        if (!type) continue;
        if (typeof trigger.label === 'string' && trigger.label) names[type] = trigger.label;
        let group = byType.get(type);
        if (!group) byType.set(type, (group = { node_type: type, operation: typeof trigger.operation === 'string' ? trigger.operation : null, situations: [] }));
        if (run.custom === true) continue;
        group.situations!.push({ key: String(run.key), name: String(run.name), lead: (run.message ?? {}) as MockRun['lead'] });
    }
    return { staged: [...byType.values()], names };
}

export function useV1Scenarios(workflowId: string | null): StagedSituations {
    const client = useProvidedClient();
    const [state, setState] = useState<StagedSituations>({ loading: Boolean(workflowId), triggers: [], error: null });
    useEffect(() => {
        if (!workflowId) return;
        if (!client) {
            setState({ loading: false, triggers: [], error: NO_CLIENT });
            return;
        }
        let cancelled = false;
        (async () => {
            try {
                const { Workflow } = await sdk();
                const offered = await Workflow.fromId(workflowId, { client }).testRuns();
                if (cancelled) return;
                const { staged, names } = stagedOfTestRuns(offered.map((run) => run.raw));
                setState({ loading: false, triggers: triggersOfStaged(staged, (type) => names[type] ?? spaced(type)), error: null });
            } catch (error) {
                const why = await said(error);
                if (!cancelled) setState({ loading: false, triggers: [], error: why });
            }
        })();
        return () => {
            cancelled = true;
        };
    }, [workflowId, client]);
    return state;
}

// ── a run ───────────────────────────────────────────────────────────────────

interface RunSlot {
    /** The run this state is of: another selection reads idle. */
    run: string;
    phase: 'running' | 'done';
    rows: LiveRow[];
    reply: string;
    error: string | null;
    startedAt: number;
}

// Kept per workflow for the page's life, so the screen drawn again (a tab switched away and back) still shows a run
// under way or the one that finished.
const runs = proxy<{ byWorkflow: Record<string, RunSlot> }>({ byWorkflow: {} });

/** A finished test run's transcript as the screen's rows: the agent's words between calls, then each call with what
 *  it was given and what the world answered. The closing words are the reply, drawn as the outcome, not a row. */
export function rowsOfTranscript(transcript: readonly Json[], reply: string, at: number): LiveRow[] {
    const rows: LiveRow[] = [];
    transcript.forEach((step, index) => {
        const id = `step-${index}`;
        if (step.role === 'assistant') {
            const text = typeof step.text === 'string' ? step.text : '';
            if (!text || (index === transcript.length - 1 && text === reply)) return;
            rows.push({ id, tool: '', status: 'completed', startedAt: at, thought: text });
            return;
        }
        const object = (value: unknown) => (value && typeof value === 'object' && !Array.isArray(value) ? (value as Record<string, unknown>) : undefined);
        rows.push({
            id,
            tool: String(step.tool ?? ''),
            status: 'completed',
            startedAt: at,
            outbound: typeof step.outbound === 'string' && step.outbound.trim() ? step.outbound.trim() : undefined,
            args: object(step.arguments),
            result: object(step.result),
        });
    });
    return rows;
}

export function useV1TestRun(workflowId: string | null, picked: PickedRun): LiveRunState {
    const client = useProvidedClient();
    const snap = useSnapshot(runs);
    const slot = workflowId ? snap.byWorkflow[workflowId] : undefined;
    const current = slot && slot.run === picked.slug ? slot : undefined;

    // The running clock the views draw.
    const [tick, forceTick] = useState(0);
    const running = current?.phase === 'running';
    useEffect(() => {
        if (!running) return;
        const t = window.setInterval(() => forceTick((n) => n + 1), 300);
        return () => window.clearInterval(t);
    }, [running]);

    const start = useCallback(async () => {
        if (!workflowId) return;
        const mine: RunSlot = { run: picked.slug, phase: 'running', rows: [], reply: '', error: null, startedAt: Date.now() };
        runs.byWorkflow[workflowId] = mine;
        // A run started since owns the screen: this one's end is then nobody's.
        const still = () => runs.byWorkflow[workflowId]?.startedAt === mine.startedAt && runs.byWorkflow[workflowId]?.run === mine.run;
        const end = (over: Partial<RunSlot>) => {
            if (still()) Object.assign(runs.byWorkflow[workflowId], over, { phase: 'done' });
        };
        if (!client) return end({ error: NO_CLIENT });
        try {
            const { Workflow } = await sdk();
            const operation = await Workflow.fromId(workflowId, { client }).rehearse({ testRun: picked.slug });
            const result = await operation.wait();
            end({ rows: rowsOfTranscript(result.transcript, result.reply, Date.now()), reply: result.reply });
        } catch (error) {
            end({ error: await said(error) });
        }
    }, [workflowId, picked.slug, client]);

    return useMemo<LiveRunState>(() => {
        void tick;
        const now = Date.now();
        return {
            phase: current?.phase ?? 'idle',
            t: current && current.phase === 'running' ? now - current.startedAt : 0,
            rows: toReplayRows(current?.rows ?? [], now),
            artifacts: current?.phase === 'done' ? deriveArtifacts(current?.rows ?? []) : null,
            failed: current?.phase === 'done' && Boolean(current.error),
            start,
            replay: start,
            error: current?.error ?? null,
            reply: current?.reply ?? '',
        };
    }, [current, start, tick]);
}

// ── the workflow's own test runs ────────────────────────────────────────────

export const v1Authoring = {
    read: async (workflowId: string, client: NoClick | null): Promise<Partial<RehearsalAuthoring> | null> => {
        if (!client) throw new Error(NO_CLIENT);
        const { Workflow } = await sdk();
        const graph = await Workflow.fromId(workflowId, { client }).graph();
        const saved = graph.settings?.rehearsal_authoring;
        return saved && typeof saved === 'object' ? (saved as Partial<RehearsalAuthoring>) : null;
    },
    write: async (workflowId: string, authoring: RehearsalAuthoring, client: NoClick | null): Promise<void> => {
        if (!client) throw new Error(NO_CLIENT);
        const { Workflow } = await sdk();
        await Workflow.fromId(workflowId, { client }).edit({}, (batch) => batch.updateWorkflow({ settings: { rehearsal_authoring: authoring as unknown as Json } }));
    },
};

// ── what still needs connecting ─────────────────────────────────────────────

export function useV1Unmet(workflowId: string | null): UnmetConnection[] {
    const client = useProvidedClient();
    const [unmet, setUnmet] = useState<UnmetConnection[]>([]);
    useEffect(() => {
        if (!workflowId || !client) return;
        let cancelled = false;
        (async () => {
            try {
                const { Workflow, stepType } = await sdk();
                const workflow = await Workflow.get(workflowId, { client });
                const steps = workflow.steps;
                const needing = new Set(steps.filter((step) => step.connection && !step.connection.attached).map((step) => step.id));
                if (cancelled || needing.size === 0) return;
                // Each unconnected type by its name in the catalog ("Without Gmail, …").
                const types = [...new Set(steps.filter((step) => needing.has(step.id)).map((step) => step.type))];
                const labels = new Map(await Promise.all(types.map(async (type) => [type, (await stepType(type, { client })).label ?? spaced(type)] as const)));
                if (cancelled) return;
                const nodes = steps.map((step) => ({ id: step.id, type: step.type, position: { x: 0, y: 0 }, data: { label: step.name, operation: step.operation ?? undefined } }) as Node);
                const edges = workflow.edges.map((edge, index) => ({ id: `e${index}`, source: edge.from, target: edge.to, targetHandle: edge.kind === 'tools' ? 'bottom' : undefined }) as Edge);
                const triggers = new Set(steps.filter((step) => step.trigger).map((step) => `${step.type}:${step.operation ?? ''}`));
                setUnmet(
                    deriveUnmetConnections(nodes, edges, {
                        needsConnection: (node) => needing.has(node.id),
                        isTriggerSource: (type, operation) => triggers.has(`${type}:${operation ?? ''}`),
                        nameOf: (type) => labels.get(type) ?? spaced(type),
                    })
                );
            } catch {
                // No readiness signal beats a wrong one.
            }
        })();
        return () => {
            cancelled = true;
        };
    }, [workflowId, client]);
    return unmet;
}

// ── what the screen remembers ───────────────────────────────────────────────

const kept = new Map<string, unknown>();
const keptListeners = new Set<() => void>();

/** Puts `value` under `key` for the page's life: how a test run is asked for from elsewhere (`autorun-<workflow>`). */
export function keep(key: string, value: unknown): void {
    kept.set(key, value);
    keptListeners.forEach((listener) => listener());
}

function subscribeKept(listener: () => void): () => void {
    keptListeners.add(listener);
    return () => void keptListeners.delete(listener);
}

/** Forgets what the screen remembered and every run kept here: what the page starts with. */
export function forgetTestRuns(): void {
    kept.clear();
    for (const id of Object.keys(runs.byWorkflow)) delete runs.byWorkflow[id];
    keptListeners.forEach((listener) => listener());
}

/** What the screen remembers, in the page's memory. */
export function useKeptHere<T>(key: string, initial: T): [T, (value: T) => void] {
    const read = () => (kept.has(key) ? (kept.get(key) as T) : initial);
    const value = useSyncExternalStore(subscribeKept, read, read);
    const set = useCallback((next: T) => keep(key, next), [key]);
    return [value, set];
}
