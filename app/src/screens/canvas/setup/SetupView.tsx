/**
 * SetupView — the state-derived setup surface behind a workflow's Setup tab:
 * one step per screen in a centred column (header, progress bar, animated
 * step transitions, Continue/Back footer), with a miniature step rail on the
 * left for orientation and jumping. Steps are DERIVED from the live graph on
 * every render (the same lens the canvas marks a step incomplete by) — no
 * stored wizard state, resumable from any entry, self-healing when an account
 * dies later. Account steps render the step's own account pickers and ask
 * the provider to prove the account works. The corridor ends at Test Run —
 * the step no derivation can judge. What the tab knows of each step type,
 * and the parts only a host has in full, come from whoever renders it (the
 * `canvas.setup` slots: reads.ts).
 */

import { lazy, Suspense, useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import type { Edge, Node } from '@xyflow/react';
import { AnimatePresence, motion } from 'framer-motion';
import { ArrowLeft, Braces, ChevronDown, FlaskConical, PanelLeftClose, Play, Plug } from 'lucide-react';
import { useSlot } from '@/slots';
import { cn } from '@/ui/utils';
import { DynamicOptionsField } from '../form/DynamicOptionsField';
import type { NodeConfigProps } from '../form/NodeConfig';
import { StepContext, useStepScope } from '../form/reads';
import { ReadinessCard, deriveUnmetConnections } from '../readiness';
import { SETUP, SETUP_MCP, SETUP_RUNTIME } from '../slots';
import { AccountStep } from './AccountStep';
import { Mark, SetupHeader, StepProgress } from './parts';
import {
    CollapsedNodeRail,
    NodeBadge,
    RAIL_COLLAPSED_WIDTH,
    RailResizeHandle,
    SetupTypesProvider,
    StepKindBadge,
    StepStateDot,
    StepStateMark,
    groupByNode,
    useRailLayout,
    type RailStep,
    type SetupNodeMeta,
} from './rail';
import { ReadinessStatus } from './ReadinessStatus';
import type { SetupLens, StepTypeFacts } from './reads';
import { TestRunPreview } from './TestRunPreview';
import type { CredentialStep } from './types';
import { HIDDEN_VARIABLE_PLACEHOLDER, holdsHiddenValue, humanizeVariableName, isVariableFilled, type WorkflowVariableDefinition } from './variables';

// The step form loads with the first step that draws it (its widgets bring CodeMirror, its checks Ajv).
const NodeConfigImpl = lazy(() => import('../form/NodeConfig').then((m) => ({ default: m.NodeConfig })));

function NodeConfig(props: NodeConfigProps) {
    return (
        <Suspense fallback={null}>
            <NodeConfigImpl {...props} />
        </Suspense>
    );
}

interface SetupStep {
    key: string;
    kind: 'credentials' | 'config' | 'variable' | 'agent' | 'test' | 'connect';
    node?: Node;
    title: string;
    detail: string;
    /** Currently unmet, per the graph. Satisfied steps stay listed for the
        session (a shrinking rail reads as jank) but wear a check. */
    unmet: boolean;
    /** Config steps only: the blank required fields — the step asks exactly
        this and renders nothing else. */
    focusFields?: string[];
    /** Config steps only: no operation chosen yet — the step IS the picker. */
    needsOperation?: boolean;
    /** Variable steps only: the definition being asked for. */
    variable?: WorkflowVariableDefinition;
    /** Credential steps only: every node this connection covers. Same-type
        nodes share one service account — the WhatsApp trigger + reply-tools
        pair must ask ONCE, and connecting attaches to all of them. */
    groupNodeIds?: string[];
}

/** A step type's glyph, where whoever renders the tab has one for it. */
function nodeIcon(facts: StepTypeFacts | undefined, className = 'h-4 w-4'): ReactNode {
    if (!facts?.Icon) return null;
    const Icon = facts.Icon;
    return <Icon className={className} style={{ color: facts.iconColor }} />;
}

function prettifyOp(value: string): string {
    const s = value.replace(/_/g, ' ').trim();
    return s.charAt(0).toUpperCase() + s.slice(1);
}

/** What the account step is told of a step, derived from the live node.
    Evidence fields stay empty — the live probe fills them. */
function toCredentialStep(node: Node, lens: SetupLens, labelOverride?: string): CredentialStep {
    const type = node.type as string;
    const facts = lens.typeOf(type);
    const allow = ((node.data?.config as Record<string, unknown>)?.agent_tool_operations ??
        []) as unknown[];
    const attached =
        Object.entries(
            (node.data?.credentialIds as Record<string, string>) ?? {}
        ).find(([k, v]) => k !== 'credential_type' && v)?.[1] ?? null;
    return {
        kind: 'credential',
        id: type,
        label: labelOverride || (node.data?.label as string) || facts.label,
        iconHtml: '',
        iconColor: undefined as unknown as string,
        iconNode: nodeIcon(facts, 'h-7 w-7'),
        why:
            facts.description ??
            'Connect the account this node acts through.',
        credentialLabel: null,
        connected: Boolean(attached),
        tools: allow
            .map((a) => (typeof a === 'string' ? a : (a as { operation?: string })?.operation))
            .filter((v): v is string => Boolean(v))
            .map((v) => ({
                value: v,
                name: prettifyOp(v),
                description: '',
                requiredScope: null,
                category: 'General',
            })),
        grantedScopes: null,
        rebind: null,
        expectedOutcome: 'untested',
        options: [],
        connectMethods: [],
        attachedId: attached,
        consequence: { loss: 'this step may not work', failure: '' },
    };
}

/** One declared variable asked as a guided question. Local draft committed on
    blur/Enter — each commit is a write of the workflow's settings, so
    per-keystroke persistence would write one per key. */
function VariablePhase({
    definition,
    binding,
    workflowId,
    icon,
    onCommit,
    onOpenCredentials,
}: {
    definition: WorkflowVariableDefinition;
    /** The config field this variable feeds, when one is bound. */
    binding: VariableBinding | null;
    workflowId?: string;
    /** The bound step's glyph. */
    icon: ReactNode;
    onCommit: (value: string) => void;
    onOpenCredentials?: () => void;
}) {
    const [draft, setDraft] = useState(definition.value ?? '');
    const outer = useStepScope();
    // Only what was typed is committed: leaving the field as it was writes nothing (an empty value would replace a
    // saved one that isn't held here).
    const commit = () => {
        if (draft !== (definition.value ?? '')) onCommit(draft);
    };
    // A bound field with dynamic options gets ITS OWN picker — the same
    // loader the config panel uses, with the bound node's credential — so the
    // user picks their repo from GitHub's list instead of typing owner/name.
    const dynamic = Boolean(binding?.prop?.['x-dynamic-options']);
    const lede =
        definition.description?.trim() ||
        (binding?.prop?.description as string | undefined) ||
        'This workflow needs a value for this variable before it can run properly.';
    return (
        <div>
            <Mark
                iconHtml=""
                iconNode={
                    binding
                        ? icon
                        : <Braces className="h-7 w-7 text-foreground/60" />
                }
                size="lg"
            />
            <h2 className="mb-0 mt-5 font-sans text-[22px] font-semibold tracking-[-0.02em]">
                {(binding?.prop?.title as string | undefined) ||
                    humanizeVariableName(definition.name)}
            </h2>
            <p className="mb-0 mt-3 text-[15px] leading-relaxed text-foreground/55">{lede}</p>
            {dynamic && binding ? (
                <div className="mt-5">
                    {/* The picker reads the bound step's own choices: it names that step. */}
                    <StepContext.Provider value={{ ...outer, workflowId, nodeId: binding.node.id }}>
                    <DynamicOptionsField
                        fieldKey={binding.fieldKey}
                        prop={binding.prop}
                        value={definition.value ?? ''}
                        // selectOption fires TWO onChange calls: the value,
                        // then a `${fieldKey}__label` bookkeeping write ('' when
                        // label === value, as repos are). Committing both let
                        // the empty label write clobber the pick — only the
                        // primary key is the variable's value.
                        onChange={(k, v) => {
                            if (k === binding.fieldKey) onCommit(v);
                        }}
                        nodeType={binding.node.type as string}
                        credentialIds={
                            (binding.node.data?.credentialIds as Record<string, string>) ?? {}
                        }
                        config={(binding.node.data?.config as Record<string, any>) ?? {}}
                        onOpenCredentials={onOpenCredentials}
                    />
                    </StepContext.Provider>
                </div>
            ) : (
                <input
                    autoFocus
                    value={draft}
                    onChange={(e) => setDraft(e.target.value)}
                    onBlur={commit}
                    onKeyDown={(e) => {
                        if (e.key === 'Enter') commit();
                    }}
                    placeholder={holdsHiddenValue(definition) ? HIDDEN_VARIABLE_PLACEHOLDER : 'Enter a value'}
                    className="mt-5 w-full rounded-lg border border-foreground/12 bg-foreground/[0.02] px-3.5 py-2.5 text-[14px] outline-none transition-colors placeholder:text-foreground/25 focus:border-foreground/35"
                />
            )}
        </div>
    );
}

interface VariableBinding {
    node: Node;
    fieldKey: string;
    prop: any;
}

/** The config field a variable is bound to — one whose WHOLE value is
    {{vars.name}}. The variable step then wears that field's real editor
    (GitHub's repository dropdown, a sheet picker) instead of a bare text
    input: the choice writes back to the VARIABLE while the field keeps its
    reference. Deterministic — no guessing which fields are personal. */
function findVariableBinding(nodes: Node[], name: string, lens: SetupLens): VariableBinding | null {
    const ref = `{{vars.${name}}}`;
    for (const node of nodes) {
        if (!node.type) continue;
        const config = (node.data as { config?: Record<string, unknown> } | undefined)?.config;
        if (!config) continue;
        for (const [fieldKey, v] of Object.entries(config)) {
            if (v !== ref) continue;
            const prop = lens.fieldOf(node, fieldKey);
            if (prop) return { node, fieldKey, prop };
        }
    }
    return null;
}

export interface SetupViewProps {
    nodes: Node[];
    edges: Edge[];
    workflowId?: string;
    onConfigChange: (nodeId: string, config: Record<string, any>) => void;
    onOperationChange: (nodeId: string, operation: string) => void;
    onCredentialIdsChange: (nodeId: string, credentialIds: Record<string, string>) => void;
    /** Open the workflow's Test Run screen. */
    onOpenTestRun: () => void;
    /** Author-declared variables (the workflow's `variable_definitions`). Unfilled
        ones become steps; filling writes through onVariableDefinitionsChange. */
    variableDefinitions?: WorkflowVariableDefinition[];
    onVariableDefinitionsChange?: (definitions: WorkflowVariableDefinition[]) => void;
}

export function SetupView(props: SetupViewProps) {
    // The steps are read through the lens: the view opens once it has what it
    // judges by, then recomputes as a later step's type lands (staying mounted).
    const lens = useSlot(SETUP).useLens(props.nodes, props.edges);
    const [opened, setOpened] = useState(lens.ready);
    if (lens.ready && !opened) setOpened(true);
    return opened ? <SetupSteps {...props} lens={lens} /> : null;
}

function SetupSteps({
    nodes,
    edges,
    workflowId,
    onConfigChange,
    onOperationChange,
    onCredentialIdsChange,
    onOpenTestRun,
    variableDefinitions,
    onVariableDefinitionsChange,
    lens,
}: SetupViewProps & { lens: SetupLens }) {
    const host = useSlot(SETUP);
    // What whoever draws the tab said of the steps' forms (a canvas that saves them itself): kept for each step's own.
    const outer = useStepScope();
    const runtime = useSlot(SETUP_RUNTIME);
    const McpConnect = useSlot(SETUP_MCP);
    const agentNode = nodes.find((n) => n.type === 'agent');
    const nameOf = (type: string) => lens.typeOf(type).label;
    // A workflow whose hub is an MCP server that serves the steps wired into it
    // finishes on the connect-your-agent step, not a Test Run — nothing in it
    // can rehearse (no agent), and "done" means an outside agent connected.
    const mcpHubNode = useMemo(
        () =>
            agentNode
                ? undefined
                : nodes.find(
                      (n) =>
                          n.type === 'mcp-server' &&
                          edges.some(
                              (e) =>
                                  e.target === n.id && e.targetHandle === 'bottom'
                          )
                  ),
        [nodes, edges, agentNode]
    );
    // How the agent's step stands, and the way on from it with no account. (A
    // host that was told which agent to choose before the tab drew writes it
    // as this first runs, so the step lands on it instead of asking again.)
    const runtimeStatus = runtime.useStep(workflowId, agentNode, onConfigChange);
    const withoutAccount = runtimeStatus.withoutAccount;

    // Resolved values of declared variables — bound config fields in the
    // config steps display these instead of raw {{vars.x}} refs.
    const definedValues = useMemo(() => {
        const out: Record<string, any> = {};
        for (const d of variableDefinitions ?? []) {
            if (d?.name?.trim() && d.value !== undefined && d.value !== '') out[d.name.trim()] = d.value;
        }
        return out;
    }, [variableDefinitions]);

    // Steps a completed session has seen stay in the rail with a check —
    // derivation alone would delete them, and a shrinking list reads as jank.
    const seenRef = useRef<Map<string, SetupStep>>(new Map());

    const steps = useMemo<SetupStep[]>(() => {
        const credentialSteps: SetupStep[] = [];
        const configSteps: SetupStep[] = [];
        for (const node of nodes) {
            if (!node.type || node.type === 'sticky-note') continue;
            const issues = lens.issuesOf(node);
            const label =
                (node.data?.label as string | undefined) || nameOf(node.type);
            // The agent's own account is OWNED by its step ("Which agent
            // runs it") - a generic account step here asked the same
            // question earlier, with the wrong picker.
            const creds =
                node.type === 'agent'
                    ? []
                    : issues.filter((i) => i.type === 'missing_credentials');
            const rest = issues.filter((i) => i.type !== 'missing_credentials');
            if (creds.length || seenRef.current.has(`${node.id}:credentials`)) {
                // Same-type nodes share one service account: merge into the
                // FIRST node's step (title = the service's catalog name) and
                // record every member — the step writes the account to all
                // of them. Two asks for one connection read as two questions
                // where there is one.
                const twin = credentialSteps.find(
                    (s) => s.node?.type === node.type
                );
                if (twin) {
                    twin.groupNodeIds = [...(twin.groupNodeIds ?? [twin.node!.id]), node.id];
                    twin.title = nameOf(node.type);
                    twin.unmet = twin.unmet || creds.length > 0;
                    twin.detail = twin.unmet ? 'Connect an account' : 'Connected';
                } else {
                    credentialSteps.push({
                        key: `${node.id}:credentials`,
                        kind: 'credentials',
                        node,
                        title: label,
                        detail: creds.length ? 'Connect an account' : 'Connected',
                        unmet: creds.length > 0,
                    });
                }
            }
            if (rest.length || seenRef.current.has(`${node.id}:config`)) {
                const fieldKeys = rest
                    .filter((i) => i.type === 'missing_required_field')
                    .map((i) => i.fieldKey)
                    .filter((k): k is string => Boolean(k));
                const needsOperation = rest.some((i) => i.type === 'missing_operation');
                configSteps.push({
                    key: `${node.id}:config`,
                    kind: 'config',
                    node,
                    title: label,
                    detail: !rest.length
                        ? 'Configured'
                        : needsOperation
                          ? 'Choose what it does'
                          : `${fieldKeys.length} field${fieldKeys.length === 1 ? '' : 's'} to fill`,
                    unmet: rest.length > 0,
                    // Empty-but-unmet (an issue with no fieldKey) falls back to
                    // the full form rather than rendering nothing to fix.
                    focusFields: fieldKeys.length ? fieldKeys : undefined,
                    needsOperation,
                });
            }
        }
        const variableSteps: SetupStep[] = (variableDefinitions ?? [])
            .filter((d) => d?.name?.trim())
            .map((d) => {
                const filled = isVariableFilled(d);
                return {
                    key: `var:${d.name.trim()}`,
                    kind: 'variable' as const,
                    title: humanizeVariableName(d.name),
                    detail: filled ? 'Filled' : d.description?.trim() || 'Needs a value',
                    unmet: !filled,
                    variable: d,
                };
            });
        // The runtime choice — "the last choice, and the only one that can ask
        // for another account." Always listed for an agent workflow; unmet where
        // the agent chosen needs an account of the person's own and has none.
        const agentSteps: SetupStep[] = [];
        if (agentNode) {
            agentSteps.push({
                key: `${agentNode.id}:runtime`,
                kind: 'agent',
                node: agentNode,
                title: 'Which agent runs it',
                detail: runtimeStatus.detail,
                unmet: runtimeStatus.unmet,
            });
        }
        const finale: SetupStep = mcpHubNode
            ? {
                  key: 'mcp-connect',
                  kind: 'connect' as const,
                  node: mcpHubNode,
                  title: 'Connect your agent',
                  detail: 'Add these tools to your coding agent',
                  unmet: false,
              }
            : {
                  key: 'test-run',
                  kind: 'test' as const,
                  title: 'Test Run',
                  detail: 'Watch it handle a staged event',
                  unmet: false,
              };
        const out = [
            ...credentialSteps,
            ...variableSteps,
            ...configSteps,
            ...agentSteps,
            finale,
        ];
        for (const s of out) seenRef.current.set(s.key, s);
        return out;
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [nodes, lens, variableDefinitions, agentNode, mcpHubNode, runtimeStatus.unmet, runtimeStatus.detail]);

    const [selectedKey, setSelectedKey] = useState<string | null>(null);
    // Footer slot the account step portals its Test Connection button into.
    const [testSlot, setTestSlot] = useState<HTMLElement | null>(null);
    // A credential step may cover several same-type nodes (one service, one
    // ask) — resolve ANY member's id to the merged step that asks for it.
    // Every jump-to-credentials seam must go through this, since callers
    // (readiness cards, variable bindings) only know a node id.
    const credentialStepKey = (nodeId: string): string =>
        steps.find(
            (s) =>
                // The agent's credential question lives on its runtime step.
                (s.kind === 'agent' && s.node?.id === nodeId) ||
                (s.kind === 'credentials' &&
                    (s.key === `${nodeId}:credentials` ||
                        s.groupNodeIds?.includes(nodeId)))
        )?.key ?? `${nodeId}:credentials`;
    // Deep link from readiness cards elsewhere (Test Run, agent chat): jump
    // straight to the named step. Kept by the host — this view may mount after
    // the card was clicked.
    const [pendingStep, setPendingStep] = host.useKept<string | null>(
        `pending-step-${workflowId ?? 'unknown'}`,
        null
    );
    useEffect(() => {
        if (pendingStep) {
            const member = pendingStep.match(/^(.+):credentials$/)?.[1];
            setSelectedKey(member ? credentialStepKey(member) : pendingStep);
            setPendingStep(null);
        }
        // credentialStepKey reads the steps memo; the effect only acts while
        // pendingStep is set, and clears it immediately.
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [pendingStep, setPendingStep]);
    // What still stops this workflow from running for real — the Test Run
    // finale names it with consequences instead of a count.
    const unmetConnections = useMemo(
        () =>
            deriveUnmetConnections(nodes, edges, {
                needsConnection: (node) => lens.issuesOf(node).some((i) => i.type === 'missing_credentials'),
                isTriggerSource: lens.isTriggerSource,
                nameOf: (type) => lens.typeOf(type).label,
            }),
        [nodes, edges, lens]
    );
    const index = Math.max(
        0,
        steps.findIndex((s) => s.key === (selectedKey ?? steps.find((x) => x.unmet)?.key))
    );
    const active = steps[index] ?? steps[steps.length - 1];
    // Once an account step is SKIPPED (moved past while unmet) its card trails
    // below every later step — the step you are looking at reports its own
    // state inline, so it never warns about itself.
    const skippedUnmet = useMemo(
        () =>
            unmetConnections.filter((u) => {
                const i = steps.findIndex(
                    (s) =>
                        s.kind === 'credentials' &&
                        u.nodeIds.some(
                            (id) =>
                                s.key === `${id}:credentials` ||
                                s.groupNodeIds?.includes(id)
                        )
                );
                return i >= 0 && i < index;
            }),
        [unmetConnections, steps, index]
    );
    const remaining = steps.filter((s) => s.unmet).length;

    const agentName =
        (agentNode?.data?.label as string | undefined) ||
        ((agentNode?.data?.config as Record<string, unknown>)?.agent_name as string) ||
        (mcpHubNode
            ? (mcpHubNode.data?.label as string | undefined) || 'Your MCP server'
            : 'Your agent');

    // Open the Test Run screen AND start the run — the host keeps the ask, so
    // it survives the screen drawing after we make it. A bare call re-runs the
    // last-viewed situation (or the first available); a selection runs that card.
    const runTest = (sel?: { trigger: string; run: string }) => {
        void host.askForTestRun(workflowId, sel && { trigger: sel.trigger, run: sel.run });
        onOpenTestRun();
    };

    const go = (i: number) => setSelectedKey(steps[Math.min(Math.max(i, 0), steps.length - 1)]?.key ?? null);

    // ---- The rail ---------------------------------------------------------
    // The rail is orientation, not the work — a fresh mount opens on the icon
    // strip so the active step gets the room, and one click expands.
    const rail = useRailLayout({ defaultCollapsed: true });
    const railNodes = useMemo<Record<string, SetupNodeMeta>>(() => {
        const map: Record<string, SetupNodeMeta> = {};
        for (const s of steps) {
            if (!s.node) continue;
            map[s.node.id] = {
                nodeId: s.node.id,
                nodeType: s.node.type as string,
                // The node's own name, not the step's question — the agent
                // step's "Which agent runs it" must not rename its group.
                label:
                    (s.node.data?.label as string | undefined) ||
                    lens.typeOf(s.node.type as string).label,
            };
        }
        if (steps.some((s) => s.kind === 'variable')) {
            map['variables'] = { nodeId: 'variables', nodeType: 'variables', label: 'Variables' };
        }
        map['test-run'] = { nodeId: 'test-run', nodeType: 'test-run', label: 'Test Run' };
        return map;
    }, [steps, lens]);
    const railSteps = useMemo<RailStep[]>(
        () =>
            steps.map((s) => ({
                id: s.key,
                nodeId:
                    s.kind === 'variable'
                        ? 'variables'
                        : (s.node?.id ?? 'test-run'),
                kind:
                    s.kind === 'credentials'
                        ? 'credential'
                        : s.kind === 'agent'
                          ? 'agent'
                          : s.needsOperation
                            ? 'operation'
                            : s.kind === 'test' || s.kind === 'connect'
                              ? 'tool'
                              : 'config',
                title:
                    s.kind === 'test'
                        ? 'Run a staged event'
                        : s.kind === 'variable'
                          ? s.title
                          : s.detail,
                state: s.unmet ? 'todo' : 'done',
            })),
        [steps]
    );
    const groups = useMemo(() => groupByNode(railSteps, railNodes), [railSteps, railNodes]);
    const isFilled = (rs: RailStep) => rs.state === 'done';
    const [collapsedGroups, setCollapsedGroups] = useState<Set<string>>(new Set());
    const toggleGroup = (nodeId: string) =>
        setCollapsedGroups((prev) => {
            const next = new Set(prev);
            if (next.has(nodeId)) next.delete(nodeId);
            else next.add(nodeId);
            return next;
        });
    // The finale (Test Run / Connect) is a destination, not a debt — it
    // never counts toward progress.
    const countable = railSteps.filter(
        (rs) => rs.nodeId !== 'test-run' && rs.id !== 'mcp-connect'
    );
    const doneCount = countable.filter(isFilled).length;

    return (
        <SetupTypesProvider value={lens.typeOf}>
        <div className="flex min-h-0 flex-1 overflow-hidden bg-background text-foreground">
            {/* LEFT — the rail: collapsible to an icon strip, resizable,
                per-node groups. */}
            <aside
                style={{
                    flexBasis: rail.collapsed ? RAIL_COLLAPSED_WIDTH : rail.width,
                    width: rail.collapsed ? RAIL_COLLAPSED_WIDTH : rail.width,
                }}
                className={cn(
                    'relative hidden shrink-0 flex-col border-r border-border dark:border-white/[0.08] md:flex',
                    !rail.resizing && 'transition-[flex-basis] duration-200'
                )}
            >
                {rail.collapsed ? (
                    <CollapsedNodeRail
                        groups={groups}
                        activeNodeId={active?.node?.id ?? (active?.kind === 'test' ? 'test-run' : undefined)}
                        isFilled={isFilled}
                        onExpand={() => rail.setCollapsed(false)}
                        onPickNode={(nodeId) => {
                            rail.setCollapsed(false);
                            const i = steps.findIndex((s) => (s.node?.id ?? 'test-run') === nodeId);
                            if (i >= 0) go(i);
                        }}
                    />
                ) : (
                    <>
                        <div className="shrink-0 border-b border-border dark:border-white/[0.08] px-4 py-4">
                            <div className="mb-3 flex items-start justify-between gap-2">
                                <div className="min-w-0">
                                    <div className="text-[0.6875rem] font-medium uppercase tracking-wider text-muted-foreground/70 dark:text-white/35">
                                        Set up
                                    </div>
                                    <div className="truncate text-sm font-semibold text-foreground/90">
                                        {agentName}
                                    </div>
                                </div>
                                <button
                                    type="button"
                                    onClick={rail.toggle}
                                    title="Collapse sidebar"
                                    className="-mr-1 -mt-1 flex h-7 w-7 shrink-0 items-center justify-center rounded-lg text-muted-foreground/70 dark:text-white/40 transition-colors hover:bg-foreground/[0.06] hover:text-foreground/80"
                                >
                                    <PanelLeftClose className="h-4 w-4" />
                                </button>
                            </div>
                            <div className="flex items-center justify-between text-[0.6875rem] tabular-nums text-muted-foreground/70 dark:text-white/40">
                                <span>
                                    {doneCount} of {countable.length} done
                                </span>
                                <span>
                                    {countable.length
                                        ? Math.round((doneCount / countable.length) * 100)
                                        : 0}
                                    %
                                </span>
                            </div>
                            <div className="mt-1.5 h-1.5 overflow-hidden rounded-full bg-foreground/[0.06]">
                                <div
                                    className="h-full rounded-full bg-foreground/45 transition-[width] duration-500 ease-out"
                                    style={{
                                        width: `${countable.length ? (doneCount / countable.length) * 100 : 0}%`,
                                    }}
                                />
                            </div>
                        </div>

                        <nav className="scrollbar-subtle flex-1 overflow-y-auto py-2">
                            {groups.map((group) => {
                                const liveDone = group.steps.filter(isFilled).length;
                                const isCollapsed = collapsedGroups.has(group.node.nodeId);
                                const isTestGroup = group.node.nodeId === 'test-run';
                                return (
                                    <div key={group.node.nodeId} className="mb-1 px-2">
                                        <button
                                            type="button"
                                            onClick={() =>
                                                isTestGroup
                                                    ? go(steps.length - 1)
                                                    : toggleGroup(group.node.nodeId)
                                            }
                                            className="flex w-full items-center gap-2 rounded-lg px-2 py-1.5 text-left transition-colors hover:bg-foreground/[0.03]"
                                        >
                                            {!isTestGroup ? (
                                                <ChevronDown
                                                    className={cn(
                                                        'h-3.5 w-3.5 shrink-0 text-muted-foreground/70 dark:text-white/30 transition-transform duration-200',
                                                        isCollapsed && '-rotate-90'
                                                    )}
                                                />
                                            ) : (
                                                <FlaskConical className="ml-0.5 h-3.5 w-3.5 shrink-0 text-muted-foreground/70 dark:text-white/40" />
                                            )}
                                            {isTestGroup ? (
                                                <span className="min-w-0 flex-1 truncate text-sm font-medium text-foreground">
                                                    Test Run
                                                </span>
                                            ) : (
                                                <NodeBadge
                                                    node={group.node}
                                                    subtitle={false}
                                                    wellClassName="h-6 w-6"
                                                    className="min-w-0 flex-1"
                                                />
                                            )}
                                            {!isTestGroup && (
                                                <span className="shrink-0 text-[0.6875rem] tabular-nums text-muted-foreground/70 dark:text-white/35">
                                                    {liveDone}/{group.steps.length}
                                                </span>
                                            )}
                                        </button>
                                        {isTestGroup ? null : isCollapsed ? (
                                            <div className="flex flex-wrap items-center gap-1 px-2 pb-1.5 pl-[1.875rem]">
                                                {group.steps.map((rs) => (
                                                    <StepStateDot
                                                        key={rs.id}
                                                        state={rs.state}
                                                        current={rs.id === active?.key}
                                                    />
                                                ))}
                                            </div>
                                        ) : (
                                            <div className="flex flex-col gap-0.5">
                                                {group.steps.map((rs) => {
                                                    const gi = steps.findIndex(
                                                        (s) => s.key === rs.id
                                                    );
                                                    const isActive = rs.id === active?.key;
                                                    return (
                                                        <button
                                                            key={rs.id}
                                                            type="button"
                                                            onClick={() => go(gi)}
                                                            className={cn(
                                                                'group flex w-full items-center gap-2.5 rounded-lg px-2 py-2 text-left transition-colors',
                                                                isActive
                                                                    ? 'bg-foreground/[0.06]'
                                                                    : 'hover:bg-foreground/[0.03]'
                                                            )}
                                                        >
                                                            <StepStateMark
                                                                state={rs.state}
                                                                current={isActive}
                                                                className="shrink-0"
                                                            />
                                                            <span
                                                                className={cn(
                                                                    'min-w-0 flex-1 truncate text-[0.8125rem] transition-colors',
                                                                    isActive
                                                                        ? 'text-foreground/90'
                                                                        : rs.state === 'todo'
                                                                          ? 'text-amber-600 dark:text-amber-300/90 group-hover:text-amber-500 dark:group-hover:text-amber-200'
                                                                          : 'text-muted-foreground dark:text-white/55 group-hover:text-foreground/80'
                                                                )}
                                                            >
                                                                {rs.title}
                                                            </span>
                                                            <StepKindBadge
                                                                kind={rs.kind}
                                                                className="shrink-0 px-1.5 py-0"
                                                            />
                                                        </button>
                                                    );
                                                })}
                                            </div>
                                        )}
                                    </div>
                                );
                            })}
                        </nav>
                    </>
                )}
                {!rail.collapsed && (
                    <RailResizeHandle onMouseDown={rail.startResize} resizing={rail.resizing} />
                )}
            </aside>

            {/* The guided column: one step per screen, centred both ways —
                justify-center when it fits, normal scroll when it doesn't. */}
            <div className="scrollbar-subtle min-w-0 flex-1 overflow-y-auto">
                <div
                    className={cn(
                        'mx-auto flex min-h-full w-full flex-col justify-center px-6 py-12',
                        // The agent's choices are a two-up grid; the narrow
                        // question column squishes them.
                        active?.kind === 'agent' ? 'max-w-[720px]' : 'max-w-[520px]'
                    )}
                >
                    <SetupHeader name={agentName} />
                    <div className="mt-5">
                        <StepProgress step={index} total={steps.length} />
                    </div>

                    {/* relative + margin on the STATIC wrapper: popLayout
                        positions the exiting step against the nearest
                        positioned ancestor, and a popped element loses its
                        own margin — both made the outgoing step jump during
                        its fade. */}
                    <div className="relative mt-8">
                    <AnimatePresence mode="popLayout">
                        <motion.div
                            key={active?.key}
                            initial={{ opacity: 0, y: 6 }}
                            animate={{ opacity: 1, y: 0 }}
                            // popLayout: the exiting step pops out of flow, so
                            // the column height changes ONCE (mode="wait"
                            // collapsed to empty for a beat, snapping the
                            // footer up then down — the per-transition jitter).
                            exit={{ opacity: 0, y: -4, transition: { duration: 0.12, ease: 'easeIn' } }}
                            transition={{ duration: 0.2, ease: [0.16, 1, 0.3, 1] }}
                        >
                            {active?.kind === 'credentials' && active.node && (
                                // The pickers name the step whose account they choose.
                                <StepContext.Provider value={{ ...outer, workflowId, nodeId: active.node.id }}>
                                <AccountStep
                                    key={active.node.id}
                                    step={toCredentialStep(active.node, lens, active.title)}
                                    bound=""
                                    onBind={() => {}}
                                    credentialIds={
                                        (active.node.data?.credentialIds as Record<
                                            string,
                                            string
                                        >) ?? {}
                                    }
                                    testSlot={testSlot}
                                    onCredentialsChange={(ids) => {
                                        // One connection covers every same-type
                                        // node in the group — the step asked once,
                                        // so the answer applies everywhere.
                                        for (const nid of active.groupNodeIds ?? [
                                            active.node!.id,
                                        ]) {
                                            onCredentialIdsChange(nid, ids);
                                        }
                                    }}
                                />
                                </StepContext.Provider>
                            )}

                            {active?.kind === 'config' && active.node && (
                                <div>
                                    <Mark
                                        iconHtml=""
                                        iconNode={nodeIcon(lens.typeOf(active.node.type as string), 'h-7 w-7')}
                                        size="lg"
                                    />
                                    <h2 className="mb-0 mt-5 font-sans text-[22px] font-semibold tracking-[-0.02em]">
                                        {active.title}
                                    </h2>
                                    <p className="mb-0 mt-3 text-[15px] leading-relaxed text-foreground/55">
                                        {active.needsOperation
                                            ? 'Choose what this node should do.'
                                            : 'Fill in what this node needs before it can run.'}
                                    </p>
                                    <div className="mt-5">
                                        {/* The step asks exactly its question: only
                                            the blank required fields render (no
                                            banner, no filled/optional fields), and
                                            the operation picker only when the
                                            operation IS the question. A satisfied
                                            step revisited shows the full form. */}
                                        <NodeConfig
                                            key={active.node.id}
                                            nodeType={active.node.type as string}
                                            withheld={active.node.data?.withheld as string[] | undefined}
                                            config={
                                                (active.node.data?.config as Record<
                                                    string,
                                                    any
                                                >) ?? {}
                                            }
                                            onChange={(config) =>
                                                onConfigChange(active.node!.id, config)
                                            }
                                            operation={
                                                active.node.data?.operation as
                                                    | string
                                                    | undefined
                                            }
                                            onOperationChange={(op) =>
                                                onOperationChange(active.node!.id, op)
                                            }
                                            onSwitchToCredentials={() =>
                                                setSelectedKey(
                                                    credentialStepKey(active.node!.id)
                                                )
                                            }
                                            credentialIds={
                                                (active.node.data?.credentialIds as Record<
                                                    string,
                                                    string
                                                >) ?? {}
                                            }
                                            workflowId={workflowId}
                                            nodeId={active.node.id}
                                            focusFields={
                                                active.needsOperation
                                                    ? []
                                                    : active.unmet
                                                      ? active.focusFields
                                                      : undefined
                                            }
                                            hideOperationPicker={
                                                active.unmet && !active.needsOperation
                                            }
                                            workflowVariables={definedValues}
                                            onVariableValueChange={
                                                onVariableDefinitionsChange
                                                    ? (name, value) =>
                                                          onVariableDefinitionsChange(
                                                              (variableDefinitions ?? []).some(
                                                                  (d) => d.name === name
                                                              )
                                                                  ? (variableDefinitions ?? []).map(
                                                                        (d) =>
                                                                            d.name === name
                                                                                ? { ...d, value }
                                                                                : d
                                                                    )
                                                                  : [
                                                                        ...(variableDefinitions ??
                                                                            []),
                                                                        { name, value },
                                                                    ]
                                                          )
                                                    : undefined
                                            }
                                        />
                                    </div>
                                </div>
                            )}

                            {active?.kind === 'variable' && active.variable && (
                                <VariablePhase
                                    key={active.key}
                                    definition={active.variable}
                                    binding={findVariableBinding(nodes, active.variable.name, lens)}
                                    workflowId={workflowId}
                                    icon={nodeIcon(
                                        lens.typeOf((findVariableBinding(nodes, active.variable.name, lens)?.node.type as string) ?? ''),
                                        'h-7 w-7'
                                    )}
                                    onOpenCredentials={() => {
                                        const b = findVariableBinding(nodes, active.variable!.name, lens);
                                        if (b) setSelectedKey(credentialStepKey(b.node.id));
                                    }}
                                    onCommit={(value) => {
                                        if (!onVariableDefinitionsChange) return;
                                        const name = active.variable!.name;
                                        onVariableDefinitionsChange(
                                            (variableDefinitions ?? []).map((d) =>
                                                d.name === name ? { ...d, value } : d
                                            )
                                        );
                                    }}
                                />
                            )}

                            {active?.kind === 'agent' && active.node && (
                                <StepContext.Provider value={{ ...outer, workflowId, nodeId: active.node.id }}>
                                <runtime.Phase
                                    key={active.node.id}
                                    node={active.node}
                                    onConfigChange={onConfigChange}
                                    onCredentialIdsChange={onCredentialIdsChange}
                                />
                                </StepContext.Provider>
                            )}

                            {active?.kind === 'test' && (
                                <div>
                                    <Mark
                                        iconHtml=""
                                        iconNode={
                                            <FlaskConical className="h-7 w-7 text-foreground/60" />
                                        }
                                        size="lg"
                                    />
                                    <h2 className="mb-0 mt-5 font-sans text-[22px] font-semibold tracking-[-0.02em]">
                                        Test Run
                                    </h2>
                                    <p className="mb-0 mt-3 text-[15px] leading-relaxed text-foreground/55">
                                        {remaining === 0
                                            ? 'Run the agent against a staged event — real agent, fabricated world, nothing sent.'
                                            : 'You can test before finishing setup: tool calls are answered by a fabricated world, so nothing needs to be live yet.'}
                                    </p>
                                    {unmetConnections.length > 0 && (
                                        <ReadinessCard
                                            unmet={unmetConnections}
                                            onConnect={(item) =>
                                                setSelectedKey(credentialStepKey(item.nodeId))
                                            }
                                            className="mt-5"
                                        />
                                    )}
                                    {workflowId && <ReadinessStatus workflowId={workflowId} />}
                                    {workflowId ? (
                                        <div className="mt-6">
                                            <TestRunPreview
                                                workflowId={workflowId}
                                                onRun={(sel) => runTest(sel)}
                                                onSkip={onOpenTestRun}
                                            />
                                        </div>
                                    ) : (
                                        <button
                                            onClick={() => runTest()}
                                            className="mt-6 inline-flex items-center gap-2 rounded-lg bg-primary px-5 py-2.5 text-[14px] font-medium text-primary-foreground transition-opacity hover:opacity-90"
                                        >
                                            <Play className="h-3.5 w-3.5" />
                                            Test Run
                                        </button>
                                    )}
                                </div>
                            )}

                            {active?.kind === 'connect' && active.node && (
                                <div>
                                    <Mark
                                        iconHtml=""
                                        iconNode={
                                            <Plug className="h-7 w-7 text-foreground/60" />
                                        }
                                        size="lg"
                                    />
                                    {workflowId && (
                                        <div className="mt-5">
                                            <McpConnect
                                                workflowId={workflowId}
                                                nodeId={active.node.id}
                                                nodeLabel={
                                                    active.node.data
                                                        ?.label as string
                                                }
                                            />
                                        </div>
                                    )}
                                    {unmetConnections.length > 0 && (
                                        <ReadinessCard
                                            unmet={unmetConnections}
                                            onConnect={(item) =>
                                                setSelectedKey(
                                                    credentialStepKey(item.nodeId)
                                                )
                                            }
                                            className="mt-6"
                                        />
                                    )}
                                </div>
                            )}
                        </motion.div>
                    </AnimatePresence>
                    </div>

                    {/* Stable footer: actions GLIDE to the new step's height
                        (layout animation) instead of snapping with it. */}
                    {active?.kind !== 'test' && active?.kind !== 'connect' && (
                        <motion.div
                            layout="position"
                            transition={{ duration: 0.2, ease: [0.16, 1, 0.3, 1] }}
                            className="mt-8 flex flex-wrap items-center justify-end gap-3"
                        >
                            {/* The account step portals its Test Connection
                                button here — beside Continue, part of the
                                STEP's actions rather than the form's. */}
                            {active?.kind === 'credentials' && (
                                <span ref={setTestSlot} className="contents" />
                            )}
                            {active?.kind === 'agent' && active.unmet && withoutAccount && (
                                <span className="mr-auto text-[12.5px] leading-relaxed text-foreground/45">
                                    {withoutAccount.note}
                                </span>
                            )}
                            {index > 0 && (
                                <button
                                    onClick={() => go(index - 1)}
                                    className="inline-flex items-center gap-1.5 rounded-lg px-3 py-2.5 text-[13.5px] text-foreground/45 transition-colors hover:text-foreground"
                                >
                                    <ArrowLeft className="h-3.5 w-3.5" /> Back
                                </button>
                            )}
                            {active?.kind === 'agent' && active.unmet && active.node && withoutAccount ? (
                                // An agent without the account it runs on cannot
                                // run a turn at all - the test would fail and read
                                // as the product being broken. Continuing makes
                                // the switch explicit instead of silent.
                                <button
                                    onClick={() => {
                                        const config = (active.node!.data?.config as Record<string, unknown>) ?? {};
                                        onConfigChange(active.node!.id, { ...config, ...withoutAccount.settings(config) });
                                        go(index + 1);
                                    }}
                                    className="rounded-lg bg-primary px-5 py-2.5 text-[14px] font-medium text-primary-foreground transition-opacity hover:opacity-90"
                                >
                                    {withoutAccount.label}
                                </button>
                            ) : (
                                <button
                                    onClick={() => go(index + 1)}
                                    className="rounded-lg bg-primary px-5 py-2.5 text-[14px] font-medium text-primary-foreground transition-opacity hover:opacity-90"
                                >
                                    Continue
                                </button>
                            )}
                        </motion.div>
                    )}

                    {/* Skipped-but-unmet accounts trail below every later
                        step — sits under the content
                        so it never pushes the step down the page. The test
                        finale renders the full list itself. */}
                    {active?.kind !== 'test' && active?.kind !== 'connect' && skippedUnmet.length > 0 && (
                        <motion.div
                            layout="position"
                            transition={{ duration: 0.2, ease: [0.16, 1, 0.3, 1] }}
                        >
                            <ReadinessCard
                                unmet={skippedUnmet}
                                onConnect={(item) =>
                                    setSelectedKey(credentialStepKey(item.nodeId))
                                }
                                className="mt-6"
                            />
                        </motion.div>
                    )}
                </div>
            </div>
        </div>
        </SetupTypesProvider>
    );
}
