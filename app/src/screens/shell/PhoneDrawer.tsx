// The phone's sidebar as a drawer under the page, and the page's way back and forward. A swipe across the page slides
// the page right off the drawer, following the finger, as a rounded card that dims; a swipe across either (or a tap on
// the page) slides it back; let go and it settles by where it was and how fast the finger moved. On a page one level
// down the same swipe slides the page off the screen it came from (a picture of it, phoneStack.ts) and goes back;
// after going back, a swipe the other way brings the screen just left back in over the page. Once first drawn (when the
// phone is idle after the first page) the sidebar stays mounted, so opening never waits on it rendering.
import { useEffect, useRef, useState, type ReactNode, type RefObject } from 'react';
import { createPortal } from 'react-dom';
import { useInRouterContext, useNavigate } from 'react-router';
import { SIDEBAR_SHEET, SIDEBAR_SHEET_OVERLAY, SidebarScaleProvider } from '@/ui/sidebarParts';
import { FIELDS, anotherLayerOpen, readDirection, releaseVelocity, settleMs, settlesOpen, takesItsOwnSwipe, type SwipeMode } from './phoneSwipe';
import { ScreensUnder, capture, here, isDeeper, show, type Shot } from './phoneStack';

interface PhoneDrawerProps {
    open: boolean;
    onOpenChange: (open: boolean) => void;
    /** The bar's way back on a page one level down, if there is one: a swipe presses it instead of opening the drawer. */
    back: () => HTMLElement | null;
    /** The control that opens the drawer, which focus returns to as it closes. */
    trigger: RefObject<HTMLElement | null>;
    /** The page, which slides right off the drawer (it carries `PHONE_PAGE`). */
    page: RefObject<HTMLElement | null>;
    children: ReactNode;
}

interface Gesture {
    /** What the swipe does, once its direction is read. */
    mode: SwipeMode | null;
    /** What a swipe right does here, and a swipe left (null: nothing). */
    right: SwipeMode | null;
    left: SwipeMode | null;
    target: Element | null;
    x0: number;
    y0: number;
    /** Where the finger was when the touch was read as a swipe, so what moves moves from there without a jump. */
    lockedAt: number | null;
    /** How open the drawer was then, 0 shut to 1 open. */
    from: number;
    dx: number;
    samples: { t: number; x: number }[];
    back: HTMLElement | null;
}

/** The screen just left by going back, which a swipe left brings back while nothing else has moved. */
interface Forward {
    to: string;
    from: string;
    shot: Shot;
}

type Go = (to: string) => void;

const EASE = 'cubic-bezier(0.2, 0.9, 0.3, 1)';
/** The page's near corners, rounded as it leaves (matching PHONE_PAGE's open radius). */
const RADIUS = 44;
/** How far behind the drawer starts, as a share of its width: it drifts in under the page. */
const PARALLAX = 0.18;
/** How far behind the screen under a page starts, as a share of the screen, and how dark it is there. */
const PEEK = 0.3;
const SHADE = 0.35;
/** The edge of a page sliding over another. */
const EDGE = '-12px 0 32px rgba(0, 0, 0, 0.4)';
/** How long going back or forward waits for the screen it lands on to render before it shows it anyway. */
const RENDER_WAIT_MS = 800;
/** How long after a tap its navigation still counts as the tap's. */
const TAP_LEADS_MS = 1500;

/** Over the page while it's pushed aside, so a tap or a swipe there closes the drawer (the page itself is inert). */
const CATCHER = 'pointer-events-none fixed inset-y-0 right-0 left-[min(80vw,340px)] z-[2] data-[open=true]:pointer-events-auto';
/** The screen a back swipe goes to, under the page; the page dims as the screen just left slides in over it. */
const UNDER = 'pointer-events-none invisible fixed inset-0 z-0 overflow-hidden bg-background';
const PAGE_SHADE = 'pointer-events-none invisible fixed inset-0 z-[2] bg-black opacity-0';
const OVER = 'pointer-events-none invisible fixed inset-0 z-[3] overflow-hidden bg-background';

/** Hands up the router's navigate where there is a router (the shell also draws without one, in tests and labs). */
function RouterGo({ into }: { into: { current: Go | null } }) {
    const navigate = useNavigate();
    useEffect(() => {
        into.current = (to) => void navigate(to);
        return () => {
            into.current = null;
        };
    }, [navigate, into]);
    return null;
}

/** Calls `then` once `done` holds (checked each frame) and the frame after has painted, or after `RENDER_WAIT_MS`. */
function whenRendered(done: () => boolean, then: () => void) {
    const start = performance.now();
    const check = () => {
        if (done() || performance.now() - start > RENDER_WAIT_MS) requestAnimationFrame(then);
        else requestAnimationFrame(check);
    };
    requestAnimationFrame(check);
}

export function PhoneDrawer({ open, onOpenChange, back, trigger, page, children }: PhoneDrawerProps) {
    const sheet = useRef<HTMLDivElement>(null);
    const dim = useRef<HTMLDivElement>(null);
    const under = useRef<HTMLDivElement>(null);
    const underShot = useRef<HTMLDivElement>(null);
    const underShade = useRef<HTMLDivElement>(null);
    const pageShade = useRef<HTMLDivElement>(null);
    const over = useRef<HTMLDivElement>(null);
    const go = useRef<Go | null>(null);
    const routed = useInRouterContext();
    const [host, setHost] = useState<HTMLElement | null>(null);
    const [pageEl, setPageEl] = useState<HTMLElement | null>(null);
    const [drawn, setDrawn] = useState(open);
    const live = useRef({ open, back, onOpenChange });
    live.current = { open, back, onOpenChange };

    useEffect(() => {
        setHost(document.body);
        setPageEl(page.current);
    }, [page]);

    // Drawn ahead of the first swipe on a touch screen, once the page has painted and the phone has a moment; elsewhere
    // when first opened.
    useEffect(() => {
        if (drawn) return;
        if (open) return setDrawn(true);
        if (!window.matchMedia?.('(pointer: coarse)').matches) return;
        if (typeof window.requestIdleCallback === 'function') {
            const idle = window.requestIdleCallback(() => setDrawn(true), { timeout: 2000 });
            return () => window.cancelIdleCallback(idle);
        }
        const timer = window.setTimeout(() => setDrawn(true), 500);
        return () => window.clearTimeout(timer);
    }, [drawn, open]);

    // Opened, focus moves into the drawer itself (not a field, which would raise the keyboard); closed with focus
    // inside it, focus goes back to the menu button for someone on a keyboard, and nowhere for a finger: a focused
    // button draws its focus ring, which a tap shouldn't leave behind.
    const wasOpen = useRef(open);
    const byKeyboard = useRef(false);
    useEffect(() => {
        const onKey = () => {
            byKeyboard.current = true;
        };
        const onPointer = () => {
            byKeyboard.current = false;
        };
        document.addEventListener('keydown', onKey, true);
        document.addEventListener('pointerdown', onPointer, true);
        return () => {
            document.removeEventListener('keydown', onKey, true);
            document.removeEventListener('pointerdown', onPointer, true);
        };
    }, []);
    useEffect(() => {
        if (open && !wasOpen.current) sheet.current?.focus({ preventScroll: true });
        if (!open && wasOpen.current && sheet.current?.contains(document.activeElement)) {
            if (byKeyboard.current) trigger.current?.focus({ preventScroll: true });
            else (document.activeElement as HTMLElement | null)?.blur();
        }
        wasOpen.current = open;
    }, [open, trigger]);

    useEffect(() => {
        if (!open) return;
        const onKey = (event: KeyboardEvent) => {
            if (event.key === 'Escape') live.current.onOpenChange(false);
        };
        document.addEventListener('keydown', onKey);
        return () => document.removeEventListener('keydown', onKey);
    }, [open]);

    useEffect(() => {
        if (!host) return;
        const screensUnder = new ScreensUnder();
        let forward: Forward | null = null;
        let gesture: Gesture | null = null;
        let frame = 0;
        let settling = 0;
        /** A page going back or forward is settling: touches wait for it. */
        let moving = false;
        const width = () => sheet.current?.offsetWidth || 300;
        const screenWidth = () => page.current?.offsetWidth || window.innerWidth;
        const clamp = (p: number) => Math.min(1, Math.max(0, p));
        const progressOf = (g: Gesture) => {
            const moved = g.dx - (g.lockedAt ?? 0);
            if (g.mode === 'back') return clamp(moved / screenWidth());
            if (g.mode === 'forward') return clamp(-moved / screenWidth());
            return clamp(g.from + moved / width());
        };

        /** How open the drawer is now, mid-settle included, read from where the page is. Where nothing is computed (no
         *  stylesheet), where its state puts it. */
        const progressNow = () => {
            const el = page.current;
            const transform = el ? getComputedStyle(el).transform : '';
            if (transform && transform !== 'none' && typeof DOMMatrixReadOnly === 'function') return clamp(new DOMMatrixReadOnly(transform).m41 / width());
            return live.current.open ? 1 : 0;
        };

        const place = (p: number) => {
            const w = width();
            const radius = Math.min(1, p * 5) * RADIUS;
            const el = page.current;
            if (el) {
                el.style.transform = `translateX(${p * w}px)`;
                el.style.borderRadius = `${radius}px 0 0 ${radius}px`;
                el.style.overflow = 'hidden';
            }
            if (dim.current) dim.current.style.opacity = String(p);
            if (sheet.current) sheet.current.style.transform = `translateX(${-(1 - p) * w * PARALLAX}px)`;
            // Your picture atop the drawer arrives late, once the drawer is mostly in view.
            const inSheet = picture();
            if (inSheet) {
                inSheet.style.opacity = String(clamp((p - 0.25) / 0.6));
                inSheet.style.transform = `scale(${0.85 + 0.15 * p})`;
            }
        };

        /** Going back `p` of the way: the page slides right off the screen under it, which drifts in and brightens. */
        const placeBack = (p: number) => {
            const w = screenWidth();
            if (page.current) page.current.style.transform = `translateX(${p * w}px)`;
            if (under.current) under.current.style.transform = `translateX(${-(1 - p) * w * PEEK}px)`;
            if (underShade.current) underShade.current.style.opacity = String((1 - p) * SHADE);
        };

        /** Going forward `p` of the way: the screen just left slides in over the page, which drifts left and dims. */
        const placeForward = (p: number) => {
            const w = screenWidth();
            if (over.current) over.current.style.transform = `translateX(${(1 - p) * w}px)`;
            if (page.current) page.current.style.transform = `translateX(${-p * w * PEEK}px)`;
            if (pageShade.current) pageShade.current.style.opacity = String(p * SHADE);
        };

        const paint = () => {
            frame = 0;
            const g = gesture;
            if (!g || g.lockedAt === null) return;
            const p = progressOf(g);
            if (g.mode === 'back') placeBack(p);
            else if (g.mode === 'forward') placeForward(p);
            else place(p);
        };

        /** Your picture atop the drawer, where the host draws one (`data-phone-me`). */
        const picture = () => sheet.current?.querySelector<HTMLElement>('[data-phone-me]') ?? null;
        const moved = () => [page.current, dim.current, sheet.current, picture()];
        const pageMoved = () => [page.current, under.current, underShade.current, pageShade.current, over.current];
        const PROPERTIES = ['transform', 'transition', 'opacity', 'visibility', 'border-radius', 'overflow', 'will-change', 'box-shadow'];
        const unstyle = (els: (HTMLElement | null)[]) => {
            for (const el of els) if (el) for (const property of PROPERTIES) el.style.removeProperty(property);
        };

        // Hands the page and drawer back to their classes (`data-menu`, `data-open`) once a settle has run.
        const release = () => unstyle(moved());

        const take = () => {
            window.clearTimeout(settling);
            if (!gesture) return;
            gesture.from = progressNow();
            for (const el of moved()) {
                if (!el) continue;
                el.style.transition = 'none';
                el.style.willChange = el === dim.current ? 'opacity' : 'transform';
            }
            const inSheet = picture();
            if (inSheet) inSheet.style.willChange = 'opacity, transform';
            if (sheet.current) sheet.current.style.visibility = 'visible';
            place(gesture.from);
        };

        const settle = (toOpen: boolean, from: number, velocity: number) => {
            const ms = settleMs(Math.abs((toOpen ? 1 : 0) - from) * width(), velocity);
            const curve = `${ms}ms ${EASE}`;
            if (page.current) page.current.style.transition = `transform ${curve}, border-radius ${curve}`;
            if (dim.current) dim.current.style.transition = `opacity ${curve}`;
            if (sheet.current) sheet.current.style.transition = `transform ${curve}`;
            const inSheet = picture();
            if (inSheet) inSheet.style.transition = `opacity ${curve}, transform ${curve}`;
            place(toOpen ? 1 : 0);
            if (toOpen !== live.current.open) live.current.onOpenChange(toOpen);
            settling = window.setTimeout(release, ms + 40);
        };

        /** Puts up the screen a back or forward swipe heads to: the one under this place (or the plain background where
         *  none was kept), or the one just left. */
        const takePage = (mode: 'back' | 'forward') => {
            window.clearTimeout(settling);
            const layer = mode === 'back' ? under.current : over.current;
            const into = mode === 'back' ? underShot.current : over.current;
            const shot = mode === 'back' ? screensUnder.get(here()) : forward?.shot;
            if (!layer || !into) return;
            if (shot) show(shot, into);
            else into.replaceChildren();
            layer.style.visibility = 'visible';
            if (mode === 'forward' && pageShade.current) pageShade.current.style.visibility = 'visible';
            if (mode === 'forward' && over.current) over.current.style.boxShadow = EDGE;
            if (mode === 'back' && page.current) page.current.style.boxShadow = EDGE;
            for (const el of pageMoved()) {
                if (!el) continue;
                el.style.transition = 'none';
                el.style.willChange = el === underShade.current || el === pageShade.current ? 'opacity' : 'transform';
            }
            if (mode === 'back') placeBack(0);
            else placeForward(0);
        };

        /** The real screen is in place under the picture: the page comes back to rest and the picture goes. */
        const finishPage = () => {
            const el = page.current;
            if (el) {
                el.style.transition = 'none';
                el.style.removeProperty('transform');
                void el.offsetWidth;
            }
            underShot.current?.replaceChildren();
            over.current?.replaceChildren();
            unstyle(pageMoved());
            moving = false;
        };

        const settlePage = (mode: 'back' | 'forward', toward: boolean, from: number, velocity: number, control: HTMLElement | null) => {
            const leaving = toward && page.current ? capture(page.current) : null;
            const ms = settleMs(Math.abs((toward ? 1 : 0) - from) * screenWidth(), velocity);
            const curve = `${ms}ms ${EASE}`;
            if (page.current) page.current.style.transition = `transform ${curve}`;
            for (const el of [under.current, over.current]) if (el) el.style.transition = `transform ${curve}`;
            for (const el of [underShade.current, pageShade.current]) if (el) el.style.transition = `opacity ${curve}`;
            if (mode === 'back') placeBack(toward ? 1 : 0);
            else placeForward(toward ? 1 : 0);
            moving = true;
            settling = window.setTimeout(() => {
                if (!toward) return finishPage();
                const left = here();
                if (mode === 'back') {
                    control?.click();
                    return whenRendered(
                        () => !control?.isConnected || live.current.back() !== control || here() !== left,
                        () => {
                            if (leaving && here() !== left) forward = { to: left, from: here(), shot: leaving };
                            finishPage();
                        }
                    );
                }
                const ahead = forward;
                forward = null;
                if (!ahead || !go.current) return finishPage();
                go.current(ahead.to);
                whenRendered(
                    () => here() === ahead.to && live.current.back() !== null,
                    () => {
                        if (leaving && here() === ahead.to) screensUnder.keep(ahead.to, leaving);
                        finishPage();
                    }
                );
            }, ms + 20);
        };

        const onStart = (event: TouchEvent) => {
            if (event.touches.length !== 1) {
                if (gesture?.lockedAt === null) gesture = null;
                return;
            }
            if (gesture || moving) return;
            const { open: isOpen, back: backOf } = live.current;
            const target = event.target instanceof Element ? event.target : null;
            if (anotherLayerOpen(sheet.current)) return;
            const backControl = isOpen ? null : backOf();
            const right: SwipeMode | null = isOpen ? null : backControl ? 'back' : 'open';
            const left: SwipeMode | null = isOpen ? 'close' : forward && forward.from === here() && go.current ? 'forward' : null;
            if (right === 'open') setDrawn(true);
            const touch = event.touches[0];
            gesture = { mode: null, right, left, target, x0: touch.clientX, y0: touch.clientY, lockedAt: null, from: 0, dx: 0, samples: [], back: backControl };
        };

        const onMove = (event: TouchEvent) => {
            const g = gesture;
            if (!g) return;
            const touch = event.touches[0];
            g.dx = touch.clientX - g.x0;
            if (g.lockedAt === null) {
                const read = readDirection(g.dx, touch.clientY - g.y0);
                if (read === null) return;
                const mode = read === 'right' ? g.right : read === 'left' ? g.left : null;
                if (!mode || (read !== 'scroll' && takesItsOwnSwipe(g.target, read))) {
                    gesture = null;
                    return;
                }
                g.mode = mode;
                g.lockedAt = g.dx;
                if (mode === 'back' || mode === 'forward') takePage(mode);
                else take();
            }
            if (event.cancelable) event.preventDefault();
            g.samples.push({ t: event.timeStamp, x: touch.clientX });
            if (g.samples.length > 12) g.samples.shift();
            if (!frame) frame = requestAnimationFrame(paint);
        };

        const onEnd = (event: TouchEvent) => {
            const g = gesture;
            gesture = null;
            if (!g || g.lockedAt === null) return;
            if (frame) {
                cancelAnimationFrame(frame);
                frame = 0;
            }
            const velocity = releaseVelocity(g.samples, event.timeStamp);
            const p = progressOf(g);
            const ended = event.type === 'touchend';
            if (g.mode === 'back' || g.mode === 'forward') {
                const toward = g.mode === 'back' ? velocity : -velocity;
                return settlePage(g.mode, ended && settlesOpen(p, toward), p, toward, g.back);
            }
            settle(ended ? settlesOpen(p, velocity) : g.from > 0.5, p, velocity);
        };

        // A tap that leaves this screen for one inside it (a channel from its list, a section of Settings) keeps a picture
        // of the screen it left, for the back swipe from there; the tap on the bar's way back keeps one of the screen it
        // leaves, for the swipe forward. The copy is made as the finger goes down, before anything has changed, so the
        // tap itself never waits on it, unless the tap is quicker than the copy.
        let tap: { place: string; at: number; shot: Shot | null; timer: number } | null = null;
        const shoot = () => {
            if (tap && !tap.shot && page.current) tap.shot = capture(page.current);
        };
        const onPointerDown = (event: PointerEvent) => {
            const el = page.current;
            const target = event.target instanceof Element ? event.target : null;
            if (!event.isPrimary || moving || live.current.open || !el || !target || !el.contains(target) || target.closest(FIELDS)) return;
            if (tap) window.clearTimeout(tap.timer);
            tap = { place: here(), at: performance.now(), shot: null, timer: window.setTimeout(shoot, 0) };
        };
        const onClick = (event: MouseEvent) => {
            const el = page.current;
            const target = event.target instanceof Element ? event.target : null;
            if (!el || !target || !el.contains(target)) return;
            if (!tap || tap.place !== here() || performance.now() - tap.at > 3000) {
                // A click without a finger (a keyboard, a test): copied now, before its handlers run.
                if (tap) window.clearTimeout(tap.timer);
                tap = { place: here(), at: performance.now(), shot: null, timer: 0 };
            }
            window.clearTimeout(tap.timer);
            shoot();
            const left = tap;
            tap = null;
            const viaBack = target.closest('[data-phone-back]') !== null;
            const start = performance.now();
            const watch = () => {
                const landed = here();
                if (landed === left.place) {
                    if (performance.now() - start < TAP_LEADS_MS) requestAnimationFrame(watch);
                    return;
                }
                if (viaBack) {
                    forward = left.shot ? { to: left.place, from: landed, shot: left.shot } : null;
                    return;
                }
                forward = null;
                if (left.shot && isDeeper(left.place, landed)) screensUnder.keep(landed, left.shot);
            };
            requestAnimationFrame(watch);
        };

        document.addEventListener('touchstart', onStart, { passive: true });
        document.addEventListener('touchmove', onMove, { passive: false });
        document.addEventListener('touchend', onEnd);
        document.addEventListener('touchcancel', onEnd);
        document.addEventListener('pointerdown', onPointerDown, { capture: true, passive: true });
        document.addEventListener('click', onClick, true);
        return () => {
            document.removeEventListener('touchstart', onStart);
            document.removeEventListener('touchmove', onMove);
            document.removeEventListener('touchend', onEnd);
            document.removeEventListener('touchcancel', onEnd);
            document.removeEventListener('pointerdown', onPointerDown, { capture: true });
            document.removeEventListener('click', onClick, true);
            if (frame) cancelAnimationFrame(frame);
            window.clearTimeout(settling);
            if (tap) window.clearTimeout(tap.timer);
        };
    }, [host, page]);

    if (!host) return null;
    return (
        <>
            {routed && <RouterGo into={go} />}
            {pageEl && createPortal(<div ref={dim} data-open={open} aria-hidden className={SIDEBAR_SHEET_OVERLAY} />, pageEl)}
            {createPortal(
                <>
                    <div
                        ref={sheet}
                        id="phone-menu"
                        role="dialog"
                        aria-modal={open || undefined}
                        aria-hidden={!open || undefined}
                        aria-label="Menu"
                        tabIndex={-1}
                        data-open={open}
                        inert={!open}
                        className={SIDEBAR_SHEET}
                    >
                        <SidebarScaleProvider value="phone">{drawn && children}</SidebarScaleProvider>
                    </div>
                    <div ref={under} aria-hidden inert className={UNDER}>
                        <div ref={underShot} className="absolute inset-0" />
                        <div ref={underShade} className="absolute inset-0 bg-black opacity-0" />
                    </div>
                    <div aria-hidden data-open={open} className={CATCHER} onClick={() => onOpenChange(false)} />
                    <div ref={pageShade} aria-hidden className={PAGE_SHADE} />
                    <div ref={over} aria-hidden inert className={OVER} />
                </>,
                host
            )}
        </>
    );
}
