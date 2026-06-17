// Tracks the bounding rects of the elements a drawer wants to leave undimmed
// when rendered in "emphasized" mode (currently: the drawer itself and the
// chat input). The returned rects feed the SVG/CSS masks in EmphasizedBackdrop
// so the dim overlay hugs their actual rounded shapes and follows resize/drag.

import { useLayoutEffect, useState } from 'react';
import { getPositioningAncestors } from '~/lib/domGeometry';

export interface CutoutRects {
    drawer: DOMRect;
    chatbox: DOMRect | null;
}

interface UseEmphasizedCutoutsOptions {
    /** Start tracking when true; reset to null when false. */
    enabled: boolean;
    drawerRef: React.RefObject<HTMLDivElement | null>;
    /** Optional anchor (e.g. in-place placeholder when the drawer is portaled). */
    anchorRef?: React.RefObject<HTMLDivElement | null>;
}

// The visible rounded rectangle inside the chatbox wrapper. Matches the
// inner chat-input card, not the full-width transparent wrapper.
const CHATBOX_SELECTOR = '[data-tour-target="chatbox"]';
const CHATBOX_INNER_SELECTOR = 'div.rounded-xl, div[class*="rounded-xl"], div[class*="rounded-2xl"]';

export function useEmphasizedCutouts({ enabled, drawerRef, anchorRef }: UseEmphasizedCutoutsOptions): CutoutRects | null {
    const [cutoutRects, setCutoutRects] = useState<CutoutRects | null>(null);

    useLayoutEffect(() => {
        if (!enabled) {
            setCutoutRects(null);
            return;
        }
        const chatboxWrapper = document.querySelector(CHATBOX_SELECTOR);
        const chatboxInner = chatboxWrapper?.querySelector(CHATBOX_INNER_SELECTOR) as HTMLElement | null;

        const update = () => {
            const drawer = drawerRef.current;
            if (!drawer) return;
            setCutoutRects({
                drawer: drawer.getBoundingClientRect(),
                chatbox: chatboxInner?.getBoundingClientRect() ?? null,
            });
        };
        update();

        const ro = new ResizeObserver(update);
        if (drawerRef.current) ro.observe(drawerRef.current);
        // Observe the anchor's offsetParent chain so the cutout follows the
        // chatbox/drawer when an in-flow sibling (e.g. credit banner) mounts and
        // shifts them without resizing the anchor itself.
        if (anchorRef?.current) getPositioningAncestors(anchorRef.current).forEach((el) => ro.observe(el));
        if (chatboxInner) ro.observe(chatboxInner);
        window.addEventListener('resize', update);
        window.addEventListener('scroll', update, true);
        return () => {
            ro.disconnect();
            window.removeEventListener('resize', update);
            window.removeEventListener('scroll', update, true);
        };
    }, [enabled, drawerRef, anchorRef]);

    return cutoutRects;
}
