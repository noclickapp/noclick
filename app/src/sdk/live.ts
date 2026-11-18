// What moves while Work is open: the account's platform frames (a channel's messages, who's typing in it, an agent's
// turn or step, a coding agent's place, a resource), which the host receives and hands here, so a view follows them with
// `useWorkFrames` (and a test delivers its own) without a connection of its own. Frames say what moved; the view reads it
// again through the platform client.
import { createContext, useContext, useEffect, useRef } from 'react';
import type { PlatformAgentEvent, PlatformChannelEvent, PlatformChannelTypingEvent, PlatformCodingAgentEvent, PlatformResourceEvent } from '@/sdk/frames';

export interface WorkFrames {
    'platform:agent': PlatformAgentEvent;
    'platform:channel': PlatformChannelEvent;
    'platform:channel_typing': PlatformChannelTypingEvent;
    'platform:coding_agent': PlatformCodingAgentEvent;
    'platform:resource': PlatformResourceEvent;
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
