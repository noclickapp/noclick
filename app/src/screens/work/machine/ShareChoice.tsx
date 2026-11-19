// What NoClick uses of a computer of yours, as one slider whose track is the split: the white is NoClick's part, the
// rest yours. It snaps to the parts in share.ts, names the one it's on and what that comes to once the computer
// reported its size, and saves when let go (after keys, a moment after the last press). In Add your computer it's set
// before the command runs (a Mac's VM is made that size); on the computer's page after, where a Mac's VM keeps it.
import { Check, Lock } from 'lucide-react';
import {
    useEffect,
    useId,
    useRef,
    useState,
    type KeyboardEvent,
    type PointerEvent,
} from 'react';
import { invalidateV1 } from '@/sdk/useV1';
import { NoClickError } from 'noclick';
import {
    setComputerShare,
    type OwnComputer,
} from '@/screens/resources/knowledge';
import { Section } from '@/screens/resources/ui';
import { cn } from '@/ui/utils';
import { useWorkClient } from '../client';
import { DEFAULT_SHARE, SHARES, shareLabel, splitOf, stepFrom } from './share';

const TITLE = 'What NoClick uses';
/** The thumb's radius: the end stop sits this far in from the track's end. */
const R = 16;
const SPRING = 'ease-[cubic-bezier(.25,1.25,.5,1)]';
const STEP_KEYS: Record<string, 1 | -1> = {
    ArrowRight: 1,
    ArrowUp: 1,
    PageUp: 1,
    ArrowLeft: -1,
    ArrowDown: -1,
    PageDown: -1,
};

const still = () =>
    typeof window !== 'undefined' &&
    !!window.matchMedia?.('(prefers-reduced-motion: reduce)').matches;
const clamp = (n: number, lo: number, hi: number) =>
    Math.max(lo, Math.min(hi, n));
const centerOf = (share: number, width: number) =>
    clamp(share * width, R, width - R);
const nearest = (px: number, centers: number[]) =>
    centers.reduce(
        (best, c, i) =>
            Math.abs(c - px) < Math.abs(centers[best] - px) ? i : best,
        0
    );

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
    if (!el || still()) return;
    el.animate(
        xs.map((x) => ({ transform: `translateX(${x}px)` })),
        { duration, easing: 'ease-out' }
    );
}

/** A share shown on its way to `target`, so the CPUs and memory count rather than jump. */
function useCount(target: number) {
    const [shown, setShown] = useState(target);
    const at = useRef(target);
    useEffect(() => {
        if (still()) {
            at.current = target;
            setShown(target);
            return;
        }
        let frame = 0;
        const step = () => {
            const off = target - at.current;
            at.current =
                Math.abs(off) < 0.003 ? target : at.current + off * 0.17;
            setShown(at.current);
            if (at.current !== target) frame = requestAnimationFrame(step);
        };
        frame = requestAnimationFrame(step);
        return () => cancelAnimationFrame(frame);
    }, [target]);
    return shown;
}

/** The stop's name, rolling to the next one the way the thumb went. */
function Roll({ value }: { value: number }) {
    const [now, setNow] = useState(value);
    const [gone, setGone] = useState<{ value: number; up: boolean } | null>(
        null
    );
    if (value !== now) {
        setGone(still() ? null : { value: now, up: value > now });
        setNow(value);
    }
    useEffect(() => {
        if (!gone) return;
        const t = setTimeout(() => setGone(null), 240);
        return () => clearTimeout(t);
    }, [gone]);
    const up = gone?.up ?? true;
    return (
        <span className="inline-grid overflow-hidden align-bottom font-medium">
            {gone && (
                <span
                    key={`gone-${gone.value}`}
                    aria-hidden
                    className={cn(
                        'whitespace-nowrap duration-[170ms] ease-in animate-out fade-out fill-mode-forwards [grid-area:1/1]',
                        up
                            ? 'slide-out-to-top-[70%]'
                            : 'slide-out-to-bottom-[70%]'
                    )}
                >
                    {shareLabel(gone.value)}
                </span>
            )}
            <span
                key={now}
                data-testid="share-stop"
                className={cn(
                    'whitespace-nowrap [grid-area:1/1]',
                    gone &&
                        cn(
                            'duration-[230ms] ease-out animate-in fade-in',
                            up
                                ? 'slide-in-from-bottom-[70%]'
                                : 'slide-in-from-top-[70%]'
                        )
                )}
            >
                {shareLabel(now)}
            </span>
        </span>
    );
}

const STATUS =
    'inline-flex items-center gap-1.5 justify-self-end whitespace-nowrap opacity-0 translate-y-[3px] [grid-area:1/1] [transition:opacity_.2s,transform_.25s_cubic-bezier(.25,1.25,.5,1)]';

/** Saving while a pick is on its way, then Saved for a moment. */
function SaveStatus({ saving, saved }: { saving: boolean; saved: boolean }) {
    return (
        <>
            <span
                aria-hidden
                data-testid="share-status"
                className="ml-auto grid text-[12.5px] font-normal text-muted-foreground"
            >
                <span
                    className={cn(
                        STATUS,
                        saving && 'translate-y-0 opacity-100'
                    )}
                >
                    <span className="h-1.5 w-1.5 animate-[pulse_.7s_ease-in-out_infinite_alternate] rounded-full bg-current" />
                    Saving
                </span>
                <span
                    className={cn(
                        STATUS,
                        !saving && saved && 'translate-y-0 opacity-100'
                    )}
                >
                    <Check className="h-3.5 w-3.5" strokeWidth={2} />
                    Saved
                </span>
            </span>
            <span
                className="sr-only"
                aria-live="polite"
                data-testid="share-saving"
            >
                {saving ? 'Saving' : saved ? 'Saved' : ''}
            </span>
        </>
    );
}

export interface ShareChoiceProps {
    computer: OwnComputer;
    /** Before it's installed, whether the command shown is a Mac's: its VM is made the size picked here. */
    mac?: boolean;
    /** The computer as the API answered a change. */
    onSaved?: (computer: OwnComputer) => void;
    /** On a page, as its own section: the page's heading, with the save state beside it. */
    section?: boolean;
}

export function ShareChoice({
    computer,
    mac = false,
    onSaved,
    section = false,
}: ShareChoiceProps) {
    const client = useWorkClient();
    const fixed = computer.agentShareFixed;
    const has = computer.agentShare ?? DEFAULT_SHARE;
    // The pick sent, shown until the computer as read says it; and one under a hand or keys, not sent yet.
    const [chosen, setChosen] = useState<number | null>(null);
    const [preview, setPreview] = useState<number | null>(null);
    const pick = preview ?? chosen ?? has;
    useEffect(() => {
        if (chosen !== null && computer.agentShare === chosen) setChosen(null);
    }, [chosen, computer.agentShare]);

    const [saving, setSaving] = useState(false);
    const [saved, setSaved] = useState(false);
    const [applied, setApplied] = useState(false);
    const [error, setError] = useState<{
        message: string;
        nextStep: string | null;
    } | null>(null);
    const [flash, setFlash] = useState(false);
    const token = useRef(0);
    useEffect(() => {
        if (!saved) return;
        const t = setTimeout(() => setSaved(false), 1600);
        return () => clearTimeout(t);
    }, [saved]);
    useEffect(() => {
        if (!flash) return;
        const t = setTimeout(() => setFlash(false), 900);
        return () => clearTimeout(t);
    }, [flash]);

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
    const live = useRef(pick);
    const hand = useRef({
        down: false,
        moved: false,
        startX: 0,
        left: 0,
        grab: 0,
        tapAt: null as number | null,
        centers: [] as number[],
    });
    const keyTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
    useEffect(() => {
        if (!hand.current.down && keyTimer.current === null)
            live.current = pick;
    }, [pick]);

    // Positions follow the track's width, without a spring when it's the width that moved.
    useEffect(() => {
        const el = track.current;
        if (!el) return;
        setWidth(el.getBoundingClientRect().width);
        const observer = new ResizeObserver(() => {
            if (hand.current.down) return;
            setResizing(true);
            setWidth(el.getBoundingClientRect().width);
            requestAnimationFrame(() =>
                requestAnimationFrame(() => setResizing(false))
            );
        });
        observer.observe(el);
        return () => observer.disconnect();
    }, []);
    const centers = SHARES.map((s) => centerOf(s.value, width));
    // Before the track is measured (first paint), where a part sits in CSS terms.
    const at = (share: number) =>
        width
            ? `${centerOf(share, width)}px`
            : `clamp(${R}px, ${share * 100}%, calc(100% - ${R}px))`;
    const thumbAt = drag !== null ? `${drag}px` : at(pick);
    const thumbPx = drag ?? centerOf(pick, width);

    const count = useCount(pick);
    const vm = computer.pairing?.vm ?? null;
    const size =
        computer.cpu && computer.memoryGb
            ? { cpu: computer.cpu, gb: computer.memoryGb }
            : vm
              ? { cpu: vm.cpus, gb: vm.memoryGb }
              : null;
    const counting = !fixed && count !== pick;
    const split = size
        ? splitOf(size.cpu, size.gb, fixed ? pick : count, fixed, counting)
        : null;
    const exact = size ? splitOf(size.cpu, size.gb, pick, fixed) : null;

    const commit = async (value: number) => {
        setPreview(null);
        live.current = value;
        if (fixed || value === (chosen ?? has)) return;
        const prior = chosen;
        const t = ++token.current;
        setChosen(value);
        setSaving(true);
        setSaved(false);
        setApplied(false);
        setError(null);
        try {
            const next = await setComputerShare(client, computer.id, value);
            if (t !== token.current) return;
            invalidateV1(`machines/${computer.id}`);
            onSaved?.(next);
            setApplied(next.status === 'running');
            setSaved(true);
        } catch (e) {
            if (t !== token.current) return;
            setChosen(prior);
            setError({
                message: e instanceof Error ? e.message : String(e),
                nextStep: e instanceof NoClickError ? e.nextStep : null,
            });
        } finally {
            if (t === token.current) setSaving(false);
        }
    };

    // The key timer saves with the render it fires in, not the one it was set in.
    const commitLatest = useRef(commit);
    useEffect(() => {
        commitLatest.current = commit;
    });

    const choose = (value: number) => {
        if (value === live.current) return;
        const i = SHARES.findIndex((s) => s.value === value);
        if (!still())
            dots.current[i]?.animate(
                [{ transform: 'scale(2.2)' }, { transform: 'scale(1)' }],
                { duration: 280, easing: 'cubic-bezier(.2,.8,.2,1)' }
            );
        live.current = value;
        setPreview(value);
    };

    const refuse = () => {
        shake(knob.current, [0, -4, 4, -2, 0], 320);
        setFlash(true);
    };

    const measure = () => {
        const rect = track.current!.getBoundingClientRect();
        setWidth(rect.width);
        return rect;
    };

    const onPointerDown = (e: PointerEvent<HTMLDivElement>) => {
        if (e.pointerType === 'mouse' && e.button !== 0) return;
        const rect = measure();
        if (fixed) {
            refuse();
            return;
        }
        const h = hand.current;
        const cs = SHARES.map((s) => centerOf(s.value, rect.width));
        const p = e.clientX - rect.left;
        const x = centerOf(live.current, rect.width);
        Object.assign(h, {
            down: true,
            moved: false,
            startX: e.clientX,
            left: rect.left,
            tapAt: null,
            centers: cs,
        });
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
            else choose(SHARES[nearest(p, cs)].value);
        }
        if (e.pointerType !== 'touch')
            thumb.current!.focus({ preventScroll: true });
    };

    const onPointerMove = (e: PointerEvent<HTMLDivElement>) => {
        const h = hand.current;
        if (!h.down) {
            if (e.pointerType === 'mouse' && !fixed && width)
                setHover(
                    nearest(
                        e.clientX - track.current!.getBoundingClientRect().left,
                        centers
                    )
                );
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
        choose(SHARES[nearest(clamp(raw, cs[0], cs[cs.length - 1]), cs)].value);
    };

    const onPointerEnd = (e: PointerEvent<HTMLDivElement>) => {
        const h = hand.current;
        if (!h.down) return;
        h.down = false;
        setPressed(false);
        setDrag(null);
        if (e.currentTarget.hasPointerCapture(e.pointerId))
            e.currentTarget.releasePointerCapture(e.pointerId);
        if (!h.moved && h.tapAt !== null && e.type !== 'pointercancel')
            choose(SHARES[nearest(h.tapAt, h.centers)].value);
        h.tapAt = null;
        void commit(live.current);
    };

    const onKeyDown = (e: KeyboardEvent<HTMLDivElement>) => {
        const from = live.current;
        const next =
            e.key in STEP_KEYS
                ? stepFrom(from, STEP_KEYS[e.key])
                : e.key === 'Home'
                  ? SHARES[0].value
                  : e.key === 'End'
                    ? SHARES[SHARES.length - 1].value
                    : undefined;
        if (next === undefined) return;
        e.preventDefault();
        if (fixed) {
            refuse();
            return;
        }
        if (next === null) {
            const dir = STEP_KEYS[e.key];
            shake(knob.current, [0, 4 * dir, 0], 260);
            return;
        }
        choose(next);
        if (keyTimer.current !== null) clearTimeout(keyTimer.current);
        keyTimer.current = setTimeout(() => {
            keyTimer.current = null;
            void commitLatest.current(live.current);
        }, 450);
    };

    const noteId = useId();
    const note = fixed
        ? 'NoClick’s VM on this Mac was made this size and keeps it: to change it, remove NoClick from the Mac and add it again.'
        : applied
          ? 'It takes this in a few seconds: agents already working keep going, and each takes its new size when it next starts.'
          : size
            ? null
            : mac
              ? 'On a Mac, NoClick’s VM is made this size when you run the command, and keeps it.'
              : 'A server just for NoClick: all of it. A computer you use: half or less, so it stays quick for you.';
    const springs = drag === null && !resizing;
    const status = <SaveStatus saving={saving} saved={saved} />;

    const body = (
        <div
            data-testid="share-choice"
            className="text-[12.5px] leading-[1.45]"
        >
            <div className="flex flex-wrap items-baseline justify-between gap-x-3 px-0.5 text-[13px] tabular-nums">
                <span className="inline-flex items-baseline whitespace-nowrap text-foreground">
                    <Roll value={pick} />
                    {split && (
                        <>
                            <span aria-hidden>&nbsp;·&nbsp;</span>
                            <span data-testid="share-noclick">
                                {split.noclick}
                            </span>
                        </>
                    )}
                </span>
                {split && (
                    <span
                        data-testid="share-you"
                        className="whitespace-nowrap text-muted-foreground"
                    >
                        You keep {split.you}
                    </span>
                )}
            </div>
            <div
                ref={track}
                data-testid="share-track"
                onPointerDown={onPointerDown}
                onPointerMove={onPointerMove}
                onPointerUp={onPointerEnd}
                onPointerCancel={onPointerEnd}
                onLostPointerCapture={onPointerEnd}
                onPointerLeave={() => setHover(null)}
                className={cn(
                    'relative h-11 touch-pan-y select-none [-webkit-tap-highlight-color:transparent]',
                    fixed ? 'cursor-not-allowed' : 'cursor-pointer'
                )}
            >
                <div
                    className={cn(
                        'absolute inset-x-0 top-3 h-5 overflow-hidden rounded-full bg-foreground/[0.08] shadow-[inset_0_0_0_1px_hsl(var(--foreground)/0.06)]',
                        fixed && 'opacity-[.45]'
                    )}
                >
                    <div
                        className={cn(
                            'absolute inset-y-0 left-0 rounded-full bg-foreground',
                            springs &&
                                `transition-[width] duration-[420ms] motion-reduce:transition-none ${SPRING}`
                        )}
                        style={{ width: thumbAt }}
                    />
                </div>
                {SHARES.map((s, i) => (
                    <span
                        key={s.value}
                        ref={(el) => {
                            dots.current[i] = el;
                        }}
                        aria-hidden
                        className={cn(
                            'pointer-events-none absolute top-[19.5px] -ml-[2.5px] h-[5px] w-[5px] rounded-full [transition:background-color_.15s,transform_.25s_cubic-bezier(.25,1.25,.5,1)] motion-reduce:transition-none',
                            (width ? centers[i] < thumbPx - 2 : s.value < pick)
                                ? 'bg-background/[0.42]'
                                : 'bg-foreground/30',
                            hover === i && s.value !== pick && 'scale-[1.7]',
                            fixed && 'opacity-[.45]'
                        )}
                        style={{ left: at(s.value) }}
                    />
                ))}
                <div
                    ref={thumb}
                    role="slider"
                    tabIndex={0}
                    aria-label={TITLE}
                    aria-describedby={note ? noteId : undefined}
                    aria-valuemin={SHARES[0].value}
                    aria-valuemax={SHARES[SHARES.length - 1].value}
                    aria-valuenow={pick}
                    aria-valuetext={`${shareLabel(pick)}${exact ? `, ${exact.noclick.replace(' · ', ' and ')}` : ''}`}
                    aria-disabled={fixed}
                    onKeyDown={onKeyDown}
                    className={cn(
                        'absolute top-1.5 -ml-4 h-8 w-8 rounded-full outline-none focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring',
                        springs &&
                            `transition-[left] duration-[420ms] motion-reduce:transition-none ${SPRING}`
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
                        {fixed && (
                            <Lock
                                data-testid="share-locked"
                                className="h-3.5 w-3.5"
                                strokeWidth={2}
                            />
                        )}
                    </span>
                </div>
            </div>
            {split && computer.conversationsAtOnce ? (
                // The API's count is for the part it has; it fades while another is picked.
                <p
                    className={cn(
                        'mt-1 px-1 tabular-nums text-muted-foreground transition-opacity',
                        pick !== has && 'opacity-50'
                    )}
                >
                    Up to {computer.conversationsAtOnce}{' '}
                    {computer.conversationsAtOnce === 1
                        ? 'agent'
                        : 'agents'}{' '}
                    at once. What you keep stays yours, whatever the agents do.
                </p>
            ) : null}
            {note && (
                <p
                    id={noteId}
                    data-testid="share-note"
                    data-flash={flash || undefined}
                    className={cn(
                        'mt-2 px-1 leading-[1.4]',
                        flash
                            ? 'text-foreground'
                            : 'text-muted-foreground transition-colors duration-[350ms]'
                    )}
                >
                    {note}
                </p>
            )}
            {error && (
                <div
                    role="alert"
                    data-testid="share-error"
                    className="mt-2 px-1 leading-[1.4]"
                >
                    <p className="text-red-600 dark:text-red-400">
                        {error.message}
                    </p>
                    {error.nextStep && (
                        <p className="mt-0.5 text-muted-foreground">
                            {error.nextStep}
                        </p>
                    )}
                </div>
            )}
        </div>
    );

    if (section)
        return (
            <Section title={TITLE} action={status}>
                {body}
            </Section>
        );
    return (
        <div>
            <div className="mb-2 flex min-h-5 items-center gap-2.5">
                <p className="text-[13px] font-medium leading-5 text-foreground">
                    {TITLE}
                </p>
                {status}
            </div>
            {body}
        </div>
    );
}
