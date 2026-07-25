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

// ── Pulse requests ──────────────────────────────────────────────────────────
// For pulsing something the requester cannot reach: a hand-off names its target
// before the panel showing it has rendered. The target claims the request when
// it mounts, or hears the event if it was already mounted — the two orderings a
// hand-off can produce.
//
// This is deliberately a request, not a rule the target evaluates itself.
// "Pulse whenever this looks unfinished" fires on every ordinary visit, which
// trains people to ignore it.

const PULSE_REQUEST_EVENT = 'noclick:pulse-request';

/** Dropped if nothing claims it — a hand-off the user abandoned must not fire a
 *  pulse minutes later when they open that panel for their own reasons. */
const PULSE_REQUEST_TTL_MS = 5000;

let pendingRequest: { key: string; at: number } | null = null;

/** Ask for a pulse on `key`, whether or not its element exists yet. */
export function requestPulse(key: string): void {
    pendingRequest = { key, at: Date.now() };
    document.dispatchEvent(
        new CustomEvent(PULSE_REQUEST_EVENT, { detail: { key } })
    );
}

/** Take the pending request for `key`, if there is a live one. Consuming it is
 *  what stops the same hand-off pulsing twice across the two orderings. */
export function claimPulse(key: string): boolean {
    if (!pendingRequest || pendingRequest.key !== key) return false;
    const fresh = Date.now() - pendingRequest.at <= PULSE_REQUEST_TTL_MS;
    pendingRequest = null;
    return fresh;
}

/** Notified when any pulse is requested; the listener still has to claim it. */
export function onPulseRequested(listener: (key: string) => void): () => void {
    const handler = (event: Event) =>
        listener((event as CustomEvent<{ key: string }>).detail.key);
    document.addEventListener(PULSE_REQUEST_EVENT, handler);
    return () => document.removeEventListener(PULSE_REQUEST_EVENT, handler);
}

/** Pulse key for a node's credential controls. */
export const credentialsPulseKey = (nodeId: string) => `credentials:${nodeId}`;
