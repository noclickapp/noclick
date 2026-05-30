// Live-updating "time ago" string from an epoch-ms timestamp. Re-renders on a
// 1s interval so captions like "just now" -> "5s ago" -> "2m ago" stay current
// without the caller managing timers. Used by the node status chip (NodeLabel)
// to show how long ago a node last completed or failed; reusable anywhere a
// fresh relative timestamp is needed. Returns '' when the timestamp is undefined.

import { useEffect, useState } from 'react';

export function formatTimeAgo(timestamp: number, now: number): string {
    // A non-finite timestamp (NaN/Infinity) has no meaningful "ago" — render nothing.
    if (!Number.isFinite(timestamp)) return '';
    // Math.max(0, ...) intentionally clamps future timestamps to "just now" (clock-skew guard).
    const sec = Math.max(0, Math.round((now - timestamp) / 1000));
    if (sec < 3) return 'just now';
    if (sec < 60) return `${sec}s ago`;
    const min = Math.floor(sec / 60);
    if (min < 60) return `${min}m ago`;
    const hr = Math.floor(min / 60);
    if (hr < 24) return `${hr}h ago`;
    return `${Math.floor(hr / 24)}d ago`;
}

export function useTimeAgo(timestamp?: number): string {
    const [now, setNow] = useState(() => Date.now());

    useEffect(() => {
        if (timestamp == null || !Number.isFinite(timestamp)) return;
        // Keep the 1s cadence so "just now" -> "5s ago" stays snappy early, but
        // suppress no-op re-renders: returning the SAME prev reference makes
        // useState bail out, so a node stuck on "5m ago" stops re-rendering 60x/min.
        const id = setInterval(
            () =>
                setNow(prev =>
                    formatTimeAgo(timestamp, Date.now()) === formatTimeAgo(timestamp, prev) ? prev : Date.now(),
                ),
            1000,
        );
        return () => clearInterval(id);
    }, [timestamp]);

    if (timestamp == null || !Number.isFinite(timestamp)) return '';
    return formatTimeAgo(timestamp, now);
}
