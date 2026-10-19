// How work moves in the coordinator's thread: the line that rewrites itself (tl-*), a turn's calls receding as the
// next arrives (stk-*), and long work's stages landing their checks (sc-*). The check, the line swap and the shine
// play for everyone; only the stack's travel honours Reduce Motion: there, earlier calls keep their places above the
// current one and fade, without sliding or tilting. `ProgressMotion` keys that off the OS setting; the design labs
// key it off their own switch with `reducedProgressMotion`. Timings scale by --sc-slow, for watching them slowed down.
import { useEffect, useRef, useState, type ReactNode } from 'react';
import { cn } from '~/lib/utils';

export const PROGRESS_MOTION = `
@keyframes tl-in { from { opacity: 0; transform: translateY(5px); filter: blur(2px); } to { opacity: 1; transform: none; filter: none; } }
.tl-in { animation: tl-in 260ms cubic-bezier(0.16, 1, 0.3, 1) both; }
@keyframes tl-out { to { opacity: 0; transform: translateY(-6px); filter: blur(3px); } }
.tl-out { animation: tl-out 280ms cubic-bezier(0.4, 0, 1, 1) both; }
@keyframes tl-settle { from { opacity: 0; filter: blur(3px); } to { opacity: 1; filter: none; } }
.tl-settle { animation: tl-settle 320ms cubic-bezier(0.16, 1, 0.3, 1) both; }
@keyframes tl-open { from { opacity: 0; transform: translateY(-3px); } to { opacity: 1; transform: none; } }
.tl-open { animation: tl-open 220ms cubic-bezier(0.16, 1, 0.3, 1) both; }
@keyframes tl-line { from { opacity: 0; transform: translateY(3px); } to { opacity: 1; transform: none; } }
.tl-line { animation: tl-line 240ms cubic-bezier(0.16, 1, 0.3, 1) both; }
@keyframes tl-breathe { 0%, 100% { opacity: 0.4; } 50% { opacity: 1; } }
.tl-beat, .tl-fill { animation: tl-breathe 1.6s ease-in-out infinite; }
@keyframes tl-fade { from { opacity: 0; } to { opacity: 1; } }
/* Light passing across a word, left to right. */
@keyframes tl-shine { from { background-position: 100% 0; } to { background-position: 0 0; } }
.tl-shine { background: linear-gradient(90deg, hsl(var(--foreground) / 0.6) 38%, hsl(var(--foreground)) 50%, hsl(var(--foreground) / 0.6) 62%) 0 0 / 300% 100%; -webkit-background-clip: text; background-clip: text; color: transparent; animation: tl-shine 2.4s cubic-bezier(0.4, 0, 0.6, 1) infinite; }

/* Each entry sits where its depth puts it (--y, --s, --rx, --o) and springs there, so a call arriving mid-move
   retargets rather than restarts; a new entry rises in from just below. */
.stk { perspective: 420px; perspective-origin: 50% 100%; }
.stk-flip { perspective: 240px; perspective-origin: 50% 50%; }
.stk-entry { opacity: var(--o); transform: translate3d(0, var(--y), 0) rotateX(var(--rx)) scale(var(--s)); transform-origin: 50% 100%; transition: transform 340ms cubic-bezier(0.34, 1.32, 0.64, 1), opacity 260ms ease-out; will-change: transform, opacity; }
.stk-flip .stk-entry { transform-origin: 50% 50%; backface-visibility: hidden; transition: transform 380ms cubic-bezier(0.3, 1.25, 0.5, 1), opacity 220ms ease-out; }
.stk-entry[data-depth="closed"] { transition: transform 360ms cubic-bezier(0.4, 0, 0.2, 1), opacity 200ms ease-out; }
@starting-style {
    .stk .stk-entry { opacity: 0; transform: translate3d(0, 10px, 0) scale(1.02); }
    .stk-flip .stk-entry { opacity: 0; transform: translate3d(0, 12px, 0) rotateX(-80deg); }
}
.stk-grid { grid-template-rows: var(--stk-space) var(--stk-row); transition: grid-template-rows 340ms cubic-bezier(0.4, 0, 0.2, 1); }
.stk-reason { transition: grid-template-rows 300ms cubic-bezier(0.4, 0, 0.2, 1); }
.stk-orb { transition: opacity 200ms ease-out; }

/* A stage finishing: its check (Draw, Pop or Ring), the rail filling toward the next stage, its time settling in as
   its freshness leaves, then the next stage coming alive. */
@keyframes sc-shrink { to { transform: scale(0); opacity: 0; } }
@keyframes sc-stroke { from { stroke-dashoffset: 1; } to { stroke-dashoffset: 0; } }
@keyframes sc-lift { 0% { transform: scale(1); } 45% { transform: scale(1.08); } 100% { transform: scale(1); } }
@keyframes sc-spring { from { transform: scale(0.3); opacity: 0; } 40% { opacity: 1; } to { transform: scale(1); opacity: 1; } }
@keyframes sc-let-go { to { opacity: 0; transform: rotate(-90deg) scale(1.3); } }
@keyframes sc-quiet { to { color: hsl(var(--muted-foreground) / 0.7); } }
@keyframes sc-grow { from { transform: scaleY(0); } to { transform: scaleY(1); } }
@keyframes sc-settle { from { opacity: 0; transform: translateX(4px); filter: blur(2px); } to { opacity: 1; transform: none; filter: none; } }
@keyframes sc-leave { to { opacity: 0; transform: translateX(-4px); filter: blur(2px); } }
@keyframes sc-wake { from { opacity: 0; transform: scale(0.3); } to { opacity: 1; transform: none; } }
@keyframes sc-brighten { from { color: hsl(var(--muted-foreground) / 0.45); } }
.sc-mark { color: hsl(var(--foreground)); animation: sc-quiet calc(420ms * var(--sc-slow, 1)) ease calc(620ms * var(--sc-slow, 1)) both; }
.sc-draw .sc-dot { animation: sc-shrink calc(160ms * var(--sc-slow, 1)) cubic-bezier(0.4, 0, 1, 1) both; }
.sc-draw .sc-stroke { stroke-dasharray: 1; animation: sc-stroke calc(300ms * var(--sc-slow, 1)) cubic-bezier(0.65, 0, 0.35, 1) calc(80ms * var(--sc-slow, 1)) both; }
.sc-draw .sc-check { animation: sc-lift calc(240ms * var(--sc-slow, 1)) cubic-bezier(0.34, 1.56, 0.64, 1) calc(330ms * var(--sc-slow, 1)) both; }
.sc-pop .sc-dot { animation: sc-shrink calc(140ms * var(--sc-slow, 1)) ease-in both; }
.sc-pop .sc-check { animation: sc-spring calc(380ms * var(--sc-slow, 1)) cubic-bezier(0.34, 1.56, 0.64, 1) calc(60ms * var(--sc-slow, 1)) both; }
.sc-ring .sc-loop circle { stroke-dasharray: 1; animation: sc-stroke calc(280ms * var(--sc-slow, 1)) cubic-bezier(0.65, 0, 0.35, 1) both; }
.sc-ring .sc-loop { animation: sc-let-go calc(260ms * var(--sc-slow, 1)) ease-out calc(540ms * var(--sc-slow, 1)) both; }
.sc-ring .sc-dot { animation: sc-shrink calc(160ms * var(--sc-slow, 1)) ease-in calc(240ms * var(--sc-slow, 1)) both; }
.sc-ring .sc-stroke { stroke-dasharray: 1; animation: sc-stroke calc(240ms * var(--sc-slow, 1)) cubic-bezier(0.65, 0, 0.35, 1) calc(300ms * var(--sc-slow, 1)) both; }
.sc-fill { animation: sc-grow calc(320ms * var(--sc-slow, 1)) cubic-bezier(0.65, 0, 0.35, 1) calc(260ms * var(--sc-slow, 1)) both; }
.sc-took { animation: sc-settle calc(300ms * var(--sc-slow, 1)) cubic-bezier(0.16, 1, 0.3, 1) calc(160ms * var(--sc-slow, 1)) both; }
.sc-took-out { animation: sc-leave calc(200ms * var(--sc-slow, 1)) cubic-bezier(0.4, 0, 1, 1) calc(60ms * var(--sc-slow, 1)) both; }
.sc-alive { animation: sc-wake calc(320ms * var(--sc-slow, 1)) cubic-bezier(0.34, 1.56, 0.64, 1) calc(560ms * var(--sc-slow, 1)) both; }
.sc-name-live { animation: sc-brighten calc(300ms * var(--sc-slow, 1)) ease calc(560ms * var(--sc-slow, 1)) both; }
.sc-took-live { animation: sc-settle calc(300ms * var(--sc-slow, 1)) cubic-bezier(0.16, 1, 0.3, 1) calc(560ms * var(--sc-slow, 1)) both; }
`;

/** Reduce Motion's one rule, under `scope` (a selector and a space, or '' inside the media query): the stack's
 *  entries stand where their depth puts them and only fade, arriving in place, its rows open without easing. */
export function reducedProgressMotion(scope: string): string {
    return `
${scope}.stk-entry { transition: opacity 200ms ease !important; }
@starting-style { ${scope}.stk .stk-entry { transform: translate3d(0, var(--y), 0) rotateX(var(--rx)) scale(var(--s)); } }
${scope}.stk-grid, ${scope}.stk-reason { transition: none; }
`;
}

const ON_THE_OS = `${PROGRESS_MOTION}\n@media (prefers-reduced-motion: reduce) {${reducedProgressMotion('')}}\n`;

/** The motion, once per page however many turns and cards draw with it (React hoists and dedupes by `href`). */
export function ProgressMotion() {
    return (
        <style href="agent-progress-motion" precedence="default">
            {ON_THE_OS}
        </style>
    );
}

/** Text that replaces itself: the new line rises in, the one before dissolves up and away. `fill` lets it take its
 *  row's whole height; `appear={false}` draws the first line in place, so a card read back from history stands still. */
export function Swap({ id, children, className, fill, appear = true }: { id: string; children: ReactNode; className?: string; fill?: boolean; appear?: boolean }) {
    const first = useRef(id);
    const shown = useRef({ id, node: children });
    const [leaving, setLeaving] = useState<{ id: string; node: ReactNode } | null>(null);
    useEffect(() => {
        if (shown.current.id === id) return;
        setLeaving(shown.current);
        const timer = window.setTimeout(() => setLeaving(null), 320);
        return () => window.clearTimeout(timer);
    }, [id]);
    useEffect(() => {
        shown.current = { id, node: children };
    });
    return (
        <span className={cn('relative block min-w-0', className)}>
            {leaving && leaving.id !== id && (
                <span key={`out-${leaving.id}`} className={cn('tl-out pointer-events-none absolute inset-x-0 top-0', fill && 'bottom-0')} aria-hidden>
                    {leaving.node}
                </span>
            )}
            <span key={`in-${id}`} className={cn((appear || id !== first.current) && 'tl-in', 'block', fill && 'h-full')}>
                {children}
            </span>
        </span>
    );
}

export type StageCheck = 'draw' | 'pop' | 'ring';

export const STAGE_CHECKS: { id: StageCheck; name: string; note: string }[] = [
    { id: 'draw', name: 'Draw', note: 'The dot shrinks away as the check strokes itself in, with a small lift at the end.' },
    { id: 'pop', name: 'Pop', note: 'The check springs in from small, just past full size, and settles.' },
    { id: 'ring', name: 'Ring', note: 'A thin ring closes around the dot, the check draws inside it, and the ring lets go.' },
];

/** Something just finished: its live dot giving way to a check, the way `check` says. */
export function FreshCheck({ check }: { check: StageCheck }) {
    return (
        <span className={cn('sc-mark relative grid h-4 w-4 place-items-center', `sc-${check}`)}>
            <span className="sc-dot absolute left-1/2 top-1/2 -ml-1 -mt-1 h-2 w-2 rounded-full bg-foreground/80" aria-hidden />
            {check === 'ring' && (
                <svg className="sc-loop absolute inset-0 -rotate-90" viewBox="0 0 16 16" fill="none" aria-hidden>
                    <circle cx="8" cy="8" r="6.75" stroke="currentColor" strokeWidth="1.25" pathLength={1} />
                </svg>
            )}
            <svg className="sc-check relative h-3 w-3" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2.5} strokeLinecap="round" strokeLinejoin="round" aria-hidden>
                <path className="sc-stroke" d="M20 6 9 17l-5-5" pathLength={1} />
            </svg>
        </span>
    );
}
