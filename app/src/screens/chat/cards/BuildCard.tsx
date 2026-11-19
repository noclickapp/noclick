// A build of an automation as its card draws it, however it was started: on its automation's canvas, where it stands,
// and the question it waits on under it. An automation's canvas draws on its newest card in the thread (canvases.ts); an
// earlier card about it is one line. "Open canvas" opens it where the host says (`chat.places`).
import type { ReactNode } from 'react';
import { ArrowUpRight } from 'lucide-react';
import { standing } from '@/slots';
import { getNodeIconMeta } from '@/lib/nodeIconRegistry';
import type { SavedGraph } from '@/lib/graphPreview';
import { obj, str, type JsonObject } from '@/lib/toolCalls';
import { PILL_QUIET, PILL_SECONDARY, Receipt } from '@/ui/chat/primitives';
import { AutomationMark } from '@/ui/glyphs';
import { cn } from '@/ui/utils';
import { CHAT_PLACES } from '../slots';
import { AgentPreviewCard, BuildStatus, type BuildPart, type BuildState } from './inline/setup';
import type { WorkflowGraph } from './useBuiltWorkflow';

/** The graph's parts in the order the flow reads: left to right, then top to bottom. */
export function partsOf(blob: SavedGraph | undefined): BuildPart[] {
    return (blob?.nodes ?? [])
        .filter((node) => node.type && !node.type.startsWith('sticky'))
        .sort((a, b) => (a.position?.x ?? 0) - (b.position?.x ?? 0) || (a.position?.y ?? 0) - (b.position?.y ?? 0))
        .map((node) => {
            const type = node.type!;
            const label = typeof node.config?.label === 'string' && node.config.label ? node.config.label : getNodeIconMeta(type)?.label || type;
            return { type, label };
        });
}

export function stateOf(status: string | undefined, live: boolean): BuildState {
    if (status === 'waiting' || status === 'awaiting_human') return 'waiting';
    if (status === 'completed') return 'done';
    if (status === 'failed' || status === 'cancelled') return 'failed';
    // A server that can't read the job back can't say it's still going.
    return live ? 'building' : 'started';
}

/** Where a finished build's app went live: the coordinator's builds say `publication`, the platform API's `published`. */
function publishedUrl(view: JsonObject | undefined): string | undefined {
    const result = obj(view, 'result');
    return str(obj(result, 'publication'), 'url') ?? str(obj(result, 'published'), 'url');
}

/** A build as its card draws it, wherever it was started and however it's read: on its automation's canvas
 *  (`canvas`: this card draws it, else it's one line), how it stands, and the question it waits on under it. */
export function BuildBody({
    workflowId,
    view,
    state,
    graph,
    name: named,
    canvas,
    question,
}: {
    workflowId: string;
    /** The build as its job (or operation) reads, or as the call answered until it's read. */
    view: JsonObject | undefined;
    state: BuildState;
    graph: WorkflowGraph | null;
    /** Its name until the canvas is read. */
    name?: string;
    canvas: boolean;
    question: ReactNode;
}) {
    const name = graph?.name || named || 'Your workflow';
    const error = str(view, 'error');
    if (str(view, 'status') === 'cancelled') return <Receipt tone="info">Stopped building {name}</Receipt>;
    const openWorkflow = () => standing(CHAT_PLACES).openWorkflow(workflowId, name);
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

