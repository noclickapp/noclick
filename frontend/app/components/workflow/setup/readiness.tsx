/**
 * Workflow readiness: what still stands between this workflow and actually
 * running for real. One derivation feeds three surfaces — the Setup tab's
 * finale, the Test Run screen's "make it real" rail, and the agent chat's
 * warning above the composer — so they can never disagree about what's
 * missing. The card design is the bench's SkipWarning: it names what stops
 * working and what the failure will actually look like, never a bare
 * "1 not connected" chip.
 */

import { useEffect, useState } from 'react';
import type { Edge, Node } from '@xyflow/react';
import { AlertTriangle } from 'lucide-react';
import { cn } from '~/lib/utils';
import { sendEventAsync } from '~/lib/socket-sender';
import {
    buildNodeValidationContext,
    validateNode,
} from '~/utils/workflowNodeValidation';
import { isTriggerSource } from '~/utils/nodeSchemas';
import { getNodeDisplayName } from '../nodes/nodeRegistry';

export interface UnmetConnection {
    /** Representative node (the trigger member when the group has one) —
        where Connect jumps; the connection applies to every nodeIds member. */
    nodeId: string;
    nodeType: string;
    label: string;
    role: 'trigger' | 'tool' | 'node';
    /** "Without Gmail, nothing will wake your agent." */
    headline: string;
    /** What the failure actually looks like, in the user's world. */
    body: string;
    /** Every node this connection covers — same-type nodes share a service
        account, so one connect must satisfy all of them (the WhatsApp
        trigger + reply-tools pair asked twice, 2026-08-10). */
    nodeIds: string[];
    /** Trigger items only: this is the agent's ONLY wake path, so "nothing
        will wake your agent" is literally true. With other triggers wired
        (met or not), the claim scopes to this channel instead. */
    soleWakePath?: boolean;
}

interface RawUnmet {
    node: Node;
    label: string;
    role: UnmetConnection['role'];
}

/** Nodes whose missing credentials will break the workflow, with the
    consequence phrased by their ROLE in the graph: a dead trigger means the
    workflow never wakes; a dead tool means the agent plans but cannot act.
    "Trigger" is the real wake predicate (isTriggerSource — trigger-typed
    node or x-is-trigger operation), not just any edge into an agent: a
    dataflow input mislabeled as a trigger claimed "nothing will wake your
    agent" four times over (2026-08-10). */
export function deriveUnmetConnections(
    nodes: Node[],
    edges: Edge[]
): UnmetConnection[] {
    const ctx = buildNodeValidationContext(nodes, edges);
    const agents = new Set(
        nodes.filter((n) => n.type === 'agent').map((n) => n.id)
    );
    const raw: RawUnmet[] = [];
    // A wake path that WORKS: a wired trigger source with no credential gap
    // (cron/webhook/form need none and count immediately). trigger-run is
    // manual by definition — it never wakes anything on its own.
    let metWakeExists = false;
    for (const node of nodes) {
        if (!node.type || node.type === 'sticky-note') continue;
        // The agent's model credential has DEDICATED surfaces (the runtime
        // step, the chat's credential banner) - a generic "this step will
        // fail" card here duplicated the ask in the wrong vocabulary.
        if (node.type === 'agent') continue;
        const data = (node.data ?? {}) as Record<string, any>;
        const operation = (data.operation ?? data.config?.operation) as
            | string
            | undefined;
        const isTool = edges.some(
            (e) =>
                e.source === node.id &&
                agents.has(e.target) &&
                e.targetHandle === 'bottom'
        );
        const isTrigger =
            !isTool &&
            isTriggerSource(node.type, operation) &&
            edges.some(
                (e) =>
                    e.source === node.id &&
                    agents.has(e.target) &&
                    e.targetHandle !== 'bottom'
            );
        const { issues } = validateNode(node, ctx);
        const unmet = issues.some((i) => i.type === 'missing_credentials');
        if (isTrigger && !unmet && node.type !== 'trigger-run') {
            metWakeExists = true;
        }
        if (!unmet) continue;
        raw.push({
            node,
            label: (data.label as string) || getNodeDisplayName(node.type),
            role: isTool ? 'tool' : isTrigger ? 'trigger' : 'node',
        });
    }
    // Same-type nodes need the SAME service account — asking per node reads
    // as two questions where there is one. Merge into a single group, then
    // mint copy per group so the claims see the whole picture.
    const byType = new Map<string, RawUnmet[]>();
    for (const item of raw) {
        const group = byType.get(item.node.type!) ?? [];
        group.push(item);
        byType.set(item.node.type!, group);
    }
    const groups = [...byType.values()];
    const unmetTriggerGroups = groups.filter((g) =>
        g.some((m) => m.role === 'trigger')
    ).length;
    const out: UnmetConnection[] = [];
    for (const group of groups) {
        const trigger = group.find((m) => m.role === 'trigger');
        const hasTool = group.some((m) => m.role === 'tool');
        const rep = trigger ?? group[0];
        const label =
            group.length > 1 ? getNodeDisplayName(rep.node.type!) : rep.label;
        let copy: { headline: string; body: string };
        let soleWakePath: boolean | undefined;
        if (trigger) {
            // "Nothing will wake your agent" is only honest when this is the
            // one and only wake path; otherwise the claim is this channel's.
            soleWakePath = !metWakeExists && unmetTriggerGroups === 1;
            copy = soleWakePath
                ? {
                      headline: `Without ${label}, nothing will wake your agent.`,
                      body: hasTool
                          ? `It will never run on its own — and even when it does run, every ${label} reply will fail. One connection powers both.`
                          : `It will never run on its own. Events can arrive all day and the workflow stays idle — you would have to trigger every run by hand.`,
                  }
                : {
                      headline: `${label} events will never reach your agent.`,
                      body: hasTool
                          ? `They'll arrive and go unanswered — and replies there will fail. One connection powers both.`
                          : `Your agent only hears ${label} through this connection — until then, those events go unanswered.`,
                  };
        } else if (hasTool) {
            copy = {
                headline: `Without ${label}, your agent can't act.`,
                body: `It can read the event and make a plan, but every ${label} call will fail the moment it tries to do the real work.`,
            };
        } else {
            copy =
                group.length > 1
                    ? {
                          headline: `Without ${label}, these steps will fail.`,
                          body: `Runs stop when they reach ${label} — one connection covers all of them.`,
                      }
                    : {
                          headline: `Without ${label}, this step will fail.`,
                          body: `Runs stop when they reach ${label} — connect it so the workflow can pass through.`,
                      };
        }
        out.push({
            nodeId: rep.node.id,
            nodeType: rep.node.type!,
            label,
            role: rep.role,
            nodeIds: group.map((m) => m.node.id),
            soleWakePath,
            ...copy,
        });
    }
    // Triggers first: a workflow that never wakes trumps everything else.
    return out.sort((a, b) =>
        a.role === b.role ? 0 : a.role === 'trigger' ? -1 : b.role === 'trigger' ? 1 : 0
    );
}

/** The saved blob's nodes → the canvas-ish shape validateNode reads (config
    nested under data, credentialIds hoisted top-level on data). */
export function adaptBlobGraph(blob: {
    nodes?: Array<Record<string, any>>;
    edges?: Array<Record<string, any>>;
}): { nodes: Node[]; edges: Edge[] } {
    const nodes = (blob.nodes ?? []).map(
        (n) =>
            ({
                id: n.id,
                type: n.type,
                position: n.position ?? { x: 0, y: 0 },
                data: {
                    label: n.config?.label,
                    operation: n.config?.operation,
                    config: n.config ?? {},
                    credentialIds: n.config?.credentialIds ?? {},
                },
            }) as Node
    );
    return { nodes, edges: (blob.edges ?? []) as Edge[] };
}

/** Fetch-and-derive for surfaces that don't hold the live graph (the Test Run
    screen, the agent chat). `agentNodeId` filters to connections wired to
    THAT agent. Fetches once per mount — those surfaces remount on tab
    switches, which is when connections actually change under them. */
export function useWorkflowReadiness(
    workflowId: string | null,
    agentNodeId?: string
): UnmetConnection[] {
    const [unmet, setUnmet] = useState<UnmetConnection[]>([]);
    useEffect(() => {
        if (!workflowId) return;
        let cancelled = false;
        (async () => {
            try {
                const res: any = await sendEventAsync({
                    event_name: 'workflow:get',
                    workflow_id: workflowId,
                } as any);
                const blob = res?.workflow?.workflow_data ?? res?.workflow?.workflow;
                if (cancelled || !blob) return;
                const { nodes, edges } = adaptBlobGraph(blob);
                let items = deriveUnmetConnections(nodes, edges);
                if (agentNodeId) {
                    const wired = new Set(
                        edges
                            .filter((e) => e.target === agentNodeId)
                            .map((e) => e.source)
                    );
                    items = items.filter((u) => u.nodeIds.some((id) => wired.has(id)));
                }
                setUnmet(items);
            } catch {
                // No readiness signal beats a wrong one.
            }
        })();
        return () => {
            cancelled = true;
        };
    }, [workflowId, agentNodeId]);
    return unmet;
}

/** The bench SkipWarning's card, live: amber, named consequence, one action.
    Past two services the full cards stack taller than the surface they warn
    on (four buried the whole chat, 2026-08-10), so the list collapses into
    ONE card — a summary line plus a connect chip per service. `compact`
    forces the choice for surfaces that can never afford the stack (the chat
    composer banner). */
export function ReadinessCard({
    unmet,
    onConnect,
    className,
    compact,
}: {
    unmet: UnmetConnection[];
    /** Take the user to where the connection happens. */
    onConnect: (item: UnmetConnection) => void;
    className?: string;
    compact?: boolean;
}) {
    if (!unmet.length) return null;
    if (compact ?? unmet.length > 2) {
        const hasSoleWake = unmet.some((u) => u.soleWakePath);
        const hasTrigger = unmet.some((u) => u.role === 'trigger');
        const body = hasSoleWake
            ? 'Nothing will wake your agent, and unconnected steps fail on real runs.'
            : hasTrigger
              ? 'Real runs will miss those events and fail at unconnected steps.'
              : 'Real runs will fail when they reach these steps.';
        return (
            <div
                className={cn(
                    'rounded-xl border border-amber-400/25 bg-amber-400/[0.04] px-4 py-3',
                    className
                )}
            >
                <div className="flex items-start gap-2.5">
                    <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-amber-400" />
                    <div className="min-w-0">
                        <p className="m-0 text-[13px] font-medium text-amber-100/95">
                            Not connected yet:{' '}
                            {unmet.map((u) => u.label).join(', ')}.
                        </p>
                        <p className="m-0 mt-0.5 text-[12.5px] leading-relaxed text-amber-100/55">
                            {body}
                        </p>
                    </div>
                </div>
                <div className="mt-2.5 flex flex-wrap gap-1.5 pl-[26px]">
                    {unmet.map((item) => (
                        <button
                            key={item.nodeId}
                            onClick={() => onConnect(item)}
                            className="rounded-lg border border-amber-400/30 px-2.5 py-1 text-[12.5px] font-medium text-amber-300 transition-colors hover:bg-amber-400/10"
                        >
                            Connect {item.label}
                        </button>
                    ))}
                </div>
            </div>
        );
    }
    return (
        <div
            className={cn(
                'overflow-hidden rounded-xl border border-amber-400/25 bg-amber-400/[0.04]',
                className
            )}
        >
            {unmet.map((item, n) => (
                <div
                    key={item.nodeId}
                    className={cn('px-4 py-3', n > 0 && 'border-t border-amber-400/15')}
                >
                    <AlertTriangle className="mb-1.5 h-4 w-4 text-amber-400" />
                    <p className="m-0 text-[13px] font-medium text-amber-100/95">
                        {item.headline}
                    </p>
                    <p className="m-0 mt-1 text-[12.5px] leading-relaxed text-amber-100/55">
                        {item.body}
                    </p>
                    <button
                        onClick={() => onConnect(item)}
                        className="mt-3 w-full rounded-lg border border-amber-400/30 px-3.5 py-1.5 text-[13px] font-medium text-amber-300 transition-colors hover:bg-amber-400/10"
                    >
                        Connect {item.label}
                    </button>
                </div>
            ))}
        </div>
    );
}
