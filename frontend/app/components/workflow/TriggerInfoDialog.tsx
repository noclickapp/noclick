// Shown when the Run button is pressed on a workflow that only starts on
// automatic events (incoming email, a new row, a schedule, …) and has no manual
// Run step. It is purely informational: it explains, in plain language, how the
// workflow actually starts so users understand why pressing Run does nothing.
// Dismissed via the close button / Escape / clicking outside. Clean, minimal
// styling: a calm padded layout with an iOS-style grouped list of events.
import { useState } from 'react';
import { Zap, Copy, Check, Plus, Settings2, Play, ExternalLink } from 'lucide-react';
import {
    Dialog,
    DialogContent,
    DialogTitle,
    DialogDescription,
} from '~/components/ui/dialog';
import { SerializedIcon } from '~/components/shared/SerializedIcon';
import type { WorkflowTrigger } from '~/utils/workflowTriggers';

interface TriggerInfoDialogProps {
    triggers: WorkflowTrigger[];
    /** Close the popup (via the X button, Escape, or clicking the backdrop). */
    onClose: () => void;
    /** Add a manual Run trigger to the canvas (placed unconnected, panned to). */
    onAddRunStep: () => void;
    /** Open a trigger node's config panel (selects it, expands the config view). */
    onOpenTriggerConfig: (nodeId: string) => void;
    /** Run the workflow now anyway (a one-off manual run of a triggered flow). */
    onRunAnyway: () => void;
}

// A full-width row showing an address/URL that fires the workflow: the value
// fills the available width (so long URLs wrap cleanly instead of squishing into
// a narrow chip) with only a small copy button pinned to the right. The optional
// "Open in a new tab" link lives on the label row above so it doesn't eat the
// URL's width.
function CopyValue({ value }: { value: string }) {
    const [copied, setCopied] = useState(false);
    return (
        <div className="flex w-full items-center gap-1 rounded-lg bg-foreground/[0.05] py-1.5 pl-2.5 pr-1.5">
            <code className="min-w-0 flex-1 break-all font-mono text-[13px] leading-relaxed text-foreground">
                {value}
            </code>
            <button
                type="button"
                title="Copy"
                onClick={() => {
                    navigator.clipboard?.writeText(value);
                    setCopied(true);
                    setTimeout(() => setCopied(false), 1500);
                }}
                className="shrink-0 rounded-md p-1.5 text-muted-foreground/70 dark:text-zinc-500 transition-colors hover:bg-foreground/10 hover:text-muted-foreground dark:hover:text-zinc-300"
            >
                {copied ? (
                    <Check className="h-3.5 w-3.5 text-emerald-600 dark:text-emerald-400" />
                ) : (
                    <Copy className="h-3.5 w-3.5" />
                )}
            </button>
        </div>
    );
}

// The parent mounts this only while open and unmounts it to close, rather than
// toggling Radix's `open` prop. That sidesteps a Radix/Presence quirk under
// `prefers-reduced-motion` where the exit animation's `animationend` never fires,
// leaving the closed dialog (and its body pointer-events lock) stuck on screen.
export function TriggerInfoDialog({ triggers, onClose, onAddRunStep, onOpenTriggerConfig, onRunAnyway }: TriggerInfoDialogProps) {
    const multiple = triggers.length > 1;

    return (
        <Dialog open onOpenChange={(o) => { if (!o) onClose(); }}>
            <DialogContent className="flex max-h-[85vh] max-w-xl flex-col gap-0 overflow-hidden border-foreground/10 p-0">
                {/* Header — pinned */}
                <div className="shrink-0 px-6 pt-7">
                    <DialogTitle className="pr-8 text-2xl font-semibold tracking-tight text-foreground">
                        This workflow runs automatically
                    </DialogTitle>
                    <DialogDescription className="mt-2 text-[15px] leading-relaxed text-muted-foreground">
                        It starts on its own, not when you press Run.
                    </DialogDescription>

                    <p className="mb-2.5 mt-6 text-[15px] font-semibold text-foreground">
                        {multiple ? 'It runs whenever any of these happen' : 'It runs whenever this happens'}
                    </p>
                </div>

                {/* Trigger list — scrolls when there are many */}
                <div className="min-h-0 flex-1 overflow-y-auto scrollbar-subtle px-6 pb-5">
                    <div className="divide-y divide-foreground/[0.05] overflow-hidden rounded-2xl border border-foreground/[0.07] bg-foreground/[0.02]">
                        {triggers.map(t => (
                            <div key={t.nodeId} className="group px-4 py-3.5">
                                <div className="flex items-start gap-3.5">
                                    <span className="mt-0.5 flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-foreground/[0.04]">
                                        {t.iconHtml ? (
                                            <SerializedIcon
                                                html={t.iconHtml}
                                                iconColor={t.iconColor}
                                                className="h-[22px] w-[22px]"
                                            />
                                        ) : (
                                            <Zap className="h-5 w-5 text-muted-foreground/70 dark:text-zinc-500" strokeWidth={1.75} />
                                        )}
                                    </span>
                                    <div className="min-w-0 flex-1">
                                        <div className="flex items-center gap-2">
                                            <span className="truncate text-[15px] font-semibold text-foreground">
                                                {t.title}
                                            </span>
                                            {t.label && t.label !== t.title && (
                                                <span className="shrink-0 truncate rounded-full bg-foreground/[0.06] px-2 py-0.5 text-[11px] text-muted-foreground">
                                                    {t.label}
                                                </span>
                                            )}
                                        </div>
                                        <p className="mt-1 text-[13px] leading-snug text-muted-foreground">
                                            {t.description}
                                        </p>
                                    </div>
                                    <button
                                        type="button"
                                        onClick={() => onOpenTriggerConfig(t.nodeId)}
                                        className="mt-0.5 inline-flex shrink-0 items-center gap-1.5 rounded-md px-2 py-1 text-[12px] font-medium text-muted-foreground/70 dark:text-zinc-500 transition-colors hover:bg-foreground/[0.06] hover:text-foreground"
                                    >
                                        <Settings2 className="h-3.5 w-3.5" />
                                        Open config
                                    </button>
                                </div>
                                {/* Params span the full card width (indented under the title) so long
                                    URLs aren't squeezed into the narrow column beside "Open config". */}
                                {t.params.length > 0 && (
                                    <div className="mt-2.5 flex flex-col gap-2 pl-[3.375rem]">
                                        {t.params.map((p, i) =>
                                            p.mono ? (
                                                <div key={i} className="flex flex-col gap-1">
                                                    <div className="flex items-center justify-between gap-2">
                                                        <span className="text-[12px] text-muted-foreground/70 dark:text-zinc-500">{p.label}</span>
                                                        {p.href && (
                                                            <a
                                                                href={p.href}
                                                                target="_blank"
                                                                rel="noopener noreferrer"
                                                                title="Open in a new tab"
                                                                className="inline-flex shrink-0 items-center gap-1 rounded-md px-2 py-0.5 text-[12px] font-medium text-muted-foreground transition-colors hover:bg-foreground/10 hover:text-foreground"
                                                            >
                                                                <ExternalLink className="h-3.5 w-3.5" />
                                                                Open
                                                            </a>
                                                        )}
                                                    </div>
                                                    <CopyValue value={p.value} />
                                                </div>
                                            ) : (
                                                <div key={i} className="flex flex-wrap items-baseline gap-x-2 gap-y-1">
                                                    <span className="text-[12px] text-muted-foreground/70 dark:text-zinc-500">{p.label}</span>
                                                    <span className="min-w-0 break-words text-[13px] font-medium text-foreground">
                                                        {p.value}
                                                    </span>
                                                </div>
                                            ),
                                        )}
                                    </div>
                                )}
                            </div>
                        ))}
                    </div>
                </div>

                {/* Footer — pinned. Supporting text left; actions right-aligned
                    with the primary (Run anyway) on the far right and a ghost
                    secondary (Add a Run step) to its left. */}
                <div className="flex shrink-0 items-center justify-between gap-3 border-t border-foreground/[0.06] px-6 pb-6 pt-4">
                    <p className="text-[13px] leading-relaxed text-muted-foreground/70 dark:text-zinc-500">
                        Want to run it yourself?
                    </p>
                    <div className="flex shrink-0 items-center gap-2">
                        <button
                            type="button"
                            onClick={onAddRunStep}
                            className="group inline-flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-[13px] font-medium text-muted-foreground transition-colors hover:bg-foreground/[0.06] hover:text-foreground"
                        >
                            <Plus className="h-3.5 w-3.5 text-muted-foreground/70 dark:text-zinc-500 transition-colors group-hover:text-muted-foreground dark:group-hover:text-zinc-300" />
                            Add a Run step
                        </button>
                        <button
                            type="button"
                            onClick={onRunAnyway}
                            className="inline-flex items-center gap-1.5 rounded-lg bg-foreground/10 px-3.5 py-1.5 text-[13px] font-semibold text-foreground ring-1 ring-inset ring-foreground/15 transition-colors hover:bg-foreground/[0.16]"
                        >
                            <Play className="h-3.5 w-3.5" fill="currentColor" />
                            Run anyway
                        </button>
                    </div>
                </div>
            </DialogContent>
        </Dialog>
    );
}
