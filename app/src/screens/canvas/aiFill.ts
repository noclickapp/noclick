// AI Fill: NoClick's drafter on one step, read back without writing it (`POST /v1/workflows/{id}/drafts` with
// `write: false`), so the canvas applies what it drafted as the person's own edit: their save writes it and their
// undo takes it back.
import { Workflow, type NoClick } from 'noclick';
import type { NodeUpdatePayload } from './applyNodeUpdate';

/** What the panel's Autofill asks for: the operation and every setting, the operation alone, the settings of the
 *  operation the step has, or one setting. */
export type AiFillMode = 'full' | 'operation' | 'fields' | 'single_field';

const DRAFT_MODES: Record<AiFillMode, 'full' | 'operation' | 'fields' | 'field'> = {
    full: 'full',
    operation: 'operation',
    fields: 'fields',
    single_field: 'field',
};

/** One step's draft as `write: false` answers it: the edit the drafter would have written, unwritten. `settings`
 *  is the settings write it would have made (a removed setting as null, the step's `userFields` and `goal` among
 *  them); null when it drafted nothing. */
export interface StepDraft {
    drafted: boolean;
    error: string | null;
    changes: { operation?: string; settings?: Record<string, unknown> } | null;
}

interface DraftResult {
    steps?: Record<string, StepDraft>;
}

/** Draft one step and read back what it would change, writing nothing. */
export async function draftStep(
    client: NoClick,
    workflowId: string,
    stepId: string,
    mode: AiFillMode,
    field?: string
): Promise<StepDraft> {
    const drafting = await Workflow.fromId(workflowId, { client }).draft([stepId], {
        mode: DRAFT_MODES[mode],
        field: mode === 'single_field' ? field : undefined,
        write: false,
    });
    const result = (await drafting.wait()).raw as DraftResult;
    const step = result?.steps?.[stepId];
    if (!step) throw new Error('The draft named no result for this step.');
    return step;
}

/** A draft as the canvas's node update: settings into its config (null removes one), its notes top-level. */
export function draftAsUpdate(draft: StepDraft): NodeUpdatePayload | null {
    if (!draft.changes) return null;
    const { userFields, goal, ...config } = draft.changes.settings ?? {};
    const update: NodeUpdatePayload = {};
    if (draft.changes.operation) update.operation = draft.changes.operation;
    if (Object.keys(config).length > 0) update.config = config;
    if (Array.isArray(userFields)) update.userFields = userFields as string[];
    if (typeof goal === 'string') update.goal = goal;
    return Object.keys(update).length > 0 ? update : null;
}
