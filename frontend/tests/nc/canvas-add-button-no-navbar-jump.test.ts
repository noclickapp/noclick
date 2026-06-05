// Regression test for the "+" (add node) button yanking the in-canvas navbar.
// Opening the flow helper via "+" auto-focuses the node-search input one frame
// in, while the panel is still mid slide-up (the input sits below the fold). A
// default .focus() scroll-reveals it, scrolling the FlowCanvas root container
// and dragging the in-canvas top bar (the "navbar") up and out, then back. The
// fix focuses with { preventScroll: true } (NodeSearchBar). This test reproduces
// the mechanism on the real app DOM: it proves a default focus DOES scroll the
// canvas here (negative control, so the test can't pass vacuously) and asserts
// the preventScroll focus the component now uses keeps the navbar fixed.
//
// Note: it asserts the DOM-level contract rather than driving the component's
// rAF-deferred focus, because requestAnimationFrame is throttled to zero in a
// backgrounded test tab — the component's focus would never fire here.
import { nc } from '~/lib/nc';

const SEARCH = 'input[placeholder="Search nodes..."]';

function closest(el: Element | null, pred: (e: Element) => boolean): Element | null {
    let cur: Element | null = el;
    while (cur) {
        if (pred(cur)) return cur;
        cur = cur.parentElement;
    }
    return null;
}

export default async function () {
    // Open the flow helper on the Nodes tab via the "+" button.
    (document.activeElement as HTMLElement | null)?.blur?.();
    if (!document.querySelector(SEARCH)) {
        (document.querySelector('[aria-label="Add a node"]') as HTMLElement)?.click();
        await nc.wait.forElement(SEARCH);
    }

    const input = document.querySelector<HTMLInputElement>(SEARCH)!;
    nc.assert.truthy(input, 'Node search input is present when the helper is open');

    // FlowCanvas root = the overflow-hidden bg-black column that scrolls on focus.
    const fcRoot = closest(input, (e) =>
        /w-full/.test(e.className) && /overflow-hidden/.test(e.className) && /bg-black/.test(e.className)
    ) as HTMLElement | null;
    nc.assert.truthy(fcRoot, 'Found the FlowCanvas root container');
    // The in-canvas "navbar" — the top bar inside that root (the element that
    // visibly scrolls out of view in the bug).
    const navbar = fcRoot!.firstElementChild as HTMLElement;
    nc.assert.truthy(navbar, 'Found the in-canvas top bar');

    // Force the off-screen condition the slide-up animation produces: push the
    // panel down so the input sits below the fold.
    const slide =
        (document.querySelector('.animate-slide-up') as HTMLElement | null) ||
        (closest(input, (e) => /h-full/.test(e.className)) as HTMLElement | null);
    const prevTransform = slide?.style.transform ?? '';
    if (slide) slide.style.transform = 'translateY(100%)';

    const navTop = () => Math.round(navbar.getBoundingClientRect().top);
    const reset = () => {
        fcRoot!.scrollTop = 0;
        input.blur();
    };

    // ── Negative control: a default focus scrolls the canvas (navbar moves up) ──
    reset();
    const navAtRest = navTop();
    input.focus();
    const navAfterDefault = navTop();
    const scrolledByDefault = fcRoot!.scrollTop;

    // ── The fix: preventScroll focus leaves the navbar exactly in place ─────────
    reset();
    input.focus({ preventScroll: true });
    const navAfterPreventScroll = navTop();
    const scrolledByPreventScroll = fcRoot!.scrollTop;

    // Restore the DOM.
    fcRoot!.scrollTop = 0;
    if (slide) slide.style.transform = prevTransform;

    // The negative control must actually move the navbar, else the test proves
    // nothing (e.g. layout changed so the input is no longer below the fold).
    nc.assert.truthy(
        scrolledByDefault > 0 && navAfterDefault < navAtRest,
        `Sanity: a default focus must scroll the canvas (scrollTop=${scrolledByDefault}, navTop ${navAtRest}->${navAfterDefault})`
    );

    // The fix: preventScroll keeps the canvas un-scrolled and the navbar fixed.
    nc.assert.equal(scrolledByPreventScroll, 0, 'preventScroll focus must not scroll the FlowCanvas root');
    nc.assert.equal(
        navAfterPreventScroll,
        navAtRest,
        'preventScroll focus must leave the in-canvas navbar exactly in place'
    );

    return { navAtRest, navAfterDefault, navAfterPreventScroll, scrolledByDefault };
}
