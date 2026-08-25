// Header-mounted conversation history popover for the AgentChatBlock.
// Sits to the right of the model picker — a clock/history icon with a
// count badge that opens a themed popover listing every saved thread
// for this agent. Each row shows label + relative timestamp, click to
// switch, trash on hover to soft-delete. "+ New chat" button at the top.
// Mirrors AgentModelPicker's portal-popover pattern so dropdowns share
// the same look-and-feel.

import { useCallback } from 'react';
import { createPortal } from 'react-dom';
import {
    History,
    Plus,
    MessageSquare,
    Check,
    Trash2,
    Loader2,
} from 'lucide-react';
import { cn } from '~/lib/utils';
import type { AgentConversationSummary } from '~/hooks/useAgentChatConversations';
import {
    harnessOf,
    harnessLabel,
    splitCarryOverContext,
    LEGACY_CLI_HARNESS,
} from '~/lib/agentChat';
import { useAnchoredPopover } from './useAnchoredPopover';

interface AgentChatHistoryProps {
    conversations: AgentConversationSummary[];
    activeKey: string;
    /** Current model on the agent node — used to flag rows whose original
     *  harness differs from this one (CLI runtime context is per-harness, so
     *  the user should know clicking a claude-code thread while codex is the
     *  active model only restores the visible transcript, not the CLI's
     *  internal state). */
    currentModel: string;
    isLoading: boolean;
    onSwitchTo: (conv: AgentConversationSummary) => void;
    onDelete: (conv: AgentConversationSummary) => void;
    onCreateNew: () => void;
    /** Called when the popover opens — refetches the list so threads
     *  created since the initial mount (or since the last refresh) appear. */
    onRefresh: () => void;
    isReadOnly: boolean;
}

/** Relative-time formatter — local copy so this surface doesn't have to
 *  import from the sidebar's internals. */
function relativeTime(iso: string): string {
    if (!iso) return '';
    const t = Date.parse(iso);
    if (Number.isNaN(t)) return '';
    const s = Math.max(0, (Date.now() - t) / 1000);
    if (s < 60) return 'just now';
    if (s < 3600) return `${Math.floor(s / 60)}m`;
    if (s < 86400) return `${Math.floor(s / 3600)}h`;
    if (s < 86400 * 7) return `${Math.floor(s / 86400)}d`;
    try {
        return new Date(t).toLocaleDateString(undefined, {
            month: 'short',
            day: 'numeric',
        });
    } catch {
        return '';
    }
}

export function AgentChatHistory({
    conversations,
    activeKey,
    currentModel,
    isLoading,
    onSwitchTo,
    onDelete,
    onCreateNew,
    onRefresh,
    isReadOnly,
}: AgentChatHistoryProps) {
    // Anchor the panel's left edge slightly left of the trigger so it grows
    // toward the centre — the trigger sits in the right side of the header.
    const computePos = useCallback(
        (rect: DOMRect) => ({
            top: rect.bottom + 8,
            left: Math.max(8, rect.left - 4),
            width: 380,
        }),
        []
    );
    const { open, setOpen, triggerRef, panelRef, pos } =
        useAnchoredPopover<HTMLButtonElement>(computePos);

    const handleToggle = useCallback(() => {
        const next = !open;
        setOpen(next);
        if (next) onRefresh();
    }, [open, onRefresh, setOpen]);

    return (
        <>
            <button
                ref={triggerRef}
                onClick={handleToggle}
                aria-label="Conversation history"
                title="Conversation history"
                data-testid="agent-chat-history-trigger"
                className="group relative flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg border border-border/60 hover:border-border hover:bg-foreground/[0.04] transition-colors text-muted-foreground hover:text-foreground"
                type="button"
            >
                <History className="w-3.5 h-3.5" />
                <span className="text-sm hidden @xl:inline">History</span>
                {conversations.length > 0 ? (
                    <span className="text-xs tabular-nums rounded-full bg-foreground/[0.06] px-1.5 py-px text-muted-foreground/80">
                        {conversations.length}
                    </span>
                ) : null}
            </button>

            {open &&
                pos &&
                createPortal(
                    <div
                        ref={panelRef}
                        style={{
                            top: pos.top,
                            left: pos.left,
                            width: pos.width,
                        }}
                        className="fixed z-[60] rounded-2xl border border-border bg-popover/95 dark:bg-zinc-950/95 backdrop-blur-md shadow-2xl overflow-hidden"
                        data-testid="agent-chat-history-panel"
                    >
                        <div className="px-4 py-3 border-b border-border dark:border-zinc-900 flex items-center justify-between gap-2">
                            <span className="text-xs uppercase tracking-wider text-muted-foreground dark:text-zinc-500">
                                History
                            </span>
                            {isLoading ? (
                                <Loader2 className="w-3.5 h-3.5 text-muted-foreground dark:text-zinc-500 animate-spin" />
                            ) : null}
                        </div>

                        <div className="px-2 py-2">
                            <button
                                type="button"
                                onClick={() => {
                                    onCreateNew();
                                    setOpen(false);
                                }}
                                disabled={isReadOnly}
                                data-testid="agent-chat-history-new"
                                className="group w-full flex items-center gap-2 rounded-lg border border-dashed border-border bg-transparent hover:bg-foreground/[0.03] hover:border-border dark:hover:border-zinc-700 transition-colors px-3 py-2 text-left disabled:opacity-50 disabled:cursor-not-allowed"
                            >
                                <Plus className="w-3.5 h-3.5 text-muted-foreground dark:text-zinc-500 group-hover:text-foreground/80 transition-colors" />
                                <span className="text-sm text-muted-foreground group-hover:text-foreground transition-colors">
                                    New chat
                                </span>
                            </button>
                        </div>

                        {conversations.length === 0 ? (
                            <div className="px-4 py-6 text-center text-sm text-muted-foreground/70 dark:text-zinc-600">
                                {isLoading
                                    ? 'Loading'
                                    : 'No conversations yet.'}
                            </div>
                        ) : (
                            (() => {
                                // Hoisted out of the row map so we don't recompute per row.
                                const currentHarness = harnessOf(currentModel);
                                return (
                                    <ul className="max-h-[420px] overflow-y-auto scrollbar-subtle px-2 pb-2 space-y-0.5">
                                        {conversations.map((c) => {
                                            const isActive =
                                                c.conversation_key ===
                                                activeKey;
                                            // Titles and previews are derived
                                            // in SQL from the first hundred
                                            // characters of the first message,
                                            // which for a carried-over thread
                                            // runs into the context block. That
                                            // derivation happens in Postgres,
                                            // where no display code runs, so
                                            // the strip has to happen here too
                                            // — carrying a thread is an
                                            // implementation detail and should
                                            // never be something the user
                                            // reads.
                                            const label =
                                                splitCarryOverContext(
                                                    c.title || c.preview || ''
                                                ).text ||
                                                c.conversation_key ||
                                                'Conversation';
                                            // Compare by harness bucket so same-harness model swaps
                                            // (gpt-4o ↔ claude-3.5 within the LLM harness) don't trigger
                                            // the cross-harness warning — only CLI runtime crossings do.
                                            const rowModel =
                                                c.agent_model ?? null;
                                            const rowHarness =
                                                harnessOf(rowModel);
                                            const isCrossHarness =
                                                !!rowModel &&
                                                rowHarness !== currentHarness;
                                            return (
                                                <li key={c.conversation_id}>
                                                    <div
                                                        data-testid="agent-chat-history-row"
                                                        data-active={
                                                            isActive
                                                                ? 'true'
                                                                : 'false'
                                                        }
                                                        data-cross-harness={
                                                            isCrossHarness
                                                                ? 'true'
                                                                : 'false'
                                                        }
                                                        className={cn(
                                                            'group flex items-center gap-2 rounded-lg px-2.5 py-1.5 transition-colors',
                                                            isActive
                                                                ? 'bg-foreground/[0.06]'
                                                                : 'hover:bg-foreground/[0.03]'
                                                        )}
                                                    >
                                                        <button
                                                            type="button"
                                                            onClick={() => {
                                                                onSwitchTo(c);
                                                                setOpen(false);
                                                            }}
                                                            disabled={
                                                                isReadOnly
                                                            }
                                                            className="flex-1 min-w-0 flex items-center gap-2 text-left"
                                                        >
                                                            <MessageSquare
                                                                className={cn(
                                                                    'w-3.5 h-3.5 shrink-0',
                                                                    isActive
                                                                        ? 'text-foreground/80'
                                                                        : 'text-muted-foreground dark:text-zinc-500'
                                                                )}
                                                            />
                                                            <span
                                                                className={cn(
                                                                    'flex-1 min-w-0 truncate text-sm',
                                                                    isActive
                                                                        ? 'text-foreground'
                                                                        : 'text-foreground/80'
                                                                )}
                                                            >
                                                                {label}
                                                            </span>
                                                            {/* Visitor thread from the agent's public share link.
                            Opening it is fine (auditability) — but sends land
                            in the visitor's conversation. */}
                                                            {c.shared ? (
                                                                <span
                                                                    data-testid="agent-chat-history-row-shared"
                                                                    title="A visitor started this conversation via your share link. Messages you send here continue their thread."
                                                                    className="shrink-0 text-[10px] rounded-md px-1.5 py-0.5 border text-sky-700 border-sky-200 bg-sky-50 dark:text-sky-300 dark:border-sky-900/50 dark:bg-sky-950/30"
                                                                >
                                                                    Shared
                                                                </span>
                                                            ) : null}
                                                            {/* Only show the harness badge for CLI runtimes
                            (Codex / Claude Code / OpenCode / OpenClaw /
                            Hermes Agent) and the legacy-CLI backfill.
                            Regular LLM chats route through the in-process
                            wrapper and don't get a brand tag —
                            harnessLabel returns '' for them, and an empty
                            badge with the styled border just looks broken. */}
                                                            {rowModel &&
                                                            harnessLabel(
                                                                rowHarness
                                                            ) ? (
                                                                <span
                                                                    data-testid="agent-chat-history-row-harness"
                                                                    title={
                                                                        rowHarness ===
                                                                        LEGACY_CLI_HARNESS
                                                                            ? "Original CLI not recorded — this row predates harness tagging, so we can't tell which CLI it used. Continuing it on the current model may mix event shapes."
                                                                            : isCrossHarness
                                                                              ? `This thread was used on ${harnessLabel(rowHarness)}. Continuing on ${harnessLabel(currentHarness) || 'the standard LLM'} restores the visible transcript only — the next send starts fresh because each harness keeps its own runtime state. Switching will realign the model picker.`
                                                                              : `Harness: ${harnessLabel(rowHarness)}${rowModel.includes('/') ? ` (${rowModel})` : ''}`
                                                                    }
                                                                    className={cn(
                                                                        'shrink-0 text-[10px] tabular-nums rounded-md px-1.5 py-0.5 border',
                                                                        isCrossHarness
                                                                            ? 'text-amber-700 border-amber-200 bg-amber-50 dark:text-amber-300 dark:border-amber-900/50 dark:bg-amber-950/30'
                                                                            : 'text-muted-foreground dark:text-zinc-500 border-border bg-card/40'
                                                                    )}
                                                                >
                                                                    {harnessLabel(
                                                                        rowHarness
                                                                    )}
                                                                </span>
                                                            ) : null}
                                                            <span className="text-[10px] text-muted-foreground/70 dark:text-zinc-600 shrink-0 tabular-nums">
                                                                {relativeTime(
                                                                    c.last_activity ||
                                                                        c.created_at
                                                                )}
                                                            </span>
                                                            {isActive ? (
                                                                <Check className="w-3.5 h-3.5 text-muted-foreground dark:text-white/70 shrink-0" />
                                                            ) : null}
                                                        </button>
                                                        <button
                                                            type="button"
                                                            onClick={() =>
                                                                onDelete(c)
                                                            }
                                                            disabled={
                                                                isReadOnly
                                                            }
                                                            aria-label="Delete conversation"
                                                            title="Delete conversation"
                                                            className="shrink-0 text-muted-foreground/70 dark:text-zinc-600 hover:text-red-400 transition-colors"
                                                        >
                                                            <Trash2 className="w-3.5 h-3.5" />
                                                        </button>
                                                    </div>
                                                </li>
                                            );
                                        })}
                                    </ul>
                                );
                            })()
                        )}
                    </div>,
                    document.body
                )}
        </>
    );
}
