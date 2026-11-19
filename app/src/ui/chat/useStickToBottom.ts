// Keeps a scrollable container pinned to the bottom as its content grows (chat transcripts, streaming agent output,
// and what draws after its message: markdown from its chunk, a diagram, a card). It only sticks while the user is at
// the bottom, so scrolling up to read history isn't yanked back down; `pin()` forces a re-stick (e.g. right after the
// user sends their own message). The container's first child holds the content. Added so the agent interface chat
// auto-scrolls without re-implementing the dance inline.
import { useCallback, useEffect, useRef } from 'react';

export function useStickToBottom<T extends HTMLElement = HTMLDivElement>(
  deps: unknown[],
  threshold = 80,
) {
  const node = useRef<T | null>(null);
  const stick = useRef(true);
  const lastTop = useRef(0);
  const lastHeight = useRef(0);
  const growth = useRef<ResizeObserver | null>(null);

  const follow = useCallback(() => {
    const el = node.current;
    if (!el || !stick.current) return;
    el.scrollTop = el.scrollHeight;
    lastTop.current = el.scrollTop;
    lastHeight.current = el.scrollHeight;
  }, []);

  // Only the user moving up leaves the bottom: content growing under a stuck view moves the bottom away without
  // moving scrollTop, and the scroll event of our own pin can arrive after more content drew. Nor does the browser
  // keeping what's in view in place as content above it settles shorter (scroll anchoring): a move up no larger than
  // the content's change in size, in the same frame, is that. Back within `threshold`px of the bottom, it sticks again.
  const onScroll = useCallback(() => {
    const el = node.current;
    if (!el) return;
    const anchored = lastTop.current - el.scrollTop <= Math.abs(el.scrollHeight - lastHeight.current);
    const movedUp = el.scrollTop < lastTop.current && !anchored;
    lastTop.current = el.scrollTop;
    lastHeight.current = el.scrollHeight;
    stick.current = el.scrollHeight - el.scrollTop - el.clientHeight < threshold || (stick.current && !movedUp);
  }, [threshold]);

  // The container, its content followed as it grows and its bottom kept in view when the container shrinks (a card
  // docking on the composer under it).
  const ref = useCallback(
    (el: T | null) => {
      growth.current?.disconnect();
      growth.current = null;
      node.current = el;
      const content = el?.firstElementChild;
      if (!content) return;
      growth.current = new ResizeObserver(follow);
      growth.current.observe(content);
      growth.current.observe(el);
    },
    [follow],
  );

  // Force the next content change to scroll to bottom regardless of position —
  // for the user's own send, where they always want to follow it.
  const pin = useCallback(() => { stick.current = true; }, []);

  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(follow, deps);

  return { ref, onScroll, pin };
}
