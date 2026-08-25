// Shared popover scaffolding for the three AgentChatBlock pickers
// (AgentModelPicker, AgentSubModelPicker, AgentChatHistory).
// Each picker has its own trigger / panel JSX + per-popover positioning
// (width / horizontal anchor), but the open/close + outside-click + Escape +
// reposition-on-resize/scroll plumbing is identical. Centralising it keeps
// the three components in lockstep on UX details (Esc closes, scrolling
// re-anchors, clicks inside the panel don't dismiss).

import { useEffect, useLayoutEffect, useRef, useState } from 'react';
import { useIsMobile } from '~/hooks/useIsMobile';

export interface AnchoredPopoverPos {
  top: number;
  left: number;
  width: number;
}

export interface UseAnchoredPopoverResult<TTrigger extends HTMLElement, TPanel extends HTMLElement> {
  open: boolean;
  setOpen: (next: boolean | ((prev: boolean) => boolean)) => void;
  triggerRef: React.RefObject<TTrigger | null>;
  panelRef: React.RefObject<TPanel | null>;
  /** Position the consumer applies to the rendered panel (via createPortal). */
  pos: AnchoredPopoverPos | null;
}

/** Compute a popover position from the trigger's bounding rect. Implementations
 *  decide width and horizontal anchor; vertical is conventionally
 *  `triggerRect.bottom + offset`. Returning null prevents positioning. */
export type ComputeAnchoredPos = (triggerRect: DOMRect) => AnchoredPopoverPos | null;

/** Manage open/close state and recompute the panel's screen position whenever
 *  the trigger moves (window resize, parent scroll, etc.). Closes on
 *  outside-click and Escape. */
export function useAnchoredPopover<TTrigger extends HTMLElement = HTMLButtonElement, TPanel extends HTMLElement = HTMLDivElement>(
  computePos: ComputeAnchoredPos,
): UseAnchoredPopoverResult<TTrigger, TPanel> {
  const [open, setOpen] = useState(false);
  const [pos, setPos] = useState<AnchoredPopoverPos | null>(null);
  const triggerRef = useRef<TTrigger | null>(null);
  const panelRef = useRef<TPanel | null>(null);
  // ≤768px matches the Dashboard's single-column mobile layout (see Dashboard's
  // useIsMobile(769)). On mobile a narrow anchored dropdown reads as cramped, so
  // every header popover drops as a full-width sheet under its trigger instead —
  // mirroring the mobile conversation-history panel.
  const isMobile = useIsMobile(769);

  // Position the panel under the trigger. Listening to scroll in capture phase
  // catches nested scroll containers (the sidebar, the chat list, etc.).
  useLayoutEffect(() => {
    if (!open || !triggerRef.current) return;
    const update = () => {
      const rect = triggerRef.current?.getBoundingClientRect();
      if (!rect) return;
      const raw = computePos(rect);
      if (!raw) {
        setPos(null);
        return;
      }
      const margin = 8;
      const vw = window.innerWidth;
      if (isMobile) {
        // Full-width sheet dropping from just under the trigger — keeps the
        // vertical anchor the caller chose but ignores its width/left so every
        // popover fills the screen the way the mobile history panel does.
        setPos({ top: raw.top, left: margin, width: vw - margin * 2 });
        return;
      }
      // Clamp to the viewport so a fixed-width panel anchored near a right-side
      // trigger can never run off the edge and get cropped. Width shrinks to
      // fit narrow screens; left is pinned so the panel stays fully on-screen.
      const width = Math.min(raw.width, vw - margin * 2);
      const left = Math.min(
        Math.max(margin, raw.left),
        Math.max(margin, vw - width - margin)
      );
      setPos({ top: raw.top, left, width });
    };
    update();
    window.addEventListener('resize', update);
    window.addEventListener('scroll', update, true);
    return () => {
      window.removeEventListener('resize', update);
      window.removeEventListener('scroll', update, true);
    };
  }, [open, computePos, isMobile]);

  useEffect(() => {
    if (!open) return;
    const onMouseDown = (e: MouseEvent) => {
      const target = e.target as Node;
      if (triggerRef.current?.contains(target)) return;
      if (panelRef.current?.contains(target)) return;
      setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') setOpen(false); };
    document.addEventListener('mousedown', onMouseDown);
    document.addEventListener('keydown', onKey);
    return () => {
      document.removeEventListener('mousedown', onMouseDown);
      document.removeEventListener('keydown', onKey);
    };
  }, [open]);

  return { open, setOpen, triggerRef, panelRef, pos };
}
