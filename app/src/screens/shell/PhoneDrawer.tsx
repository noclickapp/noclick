// The phone's sidebar as a drawer under the page. A swipe across the page slides the page right off it, following the
// finger, as a rounded card that dims; a swipe across either (or a tap on the page) slides it back; let go and it
// settles by where it was and how fast the finger moved. On a page one level down the same swipe goes back instead,
// pressing the bar's back control. Once first drawn (when the phone is idle after the first page) the sidebar stays
// mounted, so opening never waits on it rendering.
import { useEffect, useRef, useState, type ReactNode, type RefObject } from 'react';
import { createPortal } from 'react-dom';
import { ChevronLeft } from 'lucide-react';
import { SIDEBAR_SHEET, SIDEBAR_SHEET_OVERLAY, SidebarScaleProvider } from '@/ui/sidebarParts';
import { BACK_PX, anotherLayerOpen, backCounts, readDirection, releaseVelocity, settleMs, settlesOpen, takesItsOwnSwipe, type SwipeMode } from './phoneSwipe';

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
    mode: SwipeMode;
    x0: number;
    y0: number;
    /** Where the finger was when the touch was read as a swipe, so the drawer moves from there without a jump. */
    lockedAt: number | null;
    /** How open the drawer was then, 0 shut to 1 open. */
    from: number;
    dx: number;
    samples: { t: number; x: number }[];
    back: HTMLElement | null;
}

const EASE = 'cubic-bezier(0.2, 0.9, 0.3, 1)';
/** The page's near corners, rounded as it leaves (matching PHONE_PAGE's open radius). */
const RADIUS = 44;
/** How far behind the drawer starts, as a share of its width: it drifts in under the page. */
const PARALLAX = 0.18;
const ARROW_HIDDEN = -48;

/** Over the page while it's pushed aside, so a tap or a swipe there closes the drawer (the page itself is inert). */
const CATCHER = 'pointer-events-none fixed inset-y-0 right-0 left-[min(80vw,340px)] z-[2] data-[open=true]:pointer-events-auto';
const BACK_ARROW =
    'pointer-events-none fixed left-0 top-1/2 z-[65] -mt-5 flex h-10 w-10 items-center justify-center rounded-full border border-border bg-card text-foreground opacity-0 shadow-lg transition-colors duration-150 data-[armed=true]:border-transparent data-[armed=true]:bg-foreground data-[armed=true]:text-background';

export function PhoneDrawer({ open, onOpenChange, back, trigger, page, children }: PhoneDrawerProps) {
    const sheet = useRef<HTMLDivElement>(null);
    const dim = useRef<HTMLDivElement>(null);
    const arrow = useRef<HTMLDivElement>(null);
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
    // inside it, focus goes back to the menu button.
    const wasOpen = useRef(open);
    useEffect(() => {
        if (open && !wasOpen.current) sheet.current?.focus({ preventScroll: true });
        if (!open && wasOpen.current && sheet.current?.contains(document.activeElement)) trigger.current?.focus({ preventScroll: true });
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
        let gesture: Gesture | null = null;
        let frame = 0;
        let settling = 0;
        let arrowHiding = 0;
        const width = () => sheet.current?.offsetWidth || 300;
        const progressOf = (g: Gesture) => Math.min(1, Math.max(0, g.from + (g.dx - (g.lockedAt ?? 0)) / width()));

        /** How open the drawer is now, mid-settle included, read from where the page is. Where nothing is computed (no
         *  stylesheet), where its state puts it. */
        const progressNow = () => {
            const el = page.current;
            const transform = el ? getComputedStyle(el).transform : '';
            if (transform && transform !== 'none' && typeof DOMMatrixReadOnly === 'function') return Math.min(1, Math.max(0, new DOMMatrixReadOnly(transform).m41 / width()));
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
        };

        const paint = () => {
            frame = 0;
            const g = gesture;
            if (!g || g.lockedAt === null) return;
            if (g.mode !== 'back') return place(progressOf(g));
            const pulled = Math.max(0, g.dx - g.lockedAt);
            const reach = Math.min(1, pulled / BACK_PX);
            const past = Math.max(0, pulled - BACK_PX) * 0.12;
            const el = arrow.current;
            if (!el) return;
            el.style.transform = `translateX(${ARROW_HIDDEN + 62 * reach + past}px)`;
            el.style.opacity = String(Math.min(1, reach * 1.6));
            el.dataset.armed = String(pulled >= BACK_PX);
        };

        const moved = () => [page.current, dim.current, sheet.current];

        // Hands the page and drawer back to their classes (`data-menu`, `data-open`) once a settle has run.
        const release = () => {
            for (const el of moved()) {
                if (!el) continue;
                for (const property of ['transform', 'transition', 'opacity', 'visibility', 'border-radius', 'overflow', 'will-change']) el.style.removeProperty(property);
            }
        };

        const take = () => {
            window.clearTimeout(settling);
            if (!gesture) return;
            gesture.from = progressNow();
            for (const el of moved()) {
                if (!el) continue;
                el.style.transition = 'none';
                el.style.willChange = el === dim.current ? 'opacity' : 'transform';
            }
            if (sheet.current) sheet.current.style.visibility = 'visible';
            place(gesture.from);
        };

        const settle = (toOpen: boolean, from: number, velocity: number) => {
            const ms = settleMs(Math.abs((toOpen ? 1 : 0) - from) * width(), velocity);
            const curve = `${ms}ms ${EASE}`;
            if (page.current) page.current.style.transition = `transform ${curve}, border-radius ${curve}`;
            if (dim.current) dim.current.style.transition = `opacity ${curve}`;
            if (sheet.current) sheet.current.style.transition = `transform ${curve}`;
            place(toOpen ? 1 : 0);
            if (toOpen !== live.current.open) live.current.onOpenChange(toOpen);
            settling = window.setTimeout(release, ms + 40);
        };

        const hideArrow = () => {
            const el = arrow.current;
            if (!el) return;
            el.style.transition = `transform 200ms ${EASE}, opacity 200ms ${EASE}`;
            el.style.transform = `translateX(${ARROW_HIDDEN}px)`;
            el.style.opacity = '0';
            window.clearTimeout(arrowHiding);
            arrowHiding = window.setTimeout(() => {
                el.style.removeProperty('transition');
                el.dataset.armed = 'false';
            }, 220);
        };

        const onStart = (event: TouchEvent) => {
            if (event.touches.length !== 1) {
                if (gesture?.lockedAt === null) gesture = null;
                return;
            }
            if (gesture) return;
            const { open: isOpen, back: backOf } = live.current;
            const target = event.target instanceof Element ? event.target : null;
            if (anotherLayerOpen(sheet.current) || takesItsOwnSwipe(target)) return;
            const backControl = isOpen ? null : backOf();
            const mode: SwipeMode = isOpen ? 'close' : backControl ? 'back' : 'open';
            if (mode === 'open') setDrawn(true);
            const touch = event.touches[0];
            gesture = { mode, x0: touch.clientX, y0: touch.clientY, lockedAt: null, from: 0, dx: 0, samples: [], back: backControl };
        };

        const onMove = (event: TouchEvent) => {
            const g = gesture;
            if (!g) return;
            const touch = event.touches[0];
            g.dx = touch.clientX - g.x0;
            if (g.lockedAt === null) {
                const read = readDirection(g.mode, g.dx, touch.clientY - g.y0);
                if (read === null) return;
                if (read === 'scroll') {
                    gesture = null;
                    return;
                }
                g.lockedAt = g.dx;
                if (g.mode === 'back') {
                    if (arrow.current) arrow.current.style.transition = 'none';
                } else {
                    take();
                }
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
            if (g.mode === 'back') {
                hideArrow();
                if (event.type === 'touchend' && backCounts(g.dx - g.lockedAt, velocity)) g.back?.click();
                return;
            }
            const p = progressOf(g);
            settle(event.type === 'touchend' ? settlesOpen(p, velocity) : g.from > 0.5, p, velocity);
        };

        document.addEventListener('touchstart', onStart, { passive: true });
        document.addEventListener('touchmove', onMove, { passive: false });
        document.addEventListener('touchend', onEnd);
        document.addEventListener('touchcancel', onEnd);
        return () => {
            document.removeEventListener('touchstart', onStart);
            document.removeEventListener('touchmove', onMove);
            document.removeEventListener('touchend', onEnd);
            document.removeEventListener('touchcancel', onEnd);
            if (frame) cancelAnimationFrame(frame);
            window.clearTimeout(settling);
            window.clearTimeout(arrowHiding);
        };
    }, [host, page]);

    if (!host) return null;
    return (
        <>
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
                    <div aria-hidden data-open={open} className={CATCHER} onClick={() => onOpenChange(false)} />
                    <div ref={arrow} aria-hidden data-armed="false" className={BACK_ARROW} style={{ transform: `translateX(${ARROW_HIDDEN}px)` }}>
                        <ChevronLeft className="h-5 w-5" strokeWidth={2} />
                    </div>
                </>,
                host
            )}
        </>
    );
}
