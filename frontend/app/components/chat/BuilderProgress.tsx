// The live builder-progress footer at the bottom of an assistant chat bubble
// (replaces the old status line + per-node event cards). A status header whose
// thinking orb depicts the current status (searching / weaving / connecting —
// see orbStateForStatus) next to the "Thinking" pulse text (TextShimmer), over
// a Ledger of the
// workflow's nodes — each with its brand logo (which gains color as the node is
// configured), the field it's currently filling, and a quiet state mark. Nodes
// are clickable (switch to the workflow tab + pan). node drafting runs in parallel,
// so several rows are active at once. Big workflows are capped (active-first)
// with "+N more". Once the turn finishes it collapses to a one-line summary;
// it re-expands if the run resumes (e.g. after an <ask> is answered). A failed
// run shows the error + a Retry instead of vanishing.
import { useEffect, useMemo, useState } from 'react';
import { useSnapshot } from 'valtio';
import { AlertCircle, Check, ChevronDown, ChevronUp } from 'lucide-react';
import TextShimmer from '~/components/forgeui/text-shimmer';
import { cn } from '~/lib/utils';
import { activeGenStore } from '~/lib/activeGenStore';
import { getNodeIconMeta } from '~/lib/nodeIconRegistry';
import { SerializedIcon } from '~/components/shared/SerializedIcon';
import { ThinkingOrb, orbStateForStatus } from '~/components/shared/ThinkingOrb';
import { navigateToNode } from '~/utils/workflowNavigation';
import type { WorkflowEditEvent } from './types';
import { deriveBuilderNodes, type BuilderProgressNode } from './builderProgress/model';
import { InstanceKeyPrompt } from '~/components/credential/InstanceKeyPrompt';

const MAX_ROWS = 6;
const STACK_MAX = 4;

const labelTone = (state: BuilderProgressNode['state']) =>
    state === 'active' ? 'text-foreground' : state === 'done' ? 'text-muted-foreground dark:text-zinc-300' : 'text-muted-foreground/70 dark:text-zinc-500';

// Brand logo. A just-added (queued) node renders GRAYSCALE — the visible "added
// but not configured yet" state — and gains its real color once it starts being
// configured (filling) or is done. This is the gap we want to show: grayscale =
// planned, color = configured. Needs the per-field stream events (below) so the
// filling transition is actually reached.
function NodeGlyph({ type, state, className }: { type?: string; state: BuilderProgressNode['state']; className?: string }) {
    const meta = type ? getNodeIconMeta(type) : undefined;
    const dormant = state === 'queued';
    if (!meta?.iconHtml) return <span className={cn('shrink-0 rounded-sm bg-foreground/10', className ?? 'h-3.5 w-3.5')} aria-hidden />;
    return (
        <SerializedIcon
            html={meta.iconHtml}
            iconColor={meta.iconColor}
            className={cn('shrink-0 transition-all duration-500', className ?? 'h-3.5 w-3.5', dormant ? 'opacity-50 grayscale' : 'opacity-100')}
        />
    );
}

// done = thin check; active = breathe (static when frozen/failed); queued = faint dot.
function StateMark({ state, frozen }: { state: BuilderProgressNode['state']; frozen?: boolean }) {
    if (state === 'done') return <Check className="h-3 w-3 text-muted-foreground" strokeWidth={2.25} aria-hidden />;
    if (state === 'active') {
        return frozen
            ? <span className="h-1 w-1 rounded-full bg-foreground/30" aria-hidden />
            : <span className="h-1 w-1 rounded-full bg-foreground animate-pulse" aria-hidden />;
    }
    return <span className="h-1 w-1 rounded-full bg-foreground/15" aria-hidden />;
}

// In-progress status text pulses via the app's TextShimmer (the same treatment
// as the live "Thinking" label); static once done.
function ActiveText({ text, done, className }: { text: string; done?: boolean; className?: string }) {
    if (done) return <span className={cn('truncate text-muted-foreground', className)}>{text}</span>;
    return <TextShimmer duration={1.6} className={className}>{text}</TextShimmer>;
}

export function BuilderProgress({
    events,
    status,
    genId,
    isComplete,
    workflowId,
    separated = true,
    failed = false,
    error,
    errorCode,
    errorMeta,
}: {
    events: WorkflowEditEvent[];
    status?: string;
    genId?: string;
    isComplete: boolean;
    workflowId?: string;
    /** Show the top hairline separator + footer type-scale. False when this is
     *  the only content in the bubble (bootstrap), where it reads as the message. */
    separated?: boolean;
    failed?: boolean;
    error?: string;
    errorCode?: string;
    errorMeta?: Record<string, string>;
}) {
    const nodes = useMemo(() => deriveBuilderNodes(events).filter((n) => n.state !== 'removed'), [events]);
    const snap = useSnapshot(activeGenStore);
    const [expanded, setExpanded] = useState(true);
    // Sync expansion to run state: expanded while in flight (or failed, so the
    // error stays visible), collapsed once finished. This also RE-EXPANDS when a
    // collapsed turn resumes (isComplete flips back to false — e.g. <ask> answered).
    useEffect(() => {
        setExpanded(!isComplete || failed);
    }, [isComplete, failed]);

    const tokens = genId ? snap.gens[genId]?.tokensProcessed : undefined;
    const hasNodes = nodes.length > 0;
    // A finished, node-less reply (plain chat) shows nothing — unless it failed.
    if (isComplete && !hasNodes && !failed) return null;

    const total = nodes.length;
    const done = nodes.filter((n) => n.state === 'done').length;
    const canNavigate = !!workflowId;
    const showTokens = typeof tokens === 'number' && tokens > 0;
    const headerSize = separated ? 'text-xs' : 'text-sm';
    const rootClass = separated ? 'mt-2 border-t border-foreground/[0.06] pt-2' : '';

    const gen = genId ? snap.gens[genId] : undefined;
    // The one failure the chat can fix in place: a missing server-side key.
    const keyMissing = failed && errorCode === 'provider_key_missing' && !!errorMeta?.env_var;
    const onRetry = () => {
        if (gen?.conversation_id) {
            document.dispatchEvent(new CustomEvent('noclick:builder:retry', {
                detail: { prompt: gen.prompt, conversationId: gen.conversation_id },
            }));
        }
    };

    // Collapsed summary (finished successfully). A quiet, clickable one-liner.
    if (!expanded && hasNodes && !failed) {
        const stack = nodes.slice(0, STACK_MAX);
        const extra = nodes.length - stack.length;
        return (
            <div className={rootClass}>
                <button
                    type="button"
                    onClick={() => setExpanded(true)}
                    className="flex w-full items-center gap-2 text-xs text-muted-foreground/70 dark:text-zinc-500 transition-colors hover:text-muted-foreground dark:hover:text-zinc-300"
                >
                    <Check className="h-3 w-3 shrink-0 text-muted-foreground" strokeWidth={2.25} />
                    <span className="flex items-center gap-1">
                        {stack.map((n) => (
                            <NodeGlyph key={n.nodeId} type={n.type} state="done" className="h-3.5 w-3.5" />
                        ))}
                        {extra > 0 && <span className="text-muted-foreground/70 dark:text-zinc-600">+{extra}</span>}
                    </span>
                    <span className="shrink-0">{total} node{total === 1 ? '' : 's'}</span>
                    <span className="ml-auto flex shrink-0 items-center gap-2 tabular-nums">
                        {showTokens && <span>{tokens.toLocaleString()}</span>}
                        <ChevronDown className="h-3.5 w-3.5 text-muted-foreground/70 dark:text-zinc-600" />
                    </span>
                </button>
            </div>
        );
    }

    // Cap big workflows: active rows first, then the rest, then "+N more".
    let visible = nodes;
    let overflow = 0;
    if (nodes.length > MAX_ROWS) {
        const active = nodes.filter((n) => n.state === 'active');
        const rest = nodes.filter((n) => n.state !== 'active');
        visible = [...active, ...rest].slice(0, MAX_ROWS);
        overflow = nodes.length - visible.length;
    }

    const headerText = isComplete ? `Built ${total} node${total === 1 ? '' : 's'}` : status || 'Working';

    return (
        <div className={rootClass}>
            {failed ? (
                <>
                <div className={cn('flex items-center gap-2', headerSize)}>
                    <AlertCircle className="h-3.5 w-3.5 shrink-0 text-red-600/80 dark:text-red-400/80" strokeWidth={2} />
                    <span className="truncate text-muted-foreground" title={error || undefined}>
                        {keyMissing ? 'The builder needs an API key' : 'Generation failed'}
                    </span>
                    <button
                        type="button"
                        onClick={onRetry}
                        disabled={!gen?.conversation_id}
                        className="ml-auto shrink-0 rounded px-1.5 py-0.5 text-muted-foreground transition-colors hover:bg-foreground/[0.06] hover:text-foreground disabled:opacity-40"
                    >
                        Retry
                    </button>
                </div>
                {keyMissing && (
                    <div className="mt-3">
                        <InstanceKeyPrompt envVar={errorMeta!.env_var} onSaved={onRetry} />
                    </div>
                )}
                </>
            ) : (
                (() => {
                    const collapsible = isComplete && hasNodes;
                    const HeaderTag = collapsible ? 'button' : 'div';
                    return (
                        <HeaderTag
                            {...(collapsible
                                ? { type: 'button' as const, onClick: () => setExpanded(false), 'aria-label': 'Collapse' }
                                : {})}
                            className={cn('flex w-full items-center gap-2 text-left', headerSize, collapsible && 'group')}
                        >
                            {isComplete ? (
                                <Check className="h-3 w-3 shrink-0 text-muted-foreground" strokeWidth={2.25} />
                            ) : (
                                <ThinkingOrb state={orbStateForStatus(headerText)} className="shrink-0" aria-label={headerText} />
                            )}
                            <ActiveText text={headerText} done={isComplete} className={cn('truncate', headerSize)} />
                            <span className="ml-auto flex shrink-0 items-center gap-1.5 tabular-nums text-muted-foreground/70 dark:text-zinc-500">
                                {hasNodes && <span>{done}/{total}</span>}
                                {hasNodes && showTokens && <span className="text-muted-foreground/50 dark:text-zinc-700">·</span>}
                                {showTokens && <span>{tokens.toLocaleString()}</span>}
                                {collapsible && (
                                    <ChevronUp className="h-3.5 w-3.5 text-muted-foreground/70 dark:text-zinc-600 transition-colors group-hover:text-muted-foreground" />
                                )}
                            </span>
                        </HeaderTag>
                    );
                })()
            )}

            {hasNodes && (
                <div className="mt-1.5 flex flex-col gap-1">
                    {visible.map((n) => (
                        <button
                            key={n.nodeId}
                            type="button"
                            onClick={() => { if (workflowId) navigateToNode(workflowId, n.nodeId); }}
                            disabled={!canNavigate}
                            title={canNavigate ? 'Open in workflow' : undefined}
                            className={cn(
                                '-mx-1 flex w-full items-center gap-2 rounded px-1 py-0.5 text-left text-xs transition-colors',
                                canNavigate ? 'cursor-pointer hover:bg-foreground/[0.05]' : 'cursor-default',
                            )}
                        >
                            <NodeGlyph type={n.type} state={n.state} className="h-3.5 w-3.5" />
                            <span className={cn('shrink-0 truncate', labelTone(n.state))}>{n.label}</span>
                            {n.state === 'active' && (
                                <span className="truncate font-mono text-[10px] text-muted-foreground/70 dark:text-zinc-600">
                                    {n.currentField || (n.operation && n.operation !== 'default' ? n.operation : 'configuring')}
                                </span>
                            )}
                            <span className="ml-auto flex shrink-0 items-center"><StateMark state={n.state} frozen={failed} /></span>
                        </button>
                    ))}
                    {overflow > 0 && (
                        <div className="px-1 pt-0.5 text-[11px] text-muted-foreground/70 dark:text-zinc-600">+{overflow} more</div>
                    )}
                </div>
            )}
        </div>
    );
}
