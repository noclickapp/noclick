// Long work an agent set going, while it runs: each finished stage a quiet check and how long it took (its check drawn
// in as it lands), a thin rail between the marks, the stages ahead light, one live line and how fresh it is. Done, it
// folds into one line ("Deployed in 31s · sample-site.noclick.site · Open site") with the stages a tap away; failed,
// it shows the line that broke, with a way to try again and the log.
import { useState, type ReactNode } from 'react';
import { ArrowUpRight, Boxes, Check, ChevronDown, ChevronRight, Hammer, Link2, Phone, X } from 'lucide-react';
import { GlyphTile, InlineCard, LiveDot, PILL_QUIET, PILL_SECONDARY, Status } from '@/ui/chat/primitives';
import { relTime } from '@/lib/formatters';
import { cn } from '@/ui/utils';
import { FreshCheck, type StageCheck } from '@/ui/chat/motion';
import { FreshLive, stageKey, useFreshStages, type FreshStages } from './stageCheck';
import { clock, span } from '@/lib/clock';
import { breakingLine, quietText, type WorkLine, type WorkStage, type WorkView } from './workView';

export function Glyph({ kind }: { kind: string }) {
    const Icon = kind.startsWith('phone') ? Phone : kind === 'connect' ? Link2 : kind === 'workflow.build' ? Hammer : Boxes;
    return (
        <GlyphTile>
            <Icon className="h-4 w-4" />
        </GlyphTile>
    );
}

function Clock({ ms }: { ms: number }) {
    return (
        <span className="inline-flex items-center gap-2 text-[12.5px] tabular-nums text-foreground/75">
            <LiveDot />
            {clock(ms)}
        </span>
    );
}

/** How fresh the work is: "4s ago", "quiet 45s", or how long a person has had what the stage `at` asks them ("sent
 *  12s ago", then "sent 43m ago": no seconds ticking on an old ask). */
function freshness(view: WorkView, at: WorkStage, now: number): string {
    if (view.state !== 'waiting') return quietText(now - view.changedAt);
    return `sent ${now - at.start < 60_000 ? `${span(now - at.start)} ago` : relTime(new Date(at.start).toISOString(), new Date(now).toISOString())}`;
}

function LogLine({ line, wrap = false }: { line: WorkLine; wrap?: boolean }) {
    return (
        <p className={cn('tl-line font-mono text-[11.5px] leading-[18px]', wrap ? 'whitespace-pre-wrap break-words' : 'truncate', line.error ? 'text-red-600 dark:text-red-400' : 'text-foreground/70')}>
            {line.text}
        </p>
    );
}

function Marker({ state }: { state: WorkStage['state'] }) {
    if (state === 'done') return <Check className="h-3 w-3 text-muted-foreground/70" strokeWidth={2.5} />;
    if (state === 'current') return <LiveDot className="h-2 w-2" />;
    if (state === 'failed') return <X className="h-3 w-3 text-red-600 dark:text-red-400" strokeWidth={2.5} />;
    return <span className="h-1.5 w-1.5 rounded-full border border-foreground/25" />;
}

/** The stages: a quiet check and how long each took, the live one with its line and how fresh it is, the rest light,
 *  a thin rail between the marks. A stage that just finished draws its check the way `check` says, its rail fills
 *  toward the next one, and the next one's dot comes alive; `fresh` names them outright (to replay a moment). */
export function StageList({ view, now, check = 'draw', fresh: explicit }: { view: WorkView; now: number; check?: StageCheck; fresh?: FreshStages }) {
    const stages = view.stages;
    const fresh = useFreshStages(stages, explicit);
    // What it printed last belongs to work under way; waiting on a person, it's what came before the question.
    const latest = view.state === 'running' ? view.lines.slice(-1) : [];
    const breaking = breakingLine(view);
    return (
        <ol className="space-y-1.5 text-[13px] leading-[20px]">
            {stages.map((stage, i) => {
                const key = stageKey(stage);
                const current = stage.state === 'current';
                const failed = stage.state === 'failed';
                const isLast = i === stages.length - 1;
                const justDone = stage.state === 'done' && fresh.done.includes(key);
                const justLive = current && fresh.live.includes(key);
                const right = stage.state === 'pending' ? '' : current ? freshness(view, stage, now) : span((stage.end ?? now) - stage.start);
                return (
                    <li key={key} className="relative grid grid-cols-[16px_1fr_auto] gap-x-2.5">
                        {/* The rail between this stage's mark and the next one's, solid once this stage is done. */}
                        {!isLast && (
                            <span className={cn('absolute left-[7.5px] top-[16px] -bottom-[10px] w-px', stage.state === 'done' && !justDone ? 'bg-foreground/25' : 'bg-foreground/[0.08]')} aria-hidden>
                                {justDone && <span className="sc-fill absolute inset-0 origin-top bg-foreground/25" />}
                            </span>
                        )}
                        <span className="flex h-5 items-center justify-center">{justDone ? <FreshCheck check={check} /> : justLive ? <FreshLive /> : <Marker state={stage.state} />}</span>
                        <span
                            className={cn(
                                'min-w-0 truncate transition-colors duration-300',
                                current ? 'font-medium text-foreground' : failed ? 'font-medium text-red-600 dark:text-red-400' : stage.state === 'pending' ? 'text-muted-foreground/45' : 'text-muted-foreground',
                                justLive && 'sc-name-live'
                            )}
                        >
                            {stage.name}
                        </span>
                        <span className="relative text-right text-[12px] tabular-nums">
                            {/* Until its time settles in, a finishing stage keeps saying how fresh it was. */}
                            {justDone && stage.end !== undefined && (
                                <span className="sc-took-out absolute right-0 top-0 whitespace-nowrap text-muted-foreground/80" aria-hidden>
                                    {quietText(stage.end - stage.start)}
                                </span>
                            )}
                            <span key={right} className={cn('block', current ? 'text-muted-foreground/80' : 'text-muted-foreground/60', justDone && 'sc-took', justLive && 'sc-took-live')}>
                                {right}
                            </span>
                        </span>
                        {current && latest.length > 0 && (
                            <div className={cn('col-start-2 col-end-4', justLive && 'sc-took-live')}>
                                {latest.map((line, j) => (
                                    <LogLine key={`${line.text}-${j}`} line={line} />
                                ))}
                            </div>
                        )}
                        {failed && breaking && (
                            <div className="col-start-2 col-end-4">
                                <LogLine line={breaking} wrap />
                            </div>
                        )}
                    </li>
                );
            })}
        </ol>
    );
}

/** What it came to, in one line: what it made and how long it took, by its kind's own verb ("Deployed in 31s ·
 *  sample-site.noclick.site"), and what opens it; or, where it made nothing to open, what it was ("Done in 4s · Buy
 *  acme.dev"). `action` is a surface's own way in, where what it made isn't a link. */
export function DoneLine({ view, open, onToggle, action }: { view: WorkView; open?: boolean; onToggle?: () => void; action?: ReactNode }) {
    const took = (view.endedAt ?? view.workingSince) - view.workingSince;
    const verb = view.result ? view.doneVerb : 'Done';
    return (
        <div className="flex items-center gap-2 text-[13.5px]" data-testid="work-done">
            <span className="flex h-4 w-4 shrink-0 items-center justify-center">
                <Check className="h-4 w-4 text-foreground/70" strokeWidth={2.25} />
            </span>
            <span className="min-w-0 flex-1 truncate">
                <span className="text-foreground/85">{took >= 1000 ? `${verb} in ${span(took)}` : verb}</span>
                <span className="text-muted-foreground"> · {view.result?.text ?? view.title}</span>
            </span>
            {view.result?.href ? (
                <a href={view.result.href} target="_blank" rel="noopener noreferrer" className={cn(PILL_QUIET, 'h-7')}>
                    {view.result.open}
                    <ArrowUpRight className="h-3.5 w-3.5" />
                </a>
            ) : (
                action
            )}
            {onToggle && (
                <button
                    type="button"
                    onClick={onToggle}
                    aria-expanded={open}
                    aria-label="Stages"
                    className="grid h-7 w-7 place-items-center rounded-full text-muted-foreground transition-colors hover:bg-foreground/[0.05] hover:text-foreground"
                >
                    {open ? <ChevronDown className="h-3.5 w-3.5" /> : <ChevronRight className="h-3.5 w-3.5" />}
                </button>
            )}
        </div>
    );
}

/** Long work as it stands at `now`. `onRetry` tries failed work again; `doneAction` opens what it made. */
export function WorkCard({
    view,
    now,
    check = 'draw',
    fresh,
    onRetry,
    doneAction,
}: {
    view: WorkView;
    now: number;
    check?: StageCheck;
    fresh?: FreshStages;
    onRetry?: () => void;
    doneAction?: ReactNode;
}) {
    const [open, setOpen] = useState(false);
    const [log, setLog] = useState(false);
    if (view.state === 'done') {
        return (
            <div className="max-w-[560px]">
                <DoneLine view={view} open={open} onToggle={() => setOpen((v) => !v)} action={doneAction} />
                {open && (
                    <div className="tl-open mt-2.5 pl-6">
                        <StageList view={view} now={now} check={check} />
                    </div>
                )}
            </div>
        );
    }
    const failed = view.state === 'failed';
    return (
        <InlineCard
            lead={<Glyph kind={view.kind} />}
            title={view.title}
            aside={failed ? <Status state="failed">Failed</Status> : view.state === 'waiting' ? <Status state="idle">Needs you</Status> : <Clock ms={now - view.workingSince} />}
            actions={
                failed ? (
                    <>
                        {onRetry && (
                            <button type="button" className={PILL_SECONDARY} onClick={onRetry}>
                                {view.retry}
                            </button>
                        )}
                        {view.lines.length > 0 && (
                            <button type="button" className={PILL_QUIET} onClick={() => setLog((v) => !v)}>
                                {log ? 'Hide log' : 'Show log'}
                            </button>
                        )}
                    </>
                ) : undefined
            }
        >
            <StageList view={view} now={now} check={check} fresh={fresh} />
            {failed && log && (
                <div className="tl-open mt-3 rounded-xl bg-foreground/[0.03] px-3 py-2.5">
                    {view.lines.map((line, i) => (
                        <LogLine key={`${line.text}-${i}`} line={line} wrap />
                    ))}
                </div>
            )}
        </InlineCard>
    );
}
