// Post-run results modal: opens when a manual workflow run finishes. The left
// rail navigates the nodes that ran (the AI agent first); the main panel shows
// the selected node's output, and for the agent its final response plus the tool
// calls it made. Each node has a "Configure" shortcut that opens its config
// panel (same as the trigger-info popup). Mounted only while open so closing
// fully unmounts it (reduced-motion-safe — see TriggerInfoDialog).
import { useState, useEffect } from 'react';
import { Settings2, CheckCircle2, XCircle, MinusCircle, Bot, Loader2, Inbox } from 'lucide-react';
import { Dialog, DialogContent, DialogTitle } from '~/components/ui/dialog';
import { SerializedIcon } from '~/components/shared/SerializedIcon';
import { IODataDisplay } from './IODataDisplay';
import { MarkdownRenderer } from '~/components/chat/MarkdownRenderer';
import { ReplayToolCallsPanel, type ReplayToolCall } from './ReplayToolCallsPanel';
import { ErrorActionButton, type ErrorAction } from './ErrorActionButton';
import { RunPicker } from './RunPicker';
import { agentOutputMedia } from '~/lib/agentOutputMedia';
import type { WorkflowExecutionLog } from './WorkflowExecutionLogs';

export interface NodeRunResult {
    nodeId: string;
    nodeType: string;
    /** Display name — user label, else the node type's label. */
    label: string;
    iconHtml?: string;
    iconColor?: string;
    status: 'completed' | 'error' | 'skipped';
    output: unknown;
    error?: string;
    /** The fix for this failure, when the backend could name one — same payload
     *  the config panel's error banner renders. */
    errorAction?: ErrorAction;
    isAgent: boolean;
    /** Tool calls the agent made (empty for non-agent nodes). */
    toolCalls: ReplayToolCall[];
}

interface RunResultsDialogProps {
    results: NodeRunResult[];
    onClose: () => void;
    /** Open a node's config panel (expanded), like the trigger-info popup. */
    onOpenConfig: (nodeId: string) => void;
    /** Stop auto-showing this popup after future runs (re-enable in Settings). */
    onDontShowAgain: () => void;
    /** Loaded runs (newest first) for the in-popup run-switcher. */
    runs: WorkflowExecutionLog[];
    /** Execution whose results are currently shown. */
    currentExecId: string | null;
    /** True while a switched run's results are loading. */
    loading: boolean;
    /** Whether more runs can be paged into the switcher. */
    hasMore: boolean;
    /** True while the switcher's next page of runs is loading. */
    loadingMore: boolean;
    /** Page in more runs for the switcher (scroll-near-bottom). */
    onLoadMore: () => void;
    /** Load a different run's results into this popup. */
    onSelectRun: (log: WorkflowExecutionLog) => void;
}

function StatusIcon({ status }: { status: NodeRunResult['status'] }) {
    if (status === 'error') return <XCircle className="h-4 w-4 shrink-0 text-red-600 dark:text-red-400" />;
    if (status === 'skipped') return <MinusCircle className="h-4 w-4 shrink-0 text-muted-foreground/70 dark:text-zinc-500" />;
    return <CheckCircle2 className="h-4 w-4 shrink-0 text-emerald-600 dark:text-emerald-400" />;
}

function NodeIcon({ result, className }: { result: NodeRunResult; className: string }) {
    if (result.iconHtml) {
        return <SerializedIcon html={result.iconHtml} iconColor={result.iconColor} className={className} />;
    }
    return <Bot className={`${className} text-muted-foreground`} />;
}

export function RunResultsDialog({
    results, onClose, onOpenConfig, onDontShowAgain,
    runs, currentExecId, loading, hasMore, loadingMore, onLoadMore, onSelectRun,
}: RunResultsDialogProps) {
    const [selectedId, setSelectedId] = useState<string>(results[0]?.nodeId ?? '');
    useEffect(() => {
        if (!results.some(r => r.nodeId === selectedId) && results[0]) setSelectedId(results[0].nodeId);
    }, [results, selectedId]);

    const selected = results.find(r => r.nodeId === selectedId) ?? results[0];
    const agentResponse = selected?.isAgent && selected.output && typeof selected.output === 'object'
        ? (selected.output as Record<string, unknown>).response
        : undefined;
    const hasOutput = selected?.output !== undefined && selected?.output !== null;
    // Generated media (image/video/kling models) on the selected agent node.
    // Without this, an image-only run (e.g. DALL-E, whose `response` is empty)
    // renders nothing but an empty response box.
    const media = selected?.isAgent ? agentOutputMedia(selected.output) : { images: [], videos: [] };
    const hasResponseText = typeof agentResponse === 'string' && agentResponse.trim().length > 0;
    const hasResponseData = agentResponse !== undefined && typeof agentResponse !== 'string';
    const hasMedia = media.images.length > 0 || media.videos.length > 0;
    return (
        <Dialog open onOpenChange={(o) => { if (!o) onClose(); }}>
            <DialogContent className="flex h-[80vh] max-h-[80vh] w-[92vw] max-w-4xl flex-col gap-0 overflow-hidden border-foreground/10 p-0">
                {/* Header — title + run-switcher (load older runs) */}
                <div className="shrink-0 border-b border-foreground/[0.06] px-5 py-4 pr-12">
                    <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
                        <DialogTitle className="text-lg font-semibold tracking-tight text-foreground">
                            Run results
                        </DialogTitle>
                        <RunPicker
                            runs={runs}
                            currentExecId={currentExecId}
                            loading={loading}
                            hasMore={hasMore}
                            loadingMore={loadingMore}
                            onLoadMore={onLoadMore}
                            onSelectRun={onSelectRun}
                        />
                    </div>
                    <p className="mt-1.5 text-[13px] text-muted-foreground/70 dark:text-zinc-500">
                        {loading ? 'Loading run…' : `${results.length} node${results.length === 1 ? '' : 's'} ran`}
                    </p>
                </div>

                {loading ? (
                    <div className="flex min-h-0 flex-1 items-center justify-center text-muted-foreground/70 dark:text-zinc-500">
                        <Loader2 className="h-5 w-5 animate-spin" />
                    </div>
                ) : results.length === 0 ? (
                    <div className="flex min-h-0 flex-1 flex-col items-center justify-center gap-3 px-6 text-center">
                        <Inbox className="h-9 w-9 text-muted-foreground/60 dark:text-zinc-600" />
                        <p className="text-[13px] text-muted-foreground/70 dark:text-zinc-500">No node outputs were retained for this run.</p>
                    </div>
                ) : (
                <div className="flex min-h-0 flex-1">
                    {/* Left rail — node navigation */}
                    <div className="w-56 shrink-0 overflow-y-auto scrollbar-subtle border-r border-foreground/[0.06] p-2">
                        {results.map(r => (
                            <button
                                key={r.nodeId}
                                type="button"
                                onClick={() => setSelectedId(r.nodeId)}
                                className={`flex w-full items-center gap-2.5 rounded-lg px-2.5 py-2 text-left transition-colors ${
                                    r.nodeId === selectedId ? 'bg-foreground/[0.07]' : 'hover:bg-foreground/[0.03]'
                                }`}
                            >
                                <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-md bg-foreground/[0.05]">
                                    <NodeIcon result={r} className="h-3.5 w-3.5" />
                                </span>
                                <span className="min-w-0 flex-1 truncate text-[13px] text-foreground">{r.label}</span>
                                <StatusIcon status={r.status} />
                            </button>
                        ))}
                    </div>

                    {/* Main — selected node's output */}
                    <div className="flex min-w-0 flex-1 flex-col">
                        {selected && (
                            <>
                                <div className="flex shrink-0 items-center gap-2.5 border-b border-foreground/[0.06] px-5 py-3">
                                    <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-lg bg-foreground/[0.05]">
                                        <NodeIcon result={selected} className="h-4 w-4" />
                                    </span>
                                    <div className="min-w-0 flex-1 truncate text-sm font-semibold text-foreground">
                                        {selected.label}
                                    </div>
                                    <button
                                        type="button"
                                        onClick={() => onOpenConfig(selected.nodeId)}
                                        className="inline-flex shrink-0 items-center gap-1.5 rounded-md bg-primary px-3 py-1.5 text-[12px] font-semibold text-primary-foreground shadow-sm transition-colors hover:bg-primary/90"
                                    >
                                        <Settings2 className="h-3.5 w-3.5" />
                                        Open config
                                    </button>
                                </div>

                                <div className="min-h-0 flex-1 overflow-y-auto scrollbar-subtle px-5 py-4">
                                    {selected.status === 'error' && selected.error && (
                                        <div className="mb-4 rounded-lg border border-red-500/30 bg-red-500/10 px-3 py-2.5 text-[13px] leading-relaxed text-red-700 dark:text-red-300">
                                            {selected.error}
                                            {selected.errorAction && (
                                                <div className="mt-3">
                                                    <ErrorActionButton
                                                        action={selected.errorAction}
                                                        nodeId={selected.nodeId}
                                                    />
                                                </div>
                                            )}
                                        </div>
                                    )}

                                    {selected.status === 'error' ? (
                                        // A failed run produces no output — node:output fires only on
                                        // success. Any `output` still on the node is stale from an
                                        // earlier run, so show only the error, never that response.
                                        <div className="text-[13px] text-muted-foreground/70 dark:text-zinc-500">This run produced no output.</div>
                                    ) : selected.isAgent ? (
                                        <div className="flex flex-col gap-4">
                                            {hasMedia && (
                                                <div className="flex flex-col gap-2">
                                                    {media.images.map((url, i) => (
                                                        <img
                                                            key={`img-${i}`}
                                                            src={url}
                                                            alt={`Generated image ${i + 1}`}
                                                            className="w-full rounded-lg border border-foreground/[0.06] object-contain max-h-96"
                                                        />
                                                    ))}
                                                    {media.videos.map((url, i) => (
                                                        <video
                                                            key={`vid-${i}`}
                                                            src={url}
                                                            controls
                                                            className="w-full rounded-lg border border-foreground/[0.06] object-contain max-h-96 bg-black"
                                                        />
                                                    ))}
                                                </div>
                                            )}
                                            {hasResponseText && (
                                                <div className="rounded-lg border border-foreground/[0.06] bg-foreground/[0.02] px-3.5 py-3 text-[13px] leading-relaxed text-foreground">
                                                    {/* breaks: agent replies mix markdown with plain-text
                                                        newlines; this box rendered raw pre-wrap text before,
                                                        so bare \n must keep working as a line break. */}
                                                    <MarkdownRenderer content={agentResponse as string} breaks />
                                                </div>
                                            )}
                                            {hasResponseData && (
                                                <IODataDisplay data={agentResponse} label="Response" nodeId={selected.nodeId} />
                                            )}
                                            {selected.toolCalls.length > 0 && (
                                                <ReplayToolCallsPanel toolCalls={selected.toolCalls} className="w-full max-w-none" />
                                            )}
                                            {!hasMedia && !hasResponseText && !hasResponseData && selected.toolCalls.length === 0 && (
                                                // An agent envelope with no renderable content is a
                                                // delivery/empty turn, not real data — dumping the raw
                                                // {type:'agent',response:''} marker read as a blank panel
                                                // (2026-07-09). Show a clean status line instead.
                                                <div className="text-[13px] text-muted-foreground/70 dark:text-zinc-500">
                                                    The agent finished this turn without a text response.
                                                </div>
                                            )}
                                        </div>
                                    ) : (
                                        hasOutput
                                            ? <IODataDisplay data={selected.output} label="Output" nodeId={selected.nodeId} />
                                            : <div className="text-[13px] text-muted-foreground/70 dark:text-zinc-500">
                                                {selected.status === 'skipped' ? 'This node was skipped.' : 'No output.'}
                                              </div>
                                    )}
                                </div>
                            </>
                        )}
                    </div>
                </div>
                )}

                {/* Footer */}
                <div className="flex shrink-0 items-center justify-between gap-3 border-t border-foreground/[0.06] px-5 py-3">
                    <button
                        type="button"
                        onClick={() => { onDontShowAgain(); onClose(); }}
                        className="text-[12px] text-muted-foreground/70 dark:text-zinc-500 transition-colors hover:text-muted-foreground dark:hover:text-zinc-300"
                    >
                        Don&apos;t show again
                    </button>
                    <span className="text-[11px] text-muted-foreground/60 dark:text-zinc-600">Re-enable in Settings</span>
                </div>
            </DialogContent>
        </Dialog>
    );
}
