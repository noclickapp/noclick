// An agent conversation's look, t3code's on NoClick's tokens: one reading lane shared by the timeline and the box,
// borderless controls with a 4% fill on hover, drawers that tuck out from behind the box, and "alive" drawn as a slow
// shine across the words rather than dots or spinners.

/** The reading lane the timeline and the box share, so their edges line up (t3code's 46rem). */
export const LANE = 'mx-auto w-full max-w-[46rem]';

/** The box's controls: borderless, a 4% fill on hover, a press you can feel. */
export const CONTROL =
    'inline-flex h-7 min-w-0 shrink-0 items-center gap-1.5 rounded-full px-2 text-sm font-medium text-foreground/80 transition-[background-color,color,transform] duration-150 hover:bg-foreground/[0.04] hover:text-foreground active:scale-[0.97] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring/70 data-[state=open]:bg-foreground/[0.06] data-[state=open]:text-foreground';

/** What tucks out from behind the box's top edge: the menus and the banners above it. */
export const DRAWER = 'rounded-t-[26px] bg-composer ring-1 ring-inset ring-border dark:ring-foreground/[0.09]';
/** How far a drawer tucks under the box. */
export const TUCK = 17;

/** Small round buttons, t3code's xs: 28px, a press you can feel. */
export const XS_BUTTON =
    'inline-flex h-7 shrink-0 items-center justify-center gap-1.5 rounded-full px-2.5 text-xs font-medium transition-[background-color,color,transform] duration-150 active:scale-[0.97] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/70 disabled:pointer-events-none disabled:opacity-40';
export const XS_PRIMARY = 'bg-foreground text-background hover:bg-foreground/90';
export const XS_OUTLINE = 'text-foreground/85 ring-1 ring-inset ring-border hover:bg-foreground/[0.05] hover:text-foreground dark:ring-foreground/[0.12]';
export const XS_GHOST = 'text-muted-foreground hover:bg-foreground/[0.05] hover:text-foreground';

/** Text that underlines on hover, for actions in a line of text. */
export const INLINE =
    'inline-flex shrink-0 items-center rounded-full font-medium underline-offset-2 hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/70 disabled:pointer-events-none disabled:opacity-60';
export const INLINE_MUTED = `${INLINE} text-muted-foreground hover:text-foreground`;

export const ICON_BUTTON =
    'grid h-7 w-7 shrink-0 place-items-center rounded-full text-muted-foreground transition-colors hover:bg-foreground/[0.05] hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/70 data-[state=open]:bg-foreground/[0.06] data-[state=open]:text-foreground';

/** The motion only the conversation uses (the shine and the menus' rise are Work's own, agents/AgentRing's WorkMotion). */
export const CONVERSATION_CSS = `@keyframes wc-drawer { from { transform: translateY(10px); opacity: 0 } }
.wc-drawer { animation: wc-drawer 260ms cubic-bezier(0.32, 0.72, 0, 1) }
@keyframes wc-swap { from { transform: scale(0.6) rotate(-30deg); opacity: 0 } }
.wc-swap { animation: wc-swap 180ms cubic-bezier(0.32, 0.72, 0, 1) }
@keyframes wc-slide-in { from { opacity: 0; transform: translateX(12px) } }
.wc-slide-in { animation: wc-slide-in 420ms cubic-bezier(0.2, 0.8, 0.2, 1) both }
@keyframes wc-panel { from { opacity: 0; transform: translateY(-6px) scale(0.985) } }
.wc-panel { animation: wc-panel 240ms cubic-bezier(0.2, 0.8, 0.2, 1) both; transform-origin: top right }
@keyframes wc-tick { from { opacity: 0; transform: translateY(3px) } }
.wc-tick { animation: wc-tick 360ms cubic-bezier(0.2, 0.8, 0.2, 1) both }
@keyframes wc-typing { 0%, 60%, 100% { opacity: .35; transform: translateY(0) } 30% { opacity: 1; transform: translateY(-2px) } }
.wc-typing > span { animation: wc-typing 1.2s ease-in-out infinite }
.wc-typing > span:nth-child(2) { animation-delay: .15s }
.wc-typing > span:nth-child(3) { animation-delay: .3s }
@media (prefers-reduced-motion: reduce) { .wc-drawer, .wc-swap, .wc-slide-in, .wc-panel, .wc-tick, .wc-typing > span { animation: none } }`;

/** Elapsed time as t3code writes it: 12s, 1m 04s, 1h 02m. */
export function spent(ms: number): string {
    const sec = Math.max(0, Math.round(ms / 1000));
    if (sec < 60) return `${sec}s`;
    if (sec < 3600) return `${Math.floor(sec / 60)}m ${String(sec % 60).padStart(2, '0')}s`;
    return `${Math.floor(sec / 3600)}h ${String(Math.floor((sec % 3600) / 60)).padStart(2, '0')}m`;
}

export const clockOf = (at: number) => new Date(at).toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit' });
