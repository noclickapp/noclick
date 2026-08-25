// Share a finished Test Run: mints a public read-only link (/r/{id}) whose
// page renders the exact snapshot on screen — trigger card, step trace,
// outcome. Owner-only server-side; the snapshot carries display fields only
// (the backend allowlists keys at mint), so no workflow/node ids ever reach
// the public page.

import { useState } from 'react';
import { Check, Copy, Loader2, Share2 } from 'lucide-react';
import { cn } from '~/lib/utils';
import { sendEventAsync } from '~/lib/socket-sender';
import type { Scenario } from './fixture';
import type { ReplayState } from './useReplay';

function buildSnapshot(scenario: Scenario, run: ReplayState) {
    const providers = new Set<string>();
    if (scenario.iconSlug) providers.add(scenario.iconSlug);
    if (scenario.provider && scenario.provider !== 'generic') {
        providers.add(scenario.provider);
    }
    for (const r of run.rows) {
        if (r.kind === 'tool' && r.provider) providers.add(r.provider);
    }
    for (const a of run.artifacts ?? []) {
        if (a.provider) providers.add(a.provider);
    }
    return {
        version: 1,
        // The fixture replay script is bench furniture — the rows ARE the run.
        scenario: { ...scenario, events: [] },
        rows: run.rows,
        artifacts: run.artifacts,
        failed: run.failed ?? false,
        providers: [...providers],
    };
}

export function ShareRunButton({
    workflowId,
    scenario,
    run,
}: {
    workflowId: string;
    /** The displayed scenario (live outcome text already folded in). */
    scenario: Scenario;
    run: ReplayState;
}) {
    const [minting, setMinting] = useState(false);
    const [url, setUrl] = useState<string | null>(null);
    const [open, setOpen] = useState(false);
    const [copied, setCopied] = useState(false);
    const [error, setError] = useState<string | null>(null);

    const copy = async (value: string) => {
        try {
            await navigator.clipboard.writeText(value);
            setCopied(true);
            window.setTimeout(() => setCopied(false), 2000);
        } catch {
            // The input stays selectable — copy by hand.
        }
    };

    const share = async () => {
        if (minting) return;
        setError(null);
        // A second click re-opens the same link — one share per finished run.
        if (url) {
            setOpen(true);
            return;
        }
        setMinting(true);
        try {
            const res: any = await sendEventAsync({
                event_name: 'run_share:create',
                workflow_id: workflowId,
                title: scenario.name,
                snapshot: buildSnapshot(scenario, run),
            } as any);
            if (!res?.success || !res?.url) {
                throw new Error(res?.error || 'Failed to create run link');
            }
            setUrl(res.url);
            setOpen(true);
            void copy(res.url);
        } catch (e: any) {
            setError(e?.message || 'Failed to create run link');
        } finally {
            setMinting(false);
        }
    };

    return (
        <div className="relative flex shrink-0 items-center gap-2">
            {error && (
                <span className="max-w-[220px] truncate text-[11.5px] text-red-600 dark:text-red-400" title={error}>
                    {error}
                </span>
            )}
            <button
                onClick={share}
                title="Share a read-only link to this run"
                className="flex items-center gap-1.5 rounded-lg border border-foreground/15 px-3 py-1.5 text-[12.5px] font-medium text-foreground/70 transition-colors hover:bg-foreground/5 hover:text-foreground"
            >
                {minting ? (
                    <Loader2 className="h-3.5 w-3.5 animate-spin" />
                ) : (
                    <Share2 className="h-3.5 w-3.5" />
                )}
                Share this run
            </button>
            {open && url && (
                <>
                    <button
                        aria-label="Close"
                        onClick={() => setOpen(false)}
                        className="fixed inset-0 z-10 cursor-default"
                    />
                    {/* Opens UPWARD — the button sits at the end of the run,
                        often at the bottom edge of the scroll. */}
                    <div className="absolute bottom-full right-0 z-20 mb-1.5 w-[320px] rounded-xl border border-border bg-popover/95 p-3 shadow-2xl backdrop-blur-md dark:bg-zinc-950/95">
                        <p className="m-0 text-[12.5px] font-medium">
                            Anyone with this link can view this run.
                        </p>
                        <p className="m-0 mt-0.5 text-[11.5px] leading-relaxed text-foreground/45">
                            A read-only snapshot — the page says clearly that
                            the data is simulated.
                        </p>
                        <div className="mt-2 flex items-center gap-1.5">
                            <input
                                readOnly
                                value={url}
                                onFocus={(e) => e.currentTarget.select()}
                                className="min-w-0 flex-1 rounded-md border border-border bg-transparent px-2 py-1 text-[11.5px] text-foreground/70 outline-none"
                            />
                            <button
                                onClick={() => copy(url)}
                                title="Copy link"
                                className={cn(
                                    'flex shrink-0 items-center rounded-md border border-border p-1.5 transition-colors',
                                    copied
                                        ? 'text-emerald-500'
                                        : 'text-foreground/50 hover:bg-foreground/[0.05] hover:text-foreground/80'
                                )}
                            >
                                {copied ? (
                                    <Check className="h-3.5 w-3.5" />
                                ) : (
                                    <Copy className="h-3.5 w-3.5" />
                                )}
                            </button>
                        </div>
                    </div>
                </>
            )}
        </div>
    );
}
