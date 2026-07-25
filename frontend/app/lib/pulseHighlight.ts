// The shared "look here" pulse — the amber ring that flashes around an element
// worth noticing. Two callers, both in the config panel: a field control pulses
// when you click its name in the missing-fields banner or follow a deep link,
// and the banner itself pulses whenever it appears for a node, so it registers
// however you got there (clicking the node, or the IncompleteNodeNavigator
// arrows).
//
// The visual lives in tailwind.css (.deep-link-highlight + @keyframes
// deep-link-pulse); this module owns only when it starts and stops.

/** One flash of the ring. Must match the animation duration in tailwind.css. */
const PULSE_CYCLE_MS = 600;

/** Held past the last cycle so the class is never yanked mid-flash. */
const PULSE_SLACK_MS = 800;

/** Flashes for a field control — the long-standing default. */
const DEFAULT_PULSE_CYCLES = 2;

/** Pending class-removal per element, so a re-pulse can cancel the previous
 *  one. Without this the first pulse's timer fires mid-way through the second
 *  and cuts it short. */
const pendingRemoval = new WeakMap<Element, ReturnType<typeof setTimeout>>();

/** Flash the pulse ring around `el`.
 *
 *  `cycles` drives the CSS animation's iteration count and the hold time
 *  together, so they can't drift into a ring that's cut off mid-flash. The
 *  banner asks for more than a field does: it's a larger target the user was
 *  just navigated to, rather than a control they're about to type into.
 *
 *  `radius` matches the ring to the corner of whatever it is wrapping. The
 *  default suits a field control; a padded region that groups several controls
 *  wants a rounder one, or the corners read as a box drawn around the text.
 *
 *  Re-pulsing an element that's already mid-pulse restarts the animation
 *  instead of doing nothing — stepping through incomplete nodes reuses the same
 *  banner element, so without the reflow the second click looks like a no-op. */
export function pulseElement(
    el: Element,
    {
        cycles = DEFAULT_PULSE_CYCLES,
        radius,
    }: { cycles?: number; radius?: number } = {}
): void {
    const pending = pendingRemoval.get(el);
    if (pending) clearTimeout(pending);

    const style = (el as HTMLElement).style;
    el.classList.remove('deep-link-highlight');
    style.setProperty('--pulse-cycles', String(cycles));
    if (radius !== undefined) style.setProperty('--pulse-radius', `${radius}px`);
    void (el as HTMLElement).offsetWidth; // force reflow so the animation restarts
    el.classList.add('deep-link-highlight');

    pendingRemoval.set(
        el,
        setTimeout(() => {
            el.classList.remove('deep-link-highlight');
            style.removeProperty('--pulse-cycles');
            style.removeProperty('--pulse-radius');
            pendingRemoval.delete(el);
        }, cycles * PULSE_CYCLE_MS + PULSE_SLACK_MS)
    );
}

/** Flashes for the missing-fields banner. More than a field gets: the banner is
 *  a passive callout the user may not have been looking for, whereas a field
 *  pulse marks the control they just asked to jump to. */
export const BANNER_PULSE_CYCLES = 3;
