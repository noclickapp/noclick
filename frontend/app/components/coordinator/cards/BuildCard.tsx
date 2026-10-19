// A build the coordinator handed to the builder (request_build): the workflow drawn as the builder adds to it, where
// the job is (from coordinator:jobs), and, when the builder stops to ask something, its question answered right here,
// on a card of its own, with the builder's own form. An automation's canvas draws on its newest card in
// the thread (canvases.ts); an earlier card about it is one line.
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { ArrowUpRight } from 'lucide-react';
import { AskAnswer } from '~/components/dashboard/AskAnswer';
import { DashboardActionsContext, type DashboardActions } from '~/components/dashboard/primitives';
import type { AttentionItem } from '~/components/dashboard/types';
import { useDrawsCanvas } from '~/components/coordinator/canvases';
import { AgentPreviewCard, BuildStatus, type BuildPart, type BuildState } from '~/components/coordinator/inline/setup';
import { CARD, PILL_QUIET, PILL_SECONDARY, Receipt } from '~/components/coordinator/inline/primitives';
import { AutomationMark } from '~/components/shell/glyphs';
import { useAttentionActions } from '~/hooks/useAttentionActions';
import { isActiveJob, useCoordinatorJob } from '~/hooks/useCoordinatorJobs';
import { useWorkflowGraph } from '~/hooks/useWorkflowGraph';
import { obj, str, type CoordinatorToolCall, type JsonObject } from '~/lib/coordinatorToolCalls';
import { navigateToWorkflow } from '~/lib/navigation';
import { getNodeIconMeta } from '~/lib/nodeIconRegistry';
import { socketCall } from '~/lib/socketCall';
import { cn } from '~/lib/utils';
import type { ScaffoldBlob } from '~/lib/agentScaffold';

const QUESTION_POLL_MS = 5000;
const noop = () => {};

/** The graph's parts in the order the flow reads: left to right, then top to bottom. */
export function partsOf(blob: ScaffoldBlob | undefined): BuildPart[] {
    return (blob?.nodes ?? [])
        .filter((node) => node.type && !node.type.startsWith('sticky'))
        .sort((a, b) => (a.position?.x ?? 0) - (b.position?.x ?? 0) || (a.position?.y ?? 0) - (b.position?.y ?? 0))
        .map((node) => {
            const type = node.type!;
            const label = typeof node.config?.label === 'string' && node.config.label ? node.config.label : getNodeIconMeta(type)?.label || type;
            return { type, label };
        });
}

function stateOf(status: string | undefined, live: boolean): BuildState {
    if (status === 'waiting' || status === 'awaiting_human') return 'waiting';
    if (status === 'completed') return 'done';
    if (status === 'failed' || status === 'cancelled') return 'failed';
    // A server that can't read the job back can't say it's still going.
    return live ? 'building' : 'started';
}

interface PendingAsk {
    ask_id: string;
    title?: string;
    inputs?: unknown[];
}

/** The builder's parked question on this build's conversation, or, where the build names only its question, that
 *  question (and the conversation it parked); re-read while the build may be asking. Once found, the build is read by
 *  its conversation: the question the job names lags a builder that has since asked another. */
function useBuildQuestion(conversationId: string | undefined, askId: string | undefined, workflowId: string | undefined, follow: boolean) {
    const [asked, setAsked] = useState<{ ask: PendingAsk; conversationId: string } | null>(null);
    const [version, setVersion] = useState(0);
    const found = useRef(conversationId);
    const reread = useCallback(() => setVersion((v) => v + 1), []);
    useEffect(() => {
        if (!(conversationId || askId) || !workflowId) return;
        let cancelled = false;
        const read = async () => {
            try {
                const data = await socketCall('workflow:builder:list_pending', { workflow_id: workflowId });
                const runs = (data.runs ?? []) as { conversation_id: string; pending_ask?: PendingAsk | null }[];
                const known = conversationId ?? found.current;
                const run = runs.find((r) => (known ? r.conversation_id === known : r.pending_ask?.ask_id === askId));
                if (run) found.current = run.conversation_id;
                if (!cancelled) setAsked(run?.pending_ask ? { ask: run.pending_ask, conversationId: run.conversation_id } : null);
            } catch (error) {
                console.warn('[coordinator] reading the build question failed:', error);
            }
        };
        void read();
        window.addEventListener('focus', read);
        const timer = follow ? window.setInterval(() => void read(), QUESTION_POLL_MS) : undefined;
        return () => {
            cancelled = true;
            window.removeEventListener('focus', read);
            window.clearInterval(timer);
        };
    }, [conversationId, askId, workflowId, follow, version]);
    return { asked, reread };
}

function BuildQuestion({
    ask,
    conversationId,
    workflowId,
    onSending,
    onAnswered,
}: {
    ask: PendingAsk;
    conversationId: string;
    workflowId: string;
    /** The question sent (its id), or back on the card when the builder refused it (null). */
    onSending: (askId: string | null) => void;
    onAnswered: () => void;
}) {
    const refresh = useCallback(async () => onAnswered(), [onAnswered]);
    const attention = useAttentionActions(refresh);
    const actions = useMemo<DashboardActions>(() => {
        const sending =
            <A extends unknown[]>(send: (...args: A) => Promise<boolean>) =>
            (...args: A) => {
                onSending(ask.ask_id);
                void send(...args).then((taken) => taken || onSending(null));
            };
        return {
            dismissed: new Set(),
            openRun: noop,
            openConversation: noop,
            markNotificationsRead: noop,
            openNotification: noop,
            openPreferences: noop,
            ...attention,
            answerAsk: sending(attention.answerAsk),
            dismissAsk: sending(attention.dismissAsk),
        };
    }, [attention, ask.ask_id, onSending]);
    const item: AttentionItem = {
        id: `ask:${conversationId}`,
        kind: 'builder_ask',
        title: ask.title || 'The builder has a question',
        workflow: null,
        createdAt: new Date().toISOString(),
        inputs: ask.inputs ?? [],
        meta: { conversationId, askId: ask.ask_id, workflowId },
    };
    return (
        <DashboardActionsContext.Provider value={actions}>
            {/* A card of its own under the build, as the chat's connect card is. */}
            <section className={cn(CARD, 'mt-3 px-4 py-3.5')} data-testid="coordinator-build-question">
                <AskAnswer item={item} />
            </section>
        </DashboardActionsContext.Provider>
    );
}

/** One build of an automation, however it was started. */
export interface WorkflowBuildProps {
    /** The tool call whose card this is. */
    callId: string;
    workflowId: string;
    /** The job (or operation) following the build, read back through the thread's jobs. */
    jobId?: string;
    /** The builder conversation its question parks on; without it, the question is the one the job names. */
    conversationId?: string;
    /** How the build stood when the call answered, until the job is read. */
    reported?: JsonObject;
    /** Its name until the canvas is read. */
    name?: string;
    /** Read its canvas again while it may still change with no job to say so (an agent just made: its triggers land
     *  in the calls after the one that made it). */
    follow?: boolean;
}

/** Where a finished build's app went live: the coordinator's builds say `publication`, the platform API's `published`. */
function publishedUrl(view: JsonObject | undefined): string | undefined {
    const result = obj(view, 'result');
    return str(obj(result, 'publication'), 'url') ?? str(obj(result, 'published'), 'url');
}

export function WorkflowBuild({ callId, workflowId, jobId, conversationId, reported, name: named, follow = false }: WorkflowBuildProps) {
    const { live, job } = useCoordinatorJob(jobId);
    const view: JsonObject | undefined = job ?? reported;
    // A question just answered gives way to the build going on with it, until the builder asks something else.
    const [sent, setSent] = useState<string | null>(null);
    // Followed only while the ledger still has it.
    const reportedState = stateOf(str(view, 'status'), live && !!job);
    const active = isActiveJob(job);
    const canvas = useDrawsCanvas(callId, workflowId);
    const { graph } = useWorkflowGraph(workflowId, active || (follow && canvas));
    const { asked, reread } = useBuildQuestion(conversationId, str(obj(view, 'question'), 'id'), workflowId, active || reportedState === 'waiting' || !!sent);
    const asking = asked && asked.ask.ask_id !== sent ? asked : null;
    const state: BuildState = reportedState === 'waiting' && sent && !asking ? 'building' : reportedState;

    const name = graph?.name || named || 'Your workflow';
    const error = str(view, 'error');
    if (str(view, 'status') === 'cancelled') return <Receipt tone="info">Stopped building {name}</Receipt>;
    const openWorkflow = () => navigateToWorkflow({ id: workflowId, name });
    const question = asking && (
        <BuildQuestion key={asking.ask.ask_id} ask={asking.ask} conversationId={asking.conversationId} workflowId={workflowId} onSending={setSent} onAnswered={reread} />
    );
    if (!canvas) {
        return (
            <div data-testid="coordinator-build-card" data-folded="">
                <Receipt
                    tone="info"
                    lead={<AutomationMark className="h-4 w-4 shrink-0" />}
                    action={
                        <>
                            <BuildStatus state={state} />
                            <button type="button" className={cn(PILL_QUIET, 'h-7')} onClick={openWorkflow}>
                                Open canvas
                                <ArrowUpRight className="h-3.5 w-3.5" />
                            </button>
                        </>
                    }
                >
                    {name}
                </Receipt>
                {question}
            </div>
        );
    }
    const published = publishedUrl(view);
    const meta =
        state === 'failed'
            ? error || 'The builder stopped before finishing.'
            : state === 'started'
              ? 'Building now. NoClick says here when it’s done.'
              : state === 'waiting'
                ? 'Waiting for your answer below.'
                : undefined;
    return (
        <div data-testid="coordinator-build-card">
            <AgentPreviewCard
                blob={graph?.blob}
                name={name}
                meta={meta}
                state={state}
                parts={partsOf(graph?.blob)}
                onOpen={openWorkflow}
                actions={
                    published && (
                        <a href={published} target="_blank" rel="noopener noreferrer" className={PILL_SECONDARY}>
                            Open app
                            <ArrowUpRight className="h-3.5 w-3.5" />
                        </a>
                    )
                }
            />
            {question}
        </div>
    );
}

export function BuildCard({ call }: { call: CoordinatorToolCall }) {
    const workflowId = str(call.result, 'workflow_id');
    if (!workflowId) return null;
    return (
        <WorkflowBuild
            callId={call.id}
            workflowId={workflowId}
            jobId={str(call.result, 'job_id')}
            conversationId={str(call.result, 'builder_conversation_id')}
            reported={call.result}
            name={str(call.args, 'name')}
        />
    );
}
