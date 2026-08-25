// Single source of truth for `{{vars.X}}` resolution on the canvas.
//
// Merges three inputs, weakest first:
//   - `definitions` — author-declared variables (settings.variable_definitions,
//     edited in the Variables tab). Their values are the BASE layer; they live
//     in settings so the graph autosave can never clobber them, and a
//     definition with no value declares intent the Setup tab turns into a step.
//   - `persisted` — variables loaded from the workflow blob (workflow.variables),
//     written by the backend after a set-variable node executes.
//   - Live runtime outputs from set-variable nodes (node.data.output.assignments).
//     Freshest values in the current session, before they round-trip.
//
// Later layers win so the canvas reflects the latest execution without a
// reload. Also surfaces the set of declared variable names (definitions +
// set-variable assignments) so autocomplete can suggest `{{vars.X}}` before
// the variable has ever been set.
import { useMemo } from 'react';
import type { Node } from '@xyflow/react';

/** One row of settings.variable_definitions — the author's declared intent. */
/** business_name → "Business name". Every non-authoring surface shows a
    variable in the user's language; the raw name stays the reference token
    only where {{vars.x}} is actually typed (canvas panel, Settings). */
export function humanizeVariableName(name: string): string {
    const words = name.replace(/[_-]+/g, ' ').trim();
    return words.charAt(0).toUpperCase() + words.slice(1);
}

export interface WorkflowVariableDefinition {
    name: string;
    value?: string;
    description?: string;
    /** Author-bound: the value is cleared when the workflow is forked/copied,
        so every new owner's Setup asks for their own (their repo, their
        channel). The author's original keeps its value and keeps running. */
    per_user?: boolean;
}

export interface WorkflowVariables {
    /** Resolved values — definitions + persisted + live outputs, latest wins. */
    resolved: Record<string, any>;
    /** Names declared anywhere: definitions or set-variable assignments. */
    declared: Set<string>;
}

interface Assignment { variable_name?: string; value?: unknown }

/**
 * A set-variable node emits either `{ assignments: [{variable_name, value}, ...] }`
 * or the legacy single-var shape `{ variable_name, value }`. Normalize to a list.
 */
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
