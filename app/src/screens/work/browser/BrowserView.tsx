// The conversation's browser, big: on a laptop a panel over the chat (the page live, its caption in a pill under it,
// Take over in its head, and while you hold it the bar "You're in control · NoClick waits · Hand back" across its
// top); on a phone the whole screen (the page, its caption, the step that waits on you with Take over, and while you
// hold it the bar, a box that types into the page, and what it's done). Mounted once per chat, opened from the tile,
// the turn's card or Take over; it also shows the still page an act ended on.
import { useEffect, useLayoutEffect, useRef, useState, type FormEvent } from 'react';
import { createPortal } from 'react-dom';
import { ChevronDown, Minimize2 } from 'lucide-react';
import { useInPhoneShell } from '@/ui/phoneBar';
import { useBrowserView } from './useBrowserView';
import { cn } from '@/ui/utils';
import { BrowserMotion, canTakeOver, Caption, ControlBar, LARGE, LivePicture, OUTLINE, restingFrame, StatusDot, StepsList, TakeOver } from './pieces';
import { useBrowserControl, type BrowserControl, type BrowserShown } from './useConversationBrowser';
import { captionOf, isLiveState, stateOf } from './words';

const reduced = () => typeof window !== 'undefined' && !!window.matchMedia?.('(prefers-reduced-motion: reduce)').matches;

/** The view of the chat's browser, where it's open. */
export function ConversationBrowserView() {
    const ctl = useBrowserControl();
    const phone = useInPhoneShell();
    const [mounted, setMounted] = useState(false);
    useEffect(() => setMounted(true), []);
    // A hand-back puts the live view away a moment after, as the agent takes the page again.
    const state = ctl?.browser ? stateOf(ctl.browser) : 'done';
    const held = useRef(false);
    const putAway = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
    useEffect(() => {
        if (state === 'control') {
            held.current = true;
            return;
        }
        // Whatever it moves to next (working, then resting) doesn't call this off.
        if (held.current && ctl?.shown?.mode === 'live') putAway.current = setTimeout(() => ctl.hide(), 900);
        held.current = false;
    }, [state]); // eslint-disable-line react-hooks/exhaustive-deps
    useEffect(() => () => clearTimeout(putAway.current), []);
    if (!mounted || !ctl?.shown || (ctl.shown.mode === 'live' && !ctl.browser)) return null;
    return createPortal(
        <>
            <BrowserMotion />
            {phone ? <FullScreen ctl={ctl} /> : <BigView ctl={ctl} />}
        </>,
        document.body
    );
}

/** What the view shows: the browser live while it works (or a person holds it), else a still page: the one it was
 *  opened on, or the page a resting browser stopped on (streaming from it would connect to it, and a connected
 *  browser is billed). */
function shownOf(shown: BrowserShown, browser: BrowserControl['browser']): { streaming: boolean; still: string | null } {
    if (shown.mode === 'still') return { streaming: false, still: shown.frameUrl };
    if (browser && isLiveState(stateOf(browser))) return { streaming: true, still: null };
    return { streaming: false, still: browser ? restingFrame(browser) : null };
}

/** A resting browser with no page kept yet: where it stands, in its place. */
function NoPicture({ browser, className }: { browser: BrowserControl['browser']; className?: string }) {
    return <div className={cn('grid aspect-[16/10] w-full place-items-center bg-muted text-[13px] text-muted-foreground ring-1 ring-border', className)}>{browser ? captionOf(browser) : 'Closed'}</div>;
}

function useEscape(close: () => void) {
    useEffect(() => {
        const onKey = (e: KeyboardEvent) => e.key === 'Escape' && close();
        window.addEventListener('keydown', onKey);
        return () => window.removeEventListener('keydown', onKey);
    }, [close]);
}

function BigView({ ctl }: { ctl: BrowserControl }) {
    const panel = useRef<HTMLDivElement>(null);
    const live = ctl.shown!.mode === 'live';
    const browser = ctl.browser;
    const state = live && browser ? stateOf(browser) : 'done';
    const { streaming, still } = shownOf(ctl.shown!, browser);
    useEscape(ctl.hide);
    // It grows out of where it was opened, and settles calmly.
    useLayoutEffect(() => {
        if (!reduced()) panel.current?.animate([{ opacity: 0, transform: 'scale(.96) translateY(8px)' }, { opacity: 1, transform: 'none' }], { duration: 320, easing: 'cubic-bezier(.32,.72,0,1)' });
        panel.current?.focus();
    }, []);
    return (
        <div className="fixed inset-0 z-[60] flex items-center justify-center p-6" data-testid="browser-big-view">
            <button type="button" aria-label="Shrink it back" tabIndex={-1} onClick={ctl.hide} className="nb-fade absolute inset-0 cursor-default bg-background/70 backdrop-blur-[2px]" />
            <div ref={panel} tabIndex={-1} role="dialog" aria-label="The browser, big" className="relative flex max-h-full w-full max-w-[920px] flex-col rounded-[26px] bg-composer px-2 pb-2 shadow-[0_24px_56px_-20px_rgba(0,0,0,0.6)] outline-none ring-1 ring-inset ring-border dark:ring-foreground/[0.09]">
                <div className="flex h-[46px] shrink-0 items-center gap-2 pl-2.5 text-[13px]">
                    <StatusDot state={state} />
                    <span className="shrink-0 font-medium">{live ? 'Browser' : (ctl.shown as { label: string }).label}</span>
                    {live && browser?.url && <span className="min-w-0 truncate text-[11.5px] text-muted-foreground">{browser.url.replace(/^https?:\/\//, '')}</span>}
                    <span className="flex-1" />
                    {live && state !== 'control' && canTakeOver(browser) && <TakeOver ctl={ctl} quiet={state !== 'needs'} />}
                    <button type="button" aria-label="Shrink it back" onClick={ctl.hide} className="grid h-8 w-8 shrink-0 place-items-center rounded-full text-muted-foreground transition-colors hover:bg-foreground/[0.06] hover:text-foreground">
                        <Minimize2 className="h-4 w-4" strokeWidth={1.8} />
                    </button>
                </div>
                <div className="relative min-h-0">
                    {streaming && browser ? (
                        <>
                            <LivePicture browser={browser} interactive={state === 'control'} className={cn('rounded-[18px] transition-shadow', state === 'control' ? 'ring-2 ring-foreground' : state === 'needs' ? 'ring-2 ring-foreground/70' : 'ring-1 ring-border')} />
                            <div className={cn('absolute inset-x-2.5 top-2.5 transition-all duration-300 motion-reduce:transition-none', state === 'control' ? 'translate-y-0 opacity-100' : 'pointer-events-none -translate-y-14 opacity-0')}>
                                <ControlBar ctl={ctl} />
                            </div>
                            {/* A caption over the page's own picture: dark in both themes, as a video's is. */}
                            <div className={cn('absolute bottom-3.5 left-1/2 flex h-8 max-w-[80%] -translate-x-1/2 items-center rounded-full bg-black/80 px-3.5 text-[12.5px] text-white backdrop-blur transition-opacity', state === 'control' && 'opacity-0')}>
                                <Caption text={captionOf(browser)} shine={false} />
                            </div>
                        </>
                    ) : still ? (
                        <img src={still} alt="The page it ended on" className="block w-full rounded-[18px] ring-1 ring-border" />
                    ) : (
                        <NoPicture browser={browser} className="rounded-[18px]" />
                    )}
                </div>
            </div>
        </div>
    );
}

function FullScreen({ ctl }: { ctl: BrowserControl }) {
    const live = ctl.shown!.mode === 'live';
    const browser = ctl.browser;
    const state = live && browser ? stateOf(browser) : 'done';
    const { streaming, still } = shownOf(ctl.shown!, browser);
    useEscape(ctl.hide);
    return (
        <div role="dialog" aria-label="The browser" className="nb-fade fixed inset-0 z-[60] flex flex-col gap-3 overflow-y-auto bg-background px-4 pb-7 pt-[env(safe-area-inset-top)]" data-testid="browser-full-screen">
            <div className="-mx-1.5 flex h-14 shrink-0 items-center gap-1.5">
                <button type="button" aria-label="Back to the chat" onClick={ctl.hide} className="grid h-10 w-10 place-items-center rounded-full text-muted-foreground transition-colors hover:bg-foreground/[0.06] hover:text-foreground">
                    <ChevronDown className="h-5 w-5" strokeWidth={1.8} />
                </button>
                <div className="min-w-0 flex-1">
                    <p className="text-[14px] font-medium">{live ? 'Browser' : (ctl.shown as { label: string }).label}</p>
                    {live && browser?.url && <p className="truncate text-[11.5px] text-muted-foreground">{browser.url.replace(/^https?:\/\//, '')}</p>}
                </div>
                <StatusDot state={state} className="mr-2" />
            </div>
            {streaming && browser ? (
                <>
                    <LivePicture browser={browser} interactive={state === 'control'} className={cn('rounded-2xl', state === 'control' ? 'ring-2 ring-foreground' : 'ring-1 ring-border')} />
                    {state !== 'control' && (
                        <div className="min-h-5 text-[13px]">
                            <Caption text={captionOf(browser)} shine={state === 'working' || state === 'starting'} />
                        </div>
                    )}
                    {state === 'needs' && browser.waitingOn && (
                        <div className="flex flex-col gap-1 rounded-[22px] bg-card px-4 pb-4 pt-3.5 ring-1 ring-inset ring-border">
                            <p className="text-[14px] font-medium">{browser.waitingOn.person}</p>
                            <p className="text-[12.5px] text-muted-foreground">{browser.waitingOn.forYou ? 'Take over, finish it, then hand it back.' : 'Waiting on the person it asked to finish this step.'}</p>
                            {browser.waitingOn.forYou && <TakeOver ctl={ctl} large className="mt-2.5 w-full" />}
                        </div>
                    )}
                    {state === 'working' && <TakeOver ctl={ctl} quiet large className="self-start" />}
                    {state === 'control' && (
                        <div className="flex flex-col gap-2.5">
                            <ControlBar ctl={ctl} large />
                            <TypeBox browser={browser} />
                        </div>
                    )}
                    <StepsList browser={browser} className="pt-1 text-[13px]" />
                </>
            ) : (
                <>
                    {still ? <img src={still} alt="The page it ended on" className="block w-full rounded-2xl ring-1 ring-border" /> : <NoPicture browser={browser} className="rounded-2xl" />}
                    {live && browser && state !== 'done' && (
                        <>
                            <p className="text-[13px] text-muted-foreground">{captionOf(browser)}</p>
                            {canTakeOver(browser) && <TakeOver ctl={ctl} quiet large className="self-start" />}
                        </>
                    )}
                </>
            )}
        </div>
    );
}

/** A phone types into the page here: tap a field in the picture, then type, and Enter. */
function TypeBox({ browser }: { browser: NonNullable<BrowserControl['browser']> }) {
    // The picture's own feed: the same socket, so what's typed lands where the person tapped.
    const { send } = useBrowserView({ browser }, { control: true });
    const [text, setText] = useState('');
    const flush = () => {
        if (text) send({ type: 'text', text: text.slice(0, 2000) });
        setText('');
    };
    const submit = (e: FormEvent) => {
        e.preventDefault();
        flush();
    };
    return (
        <form onSubmit={submit} className="flex gap-2">
            <input value={text} onChange={(e) => setText(e.target.value)} aria-label="Type into the page" placeholder="Type into the page" autoComplete="off" enterKeyHint="send" className="h-11 min-w-0 flex-1 rounded-full bg-transparent px-4 text-[14px] outline-none ring-1 ring-inset ring-border placeholder:text-muted-foreground focus:ring-2 focus:ring-foreground" />
            <button
                type="button"
                onClick={() => {
                    flush();
                    send({ type: 'key', key: 'Enter' });
                }}
                className={cn(OUTLINE, LARGE)}
            >
                Enter
            </button>
        </form>
    );
}
