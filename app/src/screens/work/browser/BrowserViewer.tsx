// A live browser a person watches and works, through NoClick's own viewer
// (`useBrowserView`): the page's latest picture, scaled to fit, and what the
// person does on it sent back in the page's own coordinates. A mouse clicks,
// drags and scrolls with the wheel; a finger taps and swipes to scroll; on a
// computer the keyboard types into the page once the view has focus (a phone
// types through the page's typing box instead). Not `interactive`, it only
// shows the page (a chat's tile, or a browser someone else is driving).
import { useCallback, useEffect, useRef, type KeyboardEvent, type PointerEvent } from 'react';
import { cn } from '@/ui/utils';
import { useBrowserView, type BrowserViewSource, type Viewport } from './useBrowserView';

/** The keys that aren't text, as the backend takes them. */
export const VIEWER_KEYS = [
    'Enter', 'Backspace', 'Tab', 'Escape', 'Delete', 'Home', 'End', 'PageUp', 'PageDown',
    'ArrowLeft', 'ArrowUp', 'ArrowRight', 'ArrowDown',
] as const;
/** At most one move, and one scroll, this often. */
const MOVE_MS = 40;
const SCROLL_MS = 50;
/** A finger that moved less than this, this quickly, tapped. */
const TAP_PX = 10;
const TAP_MS = 500;

interface Touch {
    x: number;
    y: number;
    at: number;
    lastX: number;
    lastY: number;
    swiped: boolean;
}

/** Where (clientX, clientY) is on the page, in its CSS pixels, given where its picture is drawn. */
export function pagePoint(
    rect: { left: number; top: number; width: number; height: number },
    viewport: Viewport,
    clientX: number,
    clientY: number
): { x: number; y: number } {
    const clamp = (value: number, max: number) => Math.min(Math.max(Math.round(value), 0), max);
    return {
        x: clamp(((clientX - rect.left) / rect.width) * viewport.width, viewport.width),
        y: clamp(((clientY - rect.top) / rect.height) * viewport.height, viewport.height),
    };
}

export function BrowserViewer({
    source,
    onEnded,
    thumb = false,
    interactive = true,
    className,
}: {
    /** A browser read through the platform client (it drives it only while `interactive`), or a /live/{id} link. */
    source: BrowserViewSource;
    onEnded?: () => void;
    /** The small, slower stream a tile shows. */
    thumb?: boolean;
    interactive?: boolean;
    className?: string;
}) {
    const { state, picture, viewport, send } = useBrowserView(source, { onEnded, thumb, control: interactive && !thumb });
    const image = useRef<HTMLImageElement>(null);
    const touch = useRef<Touch | null>(null);
    const lastMove = useRef(0);
    const scroll = useRef<{ x: number; y: number; dx: number; dy: number } | null>(null);
    const scrollTimer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);

    const at = useCallback(
        (clientX: number, clientY: number) => {
            const rect = image.current?.getBoundingClientRect();
            return rect && rect.width && viewport ? pagePoint(rect, viewport, clientX, clientY) : null;
        },
        [viewport]
    );

    /** Scrolls are added up and sent at most every SCROLL_MS. */
    const scrollBy = useCallback(
        (clientX: number, clientY: number, dx: number, dy: number) => {
            const point = at(clientX, clientY);
            if (!point) return;
            const pending = scroll.current;
            scroll.current = { ...point, dx: (pending?.dx ?? 0) + dx, dy: (pending?.dy ?? 0) + dy };
            if (scrollTimer.current) return;
            scrollTimer.current = setTimeout(() => {
                scrollTimer.current = undefined;
                const due = scroll.current;
                scroll.current = null;
                if (due) send({ type: 'scroll', x: due.x, y: due.y, dx: Math.round(due.dx), dy: Math.round(due.dy) });
            }, SCROLL_MS);
        },
        [at, send]
    );

    useEffect(() => () => clearTimeout(scrollTimer.current), []);

    // The wheel needs a listener that may cancel it, which React's isn't.
    const shown = picture !== null;
    useEffect(() => {
        const element = image.current;
        if (!element || !interactive) return;
        const onWheel = (event: WheelEvent) => {
            event.preventDefault();
            scrollBy(event.clientX, event.clientY, event.deltaX, event.deltaY);
        };
        element.addEventListener('wheel', onWheel, { passive: false });
        return () => element.removeEventListener('wheel', onWheel);
    }, [scrollBy, shown, interactive]);

    const onPointerDown = (event: PointerEvent<HTMLImageElement>) => {
        const point = at(event.clientX, event.clientY);
        if (!point) return;
        event.currentTarget.parentElement?.focus();
        if (event.pointerType === 'mouse') {
            event.currentTarget.setPointerCapture?.(event.pointerId);
            send({ type: 'mouse', action: 'down', ...point });
            return;
        }
        touch.current = { x: event.clientX, y: event.clientY, at: Date.now(), lastX: event.clientX,
                          lastY: event.clientY, swiped: false };
    };

    const onPointerMove = (event: PointerEvent<HTMLImageElement>) => {
        if (event.pointerType === 'mouse') {
            const now = Date.now();
            if (now - lastMove.current < MOVE_MS) return;
            const point = at(event.clientX, event.clientY);
            if (!point) return;
            lastMove.current = now;
            send({ type: 'mouse', action: 'move', ...point });
            return;
        }
        const started = touch.current;
        const rect = image.current?.getBoundingClientRect();
        if (!started || !rect || !viewport) return;
        started.swiped ||= Math.hypot(event.clientX - started.x, event.clientY - started.y) >= TAP_PX;
        if (!started.swiped) return;
        // A finger moving up scrolls the page down, by as many page pixels as it moved on the picture.
        scrollBy(started.x, started.y, ((started.lastX - event.clientX) / rect.width) * viewport.width,
                 ((started.lastY - event.clientY) / rect.height) * viewport.height);
        started.lastX = event.clientX;
        started.lastY = event.clientY;
    };

    const onPointerUp = (event: PointerEvent<HTMLImageElement>) => {
        if (event.pointerType === 'mouse') {
            const point = at(event.clientX, event.clientY);
            if (point) send({ type: 'mouse', action: 'up', ...point });
            return;
        }
        const started = touch.current;
        touch.current = null;
        if (started && !started.swiped && Date.now() - started.at < TAP_MS) {
            const point = at(started.x, started.y);
            if (point) send({ type: 'tap', ...point });
        }
    };

    const onKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
        if (event.metaKey || event.ctrlKey || event.altKey) return;
        if ((VIEWER_KEYS as readonly string[]).includes(event.key)) {
            send({ type: 'key', key: event.key });
        } else if (event.key.length === 1) {
            send({ type: 'text', text: event.key });
        } else {
            return;
        }
        event.preventDefault();
    };

    const status =
        state !== 'live' || !picture ? (
            <div role="status" className={cn('absolute inset-0 flex items-center justify-center text-muted-foreground', thumb ? 'text-[11px]' : 'text-sm', picture && 'bg-background/60')}>
                {state === 'ended' ? 'This view has ended.' : 'Connecting to the browser…'}
            </div>
        ) : null;
    const aspectRatio = viewport ? `${viewport.width} / ${viewport.height}` : '16 / 10';
    if (!interactive) {
        return (
            <div className={cn('relative overflow-hidden bg-muted', className ?? 'rounded-xl border border-border')} style={{ aspectRatio }}>
                {picture ? <img src={picture} alt="The browser's page" draggable={false} className="block h-full w-full select-none" /> : null}
                {status}
            </div>
        );
    }

    return (
        // A remote page takes keys, so the surface is an `application` that holds focus.
        // eslint-disable-next-line jsx-a11y/no-noninteractive-element-interactions, jsx-a11y/no-noninteractive-tabindex
        <div tabIndex={0}
            role="application"
            aria-label="Live browser. Click, scroll and type to use it."
            onKeyDown={onKeyDown}
            onPaste={(event) => {
                const text = event.clipboardData.getData('text');
                if (text) send({ type: 'text', text: text.slice(0, 2000) });
                event.preventDefault();
            }}
            className={cn('relative overflow-hidden bg-muted outline-none focus-visible:ring-2 focus-visible:ring-ring', className ?? 'rounded-xl border border-border')}
            style={{ aspectRatio }}
        >
            {picture ? (
                <img
                    ref={image}
                    src={picture}
                    alt="The browser's page"
                    draggable={false}
                    onPointerDown={onPointerDown}
                    onPointerMove={onPointerMove}
                    onPointerUp={onPointerUp}
                    onPointerCancel={() => (touch.current = null)}
                    onContextMenu={(event) => event.preventDefault()}
                    className="block h-full w-full select-none [touch-action:pinch-zoom]"
                />
            ) : null}
            {status}
        </div>
    );
}
