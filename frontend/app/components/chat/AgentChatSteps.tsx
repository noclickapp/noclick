// Live activity timeline for an agent chat bubble: sandbox/status milestones
// ("Starting sandbox…") and tool calls streamed over ChatMessageEvent
// status/agentic_steps frames. While the turn runs it renders a compact
// timeline (shimmering active row, inline durations); once every step is done
// it auto-collapses to a one-line summary ("3 steps · 23s") so finished
// transcripts stay clean. Tool titles arrive as "Calling {tool}({args})" and
// are humanized to "Provider · operation" (Feed's naming convention); raw args
// and the result preview live behind the row's expander.

import { useEffect, useState } from 'react';
import {
    Check,
    ChevronDown,
    ChevronRight,
    Loader2,
    XCircle,
} from 'lucide-react';
import { cn } from '~/lib/utils';
import {
    BrandIcon,
    type BrandIconComponent,
} from '~/components/shared/BrandIcon';
import { ToolDetailBlock } from '~/components/shared/ToolDetailBlock';
import { resolveToolProviderMeta } from '~/lib/toolBrand';
import type { AgentChatStep } from '~/hooks/useAgentChat';

/** Pretty-print a JSON payload for the expander; restored previews may be
 *  truncated mid-JSON, in which case the raw string passes through. */
function prettyJson(raw: string): string {
    try {
        return JSON.stringify(JSON.parse(raw), null, 2);
    } catch {
        return raw;
    }
}

/** The error prose from a failed tool result ({"success": false, "error"}),
 *  or null for anything else — failed rows show it as red prose instead of a
 *  raw JSON envelope with escaped unicode. */
function extractToolError(raw: string): string | null {
    try {
        const parsed = JSON.parse(raw) as {
            success?: unknown;
            error?: unknown;
        };
        if (
            parsed &&
            parsed.success === false &&
            typeof parsed.error === 'string'
        ) {
            return parsed.error;
        }
    } catch {
        // not JSON — fall through
    }
    return null;
}

function formatDuration(ms: number): string {
    const s = Math.round(ms / 1000);
    if (s < 60) return `${s}s`;
    return `${Math.floor(s / 60)}m ${s % 60}s`;
}

/** "linear__create_issue" → "Linear · create issue" (the Feed's provider-dot-
 *  operation reading). The auto-included lookup tool gets its FIELD as the
 *  label ("Google Sheets · look up spreadsheet id") — "lookup options" alone
 *  is internal jargon that hides what the agent is actually doing. */
function toolRowLabel(toolName: string, args?: string): string {
    const [provider, ...rest] = toolName.split('__');
    const op = rest.join('__');
    const providerLabel = provider
        .replace(/[_-]+/g, ' ')
        .trim()
        .replace(/\b\w/g, (c) => c.toUpperCase());
    if (!op) return providerLabel;
    if (op === 'lookup_options') {
        const field = args
            ? /"field"\s*:\s*"([^"]+)"/.exec(args)?.[1]
            : undefined;
        return field
            ? `${providerLabel} · look up ${field.replace(/[_-]+/g, ' ')}`
            : `${providerLabel} · lookup options`;
    }
    return `${providerLabel} · ${op.replace(/[_-]+/g, ' ').trim()}`;
}

/** Split a tool row's wire title ("Calling {tool}({args})") into a display
 *  label, the raw call args, and the tool slug (for brand-icon resolution).
 *  Non-tool titles (status milestones, "Tool call" fallbacks) pass through. */
function parseToolTitle(title: string): {
    label: string;
    args?: string;
    toolName?: string;
} {
    const m = /^Calling ([\w.-]+)\((.*)\)$/s.exec(title);
    if (!m) return { label: title };
    return {
        label: toolRowLabel(m[1], m[2]),
        args: m[2] || undefined,
        toolName: m[1],
    };
}

/** Ticking elapsed label for the ACTIVE step. Owns its own 1s interval so the
 *  tick re-renders only this label, not the whole steps list. */
function ActiveElapsed({ startedAt }: { startedAt: number }) {
    const [now, setNow] = useState(() => Date.now());
    useEffect(() => {
        const timer = setInterval(() => setNow(Date.now()), 1000);
        return () => clearInterval(timer);
    }, []);
    const ms = Math.max(0, now - startedAt);
    if (ms < 1000) return null;
    return (
        <span
            data-testid="agent-chat-step-elapsed"
            className="flex-shrink-0 tabular-nums text-muted-foreground/60"
        >
            {formatDuration(ms)}
        </span>
    );
}

function StepRow({ step }: { step: AgentChatStep }) {
    const [open, setOpen] = useState(false);
    const active = step.status === 'in_progress';
    const { label, args, toolName } =
        step.kind === 'tool'
            ? parseToolTitle(step.title)
            : { label: step.title, args: undefined, toolName: undefined };
    const brand = toolName ? resolveToolProviderMeta(toolName) : undefined;
    const errorText = step.detail ? extractToolError(step.detail) : null;
    const canExpand = !!(step.detail || args);
    const doneMs = (step.endedAt ?? step.startedAt) - step.startedAt;

    return (
        <div
            data-testid="agent-chat-step"
            className="text-xs text-muted-foreground"
        >
            <div
                className={cn(
                    'flex items-center gap-2 py-[3px]',
                    canExpand &&
                        'cursor-pointer transition-colors hover:text-foreground/80'
                )}
                onClick={canExpand ? () => setOpen((v) => !v) : undefined}
                role={canExpand ? 'button' : undefined}
                tabIndex={canExpand ? 0 : undefined}
                onKeyDown={(e) => {
                    if (canExpand && (e.key === 'Enter' || e.key === ' ')) {
                        e.preventDefault();
                        setOpen((v) => !v);
                    }
                }}
            >
                <span className="flex h-3.5 w-3.5 flex-shrink-0 items-center justify-center">
                    {active ? (
                        <Loader2 className="h-3 w-3 animate-spin text-muted-foreground" />
                    ) : errorText ? (
                        <XCircle className="h-3 w-3 text-red-600/70 dark:text-red-400/70" />
                    ) : (
                        <Check className="h-3 w-3 text-muted-foreground/50" />
                    )}
                </span>
                {brand?.Icon ? (
                    <BrandIcon
                        Icon={brand.Icon as BrandIconComponent}
                        iconColor={brand.iconColor}
                        className="h-3.5 w-3.5 flex-shrink-0"
                    />
                ) : null}
                <span
                    className={cn(
                        'min-w-0 truncate',
                        active && 'animate-pulse-text'
                    )}
                >
                    {label}
                </span>
                {active ? (
                    <ActiveElapsed startedAt={step.startedAt} />
                ) : doneMs >= 1000 ? (
                    <span
                        data-testid="agent-chat-step-elapsed"
                        className="flex-shrink-0 tabular-nums text-muted-foreground/60"
                    >
                        {formatDuration(doneMs)}
                    </span>
                ) : null}
                {canExpand ? (
                    open ? (
                        <ChevronDown className="h-3 w-3 flex-shrink-0 text-muted-foreground/60" />
                    ) : (
                        <ChevronRight className="h-3 w-3 flex-shrink-0 text-muted-foreground/60" />
                    )
                ) : null}
            </div>
            {canExpand && open ? (
                <div className="mb-1.5 ml-[22px] flex flex-col gap-2">
                    {args && args !== '{}' ? (
                        <ToolDetailBlock label="Input" tone="neutral">
                            {prettyJson(args)}
                        </ToolDetailBlock>
                    ) : null}
                    {step.detail ? (
                        errorText ? (
                            <ToolDetailBlock
                                label="Error"
                                tone="error"
                                testId="agent-chat-step-detail"
                            >
                                {errorText}
                            </ToolDetailBlock>
                        ) : (
                            <ToolDetailBlock
                                label="Result"
                                tone="neutral"
                                testId="agent-chat-step-detail"
                            >
                                {prettyJson(step.detail)}
                            </ToolDetailBlock>
                        )
                    ) : null}
                </div>
            ) : null}
        </div>
    );
}

export function AgentChatSteps({
    steps,
    turnComplete = false,
}: {
    steps: AgentChatStep[];
    /** Collapse keys on the TURN being over, not the steps: the last tool
     *  completes seconds before the response text lands, and collapsing in
     *  that gap made the bubble look finished-but-empty. */
    turnComplete?: boolean;
}) {
    // null = automatic: expanded while the turn runs, collapsed once it ends.
    // A user click pins the choice for this bubble.
    const [pinnedOpen, setPinnedOpen] = useState<boolean | null>(null);
    const allDone =
        turnComplete && steps.every((s) => s.status === 'completed');
    const showRows = pinnedOpen ?? !allDone;

    const first = steps[0];
    const totalMs = Math.max(
        0,
        Math.max(...steps.map((s) => s.endedAt ?? s.startedAt)) -
            (first?.startedAt ?? 0)
    );
    const summary =
        `${steps.length} ${steps.length === 1 ? 'step' : 'steps'}` +
        (totalMs >= 1000 ? ` · ${formatDuration(totalMs)}` : '');

    return (
        <div data-testid="agent-chat-steps" className="mb-2 flex flex-col">
            {allDone ? (
                <button
                    type="button"
                    data-testid="agent-chat-steps-summary"
                    onClick={() => setPinnedOpen(!showRows)}
                    className="group flex w-fit items-center gap-2 rounded-md py-[3px] pr-1.5 text-xs text-muted-foreground/80 transition-colors hover:text-foreground/80"
                >
                    <span className="flex h-3.5 w-3.5 flex-shrink-0 items-center justify-center">
                        <Check className="h-3 w-3 text-muted-foreground/50" />
                    </span>
                    <span>{summary}</span>
                    {showRows ? (
                        <ChevronDown className="h-3 w-3 text-muted-foreground/60" />
                    ) : (
                        <ChevronRight className="h-3 w-3 text-muted-foreground/60" />
                    )}
                </button>
            ) : null}
            {showRows ? (
                <div
                    className={cn(
                        'flex flex-col',
                        // Expanded-from-summary rows sit inside the finished
                        // bubble — indent under a soft rail so they read as a
                        // quiet appendix, not part of the answer.
                        allDone && 'ml-[6px] border-l border-border/60 pl-3'
                    )}
                >
                    {steps.map((step) => (
                        <StepRow key={step.id} step={step} />
                    ))}
                </div>
            ) : null}
        </div>
    );
}
