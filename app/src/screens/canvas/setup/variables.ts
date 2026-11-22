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
import type { NoClick, Workflow, WorkflowGraph, WorkflowVariables as ReadValues } from 'noclick';
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
    /** It has a saved value that isn't held here (a read of the workflow through the platform API never carries
        one). Set only by the two functions below that say so, never saved. What it means is decided below. */
    hidden?: boolean;
    /** Its value as the server holds it, under the name it has there (the owner's read of the values, or a save's
        answer). Set only by `withSavedValue` below, never saved. */
    read?: { name: string; value: unknown };
}

// ── a value that's saved and not shown ──────────────────────────────────────
// The one place that says how a declared variable stands. It's one of three:
//   - blank: no value here, and none saved that isn't held here. It still needs one; Setup asks for it.
//   - shown: its value is held here (read with it, or typed).
//   - hidden: it has a saved value that isn't held here (`hidden`), and none was typed in its place. It's filled all
//     the same: nothing shows it, no save sends a value for it (an empty one would replace the saved one), and it
//     keeps its name (a save keeps a value under the variable's name, so renamed it would be lost).
// A read of a workflow holds back each value that's there (a variable with no value yet reads as blank, never as
// hidden), and `withHiddenValues` says how each such variable stands for its reader: shown, where the reader's own
// read of the values answered it (`heldBackValues`: the workflow's owner and those who can edit it), else hidden. A
// variable also becomes hidden when its value is emptied where a write can't clear one (`emptiedWhereSaved`).
//
// A shown value that came from the server carries what was read (`read`, set by `withSavedValue`): a save of the list
// names its value only once its person changed it, or its name (`savedVariableDefinitions`).

/** The path a read names a held-back variable's value by: its row in `variable_definitions`. */
const HELD_BACK_VALUE = /^variable_definitions\[(\d+)\]\.value$/;

/** Who the read of a workflow's variables' values answers, by what its reader may do with the workflow (a read's
 *  `access`): its owner and those who can edit it; someone who only views it reads none. The API judges the same and
 *  refuses anyone else; this only saves asking. */
const VALUE_READERS: readonly string[] = ['owner', 'editor'];

/** The values a read of the workflow held back (`graph`: its variables', and the graph's own), read apart as its
 *  owner and its editors read them; null where there are none to read or the read doesn't answer this reader, whose
 *  variables then stay hidden. `asOwner`: whether the client is one the read can answer (a person signed in to their
 *  own account, or a key that names `workflows:variables`); a client that isn't is never made to ask. A refusal, or
 *  an API that doesn't serve the read yet (a 404 where the workflow was just read), is no error. */
export async function heldBackValues(workflow: Workflow, graph: WorkflowGraph, asOwner: boolean): Promise<ReadValues | null> {
    const holdsSome = (graph.settingsWithheld ?? []).some((path) => HELD_BACK_VALUE.test(path)) || graph.variablesWithheld.length > 0;
    if (!asOwner || !holdsSome || !VALUE_READERS.includes(graph.access ?? '')) return null;
    const { NotFound, PermissionDenied } = await import('../standardsSdk');
    try {
        return await workflow.variables();
    } catch (error) {
        if (error instanceof PermissionDenied || error instanceof NotFound) return null;
        throw error;
    }
}

/** A variable holding `value` as the server holds it: shown, and marked with what was read. */
export function withSavedValue<Row extends object>(row: Row, name: string, value: unknown): Row & { value: unknown; read: { name: string; value: unknown } } {
    const shown = { ...row, value, read: { name, value } } as Row & { value: unknown; read: { name: string; value: unknown }; hidden?: boolean };
    delete shown.hidden;
    return shown;
}

/** A read's `variable_definitions` rows, each one whose value the read held back (`withheld`: the read's
 *  `settings_withheld`) standing as its reader sees it: shown, with the value the reader's own read of the values
 *  answered (`values`: its definitions, matched by name since the two reads are apart), else marked `hidden`. */
export function withHiddenValues<Row extends object>(
    rows: readonly Row[],
    withheld: readonly string[] | null | undefined,
    values?: readonly { name?: unknown; value?: unknown }[] | null
): (Row & { hidden?: boolean; value?: unknown; read?: { name: string; value: unknown } })[] {
    const heldBack = new Set<number>();
    for (const path of withheld ?? []) {
        const row = HELD_BACK_VALUE.exec(path);
        if (row) heldBack.add(Number(row[1]));
    }
    const read = new Map((values ?? []).map((row) => [row.name, row.value]));
    return rows.map((row, index) => {
        if (!heldBack.has(index)) return row;
        const name = (row as { name?: unknown }).name;
        const value = read.get(name);
        return typeof name === 'string' && value !== undefined && value !== null && value !== '' ? withSavedValue(row, name, value) : { ...row, hidden: true };
    });
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

/** The definitions as a save of the workflow's settings sends them: never the read's own marks, and no value for a
 *  variable whose saved value stands: one hidden and not replaced, or one read and not changed since, under the name
 *  it was read by. The save keeps it (a value sent, an empty one too, replaces the saved one). */
export function savedVariableDefinitions(definitions: WorkflowVariableDefinition[]): WorkflowVariableDefinition[] {
    return definitions.map(({ hidden, read, ...definition }) => {
        const unchanged = read !== undefined && read.name === definition.name && read.value === (definition.value ?? '');
        if ((hidden && !definition.value) || unchanged) delete definition.value;
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
 *  back with them, so one that's set comes as `hidden`, unless its reader's own read of the values answered it
 *  (`values`); one never set reads as blank. */
export function definitionsOfSettings(
    settings: Record<string, unknown> | null | undefined,
    withheld: readonly string[] | null | undefined,
    values?: readonly { name?: unknown; value?: unknown }[] | null
): WorkflowVariableDefinition[] {
    const rows = Array.isArray(settings?.variable_definitions) ? (settings.variable_definitions as Record<string, unknown>[]) : [];
    return withHiddenValues(rows, withheld, values)
        .map((row): WorkflowVariableDefinition | null => {
            const name = typeof row?.name === 'string' ? row.name.trim() : '';
            if (!name) return null;
            return {
                name,
                ...(typeof row.value === 'string' && row.value !== '' ? { value: row.value } : {}),
                ...(typeof row.description === 'string' && row.description ? { description: row.description } : {}),
                ...(row.per_user === true ? { per_user: true } : {}),
                ...(row.hidden === true ? { hidden: true } : {}),
                ...(row.read ? { read: row.read } : {}),
            };
        })
        .filter((d): d is WorkflowVariableDefinition => d !== null);
}

export interface SavedVariables {
    /** The declarations: as read, then as changed here. Empty until read. */
    definitions: WorkflowVariableDefinition[];
    /** The graph's own variables (what its set-variable steps last wrote), where their values were read: what
     *  `useWorkflowVariables` takes as `persisted`. Empty where they weren't. */
    persisted: Record<string, unknown>;
    /** Why they couldn't be read or written, where they couldn't. */
    error: string | null;
    /** Takes the declarations as changed (the Setup tab's and a step form's `onVariableDefinitionsChange`) and writes
     *  each one whose value, description or scope differs as a `define_variable` edit. A hidden value is written only
     *  once one is typed in its place, and a value emptied here stays saved (the edit never clears one). */
    change: (definitions: WorkflowVariableDefinition[]) => void;
}

const sameRow = (a: WorkflowVariableDefinition | undefined, b: WorkflowVariableDefinition): boolean =>
    !!a && (a.value ?? '') === (b.value ?? '') && (a.description ?? '') === (b.description ?? '') && Boolean(a.per_user) === Boolean(b.per_user);

interface ReadVariables {
    definitions: WorkflowVariableDefinition[];
    persisted: Record<string, unknown>;
}

async function readDefinitions(client: NoClick, workflowId: string, asOwner: boolean): Promise<ReadVariables> {
    const { Workflow } = await import('../standardsSdk');
    const workflow = Workflow.fromId(workflowId, { client });
    const graph = await workflow.graph();
    const values = await heldBackValues(workflow, graph, asOwner);
    return { definitions: definitionsOfSettings(graph.settings, graph.settingsWithheld, values?.definitions), persisted: values?.variables ?? {} };
}

const NONE_READ: Record<string, unknown> = {};

/** A workflow's declared variables on the platform API: read with its graph, each change written as a
 *  `define_variable` edit (the workflow's owner's to write: another key's is refused, and said). `asOwner`: the
 *  client is a person's own (signed in to NoClick, or a key that names `workflows:variables`), so the values the
 *  graph holds back are read too, for a workflow that person owns or can edit, and shown; left out (this app's own
 *  key carries no such scope), they're never asked for and each stays hidden. */
export function useSavedVariables(workflowId: string | undefined, { asOwner = false }: { asOwner?: boolean } = {}): SavedVariables {
    const client = useClient();
    const [definitions, setDefinitions] = useState<WorkflowVariableDefinition[]>([]);
    const [persisted, setPersisted] = useState<Record<string, unknown>>(NONE_READ);
    const [error, setError] = useState<string | null>(null);
    const held = useRef<WorkflowVariableDefinition[]>([]);
    held.current = definitions;
    // One write at a time, in order: each is the workflow's whole next version.
    const writes = useRef<Promise<void>>(Promise.resolve());

    useEffect(() => {
        if (!workflowId) return;
        let cancelled = false;
        setError(null);
        readDefinitions(client, workflowId, asOwner).then(
            (read) => {
                if (cancelled) return;
                setDefinitions(read.definitions);
                setPersisted(read.persisted);
            },
            (cause: unknown) => {
                if (!cancelled) setError(`This workflow’s variables couldn’t be read: ${cause instanceof Error ? cause.message : String(cause)}`);
            }
        );
        return () => {
            cancelled = true;
        };
    }, [client, workflowId, asOwner]);

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

    return { definitions, persisted, error, change };
}
