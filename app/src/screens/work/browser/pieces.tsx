// The pieces every live view of a conversation's browser is made of, so the Beside card's tile, the rail, the turn's
// card, the big view and the phone's full screen read as one thing: a status dot in ink (a live ping while it works, a
// ringed dot while it waits on a person, never green), a caption that ticks in as the step changes, the live picture,
// the bar a person holds the browser under ("You're in control · NoClick waits · Hand back"), the steps it took, and
// the receipt an act ends in. Motion is calm and stops for reduced motion.
import { useState, type ReactNode } from 'react';
import { Check, ChevronRight, MousePointer2, X } from 'lucide-react';
import type { Browser, JsonObject, Operation } from 'noclick';
import { BrowserViewer } from './BrowserViewer';
import { SiteIcon } from '@/ui/chat/media';
import { cn } from '@/ui/utils';
import { clockOf } from '../conversation/besideItems';
import { Elapsed } from '../conversation/Activity';
import { useBrowserAct, useBrowserControl, type BrowserControl } from './useConversationBrowser';
import { captionOf, did, doing, headlineOf, isLiveState, siteOf, stateOf, whereOf, type BrowserState, type StepLike } from './words';
import { useSlot } from '@/slots';
import { REPLY_MARKDOWN } from '../slots';

export const BROWSER_CSS = `@keyframes nb-ping { 0% { transform: scale(1); opacity: .5 } 80%, 100% { transform: scale(2.8); opacity: 0 } }
.nb-ping::after { content: ""; position: absolute; inset: 0; border-radius: 9999px; background: inherit; animation: nb-ping 2s cubic-bezier(.2,.8,.2,1) infinite }
@keyframes nb-tick { from { opacity: 0; transform: translateY(3px) } }
.nb-tick { animation: nb-tick 360ms cubic-bezier(.2,.8,.2,1) both }
@keyframes nb-rise { from { opacity: 0; transform: translateY(6px) } }
.nb-rise { animation: nb-rise 420ms cubic-bezier(.2,.8,.2,1) both }
@keyframes nb-fade { from { opacity: 0 } }
.nb-fade { animation: nb-fade 240ms ease both }
.nb-shine { color: transparent; -webkit-background-clip: text; background-clip: text; background-size: 250% 100%;
  background-image: linear-gradient(90deg, hsl(var(--muted-foreground)) 0 40%, hsl(var(--foreground)) 50%, hsl(var(--muted-foreground)) 60% 100%);
  animation: nb-shine 2.4s linear infinite }
@keyframes nb-shine { from { background-position: 115% 0 } to { background-position: -115% 0 } }
@media (prefers-reduced-motion: reduce) { .nb-ping::after { display: none } .nb-tick, .nb-rise, .nb-fade { animation: none }
  .nb-shine { animation: none; background: none; color: hsl(var(--muted-foreground)) } }`;

/** The pieces' motion, once per surface that draws them. */
export function BrowserMotion() {
    return <style>{BROWSER_CSS}</style>;
}

/** The small pills of the browser's surfaces; `lg` on a phone's full screen. */
export const PILL = 'inline-flex shrink-0 items-center justify-center gap-1.5 whitespace-nowrap rounded-full font-medium transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring active:scale-[0.97] disabled:pointer-events-none disabled:opacity-50';
export const PRIMARY = cn(PILL, 'h-7 bg-primary px-3 text-[12.5px] text-primary-foreground hover:opacity-90');
export const OUTLINE = cn(PILL, 'h-7 px-3 text-[12.5px] ring-1 ring-inset ring-border hover:bg-foreground/[0.04] dark:ring-foreground/[0.15]');
export const LARGE = 'h-11 px-5 text-[14px]';

/** Whether a picture streams from it: only while it runs, or waits parked. */
export function streams(browser: Browser | null): boolean {
    return browser?.status === 'running' || browser?.status === 'parked';
}

/** Ink, never colour: a ping while it works, a ringed dot while it waits on a person, grey once it rests. */
export function StatusDot({ state, className }: { state: BrowserState; className?: string }) {
    const waits = state === 'needs' || state === 'control';
    const works = state === 'working' || state === 'starting';
    return (
        <span
            aria-hidden
            data-state={state}
            className={cn('relative inline-block shrink-0 rounded-full', waits ? 'h-2 w-2 bg-foreground ring-[3px] ring-foreground/15' : 'h-1.5 w-1.5', works && 'nb-ping bg-foreground', !waits && !works && 'bg-muted-foreground', className)}
        />
    );
}

/** A line that ticks in when it changes, shining while it's live. */
export function Caption({ text, shine, className }: { text: string; shine?: boolean; className?: string }) {
    return (
        <span key={text} className={cn('nb-tick block min-w-0 truncate', className)} aria-live="polite">
            <span className={cn(shine && 'nb-shine')}>{text}</span>
        </span>
    );
}

/** The browser's live picture: the small, slower stream (`thumb`), or the full one, yours to drive while you hold it. */
export function LivePicture({ browser, thumb, interactive = false, className }: { browser: Browser; thumb?: boolean; interactive?: boolean; className?: string }) {
    if (!streams(browser)) return <div className={cn('aspect-[16/10] bg-muted', className)} />;
    return <BrowserViewer source={{ browser }} thumb={thumb} interactive={interactive} className={className} />;
}

/** "You're in control · NoClick waits · Hand back": the bar a person holds the browser under. */
export function ControlBar({ ctl, large, className }: { ctl: BrowserControl; large?: boolean; className?: string }) {
    return (
        <div className={cn('flex items-center gap-2 rounded-full bg-popover pl-3.5 text-popover-foreground ring-1 ring-inset ring-border dark:ring-foreground/[0.15]', large ? 'h-[52px] pr-1.5' : 'h-10 pr-1', className)} data-testid="browser-control-bar">
            <MousePointer2 className="h-3.5 w-3.5 shrink-0" strokeWidth={1.8} />
            <span className="shrink-0 text-[13px] font-medium">You’re in control</span>
            {!large && <span className="min-w-0 truncate text-[11.5px] text-muted-foreground">{ctl.agentName} waits</span>}
            <span className="flex-1" />
            <button type="button" onClick={() => void ctl.handBack()} disabled={ctl.pending !== null} className={cn(PRIMARY, large && 'h-10 px-4 text-[14px]')}>
                Hand back
            </button>
        </div>
    );
}

/** Take over: the primary action while a step waits on you, a quiet one while it works. */
export function TakeOver({ ctl, quiet, large, className }: { ctl: BrowserControl; quiet?: boolean; large?: boolean; className?: string }) {
    return (
        <button type="button" onClick={() => void ctl.takeOver()} disabled={ctl.pending !== null} className={cn(quiet ? OUTLINE : PRIMARY, large && LARGE, className)}>
            Take over
        </button>
    );
}

/** Whether the person reading may take over now: a step waits on them, or the browser works and nobody holds it. */
export function canTakeOver(browser: Browser | null): boolean {
    if (!browser) return false;
    const state = stateOf(browser);
    return state === 'needs' ? !!browser.waitingOn?.forYou : state === 'working' || state === 'idle';
}

/** What it's done so far, and the step it's on: a tick each, the newest live. */
export function StepsList({ browser, className }: { browser: Browser; className?: string }) {
    const state = stateOf(browser);
    const site = siteOf(browser.url);
    const steps = browser.steps;
    const rows: { mark: ReactNode; text: string; live?: boolean }[] = steps.map((s, i) =>
        i === steps.length - 1 && state === 'working' ? { mark: <StatusDot state="working" className="mx-1" />, text: doing(s, site), live: true } : { mark: <Check className="h-3.5 w-3.5 text-muted-foreground" strokeWidth={2} />, text: did(s, site) }
    );
    if (state === 'needs' || state === 'control') rows.push({ mark: <StatusDot state={state} className="mx-[3px]" />, text: state === 'control' ? 'You’re in control' : browser.waitingOn!.person });
    if (!rows.length) return null;
    return (
        <ol className={cn('flex flex-col gap-1.5 text-[11.5px] leading-snug', className)} data-testid="browser-steps">
            {rows.map((r, i) => (
                <li key={i} className="flex min-w-0 items-center gap-2">
                    {r.mark}
                    <span className={cn('min-w-0 truncate', r.live && 'nb-shine')}>{r.text}</span>
                </li>
            ))}
        </ol>
    );
}

/** When it started working: its act's start, else its own. */
export const startOf = (browser: Browser, act?: Operation | null): number | null => (act?.startedAt ?? browser.startedAt ?? browser.createdAt)?.getTime() ?? null;

/** How long the step at hand has run: an act's, while one drives it or waits on a person (a turn's own calls on the
 *  browser have no start of their own to count from). */
const elapsedFrom = (browser: Browser, act: Operation | null, state: BrowserState): number | null =>
    state === 'starting' ? startOf(browser) : act && !act.done && (browser.acting || state === 'needs' || state === 'control') ? startOf(browser, act) : null;

/** The page it last stopped on (its act's end, or its turn's): what shows while it rests, since a picture streamed
 *  from a resting browser would connect to it, and a connected browser is billed. */
export const restingFrame = (browser: Browser, act?: Operation | null): string | null => browser.frameUrl ?? frameOf(act);

/** "· In its sandbox", "· On noclick-dev-1": where it runs, when that's beside the agent. */
function Where({ browser }: { browser: Browser }) {
    const where = whereOf(browser);
    return where ? <span className="shrink-0 text-muted-foreground" data-testid="browser-where">· {where}</span> : null;
}

/** The tile in the Beside card: the live thumbnail (opening the big view), "Browser · site", the caption with how long
 *  its step has run, and Take over while a step waits on you. Once it rests, one line: the page it stopped on, and
 *  Paused (waiting for the next turn, unbilled) or Done. */
export function BrowserTile({ ctl, act }: { ctl: BrowserControl; act: Operation | null }) {
    const browser = ctl.browser!;
    const state = stateOf(browser);
    const site = siteOf(browser.url);
    const started = elapsedFrom(browser, act, state);
    if (!isLiveState(state)) {
        const frame = restingFrame(browser, act);
        const took = state === 'done' && act?.finishedAt && act.startedAt ? clockOf(act.finishedAt.getTime() - act.startedAt.getTime()) : null;
        return (
            <button
                type="button"
                disabled={!frame}
                onClick={() => frame && ctl.show({ mode: 'still', frameUrl: frame, label: 'The last page' })}
                className="nb-rise flex h-8 w-full items-center gap-2.5 rounded-[10px] px-2 text-left text-[13px] transition-colors hover:bg-foreground/[0.04] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring/70 disabled:hover:bg-transparent"
                data-testid="browser-tile"
                data-state={state}
            >
                <span className="h-[21px] w-[34px] shrink-0 overflow-hidden rounded-[5px] bg-muted ring-1 ring-border">{frame && <img src={frame} alt="" className="h-full w-full object-cover object-top" />}</span>
                <span className="min-w-0 flex-1 truncate">
                    Browser{site && <span className="text-muted-foreground"> · {site}</span>}
                </span>
                <Where browser={browser} />
                <span className="shrink-0 text-[11.5px] tabular-nums text-muted-foreground">{state === 'idle' ? 'Paused' : `Done${took ? ` · ${took}` : ''}`}</span>
            </button>
        );
    }
    return (
        <div className="nb-rise flex flex-col gap-1.5 px-0.5 pb-0.5 pt-1" data-testid="browser-tile" data-state={state}>
            <button type="button" aria-label="Watch the browser big" onClick={() => ctl.show({ mode: 'live' })} className={cn('block overflow-hidden rounded-[14px] transition-shadow focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring', state === 'needs' || state === 'control' ? 'ring-2 ring-foreground' : 'ring-1 ring-border dark:ring-foreground/[0.1]')}>
                <LivePicture browser={browser} thumb className="rounded-none" />
            </button>
            <div className="flex min-w-0 items-center gap-2 px-1.5 text-[13px]">
                <StatusDot state={state} />
                <span className="shrink-0 font-medium">Browser</span>
                {site && <span className="min-w-0 truncate text-muted-foreground">· {site}</span>}
                <Where browser={browser} />
            </div>
            <div className="flex min-h-4 min-w-0 items-center gap-2 px-1.5 text-[11.5px]">
                <Caption text={captionOf(browser)} shine={state === 'working' || state === 'starting'} className="flex-1" />
                {started && <span className="shrink-0 text-muted-foreground"><Elapsed from={started} /></span>}
            </div>
            {state === 'needs' && browser.waitingOn?.forYou && (
                <div className="flex justify-end px-1.5 pb-1">
                    <TakeOver ctl={ctl} />
                </div>
            )}
        </div>
    );
}

/** The browser atop the open rail: its row, the tile (live while it works, the page it stopped on once it rests), its
 *  caption, Watch big or Take over, and what its newest act did. */
export function BrowserRailBlock({ ctl, act }: { ctl: BrowserControl; act: Operation | null }) {
    const browser = ctl.browser!;
    const state = stateOf(browser);
    const live = isLiveState(state);
    const site = siteOf(browser.url);
    const started = elapsedFrom(browser, act, state);
    const frame = live ? null : restingFrame(browser, act);
    return (
        <div className="flex flex-col gap-2 px-0.5 pb-1.5 pt-1" data-testid="browser-rail" data-state={state}>
            <div className="flex min-w-0 items-center gap-2 px-1.5 text-[13px]">
                <StatusDot state={state} />
                <span className="shrink-0 font-medium">Browser</span>
                {site && <span className="min-w-0 truncate text-muted-foreground">· {site}</span>}
                <Where browser={browser} />
                <span className="flex-1" />
                {started && <span className="shrink-0 text-[11.5px] text-muted-foreground"><Elapsed from={started} /></span>}
            </div>
            {live && (
                <button type="button" aria-label="Watch the browser big" onClick={() => ctl.show({ mode: 'live' })} className="block overflow-hidden rounded-[14px] ring-1 ring-border focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring dark:ring-foreground/[0.1]">
                    <LivePicture browser={browser} thumb className="rounded-none" />
                </button>
            )}
            {frame && (
                <button type="button" aria-label="See the last page it was on" onClick={() => ctl.show({ mode: 'still', frameUrl: frame, label: 'The last page' })} className="block aspect-[16/10] overflow-hidden rounded-[14px] bg-muted ring-1 ring-border focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring dark:ring-foreground/[0.1]">
                    <img src={frame} alt="The last page it was on" className="h-full w-full object-cover object-top" />
                </button>
            )}
            <div className="px-1.5 text-[11.5px]">
                <Caption text={captionOf(browser)} shine={state === 'working'} />
            </div>
            <div className="flex gap-2 px-1.5 empty:hidden">
                {live && state !== 'needs' && (
                    <button type="button" onClick={() => ctl.show({ mode: 'live' })} className={OUTLINE}>
                        Watch big
                    </button>
                )}
                {state === 'needs' && browser.waitingOn?.forYou && <TakeOver ctl={ctl} />}
            </div>
            {browser.steps.length > 0 && (state !== 'working' || browser.acting) && (
                <>
                    <p className="px-2 pt-1.5 text-[11.5px] text-muted-foreground">{live ? 'What it’s done' : 'What it did last'}</p>
                    <StepsList browser={browser} className="px-1.5" />
                </>
            )}
        </div>
    );
}

/** The conversation's browser as the Beside card's tile, in a chat that reads one. */
export function BesideBrowserTile() {
    const ctl = useBrowserControl();
    const act = useBrowserAct(ctl?.browser?.actId ?? null).data ?? null;
    return ctl?.browser ? <BrowserTile ctl={ctl} act={act} /> : null;
}

/** The conversation's browser atop the Beside rail. */
export function BesideBrowserRail() {
    const ctl = useBrowserControl();
    const act = useBrowserAct(ctl?.browser?.actId ?? null).data ?? null;
    return ctl?.browser ? <BrowserRailBlock ctl={ctl} act={act} /> : null;
}

/** The ask, in the turn it stopped: the step it waits on a person for ("Sign in to developers.example.com."), Open the
 *  browser for the person it asked (they take it over and finish it live, in NoClick's viewer), Done once they're
 *  through (their hand back, as Done on the page NoClick sent them is), and Cancel, which calls off the task. One ask
 *  with that page: finishing or calling it off in either place ends it in both. */
export function AskRow({ ctl }: { ctl: BrowserControl }) {
    const browser = ctl.browser;
    const state = browser ? stateOf(browser) : 'done';
    if (!browser || (state !== 'needs' && state !== 'control')) return null;
    const asked = browser.waitingOn;
    if (state === 'needs' && !asked) return null;
    const held = state === 'control';
    const mine = held || !!asked?.forYou;
    const busy = ctl.pending !== null;
    const line = held
        ? asked
            ? `You’re in control. ${ctl.agentName} waits.`
            : `${ctl.agentName} waits.`
        : mine
          ? 'Open the browser, finish it there, then tap Done.'
          : 'Waiting on the person it asked to finish this step.';
    return (
        <div className="nb-rise flex flex-col gap-2.5 rounded-[14px] p-3 ring-1 ring-inset ring-border dark:ring-foreground/[0.12]" data-testid="browser-ask" data-browser-ask={browser.actId ?? browser.id}>
            <div className="flex min-w-0 items-start gap-2.5">
                <StatusDot state={state} className="mt-[7px]" />
                <div className="min-w-0 flex-1">
                    <p className="text-[13.5px] font-medium leading-snug text-foreground" data-testid="browser-ask-step">
                        {asked?.person || 'You’re in control'}
                    </p>
                    <p className="mt-0.5 text-[12px] leading-snug text-muted-foreground">{line}</p>
                </div>
            </div>
            <div className="flex flex-wrap items-center gap-2 pl-[18px]">
                {held ? (
                    <>
                        <button type="button" onClick={() => void ctl.handBack()} disabled={busy} className={PRIMARY}>
                            {asked ? 'Done' : 'Hand back'}
                        </button>
                        {!ctl.shown && (
                            <button type="button" onClick={() => ctl.show({ mode: 'live' })} className={OUTLINE}>
                                Open the browser
                            </button>
                        )}
                    </>
                ) : (
                    mine && (
                        <button type="button" onClick={() => void ctl.takeOver()} disabled={busy} className={PRIMARY}>
                            Open the browser
                        </button>
                    )
                )}
                {asked && browser.actId && (
                    <button type="button" onClick={() => void ctl.cancelAct()} disabled={busy} className={OUTLINE}>
                        Cancel
                    </button>
                )}
            </div>
        </div>
    );
}

/** Whether an act stopped short of its task: it failed, or it ended saying the task isn't done (a step it left for a
 *  person, a payment with nothing ready). */
export const actStopped = (act: Operation): boolean => act.status !== 'succeeded' || (act.result as JsonObject | null)?.done === false;

/** The receipt an act ends in: the page it ended on, what came of it, and every step it took (the last one the step it
 *  stopped at, when it stopped). */
export function Receipt({ act, ctl }: { act: Operation; ctl: BrowserControl | null }) {
    const result = act.result as JsonObject | null;
    const stopped = actStopped(act);
    const took = act.finishedAt && act.startedAt ? clockOf(act.finishedAt.getTime() - act.startedAt.getTime()) : null;
    const said = act.status === 'succeeded' ? String(result?.summary ?? '').trim() : (act.error?.message ?? 'The browser’s task stopped.');
    const steps = resultSteps(act).map((s, i, all): ReceiptStep => ({ text: did(s), stopped: stopped && i === all.length - 1 }));
    const url = typeof result?.url === 'string' ? result.url : null;
    // Its page's title is known only while the act is the browser's newest.
    const title = ctl?.browser?.actId === act.id ? ctl.browser.title : null;
    // The card says it in a line; an answer longer than its line (a table of prices) waits under the steps' disclosure.
    const outcome = headlineOf(said);
    return <ReceiptView ctl={ctl} frame={frameOf(act)} url={url} pageTitle={title} outcome={outcome || 'Used a browser'} found={said && said !== outcome ? said : null} stopped={stopped} steps={steps} took={took} />;
}

/** A step as a receipt lists it: what it did, and whether the task stopped there. */
export interface ReceiptStep {
    text: string;
    stopped?: boolean;
}

/** What a turn's own calls on the page came to, in one sentence of their words: "Opened kestrel.example/pricing and read
 *  the page". */
export function outcomeOf(steps: readonly string[]): string | null {
    const said = steps.filter((s, i) => s !== steps[i - 1]);
    if (!said.length) return null;
    const lower = (s: string) => s.charAt(0).toLowerCase() + s.slice(1);
    const [first, ...rest] = said;
    if (!rest.length) return first;
    return `${[first, ...rest.slice(0, -1).map(lower)].join(', ')} and ${lower(rest[rest.length - 1])}`;
}

/** Where a page lives, beyond its host: "/orders/K-20931". */
const pathOf = (url: string | null): string | null => {
    try {
        const path = url ? new URL(url).pathname.replace(/\/+$/, '') : '';
        return path || null;
    } catch {
        return null;
    }
};

/** A receipt, page first: the page it ended on (big on a tap) with its site on it, what came of it in a line, and one
 *  quiet "4 steps · 46s" that opens, in place, what it found (`found`: the whole answer, as markdown, where it says more
 *  than its line) and every step. With no picture kept (an older browser, or a capture that failed), the site's mark
 *  and the page's name stand in, never an empty card. Stopped short, what came of it is muted and "Needs you" leads the
 *  steps. */
export function ReceiptView({ ctl, frame, url, pageTitle = null, outcome, found = null, stopped = false, steps, took = null }: { ctl: BrowserControl | null; frame: string | null; url: string | null; pageTitle?: string | null; outcome: string; found?: string | null; stopped?: boolean; steps: readonly ReceiptStep[]; took?: string | null }) {
    const MarkdownRenderer = useSlot(REPLY_MARKDOWN);
    const [open, setOpen] = useState(false);
    const host = siteOf(url);
    const count = steps.length ? `${steps.length} ${steps.length === 1 ? 'step' : 'steps'}` : null;
    const summary = [count, took].filter(Boolean).join(' · ') || (found ? 'What it found' : '');
    const opens = steps.length > 0 || !!found;
    return (
        <div className="nb-rise flex w-full max-w-[360px] flex-col rounded-[22px] bg-card p-1.5 ring-1 ring-inset ring-border dark:ring-foreground/[0.09]" data-testid="browser-receipt" data-stopped={stopped ? '' : undefined}>
            {frame ? (
                <button type="button" aria-label="See the page it ended on, big" onClick={() => ctl?.show({ mode: 'still', frameUrl: frame, label: 'The last page' })} className="relative block aspect-[16/10] w-full overflow-hidden rounded-[16px] bg-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
                    <img src={frame} alt="The page it ended on" className="h-full w-full object-cover object-top" />
                    {host && (
                        // Over the page's own picture: dark in both themes, as a caption on a video is.
                        <span className="absolute bottom-2 left-2 inline-flex h-[22px] max-w-[calc(100%-16px)] items-center gap-1 rounded-full bg-black/60 pl-1 pr-2 text-[11.5px] font-medium text-white backdrop-blur-md" data-testid="browser-receipt-site">
                            <SiteIcon site={host} className="h-3.5 w-3.5 rounded-[4px]" />
                            <span className="truncate">{host}</span>
                        </span>
                    )}
                </button>
            ) : (
                host && (
                    <div className="flex items-center gap-3 rounded-[16px] bg-foreground/[0.04] p-2.5" data-testid="browser-receipt-page">
                        <SiteIcon site={host} className="h-8 w-8 rounded-[10px] text-[13px]" />
                        <div className="flex min-w-0 flex-col">
                            <span className="truncate text-[13px] font-medium">{host}</span>
                            {(pageTitle?.trim() || pathOf(url)) && <span className="truncate text-[12px] text-muted-foreground">{pageTitle?.trim() || pathOf(url)}</span>}
                        </div>
                    </div>
                )
            )}
            <div className="flex min-w-0 flex-col gap-1.5 px-2.5 pb-2 pt-2.5">
                <p className={cn('line-clamp-2 text-pretty text-[13.5px] font-medium leading-snug', stopped && 'text-muted-foreground')} data-testid="browser-receipt-outcome">
                    {outcome}
                </p>
                {(stopped || summary) && (
                    <div className="flex items-center gap-2 text-[12px] text-muted-foreground">
                        {stopped && (
                            <span className="inline-flex items-center gap-1.5 font-medium text-red-600 dark:text-red-400">
                                <span aria-hidden className="h-1.5 w-1.5 rounded-full bg-current" />
                                Needs you
                            </span>
                        )}
                        {stopped && summary && <span aria-hidden>·</span>}
                        {summary &&
                            (opens ? (
                                <button type="button" aria-expanded={open} onClick={() => setOpen(!open)} className="-mx-2 -my-0.5 inline-flex items-center gap-1 rounded-full px-2 py-0.5 transition-colors hover:bg-foreground/[0.06] hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
                                    {summary}
                                    <ChevronRight className={cn('h-3 w-3 transition-transform', open && 'rotate-90')} strokeWidth={2} />
                                </button>
                            ) : (
                                <span>{summary}</span>
                            ))}
                    </div>
                )}
                {open && found && (
                    <div className="min-w-0 pt-1.5" data-testid="browser-receipt-found">
                        <p className="pb-1 text-[11px] text-muted-foreground">What it found</p>
                        <MarkdownRenderer content={found} className="text-[12.5px] leading-relaxed text-foreground [&_h1]:mb-1 [&_h1]:mt-3 [&_h1]:text-[13px] [&_h1]:font-medium [&_h2]:mb-1 [&_h2]:mt-3 [&_h2]:text-[13px] [&_h2]:font-medium [&_h3]:mb-1 [&_h3]:mt-3 [&_h3]:text-[12.5px] [&_h3]:font-medium [&_table]:text-[12px] [&_td]:px-2.5 [&_td]:py-1.5 [&_th]:px-2.5 [&_th]:py-1.5" />
                    </div>
                )}
                {open && steps.length > 0 && (
                    <ol className="flex flex-col gap-1.5 pb-1 pt-1.5 text-[12.5px]" data-testid="browser-receipt-steps">
                        {steps.map((s, i) => (
                            <li key={i} className="flex min-w-0 items-baseline gap-2">
                                {s.stopped ? <X className="h-3 w-3 shrink-0 translate-y-0.5 text-red-600 dark:text-red-400" strokeWidth={2} /> : <Check className="h-3 w-3 shrink-0 translate-y-0.5 text-muted-foreground" strokeWidth={2} />}
                                <span className="min-w-0 [overflow-wrap:anywhere]">{s.text}</span>
                            </li>
                        ))}
                    </ol>
                )}
            </div>
        </div>
    );
}

/** The page an act ended on, signed for an hour from each read of the act. */
export function frameOf(act: Operation | null | undefined): string | null {
    const url = act?.raw.frame_url;
    return typeof url === 'string' ? url : null;
}

/** An act's steps as its result keeps them. */
function resultSteps(act: Operation): StepLike[] {
    const result = act.result as JsonObject | null;
    const steps = Array.isArray(result?.steps) ? (result.steps as JsonObject[]) : [];
    return steps.map((s) => ({ action: String(s.action ?? ''), target: typeof s.target === 'string' ? s.target : null, url: typeof s.url === 'string' ? s.url : null }));
}
