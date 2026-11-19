// What opens from the session: /usage, /context, /help and /rename as drawers from behind the box, and beside it a
// turn's changed files, each file's diff.
import { useEffect, useState, type ReactNode } from 'react';
import { Minimize2, Pencil, X } from 'lucide-react';
import type { Agent, AgentStepDiff, ConversationContext, ConversationUsage } from 'noclick';
import { HAIRLINE } from '@/ui/primitives';
import { createPanelWidth, type PanelWidth } from '@/ui/panelWidth';
import { ResizeEdge } from '@/ui/ResizeEdge';
import { DiffView } from '@/screens/resources/DiffView';
import { cn } from '@/ui/utils';
import { HarnessMark, harnessLabel } from '../agents/harness';
import { AgentNameField } from '../agents/rename';
import { DiffStat, diffStat } from './Activity';
import { ComposerDrawer } from './menus';
import { ICON_BUTTON, XS_BUTTON, XS_GHOST, XS_OUTLINE } from './styles';


function DrawerHead({ title, mark, onClose }: { title: string; mark?: ReactNode; onClose: () => void }) {
    return (
        <div className="flex items-center gap-2">
            {mark}
            <p className="text-sm font-medium">{title}</p>
            <button type="button" aria-label="Close" onClick={onClose} className={cn(XS_BUTTON, XS_GHOST, 'ml-auto h-6 w-6 px-0')}>
                <X className="h-3.5 w-3.5" strokeWidth={2} />
            </button>
        </div>
    );
}

/** Reads something once the drawer opens; its error is said in the drawer. */
function useRead<T>(read: () => Promise<T>): { data: T | null; error: string | null } {
    const [state, setState] = useState<{ data: T | null; error: string | null }>({ data: null, error: null });
    useEffect(() => {
        let gone = false;
        read().then(
            (data) => !gone && setState({ data, error: null }),
            (e: unknown) => !gone && setState({ data: null, error: e instanceof Error ? e.message : 'It didn’t answer.' })
        );
        return () => {
            gone = true;
        };
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, []);
    return state;
}

const usd = (n: number) => (n < 0.01 && n > 0 ? '<$0.01' : `$${n.toFixed(2)}`);
const PAYS: Record<string, string> = { noclick: 'NoClick’s key, at cost', key: 'your own key: you pay per use', plan: 'your plan' };

/** /usage: what this session has cost, and a plan's limits and when they reset (on a key, it pays per use). */
export function UsagePanel({ agent, conversation, onClose }: { agent: Agent; conversation: string; onClose: () => void }) {
    const { data, error } = useRead<ConversationUsage>(() => agent.conversation(conversation).usage());
    return (
        <ComposerDrawer label="Usage" className="px-4 pt-3">
            <DrawerHead title="Usage" mark={agent.harness && <HarnessMark harness={agent.harness} className="h-4 w-4" />} onClose={onClose} />
            {error ? (
                <p className="mb-3 mt-2 text-xs text-muted-foreground">{error}</p>
            ) : !data ? (
                <p className="mb-3 mt-2 text-xs text-muted-foreground">Reading…</p>
            ) : (
                <div className="mb-3 mt-2 space-y-3">
                    <dl className="space-y-1 text-[11px] leading-4">
                        <div className="flex justify-between">
                            <dt className="text-muted-foreground">This session</dt>
                            <dd className="tabular-nums">
                                {usd(data.costUsd ?? 0)} · {data.turns ?? 0} {data.turns === 1 ? 'turn' : 'turns'}
                            </dd>
                        </div>
                        <div className="flex justify-between">
                            <dt className="text-muted-foreground">Runs on</dt>
                            <dd>{PAYS[data.paysWith] ?? data.paysWith}</dd>
                        </div>
                        {data.modelUsage && (
                            <div className="flex justify-between">
                                <dt className="text-muted-foreground">Tokens</dt>
                                <dd className="tabular-nums">
                                    {Math.round(data.modelUsage.inputTokens / 1000)}k in · {Math.round(data.modelUsage.outputTokens / 1000)}k out
                                </dd>
                            </div>
                        )}
                    </dl>
                    {data.planLimits.length > 0 ? (
                        <ul className="space-y-3">
                            {data.planLimits.map((l) => (
                                <li key={l.label}>
                                    <div className="flex items-baseline justify-between text-xs">
                                        <span>{l.label}</span>
                                        {l.usedPercent !== null && <span className="tabular-nums text-muted-foreground">{Math.round(l.usedPercent)}% used</span>}
                                    </div>
                                    {l.usedPercent !== null && (
                                        <div className="mt-1.5 h-1.5 overflow-hidden rounded-full bg-foreground/[0.08]">
                                            <div className={cn('h-full rounded-full', l.usedPercent > 90 ? 'bg-red-500' : 'bg-muted-foreground/70')} style={{ width: `${Math.min(100, l.usedPercent)}%` }} />
                                        </div>
                                    )}
                                    {l.resetsAt && <p className="mt-1 text-[11px] text-muted-foreground">Resets {l.resetsAt.toLocaleString(undefined, { weekday: 'short', hour: 'numeric', minute: '2-digit' })}</p>}
                                </li>
                            ))}
                        </ul>
                    ) : (
                        data.paysWith === 'plan' && <p className="text-xs leading-relaxed text-muted-foreground">Its harness reports no limits for this plan.</p>
                    )}
                </div>
            )}
        </ComposerDrawer>
    );
}

/** /context: how full its context window is, when it compacts by itself, and Compact where its harness can. */
export function ContextPanel({ agent, conversation, canCompact, working, onCompact, onClose }: { agent: Agent; conversation: string; canCompact: boolean; working: boolean; onCompact: () => void; onClose: () => void }) {
    const { data, error } = useRead<ConversationContext>(() => agent.conversation(conversation).context());
    const pct = data?.percent ?? (data?.usedTokens != null && data.windowTokens ? Math.round((data.usedTokens / data.windowTokens) * 100) : null);
    return (
        <ComposerDrawer label="Context" className="px-4 pt-3">
            <DrawerHead title="Context window" onClose={onClose} />
            {error ? (
                <p className="mb-3 mt-2 text-xs text-muted-foreground">{error}</p>
            ) : !data ? (
                <p className="mb-3 mt-2 text-xs text-muted-foreground">Reading…</p>
            ) : (
                <div className="mb-3 mt-2">
                    {data.usedTokens == null ? (
                        <p className="text-xs text-muted-foreground">Nothing yet: its first turn fills it.</p>
                    ) : (
                        <>
                            <p className="text-[11px] tabular-nums text-muted-foreground">
                                {Math.round(data.usedTokens / 1000)}k / {Math.round((data.windowTokens ?? 0) / 1000)}k · {pct}%
                            </p>
                            <div className="relative mt-2 h-1.5 rounded-full bg-foreground/[0.08]">
                                <div className={cn('h-full rounded-full', (pct ?? 0) > 90 ? 'bg-red-500' : 'bg-muted-foreground/70')} style={{ width: `${Math.min(100, pct ?? 0)}%` }} />
                                {data.autoCompactsAt != null && <span aria-hidden className="absolute -top-[3px] h-3 w-px bg-foreground/40" style={{ left: `${data.autoCompactsAt * 100}%` }} />}
                            </div>
                            {data.autoCompactsAt != null && <p className="mt-2 text-[11px] text-muted-foreground">Compacts by itself at {Math.round(data.autoCompactsAt * 100)}%.</p>}
                        </>
                    )}
                    {canCompact ? (
                        <>
                            <button type="button" onClick={onCompact} className={cn(XS_BUTTON, XS_OUTLINE, 'mt-3 w-full')}>
                                <Minimize2 className="h-3.5 w-3.5" strokeWidth={2} />
                                Compact context
                            </button>
                            {working && <p className="mt-2 text-[11px] text-muted-foreground">It runs once {agent.name} is between turns.</p>}
                        </>
                    ) : (
                        agent.harness && <p className="mt-2.5 text-[11px] text-muted-foreground">{harnessLabel(agent.harness)} only compacts by itself.</p>
                    )}
                </div>
            )}
        </ComposerDrawer>
    );
}

/** /help: what the box does. */
export function HelpPanel({ onClose }: { onClose: () => void }) {
    const ROWS: [string, string][] = [
        ['/', 'Commands: NoClick’s own, then its harness’s'],
        ['/mcp', 'The apps and tools it can use, and adding more'],
        ['/loop', 'A prompt again and again: /loop 5m … on an interval, /loop … when it decides, /loop stop to end it'],
        ['/rename', 'A new name for the agent: /rename Bakery helper, or /rename alone to edit it here'],
        ['@', 'One of its files, another agent, a person'],
        ['$', 'One of its skills, run with what you write'],
        ['Files', 'Paste or drop them, or use the paperclip'],
        ['While it works', 'A message joins what it’s doing; the queue waits for the turn to end'],
    ];
    return (
        <ComposerDrawer label="Help" className="px-4 pt-3">
            <DrawerHead title="In this box" onClose={onClose} />
            <dl className="mb-3 mt-2 grid grid-cols-[auto_1fr] gap-x-4 gap-y-1.5 text-xs">
                {ROWS.map(([k, v]) => (
                    <div key={k} className="contents">
                        <dt className="font-medium text-foreground/85">{k}</dt>
                        <dd className="text-muted-foreground">{v}</dd>
                    </div>
                ))}
            </dl>
        </ComposerDrawer>
    );
}

/** /rename with no name, or one refused: the agent's name to edit in the box's drawer (`draft` and `error` what it
 *  opens with). Enter saves, Esc closes. */
export function RenamePanel({ name, draft, error, onSave, onClose }: { name: string; draft?: string; error?: string | null; onSave: (name: string) => Promise<string | null>; onClose: () => void }) {
    return (
        <ComposerDrawer label="Rename the agent" className="px-4 pb-1 pt-3">
            <DrawerHead title={`Rename ${name}`} mark={<Pencil className="h-3.5 w-3.5 text-muted-foreground" strokeWidth={2} />} onClose={onClose} />
            <div className="mb-3 mt-2">
                <AgentNameField current={name} draft={draft} error={error} label="New name" onSave={onSave} onCancel={onClose} />
                <p className="mt-1.5 text-[11px] text-muted-foreground">Its old name keeps reaching it.</p>
            </div>
        </ComposerDrawer>
    );
}

export const CHANGES_PANEL = createPanelWidth({ key: 'nc-work-changes', initial: 560, min: 400, max: 900 });

/** A column beside the conversation, resizable from its edge; full width on a phone. */
function PanelFrame({ children, panel, label }: { children: ReactNode; panel: PanelWidth; label: string }) {
    const width = panel.useWidth();
    return (
        <aside aria-label={label} className={cn('absolute inset-0 z-20 flex flex-col bg-background md:relative md:inset-auto md:z-auto md:shrink-0 md:border-l', HAIRLINE)} style={{ ['--panel-w' as string]: `${width}px` }}>
            <div className="hidden md:block">
                <ResizeEdge panel={panel} side="left" label={`Resize ${label.toLowerCase()}`} />
            </div>
            <div className="flex min-h-0 w-full flex-1 flex-col md:w-[var(--panel-w)]">{children}</div>
        </aside>
    );
}

function PanelHead({ title, sub, onClose }: { title: string; sub: string; onClose: () => void }) {
    return (
        <div className={cn('flex h-12 shrink-0 items-center gap-2 border-b pl-5 pr-3', HAIRLINE)}>
            <p className="text-sm font-medium">{title}</p>
            <p className="min-w-0 truncate text-xs text-muted-foreground">{sub}</p>
            <span className="ml-auto flex items-center gap-1">
                <button type="button" aria-label="Close" onClick={onClose} className={ICON_BUTTON}>
                    <X className="h-4 w-4" />
                </button>
            </span>
        </div>
    );
}

/** A new file's whole content, as a unified diff DiffView reads. */
function asPatch(d: AgentStepDiff): string {
    if (/^@@ /m.test(d.diff)) return d.diff;
    const lines = d.diff.replace(/\n$/, '').split('\n');
    return `@@ -0,0 +1,${lines.length} @@\n${lines.map((l) => `+${l}`).join('\n')}\n`;
}

/** A turn's changed files beside the conversation, each file's diff. */
export function ChangesPanel({ agentName, files, onClose }: { agentName: string; files: AgentStepDiff[]; onClose: () => void }) {
    return (
        <PanelFrame panel={CHANGES_PANEL} label="Changed files">
            <PanelHead title={`Changed ${files.length} ${files.length === 1 ? 'file' : 'files'}`} sub={agentName} onClose={onClose} />
            <div className="min-h-0 flex-1 space-y-3 overflow-y-auto px-4 pb-6 pt-3 scrollbar-subtle">
                {files.map((f) => (
                    <div key={f.path} className={cn('overflow-hidden rounded-[26px] border', HAIRLINE)}>
                        <p className={cn('flex items-center gap-2 border-b bg-foreground/[0.02] px-4 py-2 font-mono text-xs', HAIRLINE)}>
                            <span className="min-w-0 truncate">{f.path}</span>
                            <DiffStat {...diffStat([f])} className="ml-auto shrink-0" />
                        </p>
                        <DiffView patch={asPatch(f)} path={f.path} />
                    </div>
                ))}
            </div>
        </PanelFrame>
    );
}
