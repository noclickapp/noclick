// A press held on a touch screen, a phone's way to what a laptop shows on hover: holding fires `onLong`, and the tap
// that ends the hold does nothing else. A mouse is left to its hover; a finger that moves is scrolling, not holding.
import { useEffect, useRef, type MouseEvent, type PointerEvent } from 'react';

const HOLD_MS = 450;
const SLOP_PX = 10;

export function useLongPress(onLong: () => void) {
    const timer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
    const from = useRef<{ x: number; y: number } | null>(null);
    const held = useRef(false);
    const stop = () => {
        clearTimeout(timer.current);
        from.current = null;
    };
    useEffect(() => stop, []);
    return {
        onPointerDown: (e: PointerEvent) => {
            if (e.pointerType === 'mouse') return;
            held.current = false;
            from.current = { x: e.clientX, y: e.clientY };
            timer.current = setTimeout(() => {
                held.current = true;
                from.current = null;
                onLong();
            }, HOLD_MS);
        },
        onPointerMove: (e: PointerEvent) => {
            if (from.current && Math.hypot(e.clientX - from.current.x, e.clientY - from.current.y) > SLOP_PX) stop();
        },
        onPointerUp: stop,
        onPointerCancel: stop,
        // The browser's own long-press menu (copy, look up) would sit over the sheet.
        onContextMenu: (e: MouseEvent) => {
            if (held.current || from.current) e.preventDefault();
        },
        onClickCapture: (e: MouseEvent) => {
            if (!held.current) return;
            held.current = false;
            e.preventDefault();
            e.stopPropagation();
        },
    };
}
