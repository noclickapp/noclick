// What moves while Work is open: the account's platform frames (a channel's messages, who's typing in it, an agent's
// turn or step, a coding agent's place, a resource), which the host receives and hands here, so a view follows them with
// `useWorkFrames` (and a test delivers its own) without a connection of its own. Frames say what moved; the view reads it
// again through the platform client. A `reset` says something may have moved that no frame named: every view reads
// again what it shows.
import { createContext, useContext, useEffect, useRef } from 'react';
import type { PlatformAgentEvent, PlatformChannelEvent, PlatformChannelTypingEvent, PlatformCodingAgentEvent, PlatformResourceEvent } from '@/sdk/frames';

/** Read again whatever is shown. `backstop`: a host with no live source (or one not live yet), on its timer;
 *  `stream`: the change stream said too much changed to name it, or opened without carrying on from its last change. */
export interface WorkReset {
    why: 'backstop' | 'stream';
}

export interface WorkFrames {
    'platform:agent': PlatformAgentEvent;
    'platform:channel': PlatformChannelEvent;
    'platform:channel_typing': PlatformChannelTypingEvent;
    'platform:coding_agent': PlatformCodingAgentEvent;
    'platform:resource': PlatformResourceEvent;
    reset: WorkReset;
}
export type WorkFrameKind = keyof WorkFrames;

export interface WorkLive {
    on<K extends WorkFrameKind>(kind: K, listener: (frame: WorkFrames[K]) => void): () => void;
    deliver<K extends WorkFrameKind>(kind: K, frame: WorkFrames[K]): void;
}

export function createWorkLive(): WorkLive {
    const listeners = new Map<WorkFrameKind, Set<(frame: never) => void>>();
    return {
        on: (kind, listener) => {
            const set = listeners.get(kind) ?? new Set();
            listeners.set(kind, set);
            set.add(listener as (frame: never) => void);
            return () => void set.delete(listener as (frame: never) => void);
        },
        deliver: (kind, frame) => listeners.get(kind)?.forEach((listener) => (listener as (f: typeof frame) => void)(frame)),
    };
}

/** How often a host with no live source has what's shown read again. */
export const BACKSTOP_MS = 60_000;

/** For a host with no live source: a `reset` every `everyMs` while the page is shown (a read also runs again when the
 *  page is focused). Returns what stops it. */
export function resetEvery(live: WorkLive, everyMs = BACKSTOP_MS): () => void {
    const timer = window.setInterval(() => {
        if (document.visibilityState === 'visible') live.deliver('reset', { why: 'backstop' });
    }, everyMs);
    return () => window.clearInterval(timer);
}

export const WorkLiveContext = createContext<WorkLive | null>(null);

export function useWorkLive(): WorkLive {
    const live = useContext(WorkLiveContext);
    if (!live) throw new Error('Work views render inside WorkLiveContext.');
    return live;
}

/** Calls `handler` with each frame of `kind` while mounted; the latest handler, so it needn't be stable. */
export function useWorkFrames<K extends WorkFrameKind>(kind: K, handler: (frame: WorkFrames[K]) => void): void {
    const live = useWorkLive();
    const latest = useRef(handler);
    latest.current = handler;
    useEffect(() => live.on(kind, (frame) => latest.current(frame)), [live, kind]);
}
