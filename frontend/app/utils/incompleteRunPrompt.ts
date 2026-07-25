// Builds the "these steps aren't ready" list the Run button shows before it
// starts a workflow. Pressing Run used to start a run regardless, which then
// stopped at the first unconfigured step with a runtime error; this surfaces
// every hole up front, with a way to jump straight to each one.
//
// Mirrors workflowTriggers.getTriggerRunPrompt: a pure "should Run be
// intercepted, and with what?" function, so the gate is testable without the
// canvas.
import type { Node } from '@xyflow/react';
import { getNodeIconMeta } from '~/lib/nodeIconRegistry';
import {
    getIncompleteNodes,
    validateNode,
    type NodeValidationContext,
    type NodeValidationIssue,
} from '~/utils/workflowNodeValidation';

export interface IncompleteStep {
    nodeId: string;
    nodeType: string;
    /** Service / step name, e.g. "Gmail", "Slack". */
    title: string;
    /** User-given node label, if any (shown as a subtle tag). */
    label: string;
    /** What's missing — credentials and/or specific required fields. */
    issues: NodeValidationIssue[];
    iconHtml?: string;
    iconColor?: string;
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
        .map(node => {
            const meta = getNodeIconMeta(node.type ?? '');
            const label = (node.data?.label as string | undefined) || '';
            return {
                nodeId: node.id,
                nodeType: node.type ?? '',
                title: meta?.label || label || node.type || 'Step',
                label,
                issues: validateNode(node, context).issues,
                iconHtml: meta?.iconHtml,
                iconColor: meta?.iconColor,
            };
        });
    return steps.length > 0 ? steps : null;
}
