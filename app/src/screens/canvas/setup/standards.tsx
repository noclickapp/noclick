// What stands in the Setup tab's slots (../slots.ts) when no host fills them, on the platform API alone: the lens
// (each step judged against its type as `GET /v1/step_types/{type}` describes it: its settings' schema, its
// operations and whether one needs an account); an account's proof (`POST /v1/connections/{ref}/verify`); the setup
// check (`GET /v1/workflows/{id}`'s readiness); the staged frame's marks from the catalog the host loaded, if any;
// what the tab remembers, in the page's memory; and asking the Test Run screen for a run. The three parts only a host
// has in full say plainly what they do here: the agent's step shows the model the agent names and connects its AI
// account (`connect.model`); connecting a coding agent, and the cover on the way in, are NoClick's app's.
//
// Function declarations, as everything ../slots.ts reads from here at its declarations: a module that reads its slots
// may be what loads slots.ts while this file hasn't run yet. What's heavy (the SDK, the account pickers) loads when
// it's first used without a host.
import { lazy, Suspense, useCallback, useEffect, useMemo, useState } from 'react';
import type { Edge, Node } from '@xyflow/react';
import type { StepType } from 'noclick';
import { ArrowUpRight } from 'lucide-react';
import { toolOperationsRunWithoutAccount } from '@/lib/accountWays';
import type { ConnectionCheck } from '@/lib/connectionCheck';
import { getNodeIconData } from '@/lib/nodeIconRegistry';
import { useClient } from '@/sdk/client';
import { NOCLICK_SITE, workflowUrl } from '@/screens/console/lib/site';
import { describeRequireOneOfGroup, evaluateRequireOneOf, isFieldEmpty, isFieldRequired } from '../stepFields';
import { fieldsForOption, offersOperationChoice, requireOneOfGroupsOf, schemaInfoOf } from '../stepSchema';
import { readStepType, stepTypeSettled, useStepTypesSettled } from '../slotStandards';
import { rehydrateRehearsalAuthoring } from '../testRun/authoring';
import type { TestRunRequest } from '../testRun/reads';
import { keep } from '../testRun/standards';
import type { Mark as FrameMark } from '../testRun/variants';
import type { McpConnectProps, RuntimePhaseProps, RuntimeStep, SetupLens, SetupReport, SetupReportRead, StepIssue } from './reads';

const external = { target: '_blank', rel: 'noopener noreferrer' } as const;

// ── the lens ────────────────────────────────────────────────────────────────

/** Steps that only pass an event on: a trigger behind one still feeds the agent after it. */
const ROUTING = new Set(['conditional', 'switch']);
const NOTES = new Set(['sticky-note', 'stickyNote']);

/** A type's name where the API gives none: its id, spaced ("automation-google-sheets" → "Google sheets"). */
function spaced(type: string): string {
    const words = type.replace(/^automation-/, '').replace(/[-_]+/g, ' ').trim();
    return words.charAt(0).toUpperCase() + words.slice(1);
}

const dataOf = (node: Node) => (node.data ?? {}) as Record<string, any>;
const operationOf = (node: Node): string | undefined => dataOf(node).operation ?? undefined;

function startsRuns(known: StepType | undefined, operation: string | undefined): boolean {
    if (!known) return false;
    return known.trigger || (!!operation && known.operations.some((op) => op.name === operation && op.trigger));
}

/** What a read held back of a step's settings (a secret) stands as set: the stored step holds it. */
function withWithheld(config: Record<string, unknown>, withheld: unknown): Record<string, unknown> {
    if (!Array.isArray(withheld) || withheld.length === 0) return config;
    const judged = { ...config };
    for (const path of withheld) {
        if (typeof path === 'string' && /^[\w-]+$/.test(path) && isFieldEmpty(judged[path])) judged[path] = '[withheld]';
    }
    return judged;
}

/** Whether the step still needs an account: its type takes one, what it does needs it, and it holds none. A tool
 *  wired to an agent is judged by the operations it allows. The agent's own account is its step's question. */
function needsAccount(known: StepType, node: Node, wired: boolean): boolean {
    if (node.type === 'agent' || !known.connection) return false;
    const data = dataOf(node);
    const attached = Object.values((data.credentialIds ?? {}) as Record<string, string>).some((id) => id && id.trim() !== '');
    if (attached) return false;
    if (wired) {
        if (toolOperationsRunWithoutAccount(known.schema, data)) return false;
        const allowed = Array.isArray(data.config?.agent_tool_operations) ? (data.config.agent_tool_operations as unknown[]) : [];
        const names = allowed.map((op) => (typeof op === 'string' ? op : (op as { operation?: string } | null)?.operation));
        const listed = known.operations.filter((op) => names.includes(op.name));
        return listed.length ? listed.some((op) => op.needsAccount) : known.connection.needed;
    }
    const operation = operationOf(node);
    const found = operation ? known.operations.find((op) => op.name === operation) : undefined;
    return found ? found.needsAccount : known.connection.needed;
}

function issuesOn(node: Node, known: StepType | undefined, wired: boolean, fed: boolean): StepIssue[] {
    if (!node.type || !known) return [];
    const issues: StepIssue[] = [];
    const data = dataOf(node);
    const config = (data.config ?? {}) as Record<string, unknown>;

    // A tool wired into an agent offers the operations it allows instead of running one: it needs at least one, and
    // an account only if one of them does.
    if (wired) {
        if (needsAccount(known, node, true)) issues.push({ type: 'missing_credentials', message: 'Credentials required' });
        const ops = config.agent_tool_operations;
        if (!Array.isArray(ops) || ops.length === 0) {
            issues.push({ type: 'missing_required_field', message: 'Select at least one action to expose to the agent', fieldKey: 'agent_tool_operations' });
        }
        return issues;
    }

    if (needsAccount(known, node, false)) issues.push({ type: 'missing_credentials', message: 'Credentials required' });

    const operation = operationOf(node);
    // A trigger that's registered but can't hear (the app isn't in the channel) is as unfinished as a blank field.
    const triggerError = typeof config.trigger_error === 'string' ? config.trigger_error.trim() : '';
    if (triggerError && issues.length === 0 && startsRuns(known, operation)) issues.push({ type: 'trigger_not_receiving', message: triggerError });

    const info = schemaInfoOf(known.schema);
    if (!info) return issues;
    const discriminator = info.discriminator.fieldName;
    // Which settings the step needs depends on what it does: with nothing chosen, that's the whole answer.
    if (!operation && offersOperationChoice(info)) {
        issues.push({ type: 'missing_operation', message: 'Choose an action', fieldKey: discriminator ?? undefined });
        return issues;
    }

    const fields = fieldsForOption(info, undefined, operation);
    const judged = withWithheld(config, data.withheld);
    for (const field of fields) {
        if (!isFieldRequired(field, discriminator) || !isFieldEmpty(judged[field.key])) continue;
        issues.push({ type: 'missing_required_field', message: `${field.prop.title || field.key} is required`, fieldKey: field.key });
    }
    // An agent's message is required unless a trigger feeds it (the event is then its turn) or each turn brings one.
    if (node.type === 'agent' && isFieldEmpty(config.message) && config.message_per_turn !== true && !fed) {
        issues.push({ type: 'missing_required_field', message: 'Message is required', fieldKey: 'message' });
    }
    const groups = requireOneOfGroupsOf(info, undefined, operation);
    if (groups.length > 0) {
        const titleOf = (key: string) => fields.find((f) => f.key === key)?.prop.title || key;
        for (const group of evaluateRequireOneOf(groups, judged).unsatisfiedGroups) {
            issues.push({ type: 'missing_required_field', message: `Provide ${describeRequireOneOfGroup(group, titleOf)}`, fieldKey: group[0]?.[0] });
        }
    }
    return issues;
}

/** The lens over the workflow as the canvas holds it, each step judged against its type as the API describes it;
 *  it's ready once every type of the workflow's has been read (or couldn't be: such a step is asked nothing). */
export function useV1Lens(nodes: Node[], edges: Edge[]): SetupLens {
    const client = useClient();
    // A new reading each time another type lands.
    const settled = useStepTypesSettled(client);
    return useMemo<SetupLens>(() => {
        const read = (type: string | null | undefined) => (type && !NOTES.has(type) ? readStepType(client, type) : undefined);
        const types = [...new Set(nodes.map((n) => n.type).filter((t): t is string => Boolean(t) && !NOTES.has(t as string)))];
        for (const type of types) read(type);
        const byId = new Map(nodes.map((n) => [n.id, n]));
        const hosts = new Set(nodes.filter((n) => n.type === 'agent' || n.type === 'mcp-server').map((n) => n.id));
        const wired = new Set<string>();
        for (const edge of edges) {
            const source = byId.get(edge.source);
            if (edge.targetHandle === 'bottom' && source && hosts.has(edge.target) && read(source.type)?.kinds.includes('tool')) wired.add(source.id);
        }
        const fedBy = (agentId: string): boolean => {
            const seen = new Set([agentId]);
            const frontier = [agentId];
            while (frontier.length) {
                const target = frontier.pop()!;
                for (const edge of edges) {
                    if (edge.target !== target || (target === agentId && edge.targetHandle === 'bottom')) continue;
                    const source = byId.get(edge.source);
                    if (!source?.type || seen.has(source.id)) continue;
                    seen.add(source.id);
                    if (ROUTING.has(source.type)) frontier.push(source.id);
                    else if (startsRuns(read(source.type), operationOf(source))) return true;
                }
            }
            return false;
        };
        return {
            ready: types.every((type) => stepTypeSettled(client, type)),
            issuesOf: (node) => issuesOn(node, read(node.type), wired.has(node.id), node.type === 'agent' && fedBy(node.id)),
            typeOf: (type) => {
                const known = read(type);
                return { label: known?.label ?? spaced(type), description: known?.description ?? undefined };
            },
            fieldOf: (node, fieldKey) => {
                const info = schemaInfoOf(read(node.type)?.schema);
                return (fieldsForOption(info, undefined, operationOf(node)).find((field) => field.key === fieldKey)?.prop as Record<string, any> | undefined) ?? null;
            },
            isTriggerSource: (type, operation) => startsRuns(read(type), operation),
        };
        // `settled` is read for what it says of time: the types read so far.
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [client, settled, nodes, edges]);
}

// ── an account's proof ──────────────────────────────────────────────────────

/** Asks the provider about the account a step holds, through the connection that holds it. */
export function useV1Probe(): (stepType: string, credentialId: string) => Promise<ConnectionCheck | null> {
    const client = useClient();
    return useCallback(
        async (_stepType: string, credentialId: string) => {
            const [{ Connection }, { checkOf }] = await Promise.all([import('../standardsSdk'), import('@/ui/connectStandards')]);
            const holding = (await Connection.list({ client })).find((connection) => connection.credentialId === credentialId);
            return holding ? checkOf(await holding.verify()) : null;
        },
        [client]
    );
}

// ── the setup check ─────────────────────────────────────────────────────────

/** The workflow's readiness as the API reads it: what it means, what's in the way, then what isn't in the way and
 *  what no run has shown to work yet. */
export function useV1Report(workflowId: string): { read: SetupReportRead; refresh: () => void } {
    const client = useClient();
    const [read, setRead] = useState<SetupReportRead>({ status: 'loading' });
    const [revision, setRevision] = useState(0);
    const refresh = useCallback(() => setRevision((value) => value + 1), []);
    useEffect(() => {
        let cancelled = false;
        setRead({ status: 'loading' });
        void (async () => {
            try {
                const { Workflow } = await import('../standardsSdk');
                const readiness = (await Workflow.get(workflowId, { client })).readiness;
                const report: SetupReport = {
                    title: readiness.meaning || readiness.status,
                    issues: readiness.issues.map((issue) => issue.message),
                    notes: [...readiness.warnings, ...readiness.unverified].map((line) => line.message),
                };
                if (!cancelled) setRead({ status: 'ready', report });
            } catch (cause) {
                if (!cancelled) setRead({ status: 'failed', message: cause instanceof Error ? cause.message : 'Could not verify setup.' });
            }
        })();
        return () => {
            cancelled = true;
        };
    }, [workflowId, revision, client]);
    return { read, refresh };
}

// ── the staged frame's marks, the tab's memory, asking for a run ────────────

/** Each app's mark from the catalog the host loaded (none loaded: the frames draw without them), by the name its
 *  tools carry (`automation-slack` → `slack`). */
export function useCatalogIcons(): Record<string, FrameMark> {
    return useMemo(() => {
        const icons: Record<string, FrameMark> = {};
        for (const [type, meta] of Object.entries(getNodeIconData())) {
            if (!meta.iconHtml) continue;
            icons[type.replace(/^automation-/, '').replace(/-/g, '_')] = { iconHtml: meta.iconHtml, iconColor: meta.iconColor };
        }
        return icons;
    }, []);
}

/** Asks the Test Run screen to start a run once it draws: the workflow's own test runs are read again first (the one
 *  named may have just been added), then the ask is kept where the screen looks for it. */
export async function askHereForTestRun(workflowId: string | undefined, request?: TestRunRequest): Promise<void> {
    if (!workflowId) return;
    try {
        await rehydrateRehearsalAuthoring(workflowId);
    } catch {
        // The screen then starts the first run it's offered.
    }
    keep(`autorun-${workflowId}`, { trigger: request?.trigger, run: request?.run });
}

/** Beside the name of what's being set up: a quiet ring. */
export function QuietOrb() {
    return <span aria-hidden className="inline-block h-[34px] w-[34px] shrink-0 rounded-full border-2 border-foreground/15 bg-foreground/[0.04]" />;
}

// ── which agent runs it ─────────────────────────────────────────────────────

/** The model an agent step names. */
function modelOf(node: Node | undefined): string {
    const model = dataOf(node ?? ({ data: {} } as Node)).config?.model;
    return typeof model === 'string' ? model : '';
}

/** How the agent's step stands, as far as the API says: the model it names. Whether that model runs on NoClick's key
 *  or needs an AI account of the person's own is NoClick's to know, so the step is never held unmet here: the setup
 *  check (the workflow's readiness) names an agent whose account is missing. */
export function useV1RuntimeStep(_workflowId: string | undefined, node: Node | undefined): RuntimeStep {
    // The API names no model to fall back on, so the step just goes on.
    return { unmet: false, detail: modelOf(node) || 'No model chosen', withoutAccount: null };
}

const AccountPickers = lazy(() => import('./RuntimeAccounts'));

/** The agent's step without a host: the model the agent names, and the AI account it runs on, connected through
 *  `connect.model`. Choosing among NoClick's models and coding agents, with what each needs, is NoClick's app's. */
export function RuntimeOnApi({ node, onCredentialIdsChange }: RuntimePhaseProps) {
    const model = modelOf(node);
    return (
        <div>
            <h2 className="mb-0 font-sans text-[22px] font-semibold tracking-[-0.02em]">Which agent runs it</h2>
            <p className="mb-0 mt-2 text-[14px] leading-relaxed text-foreground/45">
                {model ? (
                    <>
                        This workflow’s agent runs on <span className="font-medium text-foreground/85">{model}</span>. Change the model in the agent step’s settings.
                    </>
                ) : (
                    'This workflow’s agent names no model yet. Choose one in the agent step’s settings.'
                )}
            </p>
            <div className="mt-5">
                <Suspense fallback={null}>
                    <AccountPickers node={node} onCredentialIdsChange={onCredentialIdsChange} />
                </Suspense>
            </div>
            <p className="mb-0 mt-5 text-[12.5px] leading-relaxed text-foreground/45">
                Choosing among NoClick’s own models and coding agents (Claude Code, Codex and the rest), with the plan or key each takes, is in{' '}
                <a href={`${NOCLICK_SITE}/dashboard`} {...external} className="underline decoration-foreground/25 underline-offset-2 hover:decoration-foreground/70">
                    NoClick’s app
                </a>
                .
            </p>
        </div>
    );
}

// ── connecting a coding agent ───────────────────────────────────────────────

/** Where a workflow serves its tools to a coding agent, its last step connects one. The link such an agent adds is a
 *  capability (whoever holds it calls the tools), which the API hands to no app's key, so this app doesn't show it:
 *  it says so, and opens the workflow in NoClick's app, where the link and each agent's steps are. */
export function McpConnectOnNoClick({ workflowId, nodeLabel }: McpConnectProps) {
    return (
        <div className="space-y-4">
            <h2 className="mb-0 font-sans text-[22px] font-semibold tracking-[-0.02em]">Connect your coding agent</h2>
            <p className="m-0 text-[14px] leading-relaxed text-foreground/55">
                {nodeLabel || 'This workflow'} serves its tools to a coding agent (Claude Code, Codex, Cursor and others) over a link of its own. Whoever holds that link can call the tools, so it’s shown only
                in NoClick’s app, signed in as the workflow’s owner, with the steps for each agent and whether yours has connected.
            </p>
            <a href={workflowUrl(NOCLICK_SITE, workflowId)} {...external} className="inline-flex items-center gap-1.5 rounded-lg bg-primary px-4 py-2 text-[13px] font-medium text-primary-foreground transition-opacity hover:opacity-90">
                Connect it on NoClick
                <ArrowUpRight className="h-3.5 w-3.5" />
            </a>
        </div>
    );
}

// ── the cover on the way in ─────────────────────────────────────────────────

/** This app opens a workflow's Setup in place, on a workflow it already holds: nothing is copied on the way, so
 *  nothing covers the page. */
export function NoCover() {
    return null;
}
