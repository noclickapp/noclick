// DOM geometry helpers for elements positioned imperatively from a live rect.
// `getPositioningAncestors` returns the elements whose box size determines an
// element's viewport position, so a ResizeObserver can catch layout shifts that
// MOVE the element without resizing it (e.g. a banner mounting beside it).

/**
 * The element itself plus its offsetParent chain (up to, excluding, body).
 * ResizeObserver only fires on size changes; an absolutely-positioned anchor of
 * fixed size never resizes, but the positioned ancestors that establish its
 * coordinates do grow/shrink when in-flow siblings mount. Observing this set
 * makes a getBoundingClientRect-derived position recompute on those shifts.
 */
export function getPositioningAncestors(el: HTMLElement): HTMLElement[] {
    const els: HTMLElement[] = [el];
    let cur = el.offsetParent as HTMLElement | null;
    while (cur && cur !== document.body) {
        els.push(cur);
        cur = cur.offsetParent as HTMLElement | null;
    }
    return els;
}
