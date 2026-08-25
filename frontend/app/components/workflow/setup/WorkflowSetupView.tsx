/**
 * WorkflowSetupView — the state-derived setup surface behind the permanent
 * Setup tab, in the GUIDED-RAIL composition designed at /design/onboarding/
 * guided: one step per screen in a centred column (orb header, progress bar,
 * animated phase transitions, Continue/Back footer), with a miniature step
 * rail on the left for orientation and jumping. Steps are DERIVED from the
 * live graph on every render (the same validateNode lens the yellow
 * incomplete pill uses) — no stored wizard state, resumable from any entry,
 * self-healing when a credential dies later. Credential steps render the
 * bench's CredentialPhase, which mounts the REAL NodeCredentials and runs the
 * real credential:test_connection evidence probe. The corridor ends at Test
 * Run — the step no derivation can judge.
 */

import { useEffect, useMemo, useRef, useState } from 'react';
import type { Edge, Node } from '@xyflow/react';
import { AnimatePresence, motion } from 'framer-motion';
import { ArrowLeft, Braces, ChevronDown, FlaskConical, PanelLeftClose, Play } from 'lucide-react';
import { cn } from '~/lib/utils';
import {
    CollapsedNodeRail,
    NodeBadge,
    RAIL_COLLAPSED_WIDTH,
    RailResizeHandle,
    StepKindBadge,
    StepStateDot,
    StepStateMark,
    groupByNode,
    useRailLayout,
    type SetupNodeMeta,
    type SetupStep as RailStep,
} from '~/components/setupviews/shared';
import { useValtioState } from '~/hooks/useValtioState';
import type { WorkflowVariableDefinition } from '~/hooks/useWorkflowVariables';
import { humanizeVariableName } from '~/hooks/useWorkflowVariables';
import {
    buildNodeValidationContext,
    validateNode,
} from '~/utils/workflowNodeValidation';
import { CredentialPhase, Mark } from '~/components/design/onboarding/phases';
import { SetupHeader, StepProgress } from '~/components/design/onboarding/primitives';
import type { CredentialStep } from '~/components/design/onboarding/types';
import { AVAILABLE_NODES, getNodeDisplayName } from '../nodes/nodeRegistry';
import { getNodeSchema } from '~/utils/nodeSchemas';
import { getFieldsForOption } from '~/utils/schemaFieldExtractor';
import { DynamicOptionsField } from '../DynamicOptionsField';
import { NodeConfig } from '../NodeConfig';
import { AgentRuntimePhase, buildModelPatch } from './AgentRuntimePhase';
import { SetupTestRunPreview } from './SetupTestRunPreview';
import { ReadinessCard, deriveUnmetConnections } from './readiness';
import { requestTestRun } from '~/components/design/rehearsal/testRunHandoff';
import { HARNESSES } from '~/data/harness-content';
import { DEFAULT_AGENT_MODEL, LLM_HARNESS, harnessOf } from '~/lib/agentChat';
import {
    agentAllowsUsageBased,
    getAgentCredentialIdForProvider,
    getAgentEffectiveModel,
    getAgentSelectedModel,
    inferProviderFromPrefix,
} from '~/lib/agentCredentialModel';
import type { ModelProvider } from '~/types/provider';
import { useModels } from '~/hooks/useModels';

interface SetupStep {
    key: string;
    kind: 'credentials' | 'config' | 'variable' | 'agent' | 'test';
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

function nodeIcon(type: string | undefined, className = 'h-4 w-4') {
    const def = AVAILABLE_NODES.find((n) => n.type === type);
    if (!def?.Icon) return null;
    const Icon = def.Icon;
    return <Icon className={className} style={{ color: def.iconColor }} />;
}

function prettifyOp(value: string): string {
    const s = value.replace(/_/g, ' ').trim();
    return s.charAt(0).toUpperCase() + s.slice(1);
}

/** A real CredentialStep for the bench's CredentialPhase, derived from the
    live node instead of the captured fixture. Evidence fields stay empty —
    the live probe fills them; the fixture fallbacks were for the bench. */
function toCredentialStep(node: Node, labelOverride?: string): CredentialStep {
    const type = node.type as string;
    const schema = getNodeSchema(type) as { description?: string } | null;
    const allow = ((node.data?.config as Record<string, unknown>)?.agent_tool_operations ??
        []) as unknown[];
    const attached =
        Object.entries(
            (node.data?.credentialIds as Record<string, string>) ?? {}
        ).find(([k, v]) => k !== 'credential_type' && v)?.[1] ?? null;
    return {
        kind: 'credential',
        id: type,
        label: labelOverride || (node.data?.label as string) || getNodeDisplayName(type),
        iconHtml: '',
        iconColor: undefined as unknown as string,
        iconNode: nodeIcon(type, 'h-7 w-7'),
        why:
            schema?.description ??
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
    blur/Enter — settings writes are immediate upstream, so per-keystroke
    persistence would spam workflow:update. */
function VariablePhase({
    definition,
    binding,
    onCommit,
    onOpenCredentials,
}: {
    definition: WorkflowVariableDefinition;
    /** The config field this variable feeds, when one is bound. */
    binding: VariableBinding | null;
    onCommit: (value: string) => void;
    onOpenCredentials?: () => void;
}) {
    const [draft, setDraft] = useState(definition.value ?? '');
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
                        ? nodeIcon(binding.node.type, 'h-7 w-7')
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
                </div>
            ) : (
                <input
                    autoFocus
                    value={draft}
                    onChange={(e) => setDraft(e.target.value)}
                    onBlur={() => onCommit(draft)}
                    onKeyDown={(e) => {
                        if (e.key === 'Enter') onCommit(draft);
                    }}
                    placeholder="Enter a value"
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
function findVariableBinding(nodes: Node[], name: string): VariableBinding | null {
    const ref = `{{vars.${name}}}`;
    for (const node of nodes) {
        if (!node.type) continue;
        const config = (node.data as { config?: Record<string, unknown> } | undefined)?.config;
        if (!config) continue;
        for (const [fieldKey, v] of Object.entries(config)) {
            if (v !== ref) continue;
            const fields = getFieldsForOption(
                node.type,
                undefined,
                (node.data as { operation?: string } | undefined)?.operation
            );
            const field = fields.find((f) => f.key === fieldKey);
            if (field) return { node, fieldKey, prop: field.prop };
        }
    }
    return null;
}

export function WorkflowSetupView({
    nodes,
    edges,
    workflowId,
    onConfigChange,
    onOperationChange,
    onCredentialIdsChange,
    onOpenTestRun,
    variableDefinitions,
    onVariableDefinitionsChange,
}: {
    nodes: Node[];
    edges: Edge[];
    workflowId?: string;
    onConfigChange: (nodeId: string, config: Record<string, any>) => void;
    onOperationChange: (nodeId: string, operation: string) => void;
    onCredentialIdsChange: (nodeId: string, credentialIds: Record<string, string>) => void;
    /** Switch to the interface and open Test Run mode. */
    onOpenTestRun: () => void;
    /** Author-declared variables (settings.variable_definitions). Unfilled
        ones become steps; filling writes through onVariableDefinitionsChange. */
    variableDefinitions?: WorkflowVariableDefinition[];
    onVariableDefinitionsChange?: (definitions: WorkflowVariableDefinition[]) => void;
}) {
    const ctx = useMemo(() => buildNodeValidationContext(nodes, edges), [nodes, edges]);
    const { getModelById } = useModels();
    const agentNode = nodes.find((n) => n.type === 'agent');
    // A combo-page fork ("X with Claude Code") names the harness up front —
    // consume it ONCE into the agent's config so the runtime step lands
    // preselected on that harness instead of asking again.
    useEffect(() => {
        if (!workflowId || !agentNode || typeof window === 'undefined') return;
        const key = `noclick_setup_harness_model:${workflowId}`;
        let model: string | null = null;
        try {
            model = sessionStorage.getItem(key);
            if (model) sessionStorage.removeItem(key);
        } catch {
            return;
        }
        if (!model) return;
        const config = (agentNode.data?.config as Record<string, unknown>) ?? {};
        onConfigChange(agentNode.id, {
            ...config,
            ...buildModelPatch(model, config, getModelById),
        });
        // One-shot on mount; agentNode identity churns per render.
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [workflowId]);

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
            const { issues } = validateNode(node, ctx);
            const label =
                (node.data?.label as string | undefined) || getNodeDisplayName(node.type);
            // The agent's model credential is OWNED by the runtime step
            // ("Which agent runs it") - a generic credential step here asked
            // the same question earlier with the wrong UI (raw provider
            // panel instead of the harness picker).
            const creds =
                node.type === 'agent'
                    ? []
                    : issues.filter((i) => i.type === 'missing_credentials');
            const rest = issues.filter((i) => i.type !== 'missing_credentials');
            if (creds.length || seenRef.current.has(`${node.id}:credentials`)) {
                // Same-type nodes share one service account: merge into the
                // FIRST node's step (title = the service's catalog name) and
                // record every member — the phase writes the credential to
                // all of them. Two WhatsApp asks for one connection read as
                // two questions where there is one (2026-08-10).
                const twin = credentialSteps.find(
                    (s) => s.node?.type === node.type
                );
                if (twin) {
                    twin.groupNodeIds = [...(twin.groupNodeIds ?? [twin.node!.id]), node.id];
                    twin.title = getNodeDisplayName(node.type);
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
                const filled = Boolean((d.value ?? '').trim());
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
        // for another account." Always listed for an agent workflow; unmet is
        // the BYOK cliff: a harness/model that needs the user's own credential
        // with none attached (platform-managed models are ready by default).
        const agentSteps: SetupStep[] = [];
        if (agentNode) {
            const config = (agentNode.data?.config as Record<string, unknown>) ?? {};
            const credIds = (agentNode.data?.credentialIds as Record<string, string>) ?? {};
            const selected = getAgentSelectedModel(undefined, config);
            const effective = getAgentEffectiveModel(undefined, config);
            const provider = (getModelById(effective)?.provider ??
                inferProviderFromPrefix(effective)) as ModelProvider | null;
            const usageBased = agentAllowsUsageBased(selected, provider);
            const unmet = !usageBased && !getAgentCredentialIdForProvider(credIds, provider);
            const slug = harnessOf(selected);
            agentSteps.push({
                key: `${agentNode.id}:runtime`,
                kind: 'agent',
                node: agentNode,
                title: 'Which agent runs it',
                detail: unmet
                    ? 'Connect your account'
                    : slug === LLM_HARNESS
                      ? 'Platform managed'
                      : (HARNESSES[slug]?.displayName ?? slug),
                unmet,
            });
        }
        const finale: SetupStep = {
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
    }, [nodes, ctx, variableDefinitions, agentNode, getModelById]);

    const [selectedKey, setSelectedKey] = useState<string | null>(null);
    // Footer slot the credential phase portals its Test Connection button into.
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
    // straight to the named step. Sticky valtio — this view may mount after
    // the card was clicked.
    const [pendingStep, setPendingStep] = useValtioState<string | null>(
        'workflowSetup',
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
        () => deriveUnmetConnections(nodes, edges),
        [nodes, edges]
    );
    const index = Math.max(
        0,
        steps.findIndex((s) => s.key === (selectedKey ?? steps.find((x) => x.unmet)?.key))
    );
    const active = steps[index] ?? steps[steps.length - 1];
    // The bench SkipWarning's rule, live: once a credential step is SKIPPED
    // (moved past while unmet) its card trails below every later step — the
    // step you are looking at reports its own state inline, so it never
    // warns about itself.
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
        'Your agent';

    // Consumed by AgentChatBlock on the interface tab — sticky state, not a
    // window event, so it survives the tab mounting after we set it.
    const [, setPendingTest] = useValtioState<boolean>(
        'agentChatBlock',
        `open-test-${workflowId ?? 'unknown'}`,
        false
    );
    // Navigate to the interface AND start the rehearsal — same hand-off the
    // builder's <run_test/> uses. A bare call re-runs the last-viewed
    // situation (or the first available); a selection runs that card.
    const runTest = (sel?: { trigger: string; run: string }) => {
        if (workflowId) {
            void requestTestRun(workflowId, sel && { trigger: sel.trigger, run: sel.run });
        } else {
            setPendingTest(true);
        }
        onOpenTestRun();
    };

    const go = (i: number) => setSelectedKey(steps[Math.min(Math.max(i, 0), steps.length - 1)]?.key ?? null);

    // ---- Split Rail (restored setupviews shell) --------------------------
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
                    getNodeDisplayName(s.node.type as string),
                upstream: [],
            };
        }
        if (steps.some((s) => s.kind === 'variable')) {
            map['variables'] = { nodeId: 'variables', nodeType: 'variables', label: 'Variables', upstream: [] };
        }
        map['test-run'] = { nodeId: 'test-run', nodeType: 'test-run', label: 'Test Run', upstream: [] };
        return map;
    }, [steps]);
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
                            : s.kind === 'test'
                              ? 'tool'
                              : 'config',
                title:
                    s.kind === 'test'
                        ? 'Run a staged event'
                        : s.kind === 'variable'
                          ? s.title
                          : s.detail,
                required: true,
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
    // The Test Run finale is a destination, not a debt — it
    // never counts toward progress.
    const countable = railSteps.filter((rs) => rs.nodeId !== 'test-run');
    const doneCount = countable.filter(isFilled).length;

    return (
        <div className="flex min-h-0 flex-1 overflow-hidden bg-background text-foreground">
            {/* LEFT — the Split Rail: collapsible to an icon strip, resizable,
                per-node groups. Same shell the earlier setup view shipped. */}
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
                        // The harness cards are a two-up grid; the narrow
                        // question column squishes them (same widening the
                        // bench applies on its runtime step).
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
                                <CredentialPhase
                                    key={active.node.id}
                                    step={toCredentialStep(active.node, active.title)}
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
                            )}

                            {active?.kind === 'config' && active.node && (
                                <div>
                                    <Mark
                                        iconHtml=""
                                        iconNode={nodeIcon(active.node.type, 'h-7 w-7')}
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
                                    binding={findVariableBinding(nodes, active.variable.name)}
                                    onOpenCredentials={() => {
                                        const b = findVariableBinding(nodes, active.variable!.name);
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
                                <AgentRuntimePhase
                                    key={active.node.id}
                                    node={active.node}
                                    onConfigChange={onConfigChange}
                                    onCredentialIdsChange={onCredentialIdsChange}
                                />
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
                                    {workflowId ? (
                                        <div className="mt-6">
                                            <SetupTestRunPreview
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

                        </motion.div>
                    </AnimatePresence>
                    </div>

                    {/* Stable footer: actions GLIDE to the new step's height
                        (layout animation) instead of snapping with it. */}
                    {active?.kind !== 'test' && (
                        <motion.div
                            layout="position"
                            transition={{ duration: 0.2, ease: [0.16, 1, 0.3, 1] }}
                            className="mt-8 flex flex-wrap items-center justify-end gap-3"
                        >
                            {/* CredentialPhase portals its Test Connection
                                button here — beside Continue, part of the
                                STEP's actions rather than the form's. */}
                            {active?.kind === 'credentials' && (
                                <span ref={setTestSlot} className="contents" />
                            )}
                            {active?.kind === 'agent' && active.unmet && (
                                <span className="mr-auto text-[12.5px] leading-relaxed text-foreground/45">
                                    No account connected for this agent — continuing
                                    switches it to NoClick&rsquo;s platform models.
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
                            {active?.kind === 'agent' && active.unmet && active.node ? (
                                // A CLI harness without its account cannot run
                                // a turn at all - the test would fail and read
                                // as the product being broken. Continuing makes
                                // the switch explicit instead of silent.
                                <button
                                    onClick={() => {
                                        onConfigChange(active.node!.id, {
                                            ...((active.node!.data?.config as Record<string, unknown>) ?? {}),
                                            ...buildModelPatch(
                                                DEFAULT_AGENT_MODEL,
                                                (active.node!.data?.config as Record<string, unknown>) ?? {},
                                                getModelById
                                            ),
                                        });
                                        go(index + 1);
                                    }}
                                    className="rounded-lg bg-primary px-5 py-2.5 text-[14px] font-medium text-primary-foreground transition-opacity hover:opacity-90"
                                >
                                    Continue with platform models
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

                    {/* Skipped-but-unmet credentials trail below every later
                        step (the bench SkipWarning) — sits under the content
                        so it never pushes the step down the page. The test
                        finale renders the full list itself. */}
                    {active?.kind !== 'test' && skippedUnmet.length > 0 && (
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
    );
}
