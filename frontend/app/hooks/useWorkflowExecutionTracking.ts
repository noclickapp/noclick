import { useCallback, useEffect, useRef, useState } from 'react';
import type { Node } from '@xyflow/react';
import { applyNodeUpdate } from '~/lib/applyNodeUpdate';
import { getWorkflowPresenceService } from '~/lib/collaboration';
import type { ExecutionStateResponse } from '~/lib/collaboration/workflowPresenceService';
import { setAgentPresence } from '~/lib/agentPresenceStore';
import { useSocketEvent } from '~/hooks/useSocketEvent';
import type { WorkflowExecutionLog } from '~/components/workflow/WorkflowExecutionLogs';
import { track } from '~/lib/telemetry';

// If a run never produces a workflow:started event within this window, the
// optimistic pending- placeholder is rolled back so the Run button doesn't
// stay stuck on "Stop". workflow:started normally arrives within seconds;
// this only fires when the run genuinely failed to start.
const PENDING_EXECUTION_TIMEOUT_MS = 60_000;

// Node execution states that mean the node has finished. An execution whose
// nodes are ALL in a terminal state is not in flight — used by the relay
// recovery handler to reject finished executions from the workflow relay
// snapshot (the relay keeps an execution listed for up to 5 min after its last
// event, so a reopened workflow would otherwise show finished runs as live).
const TERMINAL_NODE_STATES = new Set(['idle', 'completed', 'error', 'skipped', 'success']);

/**
 * True if a recovered execution looks genuinely in flight: at least one node
 * is in a non-terminal state. An execution with all-terminal (or no) node
 * states has finished. A live run that is momentarily all-terminal (between
 * nodes) self-heals — its next workflow:node:state event re-registers it.
 */
export function isRecoveredExecutionInFlight(nodeStates: Record<string, string>): boolean {
    return Object.values(nodeStates).some((s) => !TERMINAL_NODE_STATES.has(s));
}

// A single concurrent workflow execution. Keyed by execution_id (or a
// synthetic `pending-<timestamp>` / temp id while waiting for the server's
// workflow:started event).
export interface ActiveExecution {
    startedAt: number;
    nodeIds: Set<string>;
}

interface UseWorkflowExecutionTrackingParams {
    workflowId?: string;
    /** Live nodes ref for reading the current node count in logs + executionId matches. */
    nodesRef: React.MutableRefObject<Node[]>;
    setNodes: (updater: (prev: Node[]) => Node[]) => void;
    isMobile: boolean;
    /** Mobile-only error toast queue; parent passes through. */
    enqueueMobileError: (title: string, description: string) => void;
}

// Bundles all execution-tracking state and the two lifecycle socket listeners
// (workflow:started, workflow:complete). The node-state and node-output
// listeners stay in the parent because they reach into UI-navigation state
// (selectedNode, FlowHelperView, pan-to-node) that doesn't belong in this hook.
//
// Returns the raw state + setters + refs because there are ~20 direct
// callsites in the parent (runWorkflow, stopWorkflow, runFromNode, runSingleNode,
// optimistic pending writes, hover-highlight render, checkpoint restore, etc.).
// A "commands-only" API would require touching every callsite; keeping
// setter-passthrough lets this extraction be purely additive.
export function useWorkflowExecutionTracking({
    workflowId,
    nodesRef,
    setNodes,
    isMobile,
    enqueueMobileError,
}: UseWorkflowExecutionTrackingParams) {
    // activeExecutions + its ref + a setter that keeps the ref in sync with state
    const [activeExecutions, _setActiveExecutions] = useState<Map<string, ActiveExecution>>(new Map());
    const activeExecutionsRef = useRef<Map<string, ActiveExecution>>(new Map());
    const setActiveExecutions = useCallback(
        (updater: (prev: Map<string, ActiveExecution>) => Map<string, ActiveExecution>) => {
            _setActiveExecutions((prev) => {
                const next = updater(prev);
                activeExecutionsRef.current = next;
                return next;
            });
        },
        []
    );
    const isWorkflowRunning = activeExecutions.size > 0;

    // Add a placeholder `pending-<ts>` entry so the UI flips to "stop" immediately
    // when the user hits run. The real execution_id arrives via workflow:started
    // and replaces this entry. Returns the temp id so callers that need to
    // correlate logs can reference it.
    const addPendingExecution = useCallback((): string => {
        const tempId = `pending-${Date.now()}`;
        setActiveExecutions((prev) =>
            new Map(prev).set(tempId, { startedAt: Date.now(), nodeIds: new Set<string>() })
        );
        // Safety net: roll back the optimistic placeholder if workflow:started
        // never arrives to replace it (lost event / run failed to start).
        // Without this the Run button stays stuck on "Stop" indefinitely.
        setTimeout(() => {
            setActiveExecutions((prev) => {
                if (!prev.has(tempId)) return prev;
                console.warn(
                    `[execution] pending run ${tempId} expired without a workflow:started event; clearing stale running state`
                );
                const next = new Map(prev);
                next.delete(tempId);
                return next;
            });
        }, PENDING_EXECUTION_TIMEOUT_MS);
        return tempId;
    }, [setActiveExecutions]);

    // Execution ID being hovered in the stop dropdown → highlights its nodes
    const [hoveredExecutionId, setHoveredExecutionId] = useState<string | null>(null);

    // Loading state for interface blocks during execution
    const [loadingBlockIds, setLoadingBlockIds] = useState<Set<string>>(new Set());

    // Time the most recent run started — used for "time to first output" analytics
    const runStartTimeRef = useRef<number>(0);

    // Completed execution IDs, to handle out-of-order Event Relay delivery
    // (workflow:complete can arrive before workflow:started for webhook-triggered runs).
    // Capped at 100 entries to prevent unbounded growth.
    const completedExecutionIdsRef = useRef<Set<string>>(new Set());

    // Execution IDs for background runs (interface components fetching their own
    // data via the SDK). These execute for real but must NOT count toward the
    // global Run/Stop button. The id is learned from workflow:started — the
    // relay guarantees it arrives before any workflow:node:state for the run —
    // and consulted by the node:state handler so it skips activeExecutions too.
    const backgroundExecutionIdsRef = useRef<Set<string>>(new Set());

    // Execution log history (shown in the Logs tab)
    const [logs, setLogs] = useState<WorkflowExecutionLog[]>([]);

    // ─── Socket: workflow:started ─────────────────────────────────────────────
    useSocketEvent('workflow:started', useCallback((data) => {
        if (data.workflow_id && data.workflow_id !== workflowId) return;

        // Background run (interface component fetching its own data): it executes
        // for real, but stays out of the global Run button and the Logs tab.
        // Record the id so node:state / workflow:complete skip it too.
        if (data.background) {
            backgroundExecutionIdsRef.current.add(data.execution_id);
            return;
        }

        // BE-acknowledged the run. Distinct from workflow.run_started (which
        // is FE-perceived at click time) — the gap between them is the
        // request-to-ack latency, queryable as a separate signal.
        track('workflow.run_acked', {
            execution_id: data.execution_id,
            workflow_id: data.workflow_id,
            resumed: !!data.resumed,
        });

        // Guard against out-of-order delivery: if this execution's
        // workflow:complete already arrived, don't re-register it as active —
        // but still strip the optimistic pending- placeholder below, otherwise
        // the placeholder is orphaned and the Run button stays stuck.
        // A resumed run (suspended on a delay/approval node, now waking up)
        // legitimately re-starts an execution_id whose earlier segment already
        // completed — don't treat that as stale out-of-order delivery.
        const alreadyCompleted = completedExecutionIdsRef.current.has(data.execution_id) && !data.resumed;

        // Replace any optimistic pending- entry with the real execution ID.
        // Preserve nodeIds if node:state events already created the entry
        // before workflow:started arrived (can happen under slow relays).
        setActiveExecutions((prev) => {
            const next = new Map(prev);
            for (const key of next.keys()) {
                if (key.startsWith('pending-')) {
                    next.delete(key);
                    break;
                }
            }
            if (!alreadyCompleted) {
                const existing = next.get(data.execution_id);
                next.set(data.execution_id, {
                    startedAt: Date.now(),
                    nodeIds: existing?.nodeIds ?? new Set<string>(),
                });
            }
            return next;
        });

        if (alreadyCompleted) return;

        const startedLog: WorkflowExecutionLog = {
            id: data.execution_id,
            timestamp: new Date(),
            status: 'running',
            message: `Executing workflow with ${nodesRef.current.length} nodes...`,
        };

        // Update the temporary running log with the actual execution ID
        setLogs((prev) => {
            const updated = [...prev];
            // A run we already have a log line for (a suspended run resuming):
            // flip the existing line back to running instead of duplicating it.
            const existingIndex = updated.findIndex((log) => log.id === data.execution_id);
            if (existingIndex !== -1) {
                updated[existingIndex] = {
                    ...updated[existingIndex],
                    status: 'running',
                    message: startedLog.message,
                };
                return updated;
            }
            const runningIndex = updated.findIndex(
                (log) => log.status === 'running' && log.id.startsWith('run-')
            );
            if (runningIndex !== -1) {
                updated[runningIndex] = startedLog;
            } else {
                updated.unshift(startedLog);
            }
            return updated;
        });
    }, [workflowId, setActiveExecutions, nodesRef]));

    // ─── Socket: workflow:complete ────────────────────────────────────────────
    useSocketEvent('workflow:complete', useCallback((data) => {
        if (data.workflow_id && data.workflow_id !== workflowId) return;

        // Background run completed — it was never in activeExecutions or the
        // logs, so just forget the id and skip all foreground bookkeeping.
        if (backgroundExecutionIdsRef.current.delete(data.execution_id)) return;

        // Engineering-side completion event. Pairs with workflow.run_started
        // to compute success rate, P99 duration, suspended share, etc.
        track('workflow.run_completed', {
            execution_id: data.execution_id,
            workflow_id: data.workflow_id,
            success: !!data.success,
            suspended: !!data.suspended,
            duration_sec: typeof data.duration === 'number' ? data.duration : null,
            nodes_executed: typeof data.nodes_executed === 'number' ? data.nodes_executed : null,
            had_error: !!data.error,
        });

        // Track completion so late-arriving workflow:started events are ignored.
        // Capped at 100 + FIFO eviction: 100 is comfortably above the
        // concurrent-execution ceiling — if this is ever exceeded in practice it
        // would mean 100 executions completed before a single workflow:started
        // arrived, which would indicate a more serious relay failure. Set
        // insertion order is guaranteed (ES2015+ in all supported engines).
        completedExecutionIdsRef.current.add(data.execution_id);
        if (completedExecutionIdsRef.current.size > 100) {
            const first = completedExecutionIdsRef.current.values().next().value;
            if (first) completedExecutionIdsRef.current.delete(first);
        }

        // A suspended run paused on a delay/approval node — it has not finished,
        // so show it as "Waiting" rather than completed.
        const completedLog: WorkflowExecutionLog = {
            id: data.execution_id,
            timestamp: new Date(),
            status: data.suspended ? 'waiting' : data.success ? 'success' : 'error',
            message: data.suspended
                ? 'Workflow paused — waiting to resume.'
                : data.error || `Workflow completed successfully. Processed ${data.nodes_executed} nodes.`,
            duration: Math.round(data.duration * 1000),
            nodesExecuted: data.nodes_executed,
        };

        setLogs((prev) => {
            const updated = [...prev];
            const runningIndex = updated.findIndex(
                (log) => log.id === data.execution_id && log.status === 'running'
            );
            if (runningIndex !== -1) {
                updated[runningIndex] = completedLog;
            } else {
                updated.unshift(completedLog);
            }
            return updated;
        });

        setActiveExecutions((prev) => {
            const next = new Map(prev);
            const removed = next.delete(data.execution_id);
            // If workflow:started was lost or arrived out-of-order, the
            // optimistic pending- placeholder was never swapped for the real
            // execution id — the delete above is a no-op. Drop a pending-
            // entry so the run state clears instead of hanging.
            if (!removed) {
                for (const key of next.keys()) {
                    if (key.startsWith('pending-')) {
                        next.delete(key);
                        break;
                    }
                }
            }
            return next;
        });

        // Clear loading state + runStartTime only when no executions remain
        if (activeExecutionsRef.current.size === 0) {
            setLoadingBlockIds(new Set());
            runStartTimeRef.current = 0;
        }

        // Reset only nodes belonging to this execution; nodes from other
        // concurrent executions keep their current state.
        setNodes((nodes) =>
            nodes.map((n) => {
                const state = n.data?.executionState;
                if (!state || state === 'idle') return n;
                if (n.data?._executionId !== data.execution_id) return n;
                return applyNodeUpdate(n, {
                    extras: {
                        executionState: state === 'error' ? 'error' : 'idle',
                    },
                });
            })
        );

        // Mobile: queue a toast if workflow failed without a per-node error
        if (isMobile && !data.success && data.error) {
            enqueueMobileError('Workflow failed', data.error);
        }
    }, [setNodes, workflowId, isMobile, enqueueMobileError, setActiveExecutions]));

    // ─── workflow relay state recovery ───────────────────────────────────────
    // Recover in-flight executions on page load / reconnect. The presence
    // service auto-requests state on auth:success; this just subscribes.
    useEffect(() => {
        if (!workflowId) return;
        const presenceService = getWorkflowPresenceService(workflowId);

        const unsubExec = presenceService.subscribeToExecutionEvents((event: ExecutionStateResponse) => {
            if (!event.executions?.length) return;
            const executions = event.executions;

            setActiveExecutions((prev) => {
                const next = new Map(prev);
                for (const exec of executions) {
                    // Reject finished executions from the relay snapshot — they
                    // would otherwise show as phantom "running" entries every
                    // time the workflow is reopened (see isRecoveredExecutionInFlight).
                    if (!isRecoveredExecutionInFlight(exec.nodeStates)) continue;
                    next.set(exec.executionId, {
                        startedAt: Date.now(),
                        nodeIds: new Set<string>(Object.keys(exec.nodeStates)),
                    });
                }
                return next;
            });

            // Apply node states + outputs from the latest execution that has
            // state for each node. Recovery is a stale snapshot of what the
            // DO had buffered — the live workflow:node:output channel is
            // authoritative once it has populated a node. Skip the recovery
            // write for any node whose current execution_id matches and
            // already has output, so we never overwrite a freshly-arrived
            // live output with the relay's older buffered value.
            setNodes((nodes) =>
                nodes.map((n) => {
                    let nodeState: string | undefined;
                    let nodeOutput: unknown;
                    let nodeExecId: string | undefined;
                    for (const exec of executions) {
                        if (exec.nodeStates[n.id]) {
                            nodeState = exec.nodeStates[n.id];
                            nodeExecId = exec.executionId;
                        }
                        if (exec.nodeOutputs[n.id]) {
                            nodeOutput = exec.nodeOutputs[n.id];
                        }
                    }
                    if (!nodeState && !nodeOutput) return n;
                    const extras: Record<string, any> = {};
                    if (nodeState) {
                        extras.executionState = nodeState;
                        extras._executionId = nodeExecId;
                        // Recovered terminal state: stamp _lastRunAt only when
                        // nothing fresher owns it. The FlowCanvas live node-state
                        // handler does the same for directly watched runs; this
                        // covers reopening a workflow mid-flight.
                        if ((nodeState === 'completed' || nodeState === 'error')
                            && n.data?._lastRunAt === undefined) {
                            extras._lastRunStatus = nodeState;
                            extras._lastRunAt = Date.now();
                        }
                    }
                    if (nodeOutput) {
                        const liveHasFresherOutput =
                            n.data?.output !== undefined &&
                            n.data?._executionId === nodeExecId;
                        if (!liveHasFresherOutput) {
                            extras.output = nodeOutput;
                            extras.outputTimestamp = Date.now();
                        }
                    }
                    return applyNodeUpdate(n, { extras });
                })
            );
        });

        // Relay-backed local agent presence drives the canvas count and the
        // conversation-scoped busy state without touching workflow data.
        const unsubAgents = presenceService.subscribeToAgentPresence(setAgentPresence);

        return () => { unsubExec(); unsubAgents(); };
    }, [workflowId, setActiveExecutions, setNodes]);

    return {
        // State
        activeExecutions,
        isWorkflowRunning,
        hoveredExecutionId,
        loadingBlockIds,
        logs,
        // Setters
        setActiveExecutions,
        setHoveredExecutionId,
        setLoadingBlockIds,
        setLogs,
        // Refs
        activeExecutionsRef,
        completedExecutionIdsRef,
        backgroundExecutionIdsRef,
        runStartTimeRef,
        // Commands
        addPendingExecution,
    };
}
