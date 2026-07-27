// Builds the "these steps aren't ready" list the Run button shows before it
// starts a workflow. Pressing Run used to start a run regardless, which then
// stopped at the first unconfigured step with a runtime error; this surfaces
// every hole up front, and — since the popup edits fields in place — resolves
// them without leaving it.
//
// Mirrors workflowTriggers.getTriggerRunPrompt: a pure "should Run be
// intercepted, and with what?" function, so the gate is testable without the
// canvas.
import type { Edge, Node } from '@xyflow/react';
import { agentIconType } from '~/lib/harnessBrand';
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
    /** Selected operation. Credential requirements are per-operation, so the
     *  inline credential block needs it to ask for the right ones. */
    operation?: string;
    /** Missing required fields that can be filled in the popup. */
    fields: IncompleteField[];
    /** Missing credentials, or anything else with no inline editor — these need
     *  the config panel. */
    blockers: NodeValidationIssue[];
    /** Show the operation picker: this step is a tool provider that arrived
     *  with nothing allowlisted. Not a schema field (it is a canvas-only config
     *  key), so it gets the real picker rather than a text control — otherwise
     *  the popup could only say "select at least one action" and leave the user
     *  to go find where.
     *
     *  Sticky like the field editors, and for the same reason: the requirement
     *  is satisfied by the FIRST selection, so deriving this live tore the
     *  picker out from under someone who wanted to allowlist two actions. */
    needsToolActions: boolean;
    /** Show the node's own action picker: nothing is selected yet, and until it
     *  is, which fields this step needs is unknowable. Sticky on the same terms
     *  as the editors — the first pick satisfies it, and a picker that vanishes
     *  on the first pick cannot be corrected. */
    needsOperation: boolean;
    /** Show the credentials block. Sticky, so connecting an account leaves it
     *  in place marked Done rather than emptying the step. */
    needsCredentials: boolean;
    /** Whether that block is satisfied right now. */
    credentialsConnected: boolean;
    /** Nothing missing any more. Stays in the list so the row can show as done
     *  instead of vanishing under the cursor mid-edit. */
    resolved: boolean;
    iconHtml?: string;
    iconColor?: string;
}

/** Canvas-only config key holding a tool provider's allowlisted operations. */
export const TOOL_OPERATIONS_KEY = 'agent_tool_operations';

/** Sticky-key sentinel for the node's own action. Not a config field — the
 *  operation is top-level metadata — but it shares the stickiness so the block
 *  stays put once shown, like every other requirement. */
export const OPERATION_KEY = '__operation__';

/** Sticky-key sentinel for the step's credentials. Like the operation, not a
 *  config field — the connection lives in `credentialIds` — but it needs the
 *  same stickiness: connecting an account satisfies the requirement, and a
 *  block that disappears on being satisfied leaves the step showing "nothing
 *  left to fill in" instead of the account that was just connected. */
export const CREDENTIALS_KEY = '__credentials__';

/** The node's live config, which is where field values are authoritative. */
function nodeConfig(node: Node): Record<string, unknown> {
    return (node.data?.config ?? {}) as Record<string, unknown>;
}

/**
 * The icon a node shows. An agent resolves to its HARNESS mark (`agent:codex`,
 * `agent:openclaw`, …) rather than the generic robot — the same synthetic keys
 * the workflow-browser icon rows use, so an agent looks like the thing it
 * actually runs under.
 *
 * Deliberately the icon ONLY. The harness entry is labelled "Agent (Codex)",
 * which captions the mark rather than naming the node, so the title keeps
 * coming from the plain type. And an unresolved harness key drops back to the
 * plain type: the synthetic entries arrive with the rest of the registry, so a
 * miss means "not loaded yet", not "this agent has no icon".
 */
function iconMetaOf(node: Node) {
    const type = node.type ?? '';
    if (type !== 'agent') return getNodeIconMeta(type);
    const model = (node.data?.config as Record<string, unknown> | undefined)
        ?.model as string | undefined;
    return getNodeIconMeta(agentIconType(model)) ?? getNodeIconMeta(type);
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
    sticky: readonly string[] = []
): IncompleteStep {
    const meta = iconMetaOf(node);
    const label = (node.data?.label as string | undefined) || '';
    const operation =
        (node.data?.operation as string | undefined) ??
        (nodeConfig(node).operation as string | undefined);
    const schemaFields = new Map(
        getFieldsForOption(node.type ?? '', undefined, operation).map((f) => [
            f.key,
            f.prop,
        ])
    );

    const missing = new Map<string, string>();
    const blockers: NodeValidationIssue[] = [];
    let toolActionsMissing = false;
    let operationMissing = false;
    let credentialsMissing = false;
    for (const issue of validateNode(node, context).issues) {
        const prop = issue.fieldKey
            ? schemaFields.get(issue.fieldKey)
            : undefined;
        if (issue.type === 'missing_operation') {
            operationMissing = true;
        } else if (issue.type === 'missing_credentials') {
            credentialsMissing = true;
        } else if (issue.fieldKey === TOOL_OPERATIONS_KEY) {
            toolActionsMissing = true;
        } else if (issue.fieldKey && prop) {
            missing.set(issue.fieldKey, issue.message);
        } else {
            blockers.push(issue);
        }
    }
    // Shown while still missing OR once shown before — but only the live state
    // decides whether the step is done.
    const needsToolActions =
        toolActionsMissing || sticky.includes(TOOL_OPERATIONS_KEY);
    const needsOperation = operationMissing || sticky.includes(OPERATION_KEY);
    const needsCredentials =
        credentialsMissing || sticky.includes(CREDENTIALS_KEY);

    // Sticky keys first, in the order they were first shown, then anything newly
    // missing. A key the schema no longer describes (the operation changed under
    // the popup) is dropped rather than rendered as an uncontrolled box.
    const keys = [...new Set([...sticky, ...missing.keys()])].filter((k) =>
        schemaFields.has(k)
    );
    const fields: IncompleteField[] = keys.map((key) => ({
        key,
        prop: schemaFields.get(key)!,
        message: missing.get(key) ?? '',
        filled: !missing.has(key),
    }));

    return {
        nodeId: node.id,
        nodeType: node.type ?? '',
        title: nodeTitle(node),
        label,
        operation,
        fields,
        blockers,
        needsToolActions,
        needsOperation,
        needsCredentials,
        credentialsConnected: !credentialsMissing,
        resolved:
            missing.size === 0 &&
            blockers.length === 0 &&
            !credentialsMissing &&
            !toolActionsMissing &&
            !operationMissing,
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
    context?: NodeValidationContext
): IncompleteStep[] | null {
    const steps = getIncompleteNodes(nodes, context)
        .filter((node) => !node.data?.disabled)
        .map((node) => describeStep(node, context));
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
    stickyFields: Record<string, string[]> = {}
): IncompleteStep[] {
    const byId = new Map(nodes.map((n) => [n.id, n]));
    return nodeIds
        .map((id) => byId.get(id))
        .filter((n): n is Node => !!n)
        .map((node) =>
            describeStep(node, context, stickyFields[node.id] ?? [])
        );
}

// ── Run paths ───────────────────────────────────────────────────────────────
// The entry points a full run starts from. Surfaced in the Run popup so a
// workflow with several independent branches can be run selectively, and so an
// agent entry point can be given its opening message before the run starts.

/** One selectable entry point for a run. */
export interface RunPath {
    nodeId: string;
    nodeType: string;
    /** Service / step name, e.g. "Gmail". */
    title: string;
    label: string;
    isAgent: boolean;
    /** For agents: the node's saved message, used to prefill the popup's box. */
    message: string;
    /** Names of the steps this entry point runs after itself, in graph order.
     *  Without them a row is just the HEAD of a branch — you are asked to tick
     *  a path while being shown one node of it. */
    downstream: string[];
    /** Names of the tool providers wired into it. Not steps: they run only if
     *  the agent calls them, so they are worth naming separately. */
    tools: string[];
    iconHtml?: string;
    iconColor?: string;
}

/** Display name for a node — the service name, else the user's label. The name
 *  comes from the plain type: a harness entry is labelled "Agent (Codex)",
 *  which is the icon's caption, not what this node is called. */
function nodeTitle(node: Node): string {
    const label = (node.data?.label as string | undefined) || '';
    return (
        getNodeIconMeta(node.type ?? '')?.label || label || node.type || 'Step'
    );
}

/**
 * The graph's entry points: nodes nothing feeds into.
 *
 * Two kinds of edge are deliberately not "feeding into":
 *
 * - Bottom-handle edges point from a tool provider INTO its agent, so counting
 *   them would make an agent with tools look like a mid-graph node rather than
 *   the entry point it is.
 * - The providers themselves have no incoming edges at all, so they would each
 *   look like an entry point. They cannot start anything — they only answer an
 *   agent's tool calls — so they are excluded by name.
 *
 * Disabled nodes are skipped for the same reason the Run gate skips them: the
 * backend does not execute them.
 */
/** One node described as an entry point. Used directly for a node-scoped run,
 *  where the start node IS the entry point and there is nothing to choose. */
export function describeRunPath(
    node: Node,
    downstream: string[] = [],
    tools: string[] = []
): RunPath {
    const meta = iconMetaOf(node);
    return {
        nodeId: node.id,
        nodeType: node.type ?? '',
        title: nodeTitle(node),
        label: (node.data?.label as string | undefined) || '',
        isAgent: node.type === 'agent',
        message: String(nodeConfig(node).message ?? ''),
        downstream,
        tools,
        iconHtml: meta?.iconHtml,
        iconColor: meta?.iconColor,
    };
}

/** Names of the tool providers wired into one node. */
export function toolProviderTitles(
    nodeId: string,
    nodes: Node[],
    edges: Edge[]
): string[] {
    const byId = new Map(nodes.map((n) => [n.id, n]));
    return edges
        .filter((e) => e.targetHandle === 'bottom' && e.target === nodeId)
        .map((e) => byId.get(e.source))
        .filter((n): n is Node => !!n && !n.data?.disabled)
        .map(nodeTitle);
}

export function getRunStartPaths(nodes: Node[], edges: Edge[]): RunPath[] {
    const byId = new Map(nodes.map((n) => [n.id, n]));
    const fedInto = new Set<string>();
    const toolProviders = new Set<string>();
    const nextOf = new Map<string, string[]>();
    const toolsOf = new Map<string, string[]>();
    for (const edge of edges) {
        const bucket = edge.targetHandle === 'bottom' ? toolsOf : nextOf;
        const key = edge.targetHandle === 'bottom' ? edge.target : edge.source;
        const value =
            edge.targetHandle === 'bottom' ? edge.source : edge.target;
        bucket.set(key, [...(bucket.get(key) ?? []), value]);
        if (edge.targetHandle === 'bottom') toolProviders.add(edge.source);
        else fedInto.add(edge.target);
    }

    /** Forward walk from a root, in breadth order, naming each step once. */
    const chainFrom = (rootId: string): string[] => {
        const seen = new Set([rootId]);
        const queue = [rootId];
        const names: string[] = [];
        while (queue.length > 0) {
            for (const next of nextOf.get(queue.shift()!) ?? []) {
                if (seen.has(next)) continue;
                seen.add(next);
                queue.push(next);
                const node = byId.get(next);
                if (node && !node.data?.disabled) names.push(nodeTitle(node));
            }
        }
        return names;
    };

    return nodes
        .filter(
            (node) =>
                node.type &&
                node.type !== 'stickyNote' &&
                !node.id.startsWith('cursor-') &&
                !node.data?.disabled &&
                !fedInto.has(node.id) &&
                !toolProviders.has(node.id)
        )
        .map((node) =>
            describeRunPath(
                node,
                chainFrom(node.id),
                (toolsOf.get(node.id) ?? [])
                    .map((id) => byId.get(id))
                    .filter((n): n is Node => !!n && !n.data?.disabled)
                    .map(nodeTitle)
            )
        );
}
