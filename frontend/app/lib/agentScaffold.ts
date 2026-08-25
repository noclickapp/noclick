// Builds the workflow blob for the /agents one-click "open this agent" button:
// one AI-agent node configured to a CLI harness, plus one trigger/integration
// node per selection wired into the agent (triggers -> left handle, tools ->
// bottom handle as tool providers).
//
// The scaffold is deliberately near-BARE: tool nodes get no operation /
// agent_tool_operations, and integration trigger nodes get only their DEFAULT
// trigger operation (so they are real, firing triggers that render the trigger
// bolt — a bare integration trigger can't fire and looks like a normal node).
// We open the graph as scaffolding and hand the internal AI builder a
// `builderPrompt` (see deriveBuilderPrompt) that walks the user through
// confirming the trigger op and picking the right tool operations from their goal.
//
// Added for the agent-harness SEO pages. Kept pure + client-safe (no node
// registry, no server imports) so route components and the one-click handler can
// build the blob in the browser. It reuses createWorkflowNode + serializeNode/
// EdgeForSave from applyNodeUpdate so the emitted shape is byte-for-byte what the
// app persists — the blob is handed straight to WorkflowCreateRequest.workflow_data.

import type { Node, Edge } from '@xyflow/react';
import {
    createWorkflowNode,
    serializeNodeForSave,
    serializeEdgeForSave,
} from '~/lib/applyNodeUpdate';
import { seedWrapperSubmodel } from '~/lib/agentCredentialModel';

/** A provider app to wire into the agent as a (yet-unconfigured) tool provider. */
export interface ScaffoldIntegration {
    /** Node type, e.g. "automation-slack". */
    type: string;
    /** Display label for the node, e.g. "Slack". */
    label: string;
    /** Baked `agent_tool_operations` allowlist (the pair-page wizard's chosen
        tool preset). Absent = bare provider, configured later by the builder. */
    toolOperations?: string[];
}

/** A trigger to wire into the agent's input so its fired event runs the agent. */
export interface ScaffoldTrigger {
    /** Node type, e.g. "trigger-webhook" or "automation-slack". */
    type: string;
    /** Display label for the node. */
    label: string;
    /** Default trigger operation for integration triggers (an x-is-trigger op);
        null/absent for built-in trigger-* types, which are triggers by type. */
    operation?: string | null;
}

export interface BuildScaffoldArgs {
    /** data.config.model value, e.g. "claude-code" (backend infers model_type). */
    harnessModel: string;
    /** Agent node label / harness display name, e.g. "Claude Code". */
    harnessLabel: string;
    /** The agent's standing task instructions (config.message — required field). */
    message: string;
    integrations: ScaffoldIntegration[];
    /** Triggers wired into the agent's input handle (optional). */
    triggers?: ScaffoldTrigger[];
    /** Optional explicit workflow name; otherwise derived from the harness + apps. */
    name?: string;
}

/** A node in the saved/wire shape produced by serializeNodeForSave. */
export interface ScaffoldNode {
    id: string;
    type?: string;
    position: { x: number; y: number };
    config: Record<string, unknown>;
}

/** An edge in the saved/wire shape produced by serializeEdgeForSave. */
export interface ScaffoldEdge {
    id: string;
    source: string;
    target: string;
    sourceHandle?: string | null;
    targetHandle?: string | null;
}

/** Saved/wire workflow shape ({nodes, edges}) — what WorkflowCreateRequest stores. */
export interface ScaffoldBlob {
    nodes: ScaffoldNode[];
    edges: ScaffoldEdge[];
}

/** The pair-page wizard's pre-auth choices, carried through the sign-in
    round-trip inside the stashed intent. Present ⇒ the dashboard consumer
    opens the full-screen Setup takeover and does NOT auto-run the AI builder
    (allowlists are already baked from the chosen presets). */
export interface ScaffoldSetupIntent {
    /** Runtime supplied by the agent setup wizard. */
    runtime: 'cloud';
    /** Chosen preset id per provider node type — funnel analytics only. */
    presetIds?: Record<string, string>;
}

export interface ScaffoldIntent {
    name: string;
    workflowData: ScaffoldBlob;
    /**
     * A message to auto-send to the internal AI builder once the bare scaffold
     * opens, so it guides the user through choosing trigger + tool operations.
     * Ignored when `setup` is present (the wizard already made those choices).
     */
    builderPrompt: string;
    /** Present only for pair-page wizard scaffolds. */
    setup?: ScaffoldSetupIntent;
}

const AGENT_ID = 'agent';
// Edge ids match the backend's canonical add_edge format (graph_state.add_edge:
// `e_{from}_{to}`) so an AI-builder round-trip reconciles against the scaffold's
// edges (dedup + remove keyed on this id) instead of re-emitting a second
// overlapping edge — the "almost solid" double-edge bug.
const edgeId = (source: string) => `e_${source}_${AGENT_ID}`;
// Tools edge contract: provider's top handle -> agent's bottom handle. The
// targetHandle "bottom" is the load-bearing signal the backend reads to treat
// the source as a tool provider (see AgentNode._is_wired_tool_provider).
const PROVIDER_SOURCE_HANDLE = 'top';
const AGENT_TARGET_HANDLE = 'bottom';
// Trigger edge: a trigger wired into the agent's input (left) handle fires the
// agent with its event. Any non-'bottom' target handle counts as a trigger
// source (AgentNode._resolve_trigger_event); 'left' is the visual convention.
const AGENT_INPUT_HANDLE = 'left';

function slugForId(type: string): string {
    return type.replace(/^(automation|trigger)-/, '');
}

function deriveName(args: BuildScaffoldArgs): string {
    if (args.name) return args.name;
    const labels = args.integrations.map((i) => i.label);
    if (labels.length === 1) return `${args.harnessLabel} + ${labels[0]}`;
    if (labels.length === 2) return `${args.harnessLabel} + ${labels[0]} and ${labels[1]}`;
    if (labels.length > 2) return `${args.harnessLabel} agent (${labels.length} tools)`;
    return `${args.harnessLabel} agent`;
}

/**
 * The message auto-sent to the internal AI builder when the bare scaffold opens.
 *
 * Phrased as the user's opening request. We deliberately do NOT inject a guessed
 * goal (the scaffold only knows the apps, not what the user actually wants), and
 * we don't want the old "ask my goal, then walk me through it one step at a time"
 * interrogation either. Instead we bias the builder toward a quick start: at most
 * a question or two to get the gist, then focus the effort on connecting each
 * node's account and wiring it up, picking sensible operation defaults rather
 * than making the user choose them all.
 */
function deriveBuilderPrompt(args: BuildScaffoldArgs): string {
    const triggerLabels = (args.triggers ?? []).map((t) => t.label);
    const toolLabels = args.integrations.map((i) => i.label);
    const appList = toolLabels.length ? toolLabels.join(', ') : 'the connected apps';
    const triggerClause = triggerLabels.length
        ? ` and set a sensible trigger event on the ${triggerLabels.join(', ')} trigger ${triggerLabels.length > 1 ? 'nodes' : 'node'}`
        : '';

    return (
        `I just scaffolded this ${args.harnessLabel} agent from a template — the nodes are wired but their operations aren't picked yet. ` +
        `Keep it quick: ask me at most a question or two to get what I'm going for, then mainly focus on getting the accounts connected for each node and hooking everything up. ` +
        `Pick sensible ${appList} operations for me${triggerClause} rather than making me choose them all, and once it's wired up tell me what you set so I can change anything.`
    );
}

/**
 * Build a ready-to-open workflow with a harness agent and its wired tool
 * providers. The agent sits on top; providers are laid out below it (matching
 * the bottom-handle autolayout convention).
 */
export function buildAgentScaffold(args: BuildScaffoldArgs): ScaffoldIntent {
    // Layout (node sizes: agent 200x140, triggers/tools 90x90):
    //  - Triggers stack in a LEFT lane (x 20..110), vertically centered on the
    //    agent's left handle, feeding it.
    //  - The agent + its centered tool row sit to the RIGHT of that lane; the
    //    agent shifts right as the tool fan widens so the leftmost tool always
    //    clears the trigger lane. Triggers and tools therefore never overlap
    //    (separate horizontal lanes), regardless of how many of each are picked.
    const triggers = args.triggers ?? [];
    const hasTriggers = triggers.length > 0;
    const toolCount = args.integrations.length;
    const TOOL_SPACING = 160;
    const TOOL_HALF_W = 45;
    const AGENT_HALF_W = 100;
    const AGENT_Y = 40;
    const AGENT_H = 140;
    const TRIGGER_STEP = 150; // 90px-tall nodes → ~60px vertical gap between triggers
    const TRIGGER_H = 90;
    const TRIGGER_LANE_RIGHT = 160; // triggers (x20..110) live left of this
    const halfFan = toolCount > 1 ? ((toolCount - 1) / 2) * TOOL_SPACING : 0;
    const agentCenterX = hasTriggers
        ? Math.max(320, TRIGGER_LANE_RIGHT + AGENT_HALF_W, TRIGGER_LANE_RIGHT + TOOL_HALF_W + halfFan)
        : Math.max(300, TOOL_HALF_W + halfFan);

    // Trigger column: vertically centered on the agent's left handle.
    const triggerColTop = AGENT_Y + AGENT_H / 2 - ((triggers.length - 1) * TRIGGER_STEP) / 2 - TRIGGER_H / 2;
    const triggerColBottom = hasTriggers ? triggerColTop + (triggers.length - 1) * TRIGGER_STEP + TRIGGER_H : 0;
    // Tool row below BOTH the agent and the trigger column, so the trigger→agent
    // edges never cross into the tool row.
    const TOOLS_Y = Math.max(AGENT_Y + AGENT_H + 90, triggerColBottom + 70);

    const agentNode: Node = createWorkflowNode(AGENT_ID, 'agent', { x: agentCenterX - AGENT_HALF_W, y: AGENT_Y }, {
        label: args.harnessLabel,
        model: args.harnessModel,
        message: args.message,
        // Seed a wrapper harness's default sub-model so the scaffolded node
        // carries a concrete provider (no-op for regular models).
        ...seedWrapperSubmodel(args.harnessModel),
    });

    const triggerNodes: Node[] = [];
    const providerNodes: Node[] = [];
    const edges: Edge[] = [];

    // Triggers fan into the agent's left (input) handle. Integration triggers get
    // their default trigger operation (so they fire AND render the trigger bolt —
    // a bare integration trigger is non-functional and looks like a normal node);
    // built-in trigger-* types are triggers by type, so they stay operation-less.
    triggers.forEach((trigger, i) => {
        const id = `trigger-${slugForId(trigger.type)}-${i + 1}`;
        triggerNodes.push(
            createWorkflowNode(
                id,
                trigger.type,
                { x: 20, y: triggerColTop + i * TRIGGER_STEP },
                { label: trigger.label },
                trigger.operation ? { operation: trigger.operation } : {},
            ),
        );
        edges.push({
            id: edgeId(id),
            source: id,
            target: AGENT_ID,
            targetHandle: AGENT_INPUT_HANDLE,
        } as Edge);
    });

    // Tool providers wire into the agent's bottom handle. Bare by default (the
    // builder selects operations later); the pair-page wizard bakes the chosen
    // preset's allowlist so setup needs no builder run at all.
    args.integrations.forEach((integration, i) => {
        const id = `${slugForId(integration.type)}-${i + 1}`;
        // Centered under the agent (node width ~90, so offset by 45).
        const cx = agentCenterX + (i - (toolCount - 1) / 2) * TOOL_SPACING;
        providerNodes.push(
            createWorkflowNode(id, integration.type, { x: cx - TOOL_HALF_W, y: TOOLS_Y }, {
                label: integration.label,
                ...(integration.toolOperations?.length
                    ? { agent_tool_operations: integration.toolOperations }
                    : {}),
            }),
        );
        edges.push({
            id: edgeId(id),
            source: id,
            target: AGENT_ID,
            sourceHandle: PROVIDER_SOURCE_HANDLE,
            targetHandle: AGENT_TARGET_HANDLE,
        } as Edge);
    });

    return {
        name: deriveName(args),
        workflowData: {
            nodes: [agentNode, ...triggerNodes, ...providerNodes].map(serializeNodeForSave),
            edges: edges.map(serializeEdgeForSave),
        },
        builderPrompt: deriveBuilderPrompt(args),
    };
}

// ── Deferred-open intent (survives the sign-in round-trip) ──────────────────
// The marketing page stashes the built blob, then routes to /dashboard. The
// WorkflowBrowser consumer reads SCAFFOLD_DATA_KEY once connected and creates +
// opens the workflow. PENDING_SCAFFOLD_KEY flags an anonymous click so the
// post-auth effect knows to proceed once the visitor returns signed in.

export const SCAFFOLD_DATA_KEY = 'noclick_scaffold_workflow_data';
export const PENDING_SCAFFOLD_KEY = 'noclick_pending_scaffold';

export function stashScaffoldIntent(intent: ScaffoldIntent): void {
    if (typeof window === 'undefined') return;
    sessionStorage.setItem(SCAFFOLD_DATA_KEY, JSON.stringify(intent));
}

export function readScaffoldIntent(): ScaffoldIntent | null {
    if (typeof window === 'undefined') return null;
    const raw = sessionStorage.getItem(SCAFFOLD_DATA_KEY);
    if (!raw) return null;
    try {
        const parsed = JSON.parse(raw) as ScaffoldIntent;
        if (!parsed?.workflowData?.nodes?.length) return null;
        return parsed;
    } catch {
        return null;
    }
}

export function clearScaffoldIntent(): void {
    if (typeof window === 'undefined') return;
    sessionStorage.removeItem(SCAFFOLD_DATA_KEY);
}
