// Debounced-once degradation telemetry: when `when` holds continuously for
// `afterMs`, emit ONE telemetry event per key per session. Built for "silent
// fallback is a masked outage" seams, where a silent fallback can hide a
// persistent degradation unless the seam is watched. Generic so the next
// degradation watchdog reuses it instead
// of hand-rolling another Set + setTimeout dance.

import { useEffect } from 'react';

import { track } from '~/lib/telemetry';

/** Keys that already reported this session. */
const _reported = new Set<string>();

const DEFAULT_AFTER_MS = 2 * 60 * 1000;

export function useTrackOnceAfter(
  key: string,
  event: string,
  attrs: Record<string, unknown>,
  when: boolean,
  afterMs: number = DEFAULT_AFTER_MS,
): void {
  useEffect(() => {
    if (!when || _reported.has(key)) return;
    const timer = setTimeout(() => {
      if (_reported.has(key)) return;
      _reported.add(key);
      track(event, attrs);
    }, afterMs);
    // `when` flipping false (condition recovered) cancels the pending report.
    return () => clearTimeout(timer);
    // attrs is intentionally not a dep — it's captured at arm time; re-arming on
    // object identity would reset the debounce every render.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key, event, when, afterMs]);
}
