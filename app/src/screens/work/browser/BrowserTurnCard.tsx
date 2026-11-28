// A browser act, in the turn that started it, on the Chat page and in Work alike (one card in the shared card
// registry). On a laptop the browser itself lives in the Beside card: the turn says "Using a browser · beside this
// conversation" (opening it big), carries the ask's card when a step waits on you (the step, Open the browser, Done,
// Cancel: `AskRow`), and ends in the receipt.
// On a phone the live thumbnail is in the turn: it opens full screen, a pinned chip keeps it a tap away once it
// scrolls out of sight, and it settles into the same receipt when the act is done.
import { useEffect, useMemo, useRef, useState, type RefObject } from 'react';
import { createPortal } from 'react-dom';
import { ChevronDown, Globe, Maximize2 } from 'lucide-react';
import { useNewerCard } from '@/screens/chat/cards/canvases';
import { useInPhoneShell } from '@/ui/phoneBar';
import { failed, obj, str, type CoordinatorToolCall } from '@/lib/toolCalls';
import { stepLine, stepName } from '@/lib/stepLabels';
import { cn } from '@/ui/utils';
import { Elapsed } from '@/screens/work/conversation/Activity';
import { actIdOf, BROWSER_CANVAS, isBrowserCall, operationOf } from '@/screens/chat/cards/cardMatchers';
import { AskRow, BrowserMotion, Caption, frameOf, LivePicture, outcomeOf, Receipt, ReceiptView, restingFrame, startOf, StatusDot } from './pieces';
import { useBrowserAct, useBrowserControl, type BrowserControl } from './useConversationBrowser';
import { captionOf, isLiveState, siteOf, stateOf } from './words';

export function BrowserTurnCard({ call }: { call: CoordinatorToolCall }) {
    const ctl = useBrowserControl();
    const phone = useInPhoneShell();
    const browser = ctl?.browser ?? null;
    // A call still running names no act yet: it's the one driving the conversation's browser.
    const opId = actIdOf(call) ?? (call.running && browser?.acting ? browser.actId : null);
    const act = useBrowserAct(opId).data ?? null;
    const live = !!ctl && !!browser && !act?.done && (call.running || (!!opId && browser.actId === opId)) && stateOf(browser) !== 'done';
    return (
        <div className="flex flex-col gap-2.5" data-testid="browser-turn-card" data-live={live ? '' : undefined}>
            <BrowserMotion />
            {live && phone && <Inline ctl={ctl} act={act} />}
            {!phone && (live || act?.done) && <ActRow ctl={ctl} live={live} frame={frameOf(act)} />}
            {live && <AskRow ctl={ctl} />}
            {act?.done && <Receipt act={act} ctl={ctl} />}
        </div>
    );
}

/** A turn that used the conversation's browser without an act: it opened and read pages itself (a follow-up "now open
 *  apple.com"). Drawn on the turn's first browser call, as an act's card is: live while the turn has the browser (in the
 *  Beside card on a laptop, in the turn on a phone, with the ask and Take over), then its receipt: the page the turn
 *  left it on and what it did. Only the thread's newest browser card is live and pictured; an older one is a line. */
export function BrowserUseCard({ call, turn }: { call: CoordinatorToolCall; turn?: readonly CoordinatorToolCall[] }) {
    const ctl = useBrowserControl();
    const phone = useInPhoneShell();
    const browser = ctl?.browser ?? null;
    const calls = useMemo(() => (turn ?? [call]).filter((c) => isBrowserCall(c) && !failed(c.result)), [turn, call]);
    const newer = useNewerCard(call.id, BROWSER_CANVAS);
    const newest = !newer || calls.some((c) => c.id === newer.id);
    const running = calls.find((c) => c.running) ?? null;
    // At work while one of its calls runs, or while the browser it left works on (the turn hasn't ended).
    const atWork = newest && (!!running || (!!browser && isLiveState(stateOf(browser))));
    // Live once there's a browser to show (a first call still starting one has none to read yet).
    const live = atWork && !!ctl && !!browser;
    // Each call said as the turn's log says it (@/lib/stepLabels): "Opened kestrel.example/pricing".
    const steps = calls.flatMap((c) => (stepOf(c) ? [{ text: said(c, 'done') }] : []));
    const url = [...calls].reverse().map(pageOf).find(Boolean) ?? (newest ? (browser?.url ?? null) : null);
    return (
        <div className="flex flex-col gap-2.5" data-testid="browser-use-card" data-live={atWork ? '' : undefined}>
            <BrowserMotion />
            {live && phone && <Inline ctl={ctl} act={null} caption={running && stepOf(running) ? said(running, 'running') : null} />}
            {atWork && !(live && phone) && <ActRow ctl={ctl} live frame={null} />}
            {live && <AskRow ctl={ctl} />}
            {!atWork && newest && (
                <ReceiptView ctl={ctl} frame={browser ? restingFrame(browser) : null} url={url} pageTitle={browser?.title ?? null} outcome={outcomeOf(steps.map((s) => s.text)) ?? 'Used a browser'} steps={steps} />
            )}
            {!newest && <ActRow ctl={null} live={false} frame={null} site={siteOf(url)} />}
        </div>
    );
}

// The calls that do something on the page (asking for the browser isn't a step of the turn's).
const PAGE_CALLS = new Set(['browsers_goto', 'browsers_content', 'browsers_extract', 'browsers_screenshot']);

const operationOfCall = (call: CoordinatorToolCall) => (call.tool === 'api_call' ? operationOf(call) : call.tool.replace(/^browser__/, 'browsers_'));

/** Whether a call of the turn did something on the page. */
const stepOf = (call: CoordinatorToolCall): boolean => PAGE_CALLS.has(operationOfCall(call) ?? '');

/** A call as the turn's log says it: "Opening kestrel.example/pricing", "Read the page". */
function said(call: CoordinatorToolCall, phase: 'running' | 'done'): string {
    const { head, tail } = stepLine(stepName(call.tool, call.args, phase));
    return `${head}${tail ?? ''}`.replace(/\u00a0/g, ' ');
}

/** The page a call opened: where it landed, else where it was sent. */
function pageOf(call: CoordinatorToolCall): string | undefined {
    if (operationOfCall(call) !== 'browsers_goto') return undefined;
    return str(obj(call.result, 'response'), 'url') ?? str(call.result, 'url') ?? str(obj(call.args, 'arguments') ?? call.args, 'url');
}

/** "Using a browser · beside this conversation": the browser is in the Beside card; this opens it big. */
function ActRow({ ctl, live, frame, site }: { ctl: BrowserControl | null; live: boolean; frame: string | null; site?: string | null }) {
    const open = () => (live ? ctl?.show({ mode: 'live' }) : frame && ctl?.show({ mode: 'still', frameUrl: frame, label: 'The last page' }));
    return (
        <button type="button" onClick={open} disabled={!live && !frame} className="inline-flex h-[30px] max-w-full items-center gap-2 self-start rounded-full pl-2.5 pr-3 text-[13px] ring-1 ring-inset ring-border transition-colors hover:bg-foreground/[0.04] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:hover:bg-transparent dark:ring-foreground/[0.09]">
            <Globe className="h-3.5 w-3.5 shrink-0 text-muted-foreground" strokeWidth={1.8} />
            <span className="shrink-0 font-medium">{live ? 'Using a browser' : 'Used a browser'}</span>
            <span className="min-w-0 truncate text-[11.5px] text-muted-foreground">{site ?? 'beside this conversation'}</span>
        </button>
    );
}

/** The phone's live card in the turn: its row, the thumbnail (full screen on a tap), and the caption with Take over.
 *  `caption`: the turn's call at work on the page, as its log says it, where no act drives it. */
function Inline({ ctl, act, caption = null }: { ctl: BrowserControl; act: ReturnType<typeof useBrowserAct>['data'] | null; caption?: string | null }) {
    const browser = ctl.browser!;
    const state = stateOf(browser);
    const box = useRef<HTMLButtonElement>(null);
    const started = act ? startOf(browser, act) : null;
    return (
        <div className="nb-rise flex flex-col gap-2" data-testid="browser-inline">
            <div className="flex min-h-7 min-w-0 items-center gap-2 text-[13px]">
                <Globe className="h-4 w-4 shrink-0 text-muted-foreground" strokeWidth={1.8} />
                <span className="shrink-0 font-medium">Using a browser</span>
                <span className="min-w-0 truncate text-[11.5px] text-muted-foreground">{siteOf(browser.url)}</span>
                <span className="flex-1" />
                {started && <span className="shrink-0 text-[11.5px] text-muted-foreground"><Elapsed from={started} /></span>}
                <button type="button" aria-label="Watch it full screen" onClick={() => ctl.show({ mode: 'live' })} className="grid h-10 w-10 shrink-0 place-items-center rounded-full text-muted-foreground transition-colors hover:bg-foreground/[0.06] hover:text-foreground">
                    <Maximize2 className="h-4 w-4" strokeWidth={1.8} />
                </button>
            </div>
            <button ref={box} type="button" aria-label="Watch it full screen" onClick={() => ctl.show({ mode: 'live' })} className={cn('block overflow-hidden rounded-[14px] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring', state === 'needs' || state === 'control' ? 'ring-2 ring-foreground' : 'ring-1 ring-border')}>
                <LivePicture browser={browser} thumb className="rounded-none" />
            </button>
            <div className="flex min-h-7 min-w-0 items-center gap-2 text-[12.5px]">
                <StatusDot state={state} />
                <Caption text={caption && state === 'working' ? caption : captionOf(browser)} shine={state === 'working' || state === 'starting'} className="flex-1" />
                {/* A step that waits on you is the ask card's, under it. */}
            </div>
            <PinnedChip ctl={ctl} target={box} />
        </div>
    );
}

/** Pinned under the phone's bar while the live card is out of sight: the browser one tap away. */
function PinnedChip({ ctl, target }: { ctl: BrowserControl; target: RefObject<HTMLElement | null> }) {
    const [away, setAway] = useState(false);
    useEffect(() => {
        const el = target.current;
        if (!el || typeof IntersectionObserver === 'undefined') return;
        const seen = new IntersectionObserver(([e]) => setAway(!e.isIntersecting), { threshold: 0.15 });
        seen.observe(el);
        return () => seen.disconnect();
    }, [target]);
    if (!away || !ctl.browser || ctl.shown) return null;
    const state = stateOf(ctl.browser);
    const still = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches;
    return createPortal(
        <button
            type="button"
            onClick={() => target.current?.scrollIntoView({ block: 'center', behavior: still ? 'auto' : 'smooth' })}
            className="nb-rise fixed left-1/2 top-[calc(env(safe-area-inset-top)+64px)] z-40 flex h-8 max-w-[calc(100vw-32px)] -translate-x-1/2 items-center gap-2 rounded-full bg-composer pl-3 pr-2.5 text-[12.5px] shadow-[0_18px_48px_-18px_rgba(0,0,0,0.4)] ring-1 ring-inset ring-border"
            data-testid="browser-pinned-chip"
        >
            <StatusDot state={state} />
            <span className="shrink-0 font-medium">Browser</span>
            <Caption text={captionOf(ctl.browser)} className="text-[11.5px] text-muted-foreground" />
            <ChevronDown className="h-3.5 w-3.5 shrink-0 text-muted-foreground" strokeWidth={2} />
        </button>,
        document.body
    );
}
