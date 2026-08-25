// Regression test for the "re-entering a workflow shows phantom runs" bug.
//
// When a workflow is (re)opened, useWorkflowExecutionTracking subscribes to
// the workflow relay presence service and consumes the relay's `execution_state`
// snapshot, projecting each in-flight execution into `activeExecutions` —
// which drives the Run/Stop button. The relay keeps an execution in that
// snapshot for up to 5 min (TTL) after its last event, so a FINISHED run
// (every node in a terminal state) would otherwise re-appear as a phantom
// "Stop (N)" entry on every reopen. Recovery must reject those and keep
// only genuinely in-flight executions.
//
// This drives synthetic frames through the REAL WorkflowPresenceService and
// the REAL socket receiver — the same paths the relay and socket use — and
// asserts the projected `activeExecutions` (read via the test harness).
//
// Requires the workflow editor to be open. Run:
//   mcp__nc__nc_run_test({ file: "tests/nc/execution-recovery.test.ts" })

import { nc } from '~/lib/nc';
import { getWorkflowPresenceService } from '~/lib/collaboration';
import { socketReceiver } from '~/lib/socket-receiver';

// IDs namespaced so they can never collide with real executions/nodes.
const ZOMBIE_EXEC = '__nc_recovery_zombie__';
const LIVE_EXEC = '__nc_recovery_live__';

interface TestHarness {
    getWorkflowId?: () => string | null;
    getActiveExecutionIds?: () => string[];
}

export default async function () {
    const out: Record<string, unknown> = {};

    const harness = (window as unknown as { __workflowTest?: TestHarness }).__workflowTest;
    const workflowId = harness?.getWorkflowId?.();
    if (!workflowId || typeof harness?.getActiveExecutionIds !== 'function') {
        out.skipped = 'Open the workflow editor before running this test.';
        return out;
    }
    const getActiveExecutionIds = harness.getActiveExecutionIds;

    // Same presence-service instance the recovery hook subscribed to (the
    // singleton is keyed by workflowId). handleMessage is the exact entry
    // point the relay WebSocket's onmessage uses.
    const svc = getWorkflowPresenceService(workflowId) as unknown as {
        handleMessage: (msg: unknown) => void;
    };
    const deliverExecutionState = (executions: unknown[]) =>
        svc.handleMessage({ type: 'execution_state', executions });
    const dispatchSocket = (event: string, data: unknown) =>
        (socketReceiver as unknown as { handleEvent: (e: string, a: unknown[]) => void })
            .handleEvent(event, [data]);

    const activeIds = () => getActiveExecutionIds();
    const baseline = activeIds();
    out.baseline = baseline;

    try {
        // ── relay snapshot: one finished execution + one genuinely live one ──
        // Zombie: every node terminal → finished, must NOT be recovered.
        // Live: a node still 'running' → in flight, must be recovered.
        deliverExecutionState([
            {
                executionId: ZOMBIE_EXEC,
                nodeStates: { __nc_z1: 'completed', __nc_z2: 'error' },
                nodeOutputs: {},
            },
            {
                executionId: LIVE_EXEC,
                nodeStates: { __nc_l1: 'running', __nc_l2: 'completed' },
                nodeOutputs: {},
            },
        ]);
        await nc.wait.until(() => activeIds().includes(LIVE_EXEC), 3000);

        const afterRecovery = activeIds();
        out.afterRecovery = afterRecovery;
        nc.assert.includes(afterRecovery, LIVE_EXEC,
            'live execution (running node) must be recovered as active');
        nc.assert.falsy(afterRecovery.includes(ZOMBIE_EXEC),
            'finished execution (all nodes terminal) must NOT be recovered — this is the phantom-run bug');

        // ── workflow:complete clears the live execution ──
        dispatchSocket('workflow:complete', {
            execution_id: LIVE_EXEC,
            workflow_id: workflowId,
            success: true,
            nodes_executed: 1,
            duration: 0.1,
        });
        await nc.wait.until(() => !activeIds().includes(LIVE_EXEC), 3000);

        const afterComplete = activeIds();
        out.afterComplete = afterComplete;
        nc.assert.falsy(afterComplete.includes(LIVE_EXEC),
            'workflow:complete must clear the recovered execution');
    } finally {
        // Safety net: if an assertion failed mid-way, make sure neither
        // synthetic execution is left stuck in the Run button.
        for (const id of [LIVE_EXEC, ZOMBIE_EXEC]) {
            if (activeIds().includes(id)) {
                dispatchSocket('workflow:complete', {
                    execution_id: id, workflow_id: workflowId,
                    success: true, nodes_executed: 0, duration: 0,
                });
            }
        }
    }

    out.ok = true;
    return out;
}
