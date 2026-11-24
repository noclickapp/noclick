// A slider that rests only on its stops: a thick track filled up to a round thumb, with a dot at each stop. Under a
// hand the thumb leans into the nearest stop and gives a little past either end, then springs to the stop it's let go
// on. Each stop it comes to is a preview; the one it's let go on is committed (after keys, a moment after the last
// press). What NoClick uses of a computer and how hard a model thinks are both set on it. `RollText` is the stop's
// name beside it, rolling the way the thumb went.
import { useEffect, useRef, useState, type KeyboardEvent, type PointerEvent, type ReactNode } from 'react';
import { cn } from '@/ui/utils';

/** The thumb's radius: an end stop sits this far in from the track's end. */
const R = 16;
const SPRING = 'ease-[cubic-bezier(.25,1.25,.5,1)]';
const STEP_KEYS: Record<string, 1 | -1> = { ArrowRight: 1, ArrowUp: 1, PageUp: 1, ArrowLeft: -1, ArrowDown: -1, PageDown: -1 };

/** Whether the person asked for less motion. */
export const reducedMotion = () => typeof window !== 'undefined' && !!window.matchMedia?.('(prefers-reduced-motion: reduce)').matches;
const clamp = (n: number, lo: number, hi: number) => Math.max(lo, Math.min(hi, n));
const nearest = (px: number, centers: number[]) => centers.reduce((best, c, i) => (Math.abs(c - px) < Math.abs(centers[best] - px) ? i : best), 0);

/** Under a hand the thumb leans into the nearest stop and gives a little past either end, so stops feel caught. */
function shape(raw: number, centers: number[]) {
    const lo = centers[0];
    const hi = centers[centers.length - 1];
    const give = (over: number) => 8 * (1 - 1 / (over / 28 + 1));
    if (raw < lo) return lo - give(lo - raw);
    if (raw > hi) return hi + give(raw - hi);
    const c = centers[nearest(raw, centers)];
    const off = raw - c;
    return Math.abs(off) < 16 ? c + (off * Math.abs(off)) / 16 : raw;
}

function shake(el: HTMLElement | null, xs: number[], duration: number) {
    if (!el || reducedMotion()) return;
    el.animate(
        xs.map((x) => ({ transform: `translateX(${x}px)` })),
        { duration, easing: 'ease-out' }
    );
}

export interface SliderStop<T> {
    value: T;
    /** Where it sits along the track, 0 (its start) to 1 (its end). */
    at: number;
}

/** Stops the same distance apart, first to last. */
export function evenStops<T>(values: readonly T[]): SliderStop<T>[] {
    return values.map((value, i) => ({ value, at: values.length > 1 ? i / (values.length - 1) : 0 }));
}

export interface StopSliderProps<T> {
    /** The stops, left to right. */
    stops: readonly SliderStop<T>[];
    /** What it rests on: one of the stops, or a value between them (then `at` says where). */
    value: T;
    at?: number;
    /** A stop it came to under a hand or keys, not let go yet. */
    onPreview?: (value: T) => void;
    /** The stop it was let go on. */
    onCommit: (value: T) => void;
    label: string;
    valueText: string;
    /** A value as aria-valuemin, -max and -now read it; its stop's place when left out. */
    amount?: (value: T) => number;
    describedBy?: string;
    /** The fill is a share of the whole track (a stop at 0.5 sits at its middle); left out, the stops spread between
     *  the thumb's two ends. */
    asShare?: boolean;
    /** It keeps its stop: a press or a key shakes the thumb and says so (`onRefused`); `knob` (a lock) shows why. */
    locked?: boolean;
    onRefused?: () => void;
    knob?: ReactNode;
    className?: string;
    testId?: string;
}

export function StopSlider<T>({ stops, value, at, onPreview, onCommit, label, valueText, amount, describedBy, asShare = false, locked = false, onRefused, knob: knobFace, className, testId }: StopSliderProps<T>) {
    const resting = stops.find((s) => s.value === value);
    const restAt = resting ? resting.at : (at ?? 0);
    const track = useRef<HTMLDivElement>(null);
    const thumb = useRef<HTMLDivElement>(null);
    const knob = useRef<HTMLSpanElement>(null);
    const dots = useRef<(HTMLSpanElement | null)[]>([]);
    const [width, setWidth] = useState(0);
    const [resizing, setResizing] = useState(false);
    const [drag, setDrag] = useState<number | null>(null);
    const [pressed, setPressed] = useState(false);
    const [hover, setHover] = useState<number | null>(null);
    // The stop the hand or keys are on right now, read by handlers that can run before a render.
    const live = useRef({ value, at: restAt });
    const hand = useRef({ down: false, moved: false, startX: 0, left: 0, grab: 0, tapAt: null as number | null, centers: [] as number[] });
    const keyTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
    useEffect(() => {
        if (!hand.current.down && keyTimer.current === null) live.current = { value, at: restAt };
    }, [value, restAt]);
    useEffect(
        () => () => {
            if (keyTimer.current !== null) clearTimeout(keyTimer.current);
        },
        []
    );

    // Positions follow the track's width, without a spring when it's the width that moved.
    useEffect(() => {
        const el = track.current;
        if (!el) return;
        setWidth(el.getBoundingClientRect().width);
        const observer = new ResizeObserver(() => {
            if (hand.current.down) return;
            setResizing(true);
            setWidth(el.getBoundingClientRect().width);
            requestAnimationFrame(() => requestAnimationFrame(() => setResizing(false)));
        });
        observer.observe(el);
        return () => observer.disconnect();
    }, []);
    const centerOf = (where: number, w: number) => (asShare ? clamp(where * w, R, w - R) : R + where * (w - 2 * R));
    const centers = stops.map((s) => centerOf(s.at, width));
    // Before the track is measured (first paint), where a stop sits in CSS terms.
    const place = (where: number) =>
        width ? `${centerOf(where, width)}px` : asShare ? `clamp(${R}px, ${where * 100}%, calc(100% - ${R}px))` : `calc(${R}px + (100% - ${2 * R}px) * ${where})`;
    const thumbAt = drag !== null ? `${drag}px` : place(restAt);
    const thumbPx = drag ?? centerOf(restAt, width);

    // The key timer commits with the render it fires in, not the one it was set in.
    const commitLatest = useRef(onCommit);
    useEffect(() => {
        commitLatest.current = onCommit;
    });

    const choose = (i: number) => {
        const stop = stops[i];
        if (stop.value === live.current.value) return;
        if (!reducedMotion()) dots.current[i]?.animate([{ transform: 'scale(2.2)' }, { transform: 'scale(1)' }], { duration: 280, easing: 'cubic-bezier(.2,.8,.2,1)' });
        live.current = stop;
        onPreview?.(stop.value);
    };

    const refuse = () => {
        shake(knob.current, [0, -4, 4, -2, 0], 320);
        onRefused?.();
    };

    const onPointerDown = (e: PointerEvent<HTMLDivElement>) => {
        if (e.pointerType === 'mouse' && e.button !== 0) return;
        const rect = track.current!.getBoundingClientRect();
        setWidth(rect.width);
        if (locked) {
            refuse();
            return;
        }
        const h = hand.current;
        const cs = stops.map((s) => centerOf(s.at, rect.width));
        const p = e.clientX - rect.left;
        const x = centerOf(live.current.at, rect.width);
        Object.assign(h, { down: true, moved: false, startX: e.clientX, left: rect.left, tapAt: null, centers: cs });
        e.currentTarget.setPointerCapture(e.pointerId);
        setPressed(true);
        if (keyTimer.current !== null) clearTimeout(keyTimer.current);
        keyTimer.current = null;
        if (e.pointerType === 'mouse') e.preventDefault();
        if (thumb.current!.contains(e.target as Node) || Math.abs(p - x) <= R) {
            h.grab = p - x;
        } else {
            h.grab = 0;
            // A finger waits to lift or slide, so a scroll that starts on the track changes nothing.
            if (e.pointerType === 'touch') h.tapAt = p;
            else choose(nearest(p, cs));
        }
        if (e.pointerType !== 'touch') thumb.current!.focus({ preventScroll: true });
    };

    const onPointerMove = (e: PointerEvent<HTMLDivElement>) => {
        const h = hand.current;
        if (!h.down) {
            if (e.pointerType === 'mouse' && !locked && width) setHover(nearest(e.clientX - track.current!.getBoundingClientRect().left, centers));
            return;
        }
        if (!h.moved) {
            if (Math.abs(e.clientX - h.startX) < 4) return;
            h.moved = true;
            h.tapAt = null;
            setHover(null);
        }
        const raw = e.clientX - h.left - h.grab;
        const cs = h.centers;
        setDrag(shape(raw, cs));
        choose(nearest(clamp(raw, cs[0], cs[cs.length - 1]), cs));
    };

    const onPointerEnd = (e: PointerEvent<HTMLDivElement>) => {
        const h = hand.current;
        if (!h.down) return;
        h.down = false;
        setPressed(false);
        setDrag(null);
        if (e.currentTarget.hasPointerCapture(e.pointerId)) e.currentTarget.releasePointerCapture(e.pointerId);
        if (!h.moved && h.tapAt !== null && e.type !== 'pointercancel') choose(nearest(h.tapAt, h.centers));
        h.tapAt = null;
        onCommit(live.current.value);
    };

    const onKeyDown = (e: KeyboardEvent<HTMLDivElement>) => {
        const from = live.current.at;
        const dir: 1 | -1 | undefined = STEP_KEYS[e.key];
        if (!dir && e.key !== 'Home' && e.key !== 'End') return;
        e.preventDefault();
        if (locked) {
            refuse();
            return;
        }
        // The stop one step that way (a value between stops steps to its neighbour); none past either end.
        const next = !dir ? (e.key === 'Home' ? 0 : stops.length - 1) : dir > 0 ? stops.findIndex((s) => s.at > from) : stops.map((s) => s.at < from).lastIndexOf(true);
        if (next < 0) {
            shake(knob.current, [0, 4 * (dir ?? 1), 0], 260);
            return;
        }
        choose(next);
        if (keyTimer.current !== null) clearTimeout(keyTimer.current);
        keyTimer.current = setTimeout(() => {
            keyTimer.current = null;
            commitLatest.current(live.current.value);
        }, 450);
    };

    const springs = drag === null && !resizing;
    const read = (v: T, fallback: number) => (amount ? amount(v) : fallback);
    return (
        <div
            ref={track}
            data-testid={testId}
            onPointerDown={onPointerDown}
            onPointerMove={onPointerMove}
            onPointerUp={onPointerEnd}
            onPointerCancel={onPointerEnd}
            onLostPointerCapture={onPointerEnd}
            onPointerLeave={() => setHover(null)}
            className={cn('relative h-11 touch-pan-y select-none [-webkit-tap-highlight-color:transparent]', locked ? 'cursor-not-allowed' : 'cursor-pointer', className)}
        >
            <div className={cn('absolute inset-x-0 top-3 h-5 overflow-hidden rounded-full bg-foreground/[0.08] shadow-[inset_0_0_0_1px_hsl(var(--foreground)/0.06)]', locked && 'opacity-[.45]')}>
                <div
                    className={cn('absolute inset-y-0 left-0 rounded-full bg-foreground', springs && `transition-[width] duration-[420ms] motion-reduce:transition-none ${SPRING}`)}
                    style={{ width: thumbAt }}
                />
            </div>
            {stops.map((s, i) => (
                <span
                    key={i}
                    ref={(el) => {
                        dots.current[i] = el;
                    }}
                    aria-hidden
                    className={cn(
                        'pointer-events-none absolute top-[19.5px] -ml-[2.5px] h-[5px] w-[5px] rounded-full motion-reduce:transition-none',
                        // A stop moves over when the stops change (a model with more of them), never as the track resizes.
                        springs
                            ? '[transition:background-color_.15s,transform_.25s_cubic-bezier(.25,1.25,.5,1),left_.42s_cubic-bezier(.25,1.25,.5,1)]'
                            : '[transition:background-color_.15s,transform_.25s_cubic-bezier(.25,1.25,.5,1)]',
                        (width ? centers[i] < thumbPx - 2 : s.at < restAt) ? 'bg-background/[0.42]' : 'bg-foreground/30',
                        hover === i && s.value !== value && 'scale-[1.7]',
                        locked && 'opacity-[.45]'
                    )}
                    style={{ left: place(s.at) }}
                />
            ))}
            <div
                ref={thumb}
                role="slider"
                tabIndex={0}
                aria-label={label}
                aria-describedby={describedBy}
                aria-valuemin={read(stops[0].value, 0)}
                aria-valuemax={read(stops[stops.length - 1].value, stops.length - 1)}
                aria-valuenow={read(value, Math.max(0, stops.findIndex((s) => s.value === value)))}
                aria-valuetext={valueText}
                aria-disabled={locked}
                onKeyDown={onKeyDown}
                className={cn(
                    'absolute top-1.5 -ml-4 h-8 w-8 rounded-full outline-none focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring',
                    springs && `transition-[left] duration-[420ms] motion-reduce:transition-none ${SPRING}`
                )}
                style={{ left: thumbAt }}
            >
                <span
                    ref={knob}
                    className={cn(
                        'grid h-full w-full place-items-center rounded-full bg-card text-foreground shadow-[0_1px_2px_hsl(var(--foreground)/0.22),0_0_0_1px_hsl(var(--foreground)/0.06),0_3px_8px_hsl(var(--foreground)/0.12)] transition-transform duration-200 motion-reduce:transition-none dark:bg-foreground dark:text-background dark:shadow-[0_1px_2px_hsl(var(--background)/0.55),0_3px_10px_hsl(var(--background)/0.35)]',
                        SPRING,
                        pressed && 'scale-110'
                    )}
                >
                    {knobFace}
                </span>
            </div>
        </div>
    );
}

/** A stop's name, rolling to the next one the way the thumb went: up when `order` grew, down when it fell. */
export function RollText({ text, order, className, testId }: { text: string; order: number; className?: string; testId?: string }) {
    const [now, setNow] = useState({ text, order });
    const [gone, setGone] = useState<{ text: string; up: boolean } | null>(null);
    if (text !== now.text) {
        setGone(reducedMotion() ? null : { text: now.text, up: order > now.order });
        setNow({ text, order });
    }
    useEffect(() => {
        if (!gone) return;
        const t = setTimeout(() => setGone(null), 240);
        return () => clearTimeout(t);
    }, [gone]);
    const up = gone?.up ?? true;
    return (
        <span className={cn('inline-grid overflow-hidden align-bottom font-medium', className)}>
            {gone && (
                <span
                    key={`gone-${gone.text}`}
                    aria-hidden
                    className={cn('whitespace-nowrap duration-[170ms] ease-in animate-out fade-out fill-mode-forwards [grid-area:1/1]', up ? 'slide-out-to-top-[70%]' : 'slide-out-to-bottom-[70%]')}
                >
                    {gone.text}
                </span>
            )}
            <span
                key={now.text}
                data-testid={testId}
                className={cn('whitespace-nowrap [grid-area:1/1]', gone && cn('duration-[230ms] ease-out animate-in fade-in', up ? 'slide-in-from-bottom-[70%]' : 'slide-in-from-top-[70%]'))}
            >
                {now.text}
            </span>
        </span>
    );
}
