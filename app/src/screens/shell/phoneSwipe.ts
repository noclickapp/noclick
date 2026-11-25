// How the phone shell reads a sideways swipe: whether a touch is a swipe or a scroll, whether it began on something that
// takes sideways drags itself, and where a released drawer or page settles. Plain functions over numbers and elements, so
// the drawer (PhoneDrawer.tsx) stays a thin layer of touch events over them and they can be tested without a finger.

/** What a swipe does: opens or closes the drawer, or goes back to the screen under this one, or forward to the one
 *  just left. */
export type SwipeMode = 'open' | 'close' | 'back' | 'forward';

/** How far a touch moves before it's read as a swipe or a scroll. */
export const SLOP_PX = 8;
/** A swipe leans this much more sideways than up or down. */
const SIDEWAYS = 1.15;
/** Past this speed (px per ms) a release goes where the finger was heading, however far it got. */
export const FLICK = 0.35;
/** A moving touch read: a swipe to the right or left, a scroll (anything else), or too small to say yet. */
export function readDirection(dx: number, dy: number): 'right' | 'left' | 'scroll' | null {
    if (Math.abs(dx) < SLOP_PX && Math.abs(dy) < SLOP_PX) return null;
    if (Math.abs(dx) <= Math.abs(dy) * SIDEWAYS) return 'scroll';
    return dx > 0 ? 'right' : 'left';
}

/** Whether a released drawer settles open (or a page goes on to the screen it's pulled toward), from how far it got (0
 *  where it started, 1 all the way) and the finger's speed (px per ms, positive toward 1). A flick wins; otherwise the
 *  nearer side. */
export function settlesOpen(progress: number, velocity: number): boolean {
    if (velocity > FLICK) return true;
    if (velocity < -FLICK) return false;
    return progress > 0.5;
}

/** How long a released drawer takes to settle: about as fast as the finger left it (the curve starts at ~4.5× its
 *  average speed), within bounds that keep a slow release from dragging and a flick from snapping. */
export function settleMs(distance: number, velocity: number): number {
    const fingerPace = Math.abs(velocity) > 0.05 ? (4.5 * distance) / Math.abs(velocity) : Infinity;
    return Math.round(Math.min(320, Math.max(170, fingerPace)));
}

/** The finger's speed at release, in px per ms, from where it was over its last ~100ms. A finger that stopped before
 *  letting go has none. */
export function releaseVelocity(samples: readonly { t: number; x: number }[], now: number): number {
    const recent = samples.filter((s) => now - s.t <= 100);
    if (recent.length < 2) return 0;
    const first = recent[0];
    const last = recent[recent.length - 1];
    if (now - last.t > 60 || last.t === first.t) return 0;
    return (last.x - first.x) / (last.t - first.t);
}

const OWN_SWIPES = '[data-no-swipe], .react-flow, input[type="range"], [role="slider"]';
/** What a person types in: a tap there places the caret, and a swipe there selects text. */
export const FIELDS = 'input, textarea, select, [contenteditable]:not([contenteditable="false"])';

/** True when a touch on `target` belongs to what it landed on: the canvas, a slider, the field being typed in, anything
 *  marked `data-no-swipe`, or something that scrolls sideways and has room to go the finger's way (a swipe right first
 *  scrolls a list back to its start; a swipe left scrolls it on to its end). */
export function takesItsOwnSwipe(target: Element | null, toward: 'right' | 'left' = 'right'): boolean {
    const typing = document.activeElement;
    if (typing && typing !== document.body && typing.matches(FIELDS) && target && typing.contains(target)) return true;
    for (let el = target; el && el !== document.body; el = el.parentElement) {
        if (el.matches(OWN_SWIPES)) return true;
        const room = toward === 'right' ? el.scrollLeft > 0 : el.scrollLeft < el.scrollWidth - el.clientWidth - 1;
        if (room && el.scrollWidth > el.clientWidth) {
            const overflow = getComputedStyle(el).overflowX;
            if (overflow === 'auto' || overflow === 'scroll') return true;
        }
    }
    return false;
}

/** True while a dialog or menu other than the drawer is up: a swipe then belongs to it. */
export function anotherLayerOpen(drawer: Element | null): boolean {
    for (const el of document.querySelectorAll('[role="dialog"], [role="alertdialog"], [role="menu"]')) {
        if (el !== drawer) return true;
    }
    return false;
}
