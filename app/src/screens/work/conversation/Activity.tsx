// A turn's work as t3code's activity log draws it. Finished, one quiet "Worked for 43s" line that opens into each step;
// while the agent works, "Working for 1m 04s" over its steps, the running one shining and its command's output arriving
// under it. Each step is an icon in a 24px slot and what it did: a command with its output and exit code, an edit with
// its diff, a read, a search, one of NoClick's own tools with what it was given and what it answered.
import { useEffect, useRef, useState, type ReactNode } from 'react';
import { ChevronRight, CircleAlert, CircleHelp, CornerDownRight, Download as DownloadIcon, FilePen, FileText, LoaderCircle, Minimize2, Search, ShieldCheck, SquareTerminal, Wrench, type LucideIcon } from 'lucide-react';
import { knownStepName, stepLine, type StepPhase } from '@/lib/stepLabels';
import { ShortcutTooltip } from '@/ui/ShortcutTooltip';
import { cn } from '@/ui/utils';
import { spent } from './styles';
import { ChildAgentRow, spawnedChild } from './subagents';
import { isSubagentCall, type Download, type Step } from '@/lib/agentThread/thread';

/** How a conversation shows tool calls, on this device. */
export type ToolCalls = 'all' | 'failures' | 'none';

export const TOOL_CALL_MODES: { id: ToolCalls; label: string; note: string }[] = [
    { id: 'all', label: 'Show all', note: 'Each run of tool calls as one line you can open' },
    { id: 'failures', label: 'Hide successful', note: 'A call shows while it runs, and stays if it fails' },
    { id: 'none', label: 'Hide all', note: 'Only what it says' },
];

const WORDS: Record<Step['kind'], { verb: string; running: string; icon: LucideIcon }> = {
    command: { verb: 'Ran', running: 'Running', icon: SquareTerminal },
    edit: { verb: 'Edited', running: 'Editing', icon: FilePen },
    search: { verb: 'Searched', running: 'Searching', icon: Search },
    read: { verb: 'Read', running: 'Reading', icon: FileText },
    tool: { verb: 'Used', running: 'Using', icon: Wrench },
};

/** A step that went wrong; a request you declined is your answer, not its failure. */
export const failedStep = (s: Step) => !s.id.startsWith('request:') && (s.isError || (s.kind === 'command' && s.exitCode !== null && s.exitCode !== 0));

/** "Ran 3 commands, edited 2 files": what a run of steps came to, counted, commands and edits first. */
export function summarize(steps: readonly Step[]): string {
    const counts: [Step['kind'], string, string][] = [
        ['command', 'command', 'commands'],
        ['edit', 'file', 'files'],
        ['search', 'time', 'times'],
        ['read', 'file', 'files'],
        ['tool', 'tool', 'tools'],
    ];
    const parts = counts.flatMap(([kind, one, many]) => {
        const n = steps.filter((s) => s.kind === kind).length;
        return n ? [`${WORDS[kind].verb.toLowerCase()} ${n} ${n === 1 ? one : many}`] : [];
    });
    const line = parts.join(', ');
    return line ? line.charAt(0).toUpperCase() + line.slice(1) : '';
}

/** A ticking "1m 04s" from a start time, in tabular figures so it never jitters. */
export function Elapsed({ from }: { from: number }) {
    const [now, setNow] = useState(() => Date.now());
    useEffect(() => {
        const t = setInterval(() => setNow(Date.now()), 1000);
        return () => clearInterval(t);
    }, []);
    return (
        <span className="tabular-nums" suppressHydrationWarning>
            {spent(now - from)}
        </span>
    );
}

/** What's alive: no dot, no spinner, a slow shine across the words. */
export function Shine({ children, className }: { children: ReactNode; className?: string }) {
    return <span className={cn('work-shine', className)}>{children}</span>;
}

/** "Working for 4m 12s", or "Compacting for 12s" while older history is summarized. */
export function WorkingLine({ from, compacting, downloading }: { from: number; compacting?: number | null; downloading?: Download | null }) {
    // A machine fetching its harness says so in NoClick's words, a thin bar under it where the size is known.
    if (downloading) {
        const share = downloading.total ? Math.min(1, (downloading.bytes ?? 0) / downloading.total) : null;
        return (
            <div className="px-1" aria-live="polite" data-testid="downloading">
                <p className="flex min-h-6 items-center gap-1.5 text-sm leading-relaxed text-muted-foreground">
                    <DownloadIcon className="h-3.5 w-3.5 shrink-0" strokeWidth={2} />
                    <Shine>{downloading.text}</Shine>
                </p>
                {share !== null && (
                    <div role="progressbar" aria-label="Downloading" aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round(share * 100)} className="ml-5 mt-1 h-[3px] w-56 max-w-[60%] overflow-hidden rounded-full bg-foreground/[0.08]">
                        <div className="h-full rounded-full bg-foreground/50 transition-[width] duration-500" style={{ width: `${share * 100}%` }} />
                    </div>
                )}
            </div>
        );
    }
    return (
        <p className="flex h-6 items-baseline gap-1.5 px-1 text-sm leading-relaxed text-muted-foreground" aria-live="polite">
            {compacting ? <Minimize2 className="h-3.5 w-3.5 self-center" strokeWidth={2} /> : null}
            <Shine>{compacting ? 'Compacting for' : 'Working for'}</Shine>
            <Elapsed from={compacting ?? from} />
        </p>
    );
}

/** A point in the conversation between hairlines: a day, a compaction, a new session (t3code's divider). A long label
 *  wraps between them rather than pushing the thread sideways. */
export function SystemDivider({ icon: Icon, label, detail }: { icon?: LucideIcon; label: ReactNode; detail?: ReactNode }) {
    return (
        <div className="flex items-center gap-2 px-1 py-2 text-[11px] leading-4 text-muted-foreground">
            <span aria-hidden className="h-px min-w-6 flex-1 bg-border dark:bg-foreground/[0.08]" />
            <span className="flex min-w-0 items-center gap-1.5">
                {Icon && <Icon className="h-3 w-3 shrink-0" strokeWidth={2} />}
                {/* One run of text, so a long label wraps with its detail after it. */}
                <span className="min-w-0 text-center [overflow-wrap:anywhere]">
                    <span className="font-medium">{label}</span>
                    {detail && <span className="opacity-70"> · {detail}</span>}
                </span>
            </span>
            <span aria-hidden className="h-px min-w-6 flex-1 bg-border dark:bg-foreground/[0.08]" />
        </div>
    );
}

/** A turn's finished work folded to one line: "Worked for 43s ›", "You stopped after 12s ›". Its subagents stay out
 *  under it, each one line and what it found (one can still be at work after the reply). */
export function WorkFold({ steps: all, ms, stopped, mode, children }: { steps: Step[]; ms: number; stopped?: boolean; mode: ToolCalls; children?: ReactNode }) {
    const [open, setOpen] = useState(false);
    const steps = all.filter((s) => !isSubagentCall(s));
    const subagents = all.filter(isSubagentCall).filter((s) => mode === 'all' || s.running || failedStep(s));
    const failed = steps.filter(failedStep).length;
    if (mode === 'none') return null;
    const shown = mode === 'failures' ? steps.filter(failedStep) : steps;
    if (!shown.length && !subagents.length && !(stopped && mode === 'all')) return null;
    const expanded = open || mode === 'failures';
    return (
        <div className={cn('pb-2 pt-1', mode === 'all' && 'border-b border-border/60 dark:border-foreground/[0.07]')}>
            {mode === 'all' && (shown.length > 0 || !subagents.length) && (
                <ShortcutTooltip label={summarize(steps)}>
                    <button
                        type="button"
                        onClick={() => setOpen(!open)}
                        aria-expanded={open}
                        className="flex items-center gap-1 rounded-full px-1 text-sm leading-relaxed text-muted-foreground transition-colors hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring/70"
                    >
                        <span className="tabular-nums">{stopped ? `You stopped after ${spent(ms)}` : steps.length ? `Worked for ${spent(ms)}` : 'Worked'}</span>
                        {failed > 0 && <span className="text-red-600 dark:text-red-300">· {failed} failed</span>}
                        {shown.length > 0 && <ChevronRight className={cn('h-3.5 w-3.5 shrink-0 transition-transform duration-200', open && 'rotate-90')} strokeWidth={2} />}
                    </button>
                </ShortcutTooltip>
            )}
            {expanded && shown.length > 0 && <StepList steps={shown} live={false} className={mode === 'all' ? 'mt-1' : undefined} />}
            {subagents.length > 0 && <StepList steps={subagents} live={false} className="mt-0.5" />}
            {children}
        </div>
    );
}

export function StepList({ steps, live, className }: { steps: Step[]; live: boolean; className?: string }) {
    return (
        <ul className={className}>
            {steps.map((s) => (
                <StepRow key={s.id} step={s} live={live} />
            ))}
        </ul>
    );
}

const baseName = (path: string) => path.slice(path.lastIndexOf('/') + 1) || path;

/** A tool's wire name as words, where it isn't one NoClick knows: `linear__make_ticket` reads "linear · make ticket". */
export function toolWords(tool: string): string {
    const [provider, operation] = tool.includes('__') ? tool.split('__', 2) : ['', tool];
    const words = operation.replace(/[_-]+/g, ' ').trim();
    return provider ? `${provider} · ${words}` : words;
}

/** One of NoClick's own tools, or an app's operation, said as the Chat page says it ("Listed failed runs", "Sent an
 *  email in Gmail"): what it did, then what it was about. Null for a tool NoClick doesn't know by name. */
function namedTool(step: Step, phase: StepPhase): { head: string; tail?: string } | null {
    const named = step.kind === 'tool' ? knownStepName(step.tool, step.arguments, phase) : null;
    return named && stepLine(named);
}

/** What a step did, in its row: the command, the file, what it looked for, the tool. */
function targetOf(step: Step): string {
    if (step.kind === 'command') return step.command ?? step.tool;
    if (step.kind === 'search') return `“${step.query ?? step.tool}”`;
    if (step.kind === 'read' || step.kind === 'edit') return step.path ? baseName(step.path) : step.tool;
    return toolWords(step.tool);
}

const lineCount = (diff: string, mark: '+' | '-') => diff.split('\n').filter((l) => l.startsWith(mark) && !l.startsWith(mark.repeat(3))).length;

export function diffStat(diffs: Step['diffs']): { added: number; removed: number } {
    return diffs.reduce((n, d) => ({ added: n.added + (d.change === 'add' && !/^[+-]/m.test(d.diff) ? d.diff.split('\n').length : lineCount(d.diff, '+')), removed: n.removed + lineCount(d.diff, '-') }), { added: 0, removed: 0 });
}

/** +7 −2 in mono figures, as t3code counts a change. */
export function DiffStat({ added, removed, className }: { added: number; removed: number; className?: string }) {
    return (
        <span className={cn('font-mono tabular-nums', className)}>
            {added > 0 && <span className="text-emerald-600 dark:text-emerald-400">+{added}</span>}
            {removed > 0 && <span className="ml-1 text-red-600 dark:text-red-400">−{removed}</span>}
        </span>
    );
}

/** One step, t3code's row: an icon in a 24px slot, what it did, and opened, its output or its change, indented under
 *  the words. A subagent's call is its group; a NoClick agent it started, that agent's row. */
export function StepRow({ step, live }: { step: Step; live: boolean }) {
    if (step.id.startsWith('request:')) return <AskedRow step={step} />;
    if (isSubagentCall(step)) return <SubagentGroup step={step} />;
    const child = spawnedChild(step);
    if (child) return <ChildAgentRow child={child} />;
    return <WorkRow step={step} live={live} />;
}

/** What a step is doing, in a line: "Running pytest -q", "Reading worker.py", "Listing failed runs". */
export function doing(step: Step): string {
    const named = namedTool(step, 'running');
    return named ? `${named.head}${named.tail ?? ''}`.replace(/\u00a0/g, ' ') : `${WORDS[step.kind].running} ${targetOf(step)}`;
}

/** What a subagent was asked, in a line. */
export const subagentTask = (step: Step): string => String(step.arguments.description || step.arguments.prompt || 'A subagent').split('\n')[0];

/** A subagent in its parent's log: "↳ its task · 6 steps · 1m 04s", spinning while it works with its latest step under
 *  it; opened, its own steps under a guide line; done, what it found as a quote; failed, open on its error. Its
 *  call's end is its last words: a summary, or why it failed. */
function SubagentGroup({ step }: { step: Step }) {
    const failed = failedStep(step);
    const [open, setOpen] = useState(failed);
    const was = useRef(failed);
    useEffect(() => {
        if (failed && !was.current) setOpen(true);
        was.current = failed;
    }, [failed]);
    const running = step.running;
    const latest = step.children[step.children.length - 1];
    const n = step.children.length;
    const time = running ? <Elapsed from={step.at} /> : step.durationMs !== null ? spent(step.durationMs) : null;
    const words = step.output.trim();
    const error = failed ? words || (typeof step.result === 'string' ? step.result : 'It failed.') : null;
    const lastWords = step.said.trim().split('\n').filter(Boolean).pop();
    return (
        <li data-subagent={step.id} data-status={running ? 'running' : failed ? 'failed' : 'done'} className="rounded-lg">
            <button
                type="button"
                onClick={() => setOpen(!open)}
                aria-expanded={open}
                className="group/sub flex min-h-7 w-full items-center gap-1.5 rounded-lg px-0.5 text-left text-sm leading-relaxed text-muted-foreground transition-colors hover:bg-foreground/[0.04] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring/70"
            >
                <span className="grid h-6 w-6 shrink-0 place-items-center">
                    {failed ? <CircleAlert className="h-4 w-4 text-red-500 dark:text-red-300" strokeWidth={2} /> : <CornerDownRight className="h-4 w-4 text-muted-foreground/80" strokeWidth={2} />}
                </span>
                <span className={cn('min-w-0 truncate', failed ? 'text-red-700 dark:text-red-300' : 'text-foreground/85')}>{subagentTask(step)}</span>
                <span className="shrink-0 tabular-nums">
                    · {n} {n === 1 ? 'step' : 'steps'}
                    {time && <> · {time}</>}
                </span>
                {failed && <span className="shrink-0 text-xs text-red-600 dark:text-red-300">failed</span>}
                <span className="ml-auto flex shrink-0 items-center gap-1 pl-2">
                    {running && <LoaderCircle aria-label="Running" className="h-3.5 w-3.5 animate-spin text-muted-foreground motion-reduce:animate-none" strokeWidth={2.25} />}
                    <ChevronRight className={cn('h-3.5 w-3.5 opacity-60 transition-transform duration-200 group-hover/sub:opacity-100', open && 'rotate-90')} strokeWidth={2} />
                </span>
            </button>
            {running && !open && (
                <p className="truncate pb-0.5 pl-[30px] text-xs text-muted-foreground" data-testid="subagent-now">
                    <Shine>{latest ? doing(latest) : lastWords || 'Starting…'}</Shine>
                </p>
            )}
            {open && (
                <div className="mb-1 ml-3 border-l border-border pl-2.5 dark:border-foreground/[0.1]">
                    {error && <p className="py-0.5 text-xs leading-relaxed text-red-600 [overflow-wrap:anywhere] dark:text-red-300">{error}</p>}
                    {n > 0 ? <StepList steps={step.children} live={running} /> : !error && <p className="py-0.5 text-xs text-muted-foreground">{running ? 'Starting…' : 'No steps kept.'}</p>}
                </div>
            )}
            {!running && !failed && words && (
                <blockquote className={cn('mb-1 mt-0.5 whitespace-pre-line border-l-2 border-foreground/15 pl-2.5 text-[13px] leading-snug text-foreground/75 [overflow-wrap:anywhere]', open ? 'ml-3' : 'ml-[30px] line-clamp-6')} data-testid="subagent-summary">
                    {words}
                </blockquote>
            )}
        </li>
    );
}

const ASKED_OUTCOME: Record<string, string> = { allow_once: 'Approved', allow_always: 'Always allowed this session', reject_once: 'Declined', cancel: 'Canceled', expired: 'Nobody answered in time' };

/** Something its harness asked you, as the turn kept it: what it wanted, and what became of it. */
function AskedRow({ step }: { step: Step }) {
    const args = step.arguments as { title?: string; questions?: { question?: string }[]; action?: string };
    const what = args.title ?? args.questions?.[0]?.question ?? 'Asked you';
    const [decision, note] = typeof step.result === 'string' ? step.result.split(/:\s(.*)/s) : [];
    const outcome = decision ? (ASKED_OUTCOME[decision] ?? decision) : 'Waiting';
    return (
        <li data-step="asked" className="flex min-h-6 items-start gap-1.5 rounded-lg px-0.5 text-sm leading-6 text-muted-foreground">
            <span className="grid h-6 w-6 shrink-0 place-items-center">
                {args.action || !args.questions ? <ShieldCheck className="h-4 w-4 text-muted-foreground/80" strokeWidth={2} /> : <CircleHelp className="h-4 w-4 text-muted-foreground/80" strokeWidth={2} />}
            </span>
            {/* The whole question, wrapped under "Asked", and the words it was answered with under it. */}
            <span className="min-w-0 [overflow-wrap:anywhere]">
                Asked <span className="text-foreground/80">{what.charAt(0).toLowerCase() + what.slice(1)}</span>
                {note && <span className="block text-xs leading-5">“{note}”</span>}
            </span>
            <span className={cn('ml-auto shrink-0 pl-2 text-xs', step.isError && 'text-foreground/80')}>{outcome}</span>
        </li>
    );
}

function WorkRow({ step, live }: { step: Step; live: boolean }) {
    const running = step.running && live;
    const failed = failedStep(step);
    // A running command (or edit) opens on its output; a running tool call stays closed on its words ("Opening
    // kestrel.example/pricing"), what it was given opening only when the person asks. A failure opens either way.
    const opensRunning = step.kind !== 'tool';
    const [open, setOpen] = useState((running && opensRunning) || failed);
    // A command that starts running opens; one that ends quietly folds itself away again.
    const was = useRef(running);
    const wasFailed = useRef(failed);
    useEffect(() => {
        if (running && !was.current && opensRunning) setOpen(true);
        if (!running && was.current && !failed && opensRunning) setOpen(false);
        if (failed && !wasFailed.current) setOpen(true);
        was.current = running;
        wasFailed.current = failed;
    }, [running, failed, opensRunning]);
    const w = WORDS[step.kind];
    const named = namedTool(step, running ? 'running' : 'done');
    const stat = step.kind === 'edit' ? diffStat(step.diffs) : null;
    const opens = (step.kind === 'command' && (!!step.output || running)) || (step.kind === 'edit' && step.diffs.length > 0) || (step.kind === 'tool' && (Object.keys(step.arguments).length > 0 || step.result !== null));
    return (
        <li data-step={step.kind}>
            <div className={cn('group/step flex min-h-6 items-center gap-1.5 rounded-lg px-0.5 text-sm leading-relaxed text-muted-foreground transition-colors', opens && 'hover:bg-foreground/[0.04]')}>
                <span className="grid h-6 w-6 shrink-0 place-items-center">
                    <w.icon className={cn('h-4 w-4', failed ? 'text-red-500 dark:text-red-300' : 'text-muted-foreground/80')} strokeWidth={2} />
                </span>
                {/* Its whole target on hover: a path, a command, a search, cut to one line here. */}
                <ShortcutTooltip label={step.kind === 'read' || step.kind === 'edit' ? (step.path ?? undefined) : named ? `${named.head}${named.tail ?? ''}` : targetOf(step) || undefined}>
                    <button
                        type="button"
                        onClick={() => opens && setOpen(!open)}
                        aria-expanded={opens ? open : undefined}
                        className={cn('flex min-w-0 items-baseline gap-1.5 text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/70', running && 'work-shine', !opens && 'cursor-default')}
                    >
                        {named ? (
                            // What it did, then what it was about: the detail gives way first in a narrow column.
                            <>
                                <span className={cn(named.tail ? 'shrink-0' : 'min-w-0 truncate')}>{named.head}</span>
                                {named.tail && <span className="min-w-0 truncate text-foreground/80">{named.tail.replace(/^\u00a0/, '')}</span>}
                            </>
                        ) : (
                            <>
                                <span className="shrink-0">{running ? w.running : w.verb}</span>
                                <span className={cn('min-w-0 truncate text-foreground/80', step.kind === 'command' && 'font-mono text-xs')}>{targetOf(step)}</span>
                            </>
                        )}
                        {stat && (stat.added > 0 || stat.removed > 0) && <DiffStat {...stat} className="shrink-0 text-[10px]" />}
                    </button>
                </ShortcutTooltip>
                <span className="ml-auto flex shrink-0 items-center gap-1.5 pl-2">
                    {step.kind === 'command' && step.running && !live && <span className="text-xs">stopped</span>}
                    {failed && <span className="text-xs text-red-600 dark:text-red-300">{step.exitCode !== null && step.exitCode !== 0 ? `exit ${step.exitCode}` : 'failed'}</span>}
                    {!running && step.durationMs !== null && step.kind === 'command' && <span className="text-[11px] tabular-nums opacity-0 transition-opacity duration-200 group-hover/step:opacity-100">{spent(step.durationMs)}</span>}
                    {opens && (
                        <button type="button" aria-label={open ? 'Hide' : 'Show'} onClick={() => setOpen(!open)} className="grid h-5 w-5 place-items-center rounded-full opacity-60 transition-opacity hover:bg-foreground/[0.06] hover:opacity-100 focus-visible:opacity-100">
                            <ChevronRight className={cn('h-3 w-3 transition-transform duration-200', open && 'rotate-90')} strokeWidth={2} />
                        </button>
                    )}
                </span>
            </div>
            {open && step.kind === 'command' && <OutputTail text={step.output} live={running} />}
            {open && step.kind === 'edit' && step.diffs.map((d) => <DiffBlock key={d.path} diff={d.diff} path={d.path} many={step.diffs.length > 1} />)}
            {open && step.kind === 'tool' && <ToolDetail step={step} />}
        </li>
    );
}

/** A command's output, flush under its row as t3code prints it: no box, following the newest line while you're at
 *  the bottom and staying put once you scroll up. */
export function OutputTail({ text, live }: { text: string; live: boolean }) {
    const ref = useRef<HTMLDivElement>(null);
    const pinned = useRef(true);
    useEffect(() => {
        const el = ref.current;
        if (el && pinned.current) el.scrollTop = el.scrollHeight;
    }, [text]);
    const cut = text.startsWith('[…');
    return (
        <div
            ref={ref}
            onScroll={(e) => {
                const el = e.currentTarget;
                pinned.current = el.scrollHeight - el.scrollTop - el.clientHeight <= 8;
            }}
            data-testid="command-output"
            className="mb-1.5 ml-7 max-h-80 overflow-auto whitespace-pre-wrap font-mono text-[11px] leading-relaxed text-muted-foreground scrollbar-subtle [overflow-wrap:anywhere]"
        >
            {cut && <p className="font-sans italic">Earlier output not shown</p>}
            {text ? text.replace(/^\[…[^\]]*\]\n?/, '') : <p className="font-sans italic">{live ? 'Waiting for output…' : 'No output.'}</p>}
        </div>
    );
}

/** A change, opened from its row: its lines, added in green and removed in red. */
export function DiffBlock({ diff, path, many }: { diff: string; path: string; many?: boolean }) {
    const lines = diff.split('\n').filter((l) => !l.startsWith('+++') && !l.startsWith('---') && !l.startsWith('diff ') && !l.startsWith('index '));
    return (
        <div className="mb-1.5 ml-7 overflow-hidden rounded-xl bg-foreground/[0.03] py-1 font-mono text-[11px] leading-relaxed [overflow-wrap:anywhere]">
            {many && <p className="px-2.5 pb-0.5 text-muted-foreground">{path}</p>}
            {lines.map((l, i) => (
                <p
                    key={i}
                    className={cn(
                        'whitespace-pre-wrap px-2.5',
                        l.startsWith('@@') && 'text-muted-foreground/70',
                        l.startsWith('+') && 'bg-emerald-500/[0.09] text-emerald-800 dark:text-emerald-300',
                        l.startsWith('-') && 'bg-red-500/[0.09] text-red-800 dark:text-red-300'
                    )}
                >
                    {l || ' '}
                </p>
            ))}
        </div>
    );
}

const shown = (value: unknown) => (typeof value === 'string' ? value : JSON.stringify(value, null, 2));

/** One of NoClick's tools, opened: what it was given and what it answered (or its error). */
function ToolDetail({ step }: { step: Step }) {
    const args = Object.keys(step.arguments).length ? shown(step.arguments) : null;
    const result = step.result !== null && step.result !== undefined ? shown(step.result) : null;
    return (
        <div className="mb-1.5 ml-7 max-h-64 space-y-1.5 overflow-auto whitespace-pre-wrap font-mono text-[11px] leading-relaxed text-muted-foreground scrollbar-subtle [overflow-wrap:anywhere]">
            {args && <p>{args}</p>}
            {result && <p className={cn(step.isError && 'text-red-600 dark:text-red-300')}>{result}</p>}
        </div>
    );
}
