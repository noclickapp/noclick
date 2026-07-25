// Builds the "these steps aren't ready" list the Run button shows before it
// starts a workflow. Pressing Run used to start a run regardless, which then
// stopped at the first unconfigured step with a runtime error; this surfaces
// every hole up front, and — since the popup edits fields in place — resolves
// them without leaving it.
//
// Mirrors workflowTriggers.getTriggerRunPrompt: a pure "should Run be
// intercepted, and with what?" function, so the gate is testable without the
// canvas.
import type { Node } from '@xyflow/react';
import { getNodeIconMeta } from '~/lib/nodeIconRegistry';
import { getFieldsForOption } from '~/utils/schemaFieldExtractor';
import {
    getIncompleteNodes,
    validateNode,
    type NodeValidationContext,
    type NodeValidationIssue,
} from '~/utils/workflowNodeValidation';

/** A missing required field, resolved to everything needed to edit it inline. */
export interface IncompleteField {
    key: string;
    /** Schema prop — title, type, enum, widget and dynamic-options hints. */
    prop: Record<string, unknown>;
    /** Why it is being asked for, e.g. "Provide Channel or User". */
    message: string;
    /** No longer missing. The editor stays put and just marks itself done. */
    filled: boolean;
}

export interface IncompleteStep {
    nodeId: string;
    nodeType: string;
    /** Service / step name, e.g. "Gmail", "Slack". */
    title: string;
    /** User-given node label, if any (shown as a subtle tag). */
    label: string;
    /** Missing required fields that can be filled in the popup. */
    fields: IncompleteField[];
    /** Missing credentials, or anything else with no inline editor — these need
     *  the config panel. */
    blockers: NodeValidationIssue[];
    /** Nothing missing any more. Stays in the list so the row can show as done
     *  instead of vanishing under the cursor mid-edit. */
    resolved: boolean;
    iconHtml?: string;
    iconColor?: string;
}

/** The node's live config, which is where field values are authoritative. */
function nodeConfig(node: Node): Record<string, unknown> {
    return (node.data?.config ?? {}) as Record<string, unknown>;
}

/**
 * One step's current state. Issues carrying a `fieldKey` that resolves to a real
 * schema field become inline editors; everything else (credentials, and any
 * field the schema can't describe) stays a blocker that needs the config panel.
 */
function describeStep(
    node: Node,
    context?: NodeValidationContext,
    /** Field keys the popup is already showing an editor for. They stay in the
     *  list once filled — see describeStepsForIds. */
    sticky: readonly string[] = [],
): IncompleteStep {
    const meta = getNodeIconMeta(node.type ?? '');
    const label = (node.data?.label as string | undefined) || '';
    const operation =
        (node.data?.operation as string | undefined) ??
        (nodeConfig(node).operation as string | undefined);
    const schemaFields = new Map(
        getFieldsForOption(node.type ?? '', undefined, operation).map(f => [f.key, f.prop]),
    );

    const missing = new Map<string, string>();
    const blockers: NodeValidationIssue[] = [];
    for (const issue of validateNode(node, context).issues) {
        const prop = issue.fieldKey ? schemaFields.get(issue.fieldKey) : undefined;
        if (issue.fieldKey && prop) {
            missing.set(issue.fieldKey, issue.message);
        } else {
            blockers.push(issue);
        }
    }

    // Sticky keys first, in the order they were first shown, then anything newly
    // missing. A key the schema no longer describes (the operation changed under
    // the popup) is dropped rather than rendered as an uncontrolled box.
    const keys = [...new Set([...sticky, ...missing.keys()])].filter(k =>
        schemaFields.has(k),
    );
    const fields: IncompleteField[] = keys.map(key => ({
        key,
        prop: schemaFields.get(key)!,
        message: missing.get(key) ?? '',
        filled: !missing.has(key),
    }));

    return {
        nodeId: node.id,
        nodeType: node.type ?? '',
        title: meta?.label || label || node.type || 'Step',
        label,
        fields,
        blockers,
        resolved: missing.size === 0 && blockers.length === 0,
        iconHtml: meta?.iconHtml,
        iconColor: meta?.iconColor,
    };
}

/**
 * The steps to surface when Run is pressed, or null to run normally.
 *
 * Disabled nodes are excluded: the backend skips them at execution, so an
 * unconfigured disabled step can't be why this run fails. The canvas pill
 * deliberately still counts them — it flags "needs your attention", a broader
 * question than "blocks this run".
 */
export function getIncompleteRunPrompt(
    nodes: Node[],
    context?: NodeValidationContext,
): IncompleteStep[] | null {
    const steps = getIncompleteNodes(nodes, context)
        .filter(node => !node.data?.disabled)
        .map(node => describeStep(node, context));
    return steps.length > 0 ? steps : null;
}

/**
 * Re-describe a fixed set of steps against the current graph — what the popup
 * re-runs on every edit.
 *
 * Both the step ids and their field keys are frozen when Run is pressed, and
 * nothing is ever dropped for being fixed. That stickiness is load-bearing, not
 * cosmetic: a field stops being "missing" on its FIRST keystroke, so deriving
 * the editors purely from what is currently missing unmounts the control the
 * user is typing into and throws away their focus after one character. Rows
 * behave the same way for the same reason — the list must not reflow under the
 * pointer as it is being fixed.
 *
 * Ids with no matching node are dropped: a collaborator can delete a step while
 * the popup is open.
 */
export function describeStepsForIds(
    nodes: Node[],
    nodeIds: string[],
    context?: NodeValidationContext,
    stickyFields: Record<string, string[]> = {},
): IncompleteStep[] {
    const byId = new Map(nodes.map(n => [n.id, n]));
    return nodeIds
        .map(id => byId.get(id))
        .filter((n): n is Node => !!n)
        .map(node => describeStep(node, context, stickyFields[node.id] ?? []));
}
