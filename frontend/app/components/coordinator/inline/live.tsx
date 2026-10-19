// Work that takes a while, as one primitive: a build, an agent's background run, a call NoClick is on, a video being
// made. While it runs it shows how long it's been, what it has done and what it's doing; "Keep in background" folds it
// to a live strip in the thread, and it ends as a one-line receipt (or, when it fails, the fix).
import { useState, type ReactNode } from 'react';
import { Phone, PhoneMissed } from 'lucide-react';
import { cn } from '~/lib/utils';
import { CallLines } from './channels';
import { GlyphTile, InlineCard, LiveDot, PILL_QUIET, PILL_SECONDARY, ProgressBar, Receipt, Status, StepList, useElapsed, type Step } from './primitives';

export type LiveState = 'running' | 'background' | 'done' | 'stopped' | 'failed';

/** The fold-to-a-strip state every live card keeps for itself. */
export function useLiveState(state: LiveState): [LiveState, (next: LiveState) => void] {
    const [folded, setFolded] = useState(false);
    const shown: LiveState = state === 'running' && folded ? 'background' : state;
    return [shown, (next) => setFolded(next === 'background')];
}

export interface LiveWorkProps {
    lead?: ReactNode;
    title: string;
    meta?: ReactNode;
    /** When it started (ms), for the clock. */
    since: number;
    /** When it ended (ms), once it has; the clock reads up to then. */
    until?: number;
    state: LiveState;
    /** Folds it to the strip and back. */
    onState: (state: LiveState) => void;
    /** What it's doing this moment, for the folded strip. */
    current?: ReactNode;
    steps?: Step[];
    progress?: { done: number; total: number; label: ReactNode };
    children?: ReactNode;
    /** This work's own actions (Listen in, Pause), ahead of Keep in background. */
    actions?: ReactNode;
    /** Stopping it, where the work can be stopped. */
    onStop?: () => void;
    stopLabel?: string;
    /** A stop is on its way: the button waits. */
    stopping?: boolean;
    /** The receipt once it's done. */
    done: ReactNode;
    doneAction?: ReactNode;
    /** What it says when it fails, and what fixes it. */
    failure?: { reason?: ReactNode; actions?: ReactNode };
}

export function LiveWork({ lead, title, meta, since, until, state, onState, current, steps, progress, children, actions, onStop, stopLabel = 'Stop', stopping, done, doneAction, failure }: LiveWorkProps) {
    const live = state === 'running' || state === 'background';
    const elapsed = useElapsed(since, live, until);
    if (state === 'background') {
        return (
            <div className="flex w-full max-w-[560px] items-center gap-2.5 rounded-full border border-border py-1.5 pl-3.5 pr-1.5 text-[13.5px] dark:border-foreground/[0.1]">
                <LiveDot />
                <span className="shrink-0 text-foreground">{title}</span>
                <span className="shrink-0 tabular-nums text-muted-foreground">{elapsed}</span>
                {current && <span className="min-w-0 flex-1 truncate text-muted-foreground">· {current}</span>}
                <button type="button" className={cn(PILL_QUIET, 'ml-auto h-7')} onClick={() => onState('running')}>
                    Show
                </button>
            </div>
        );
    }
    if (state === 'done') {
        return (
            <Receipt action={doneAction}>
                {done} · took {elapsed}
            </Receipt>
        );
    }
    if (state === 'stopped') {
        return <Receipt tone="info">Stopped after {elapsed}. Nothing after that point happened.</Receipt>;
    }
    return (
        <InlineCard
            lead={lead}
            title={title}
            meta={state === 'failed' && failure?.reason ? failure.reason : meta}
            aside={
                state === 'failed' ? (
                    <Status state="failed">Failed</Status>
                ) : (
                    <span className="inline-flex items-center gap-2 text-[12.5px] tabular-nums text-foreground/75">
                        <LiveDot />
                        {elapsed}
                    </span>
                )
            }
            actions={
                state === 'failed' ? (
                    failure?.actions
                ) : (
                    <>
                        {actions}
                        <button type="button" className={PILL_SECONDARY} onClick={() => onState('background')}>
                            Keep in background
                        </button>
                        {onStop && (
                            <button type="button" className={PILL_QUIET} onClick={onStop} disabled={stopping}>
                                {stopLabel}
                            </button>
                        )}
                    </>
                )
            }
        >
            {progress || steps || children ? (
                <div className="space-y-3">
                    {progress && (
                        <div className="space-y-1.5">
                            <div className="flex items-baseline justify-between gap-3 text-[13.5px]">
                                <span className="min-w-0 truncate text-foreground/85">{progress.label}</span>
                                <span className="shrink-0 tabular-nums text-muted-foreground">
                                    {progress.done} of {progress.total}
                                </span>
                            </div>
                            <ProgressBar done={progress.done} total={progress.total} />
                        </div>
                    )}
                    {steps && <StepList steps={steps} />}
                    {children}
                </div>
            ) : null}
        </InlineCard>
    );
}

// ── A call NoClick placed ────────────────────────────────────────────────────

export type CallOutcome = 'completed' | 'not_connected' | 'failed' | 'expired';

export interface LiveCallProps {
    /** Who it calls, and the line it calls from, as shown. */
    to: string;
    from?: string;
    state: 'calling' | 'answered' | 'ended';
    outcome?: CallOutcome;
    /** You hung up, from here. */
    endedByYou?: boolean;
    /** When it was placed, picked up and ended (ms). */
    placedAt: number;
    answeredAt?: number;
    endedAt?: number;
    lines: { who: 'them' | 'noclick'; text: string }[];
    onHangUp?: () => void;
    hangingUp?: boolean;
}

// The latest lines: the call is what's being said now. The whole call comes in the note when it ends.
const LINES_SHOWN = 6;

/** A call NoClick is on for you: "Calling…" until it's picked up, then what's said as it's said, with Hang up; it
 *  ends as one line, leaving the summary and the recording to the note that follows. */
export function LiveCall({ to, from, state, outcome, endedByYou, placedAt, answeredAt, endedAt, lines, onHangUp, hangingUp }: LiveCallProps) {
    const [shown, setShown] = useLiveState(state === 'ended' ? 'done' : 'running');
    const [all, setAll] = useState(false);
    if (state === 'ended' && outcome && outcome !== 'completed') {
        return (
            <Receipt tone="info" lead={<PhoneMissed className="h-4 w-4 shrink-0 text-foreground/60" />}>
                {outcome === 'not_connected'
                    ? endedByYou
                        ? `You hung up before ${to} answered`
                        : `${to} didn’t answer`
                    : outcome === 'failed'
                      ? `The call to ${to} didn’t go through`
                      : `Lost track of the call to ${to}`}
            </Receipt>
        );
    }
    const said = lines.map((line) => ({ who: line.who === 'them' ? 'Them' : 'NoClick', text: line.text }));
    const visible = all ? said : said.slice(-LINES_SHOWN);
    return (
        <LiveWork
            lead={
                <GlyphTile>
                    <Phone className="h-4 w-4" />
                </GlyphTile>
            }
            title={`Calling ${to}`}
            meta={from ? `From ${from}` : undefined}
            since={answeredAt ?? placedAt}
            until={endedAt}
            state={shown}
            onState={setShown}
            current={state === 'calling' ? 'Calling…' : said.at(-1)?.text ?? 'Picked up'}
            onStop={onHangUp}
            stopLabel={hangingUp ? 'Hanging up…' : 'Hang up'}
            stopping={hangingUp}
            done={endedByYou ? `You ended the call with ${to}` : `Call with ${to} ended`}
        >
            {state === 'calling' ? (
                <p className="text-[14px] text-muted-foreground">Calling…</p>
            ) : said.length ? (
                <div className="space-y-2">
                    <CallLines lines={visible} live testId="coordinator-live-call" />
                    {said.length > LINES_SHOWN && (
                        <button type="button" className={cn(PILL_QUIET, 'h-7 px-2')} onClick={() => setAll((v) => !v)}>
                            {all ? 'Show the latest' : `Show all ${said.length} lines`}
                        </button>
                    )}
                </div>
            ) : (
                <p className="text-[14px] text-muted-foreground">Picked up. What’s said shows up here.</p>
            )}
        </LiveWork>
    );
}
