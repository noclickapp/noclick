// A workflow's variables: what its author declared (`variable_definitions` in its settings), with the values every
// `{{vars.x}}` on the canvas resolves to, and reading and writing the declarations on the platform API.
//
// Resolution merges three inputs, weakest first:
//   - `definitions`: the declared variables. Their values are the BASE layer; they live in the workflow's settings,
//     so a save of its steps never touches them, and one with no value declares what the Setup tab asks for.
//   - `persisted`: the variables the workflow's graph holds, written after a set-variable step runs.
//   - what set-variable steps put out in this session (their steps' last output), before it comes back in a read.
// Later layers win, so the canvas shows the latest run's values. The declared names (definitions and set-variable
// assignments) are offered as `{{vars.x}}` before a variable has ever been set.
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import type { Node } from '@xyflow/react';
import type { NoClick } from 'noclick';
import { useClient } from '@/sdk/client';

/** business_name → "Business name": a variable as a person reads it. The raw name stays the token only where
    {{vars.x}} is typed. */
export function humanizeVariableName(name: string): string {
    const words = name.replace(/[_-]+/g, ' ').trim();
    return words.charAt(0).toUpperCase() + words.slice(1);
}

/** One declared variable: a row of the workflow's `variable_definitions`. */
export interface WorkflowVariableDefinition {
    name: string;
    value?: string;
    description?: string;
    /** Its value is the person's own (their repository, their channel): cleared when the workflow is copied, so each
        new owner's Setup asks for theirs. */
    per_user?: boolean;
    /** It has a saved value that isn't held here (a read through the platform API never carries one). Set only by
        the two functions below that say so, never saved. What it means is decided below. */
    hidden?: boolean;
}

// ── a value that's saved and not shown ──────────────────────────────────────
// The one place that says how a declared variable stands. It's one of three:
//   - blank: no value here, and none saved that isn't held here. It still needs one; Setup asks for it.
//   - shown: its value is held here (read with it, or typed).
//   - hidden: it has a saved value that isn't held here (`hidden`), and none was typed in its place. It's filled all
//     the same: nothing shows it, no save sends a value for it (an empty one would replace the saved one), and it
//     keeps its name (a save keeps a value under the variable's name, so renamed it would be lost).
// A variable becomes hidden in two ways, both here: its read held its value back (`withHiddenValues`), or its value
// was emptied where a write can't clear one (`emptiedWhereSaved`). A read holds back only a value that's there: a
// variable with no value yet reads as blank, never as hidden.

/** The path a read names a held-back variable's value by: its row in `variable_definitions`. */
const HELD_BACK_VALUE = /^variable_definitions\[(\d+)\]\.value$/;

/** A read's `variable_definitions` rows, each one whose value the read held back (`withheld`: the read's
 *  `settings_withheld`) marked `hidden`. */
export function withHiddenValues<Row extends object>(rows: readonly Row[], withheld: readonly string[] | null | undefined): (Row & { hidden?: boolean })[] {
    const heldBack = new Set<number>();
    for (const path of withheld ?? []) {
        const row = HELD_BACK_VALUE.exec(path);
        if (row) heldBack.add(Number(row[1]));
    }
    return rows.map((row, index) => (heldBack.has(index) ? { ...row, hidden: true } : row));
}

/** A variable as it stands once changed, where each change is written as a `define_variable` edit: an edit with no
 *  value keeps the one already saved, so a value emptied here is still saved. It's hidden from now on, not blank. */
function emptiedWhereSaved(before: WorkflowVariableDefinition | undefined, changed: WorkflowVariableDefinition): WorkflowVariableDefinition {
    if (changed.value || !before?.value) return changed;
    const { value: _emptied, ...kept } = changed;
    return { ...kept, hidden: true };
}

/** Whether a variable's saved value is one that isn't held here: hidden by its read, with nothing typed in its place. */
export function holdsHiddenValue(definition: WorkflowVariableDefinition): boolean {
    return Boolean(definition.hidden) && !definition.value;
}

/** Whether a variable has a value: one held here, or a saved one its read held back. */
export function isVariableFilled(definition: WorkflowVariableDefinition): boolean {
    return Boolean((definition.value ?? '').trim()) || Boolean(definition.hidden);
}

/** What a hidden value's field says in the value's place. */
export const HIDDEN_VARIABLE_PLACEHOLDER = 'Saved, hidden. Type to replace it.';

/** The definitions as a save of the workflow's settings sends them: never the read's own mark, and no value for a
 *  variable whose saved value is hidden, so the save keeps it (a value sent, an empty one too, replaces the saved
 *  one). */
export function savedVariableDefinitions(definitions: WorkflowVariableDefinition[]): WorkflowVariableDefinition[] {
    return definitions.map(({ hidden, ...definition }) => {
        if (hidden && !definition.value) delete definition.value;
        return definition;
    });
}

export interface WorkflowVariables {
    /** Resolved values: definitions, then persisted, then this session's outputs; the latest wins. */
    resolved: Record<string, any>;
    /** Names declared anywhere: definitions or set-variable assignments. */
    declared: Set<string>;
}

interface Assignment { variable_name?: string; value?: unknown }

/** A set-variable step puts out `{ assignments: [{variable_name, value}, ...] }`, or one `{ variable_name, value }`
 *  (an older shape): as a list. */
function extractAssignments(maybe: unknown): Assignment[] {
    if (!maybe || typeof maybe !== 'object') return [];
    const obj = maybe as Record<string, unknown>;
    if (Array.isArray(obj.assignments)) return obj.assignments as Assignment[];
    if (typeof obj.variable_name === 'string') return [{ variable_name: obj.variable_name, value: obj.value }];
    return [];
}

export function useWorkflowVariables(
    nodes: Node[],
    persisted: Record<string, any> | undefined,
    definitions?: WorkflowVariableDefinition[],
): WorkflowVariables {
    return useMemo(() => {
        const declared = new Set<string>();
        const defined: Record<string, any> = {};
        for (const d of definitions ?? []) {
            const name = d?.name?.trim();
            if (!name) continue;
            declared.add(name);
            if (d.value !== undefined && d.value !== '') defined[name] = d.value;
        }
        const live: Record<string, any> = {};

        for (const node of nodes) {
            if (node.type !== 'set-variable') continue;
            const data = node.data as { config?: Record<string, unknown>; output?: unknown } | undefined;

            const declaredAssignments = Array.isArray(data?.config?.assignments)
                ? data.config.assignments as Assignment[]
                : [];
            for (const a of declaredAssignments) {
                if (a?.variable_name) declared.add(a.variable_name);
            }

            for (const a of extractAssignments(data?.output)) {
                const k = a.variable_name;
                if (k && a.value !== undefined && a.value !== null) {
                    live[k] = a.value;
                }
            }
        }

        const resolved: Record<string, any> = { ...defined, ...(persisted || {}), ...live };
        return { resolved, declared };
    }, [nodes, persisted, definitions]);
}

// ── on the platform API ─────────────────────────────────────────────────────

/** The declarations as a read of the workflow gives them (`GET /v1/workflows/{id}/graph`): a value is never read
 *  back, so one that's set comes as `hidden`; one never set reads as blank. */
export function definitionsOfSettings(settings: Record<string, unknown> | null | undefined, withheld: readonly string[] | null | undefined): WorkflowVariableDefinition[] {
    const rows = Array.isArray(settings?.variable_definitions) ? (settings.variable_definitions as Record<string, unknown>[]) : [];
    return withHiddenValues(rows, withheld)
        .map((row): WorkflowVariableDefinition | null => {
            const name = typeof row?.name === 'string' ? row.name.trim() : '';
            if (!name) return null;
            return {
                name,
                ...(typeof row.value === 'string' && row.value !== '' ? { value: row.value } : {}),
                ...(typeof row.description === 'string' && row.description ? { description: row.description } : {}),
                ...(row.per_user === true ? { per_user: true } : {}),
                ...(row.hidden === true ? { hidden: true } : {}),
            };
        })
        .filter((d): d is WorkflowVariableDefinition => d !== null);
}

export interface SavedVariables {
    /** The declarations: as read, then as changed here. Empty until read. */
    definitions: WorkflowVariableDefinition[];
    /** Why they couldn't be read or written, where they couldn't. */
    error: string | null;
    /** Takes the declarations as changed (the Setup tab's and a step form's `onVariableDefinitionsChange`) and writes
     *  each one whose value, description or scope differs as a `define_variable` edit. A hidden value is written only
     *  once one is typed in its place, and a value emptied here stays saved (the edit never clears one). */
    change: (definitions: WorkflowVariableDefinition[]) => void;
}

const sameRow = (a: WorkflowVariableDefinition | undefined, b: WorkflowVariableDefinition): boolean =>
    !!a && (a.value ?? '') === (b.value ?? '') && (a.description ?? '') === (b.description ?? '') && Boolean(a.per_user) === Boolean(b.per_user);

async function readDefinitions(client: NoClick, workflowId: string): Promise<WorkflowVariableDefinition[]> {
    const { Workflow } = await import('../standardsSdk');
    const graph = await Workflow.fromId(workflowId, { client }).graph();
    return definitionsOfSettings(graph.settings, graph.settingsWithheld);
}

/** A workflow's declared variables on the platform API: read with its graph, each change written as a
 *  `define_variable` edit (the workflow's owner's to write: another key's is refused, and said). */
export function useSavedVariables(workflowId: string | undefined): SavedVariables {
    const client = useClient();
    const [definitions, setDefinitions] = useState<WorkflowVariableDefinition[]>([]);
    const [error, setError] = useState<string | null>(null);
    const held = useRef<WorkflowVariableDefinition[]>([]);
    held.current = definitions;
    // One write at a time, in order: each is the workflow's whole next version.
    const writes = useRef<Promise<void>>(Promise.resolve());

    useEffect(() => {
        if (!workflowId) return;
        let cancelled = false;
        setError(null);
        readDefinitions(client, workflowId).then(
            (read) => {
                if (!cancelled) setDefinitions(read);
            },
            (cause: unknown) => {
                if (!cancelled) setError(`This workflow’s variables couldn’t be read: ${cause instanceof Error ? cause.message : String(cause)}`);
            }
        );
        return () => {
            cancelled = true;
        };
    }, [client, workflowId]);

    const change = useCallback(
        (next: WorkflowVariableDefinition[]) => {
            if (!workflowId) return;
            const before = new Map(held.current.map((d) => [d.name, d]));
            const stands = next.map((d) => emptiedWhereSaved(before.get(d.name), d));
            // A hidden value is written only with one typed in its place.
            const changed = stands.filter((d) => d.name.trim() && !holdsHiddenValue(d) && !sameRow(before.get(d.name), d));
            setDefinitions(stands);
            if (changed.length === 0) return;
            writes.current = writes.current
                .then(async () => {
                    const { Workflow } = await import('../standardsSdk');
                    await Workflow.fromId(workflowId, { client }).edit({}, (batch) => {
                        for (const d of changed) batch.defineVariable(d.name, { value: d.value ?? '', description: d.description, perUser: d.per_user });
                    });
                    setError(null);
                })
                .catch((cause: unknown) => {
                    setError(`This workflow’s variables couldn’t be saved: ${cause instanceof Error ? cause.message : String(cause)}`);
                });
        },
        [client, workflowId]
    );

    return { definitions, error, change };
}
