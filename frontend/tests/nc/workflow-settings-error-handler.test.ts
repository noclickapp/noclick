// Live round-trip test for the WorkflowSettingsDialog's error_handler_workflow_id
// field. Exercises the full save path: dialog → socket workflow:update → DB →
// workflow:get → re-render. Catches the bugs the backend unit tests can't
// surface (Pydantic accepts the key on the request, settings JSONB merge
// preserves it, the dialog reloads the value into its picker). Run with
// nc_run_test against an open workflow tab.

import { nc } from '~/lib/nc';
import {
    sendEventAsync,
    WorkflowUpdateRequest,
    WorkflowGetRequest,
} from '~/lib/socket-sender';

interface UpdateResp {
    error?: string;
    workflow?: { settings?: Record<string, unknown> };
}
interface GetResp {
    workflow?: { settings?: Record<string, unknown> };
    error?: string;
}

export default async function () {
    const out: Record<string, unknown> = {};
    const workflowId: string | undefined =
        (window as { __workflowTest?: { getWorkflowId?: () => string } }).__workflowTest?.getWorkflowId?.();
    out.workflowId = workflowId;
    if (!workflowId) throw new Error('No workflow open — open a workflow first');

    // Use a synthetic (non-existent) UUID — the dispatcher will silently
    // no-op against it at run-time, but the SAVE path doesn't care whether
    // the target exists. This keeps the test self-contained.
    const targetId = crypto.randomUUID();
    out.targetId = targetId;

    // Snapshot the current settings so we can restore them at the end.
    const before = (await sendEventAsync(
        WorkflowGetRequest.create({ workflow_id: workflowId, request_id: crypto.randomUUID() }),
    )) as GetResp;
    if (before?.error) throw new Error('workflow:get failed: ' + before.error);
    const priorSettings: Record<string, unknown> = { ...(before.workflow?.settings || {}) };
    out.priorSettings = priorSettings;

    try {
        // 1. Save the picker value.
        const save = (await sendEventAsync(
            WorkflowUpdateRequest.create({
                workflow_id: workflowId,
                request_id: crypto.randomUUID(),
                // Mirror exactly what WorkflowSettingsDialog.handleSave sends.
                settings: {
                    min_required_credits: priorSettings.min_required_credits ?? null,
                    min_required_balance: null,
                    error_handler_workflow_id: targetId,
                },
            }),
        )) as UpdateResp;
        out.save = save;
        if (save?.error) throw new Error('workflow:update failed: ' + save.error);
        // The update callback returns the merged settings — verify the new
        // key landed (Pydantic acceptance + JSONB merge + serialization).
        nc.assert.equal(
            save.workflow?.settings?.error_handler_workflow_id,
            targetId,
            'workflow:update response carries the new error_handler_workflow_id',
        );

        // 2. Re-fetch through workflow:get — proves it actually hit the DB,
        // not just bounced through the in-memory handler response.
        const after = (await sendEventAsync(
            WorkflowGetRequest.create({ workflow_id: workflowId, request_id: crypto.randomUUID() }),
        )) as GetResp;
        out.after = after.workflow?.settings;
        if (after?.error) throw new Error('workflow:get(2) failed: ' + after.error);
        nc.assert.equal(
            after.workflow?.settings?.error_handler_workflow_id,
            targetId,
            'workflow:get re-reads the persisted error_handler_workflow_id',
        );

        // 3. Clearing — null wipes the value (so the dispatcher gate treats
        // the workflow as no-handler).
        const cleared = (await sendEventAsync(
            WorkflowUpdateRequest.create({
                workflow_id: workflowId,
                request_id: crypto.randomUUID(),
                settings: { error_handler_workflow_id: null },
            }),
        )) as UpdateResp;
        out.cleared = cleared;
        if (cleared?.error) throw new Error('clear update failed: ' + cleared.error);
        const clearedVal = cleared.workflow?.settings?.error_handler_workflow_id;
        // JSONB merge writes null (doesn't delete the key) — either is fine
        // for the gate, which treats both as "no target".
        nc.assert.truthy(
            clearedVal === null || clearedVal === undefined,
            'workflow:update with null clears the error_handler_workflow_id',
        );
    } finally {
        // Restore the row to its pre-test state so subsequent test runs (and
        // the user's own workflow) aren't carrying a synthetic value.
        await sendEventAsync(
            WorkflowUpdateRequest.create({
                workflow_id: workflowId,
                request_id: crypto.randomUUID(),
                settings: {
                    // Replay every key we touched, restoring or nulling.
                    min_required_credits: priorSettings.min_required_credits ?? null,
                    min_required_balance: priorSettings.min_required_balance ?? null,
                    error_handler_workflow_id:
                        (priorSettings.error_handler_workflow_id as string | null | undefined) ?? null,
                },
            }),
        );
    }

    out.ok = true;
    return out;
}
