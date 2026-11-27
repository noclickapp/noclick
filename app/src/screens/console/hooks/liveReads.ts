// What a console view follows live: the frames its host hands the console (`live`) say what moved, and the view reads it
// again then. While the account's change stream doesn't follow the console's client (it's off, or the host has no live
// source), the frames are missed, and the view reads again every BACKSTOP_POLL_MS instead, while the page is shown.
import { useEffect, useRef } from 'react';
import type { WorkFrameKind, WorkFrames } from '@/sdk/live';
import { BACKSTOP_POLL_MS } from '@/sdk/staleReads';
import { useFollowed } from '@/sdk/useV1';
import { useConsole } from './useConsole';

/** The least time between two reads a burst of frames asks for: a busy account costs a read a second at most. */
export const READ_GAP_MS = 1000;

export interface Coalesced {
    /** Ask for a run: now, or once the one under way ends and the gap since the last one has passed. */
    kick: () => void;
    stop: () => void;
}

/** `run`, one at a time and at most once a `gapMs`: a kick while one runs runs it once more after, and a kick while one
 *  waits is that one. */
export function coalesced(run: () => Promise<void> | void, gapMs = READ_GAP_MS): Coalesced {
    let running = false;
    let again = false;
    let stopped = false;
    let last = Number.NEGATIVE_INFINITY;
    let waiting: ReturnType<typeof setTimeout> | null = null;
    const go = async () => {
        waiting = null;
        running = true;
        again = false;
        last = Date.now();
        try {
            await run();
        } catch (err) {
            console.warn('[live] A read the frames asked for failed; the next frame asks again.', err);
        } finally {
            running = false;
        }
        if (again) kick();
    };
    const kick = () => {
        if (stopped || waiting) return;
        if (running) {
            again = true;
            return;
        }
        const wait = last + gapMs - Date.now();
        if (wait <= 0) void go();
        else waiting = setTimeout(() => void go(), wait);
    };
    return {
        kick,
        stop: () => {
            stopped = true;
            if (waiting) clearTimeout(waiting);
        },
    };
}

/**
 * Runs `read` when a frame of `kind` that `matches` arrives, or a reset says anything may have moved (coalesced: one at
 * a time, at most once a READ_GAP_MS, none lost); with the frames missed, every BACKSTOP_POLL_MS instead. Nothing
 * while `enabled` is false.
 */
export function useReadOnFrames<K extends WorkFrameKind>(
    kind: K,
    matches: (frame: WorkFrames[K]) => boolean,
    read: () => Promise<void>,
    enabled = true
): void {
    const { client, live } = useConsole();
    const following = useFollowed(client);
    const latest = useRef({ matches, read });
    latest.current = { matches, read };
    useEffect(() => {
        if (!enabled) return;
        const reads = coalesced(() => latest.current.read());
        const offs = live ? [live.on(kind, (frame) => latest.current.matches(frame) && reads.kick()), live.on('reset', reads.kick)] : [];
        const backstop = following
            ? undefined
            : window.setInterval(() => {
                  if (!document.hidden) reads.kick();
              }, BACKSTOP_POLL_MS);
        return () => {
            offs.forEach((off) => off());
            if (backstop !== undefined) window.clearInterval(backstop);
            reads.stop();
        };
    }, [enabled, live, kind, following]);
}
