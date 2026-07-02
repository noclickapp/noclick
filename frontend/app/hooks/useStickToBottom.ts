// Keeps a scrollable container pinned to the bottom as content grows (chat
// transcripts, streaming agent output). It only sticks while the user is already
// near the bottom, so scrolling up to read history isn't yanked back down; `pin()`
// forces a re-stick (e.g. right after the user sends their own message). Added so
// the agent interface chat auto-scrolls without re-implementing the dance inline.
import { useCallback, useEffect, useRef } from 'react';

export function useStickToBottom<T extends HTMLElement = HTMLDivElement>(
  deps: unknown[],
  threshold = 80,
) {
  const ref = useRef<T>(null);
  const stick = useRef(true);

  // Track the user's intent continuously: if they scroll away from the bottom we
  // stop sticking; once they return within `threshold`px we resume.
  const onScroll = useCallback(() => {
    const el = ref.current;
    if (!el) return;
    stick.current = el.scrollHeight - el.scrollTop - el.clientHeight < threshold;
  }, [threshold]);

  // Force the next content change to scroll to bottom regardless of position —
  // for the user's own send, where they always want to follow it.
  const pin = useCallback(() => { stick.current = true; }, []);

  useEffect(() => {
    const el = ref.current;
    if (el && stick.current) el.scrollTop = el.scrollHeight;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);

  return { ref, onScroll, pin };
}
