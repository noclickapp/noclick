// Ctrl/Cmd+drag-to-pan for ReactFlow canvases.
//
// macOS: panActivationKeyCode='Meta' works natively (Cmd sets metaKey, not
//        ctrlKey, so d3-zoom's filter passes).
// Windows/Linux: two problems block Ctrl+drag panning through ReactFlow:
//   1. d3-zoom hardcodes `!event.ctrlKey` in its mousedown filter
//   2. ReactFlow's Pane starts a selection box via onPointerDownCapture
// We bypass both by intercepting on `window` in the native capture phase.
// The app uses hydrateRoot(document), so React's event delegation lives on
// `document` — `window` is one level above in the capture chain, ensuring
// our handler fires first. stopPropagation() prevents React and d3-zoom
// from ever seeing the event. Manual panning is done via the store's panBy.
import { useEffect, useRef } from 'react';
import { useStoreApi } from '@xyflow/react';
import { useIsMac } from './useIsMac';

export function useCtrlPan(containerRef: React.RefObject<HTMLElement | null>): 'Meta' | null {
    const isMac = useIsMac();
    const store = useStoreApi();
    const dragRef = useRef<{ x: number; y: number } | null>(null);

    useEffect(() => {
        if (isMac) return;

        const onPointerDown = (e: PointerEvent) => {
            if (e.button !== 0 || !e.ctrlKey) return;
            const el = containerRef.current;
            if (!el) return;
            const target = e.target as HTMLElement;
            if (!el.contains(target)) return;
            if (target.closest('.react-flow__node') || target.closest('.react-flow__edge') || target.closest('.react-flow__handle')) return;

            e.stopPropagation();
            e.preventDefault();
            dragRef.current = { x: e.clientX, y: e.clientY };
        };

        const onPointerMove = (e: PointerEvent) => {
            if (!dragRef.current) return;
            const dx = e.clientX - dragRef.current.x;
            const dy = e.clientY - dragRef.current.y;
            dragRef.current.x = e.clientX;
            dragRef.current.y = e.clientY;
            store.getState().panBy({ x: dx, y: dy });
        };

        const onPointerUp = () => {
            dragRef.current = null;
        };

        // The app uses hydrateRoot(document), so React's event delegation
        // listeners are on `document`. We register on `window` (one level
        // above) in the capture phase so our handler fires first and
        // stopPropagation() prevents React and d3-zoom from seeing the event.
        window.addEventListener('pointerdown', onPointerDown, true);
        window.addEventListener('pointermove', onPointerMove, true);
        window.addEventListener('pointerup', onPointerUp, true);
        return () => {
            window.removeEventListener('pointerdown', onPointerDown, true);
            window.removeEventListener('pointermove', onPointerMove, true);
            window.removeEventListener('pointerup', onPointerUp, true);
        };
    }, [isMac, store, containerRef]);

    return isMac ? 'Meta' : null;
}
