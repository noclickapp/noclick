// ReplayToolCallsPanel lists the agent tool calls recorded for a past
// execution run (tool_call_events via workflow:get_execution_detail).
// Rendered from the replay banner so users can audit exactly which tools an
// agent invoked — in order, with arguments, results, credential use, and
// latency — without digging through backend logs.

import { useState } from 'react';
import {
    CheckCircle2,
    ChevronDown,
    ChevronRight,
    Wrench,
    XCircle,
} from 'lucide-react';
import { cn } from '~/lib/utils';

export interface ReplayToolCall {
    agent_node_id: string | null;
    tool_name: string;
    tool_type: string;
    provider_node_id: string | null;
    operation: string | null;
    credential_id: string | null;
    arguments: Record<string, unknown> | null;
    result_status: string;
    error: string | null;
    result_preview: string | null;
    duration_ms: number | null;
    timestamp: string | null;
}

// Map an agent output's embedded `tool_calls` package into ReplayToolCall rows.
// Some runtimes attach calls directly to the response package rather than to
// workflow:get_execution_detail, so the package is authoritative when present;
// in-process agents can fall back to execution detail.
// The package uses `created_at`; the panel renders `timestamp`.
export function toReplayToolCalls(output: unknown): ReplayToolCall[] {
    if (!output || typeof output !== 'object') return [];
    const raw = (output as Record<string, unknown>).tool_calls;
    if (!Array.isArray(raw)) return [];
    return raw.map((c) => {
        const t = (c ?? {}) as Record<string, unknown>;
        return {
            agent_node_id: (t.agent_node_id as string) ?? null,
            tool_name: String(t.tool_name ?? ''),
            tool_type: String(t.tool_type ?? ''),
            provider_node_id: (t.provider_node_id as string) ?? null,
            operation: (t.operation as string) ?? null,
            credential_id: (t.credential_id as string) ?? null,
            arguments: (t.arguments as Record<string, unknown>) ?? null,
            result_status: String(t.result_status ?? 'success'),
            error: (t.error as string) ?? null,
            result_preview: (t.result_preview as string) ?? null,
            duration_ms:
                typeof t.duration_ms === 'number' ? t.duration_ms : null,
            timestamp:
                (t.created_at as string) ?? (t.timestamp as string) ?? null,
        };
    });
}

function formatDuration(ms: number | null): string {
    if (ms === null || ms === undefined) return '';
    if (ms < 1000) return `${ms}ms`;
    return `${(ms / 1000).toFixed(1)}s`;
}

function ToolCallRow({
    call,
    animate,
}: {
    call: ReplayToolCall;
    animate?: boolean;
}) {
    const [expanded, setExpanded] = useState(false);
    const failed = call.result_status === 'error';
    return (
        <div
            className={cn(
                'border-b border-border dark:border-white/[0.05] last:border-b-0',
                animate &&
                    'animate-in fade-in slide-in-from-top-1 duration-300 motion-reduce:animate-none'
            )}
        >
            <button
                type="button"
                onClick={() => setExpanded((e) => !e)}
                className="flex w-full items-center gap-2 px-3 py-1.5 text-left hover:bg-foreground/[0.04] transition-colors"
            >
                {expanded ? (
                    <ChevronDown className="h-3 w-3 shrink-0 text-muted-foreground dark:text-zinc-500" />
                ) : (
                    <ChevronRight className="h-3 w-3 shrink-0 text-muted-foreground dark:text-zinc-500" />
                )}
                {failed ? (
                    <XCircle className="h-3.5 w-3.5 shrink-0 text-red-600 dark:text-red-400" />
                ) : (
                    <CheckCircle2 className="h-3.5 w-3.5 shrink-0 text-green-600 dark:text-green-500" />
                )}
                <span className="font-mono text-xs text-foreground truncate">
                    {call.tool_name}
                </span>
                <span className="text-[10px] text-muted-foreground dark:text-zinc-500 shrink-0">
                    {call.tool_type}
                </span>
                <span className="ml-auto flex items-center gap-2 shrink-0 text-[10px] text-muted-foreground dark:text-zinc-500">
                    {call.duration_ms !== null && (
                        <span>{formatDuration(call.duration_ms)}</span>
                    )}
                    {call.timestamp && (
                        <span>
                            {new Date(call.timestamp).toLocaleTimeString()}
                        </span>
                    )}
                </span>
            </button>
            {expanded && (
                <div className="space-y-1.5 px-8 pb-2 text-[11px]">
                    {call.operation && (
                        <div className="text-muted-foreground">
                            <span className="text-muted-foreground/70 dark:text-zinc-600">
                                operation{' '}
                            </span>
                            {call.operation}
                            {call.provider_node_id && (
                                <span className="text-muted-foreground/70 dark:text-zinc-600">
                                    {' '}
                                    · node {call.provider_node_id}
                                </span>
                            )}
                            {call.credential_id && (
                                <span className="text-muted-foreground/70 dark:text-zinc-600">
                                    {' '}
                                    · credential{' '}
                                    {call.credential_id.slice(0, 8)}…
                                </span>
                            )}
                        </div>
                    )}
                    {call.arguments &&
                        Object.keys(call.arguments).length > 0 && (
                            <pre className="overflow-x-auto whitespace-pre-wrap break-words rounded bg-muted dark:bg-black/40 p-2 font-mono text-[10px] leading-snug text-muted-foreground">
                                {JSON.stringify(call.arguments, null, 2)}
                            </pre>
                        )}
                    {failed && call.error && (
                        <div className="rounded bg-red-500/[0.08] border border-red-500/20 p-2 text-red-700 dark:text-red-300">
                            {call.error}
                        </div>
                    )}
                    {!failed && call.result_preview && (
                        <pre className="overflow-x-auto whitespace-pre-wrap break-words rounded bg-muted dark:bg-black/40 p-2 font-mono text-[10px] leading-snug text-muted-foreground dark:text-zinc-500">
                            {call.result_preview}
                        </pre>
                    )}
                </div>
            )}
        </div>
    );
}

export function ReplayToolCallsPanel({
    toolCalls,
    className,
    animateRows = false,
    pendingRows = 0,
}: {
    toolCalls: ReplayToolCall[];
    className?: string;
    animateRows?: boolean;
    pendingRows?: number;
}) {
    if (toolCalls.length === 0 && pendingRows === 0) return null;
    const failures = toolCalls.filter(
        (c) => c.result_status === 'error'
    ).length;
    return (
        <div
            className={cn(
                // Default width suits the floating replay popover; callers in a wider
                // container (e.g. the run-results modal) pass className to override it.
                'max-h-80 w-[28rem] max-w-[90vw] overflow-y-auto scrollbar-subtle rounded-lg border border-border dark:border-zinc-700/60 bg-popover/98 shadow-xl dark:shadow-black/40 backdrop-blur-md',
                className
            )}
        >
            <div className="flex items-center gap-2 border-b border-border dark:border-white/[0.06] px-3 py-2 text-xs text-muted-foreground">
                <Wrench className="h-3.5 w-3.5" />
                <span className="font-medium text-foreground/80">
                    {toolCalls.length === 0
                        ? 'Recording tool calls'
                        : `${toolCalls.length} tool call${
                              toolCalls.length === 1 ? '' : 's'
                          } recorded`}
                </span>
                {failures > 0 && (
                    <span className="text-red-600 dark:text-red-400">
                        {failures} failed
                    </span>
                )}
            </div>
            {toolCalls.map((call, i) => (
                <ToolCallRow
                    key={`${call.tool_name}-${call.timestamp ?? i}`}
                    call={call}
                    animate={animateRows}
                />
            ))}
            {Array.from({ length: pendingRows }, (_, index) => (
                <div
                    key={`pending-${index}`}
                    data-testid="tool-call-pending-row"
                    className="flex h-[37px] items-center gap-2 border-b border-border px-3 last:border-b-0 dark:border-white/[0.05]"
                    aria-hidden="true"
                >
                    <span className="h-3 w-3 rounded bg-foreground/[0.04]" />
                    <span className="h-3.5 w-3.5 rounded-full bg-foreground/[0.05]" />
                    <span
                        className="h-2 animate-pulse rounded-full bg-foreground/[0.07] motion-reduce:animate-none"
                        style={{ width: `${42 - index * 4}%` }}
                    />
                    <span className="ml-auto h-2 w-12 animate-pulse rounded-full bg-foreground/[0.045] [animation-delay:140ms] motion-reduce:animate-none" />
                </div>
            ))}
        </div>
    );
}
