/* Replays a canned rehearsal on a virtual clock so every design variant is
   judged against the same run at a chosen pace. Starts idle — the run button is
   part of the UX being designed — and state derives purely from virtual time,
   so replay, jump-to-end and scenario switches are trivial with no leaking
   timers. */

import { useEffect, useMemo, useRef, useState } from 'react';
import type { Provider, Scenario, ToolEvent } from './fixture';

export type ReplaySpeed = 1 | 4 | 'end';

export type ReplayRow =
    | { kind: 'thought'; id: string; at: number; text: string }
    | {
          kind: 'tool';
          id: string;
          at: number;
          text: string;
          provider: Provider;
          status: 'in_progress' | 'completed';
          ms?: number;
          elapsed: number;
          args: Record<string, unknown>;
          /** Present once completed — what the mock answered. */
          result?: Record<string, unknown>;
      };

export interface ReplayState {
    phase: 'idle' | 'running' | 'done';
    /** Virtual ms since run start; 0 while idle. */
    t: number;
    rows: ReplayRow[];
    artifact: Scenario['artifact'] | null;
    start: () => void;
    replay: () => void;
}

function rowsAt(scenario: Scenario, t: number): ReplayRow[] {
    const rows: ReplayRow[] = [];
    for (const e of scenario.events) {
        if (e.at > t) continue;
        if (e.kind === 'thought') {
            rows.push({ kind: 'thought', id: `th-${e.at}`, at: e.at, text: e.text });
            continue;
        }
        const done = t >= e.completeAt;
        rows.push({
            kind: 'tool',
            id: e.step,
            at: e.at,
            text: e.text,
            provider: e.provider,
            status: done ? 'completed' : 'in_progress',
            ms: done ? e.completeAt - e.at : undefined,
            elapsed: done ? 0 : t - e.at,
            args: e.args,
            result: done ? (e as ToolEvent).result : undefined,
        });
    }
    return rows;
}

export function useReplay(scenario: Scenario, speed: ReplaySpeed): ReplayState {
    // null = idle; the run only exists once the button is pressed.
    const [t, setT] = useState<number | null>(null);
    const speedRef = useRef(speed);

    // A different trigger is a different run: back to idle, never a half-played
    // timeline from the previous scenario.
    useEffect(() => setT(null), [scenario.key]);

    useEffect(() => {
        speedRef.current = speed;
        if (t === null) return;
        if (speed === 'end') {
            // Functional update, not the closure: this effect and the
            // scenario-change reset land in the same commit, and the closure's
            // stale t would resurrect a finished run on a scenario that should
            // be idle waiting for its run button.
            setT((v) => (v === null ? v : scenario.doneAt));
            return;
        }
        if (t >= scenario.doneAt) return;
        const tick = window.setInterval(() => {
            setT((v) =>
                v === null ? v : Math.min(scenario.doneAt, v + 100 * (speedRef.current as number))
            );
        }, 100);
        return () => window.clearInterval(tick);
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [speed, scenario.key, t === null, t !== null && t >= scenario.doneAt]);

    return useMemo(() => {
        const phase = t === null ? 'idle' : t >= scenario.doneAt ? 'done' : 'running';
        return {
            phase,
            t: t ?? 0,
            rows: t === null ? [] : rowsAt(scenario, t),
            artifact: phase === 'done' ? scenario.artifact : null,
            start: () => setT(speedRef.current === 'end' ? scenario.doneAt : 0),
            replay: () => setT(0),
        };
    }, [t, scenario]);
}
