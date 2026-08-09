/* Replays the canned rehearsal on a virtual clock so every design variant is
   judged against the same run at a chosen pace — 1× for feel, 4× for quick
   passes, end-state for layout work. State is derived purely from the virtual
   time, so replay/jump are trivial and no timers leak between variants. */

import { useEffect, useMemo, useRef, useState } from 'react';
import { DONE_AT, EVENTS, POSTED } from './fixture';

export type ReplaySpeed = 1 | 4 | 'end';

export interface ReplayStep {
    id: string;
    text: string;
    provider?: 'slack' | 'gmail';
    status: 'in_progress' | 'completed';
    /** Duration once completed, virtual ms. */
    ms?: number;
    /** Live elapsed while in progress, virtual ms. */
    elapsed: number;
}

export interface ReplayState {
    phase: 'running' | 'done';
    /** Virtual ms since run start. */
    t: number;
    steps: ReplayStep[];
    posted: string;
    replay: () => void;
}

function stepsAt(t: number): ReplayStep[] {
    const byId = new Map<string, ReplayStep>();
    for (const e of EVENTS) {
        if (e.at > t) continue;
        if (e.status === 'in_progress') {
            byId.set(e.step, {
                id: e.step,
                text: e.text,
                provider: e.provider,
                status: 'in_progress',
                elapsed: t - e.at,
            });
        } else {
            const started = EVENTS.find(
                (x) => x.step === e.step && x.status === 'in_progress'
            );
            byId.set(e.step, {
                id: e.step,
                text: e.text,
                provider: e.provider,
                status: 'completed',
                ms: started ? e.at - started.at : undefined,
                elapsed: 0,
            });
        }
    }
    return [...byId.values()];
}

export function useReplay(speed: ReplaySpeed): ReplayState {
    const [t, setT] = useState(speed === 'end' ? DONE_AT : 0);
    const speedRef = useRef(speed);

    useEffect(() => {
        speedRef.current = speed;
        if (speed === 'end') {
            setT(DONE_AT);
            return;
        }
        // Picking a live speed while parked at the end means "show me again".
        setT((v) => (v >= DONE_AT ? 0 : v));
        const tick = window.setInterval(() => {
            setT((v) => Math.min(DONE_AT, v + 100 * (speedRef.current as number)));
        }, 100);
        return () => window.clearInterval(tick);
    }, [speed]);

    return useMemo(
        () => ({
            phase: t >= DONE_AT ? 'done' : 'running',
            t,
            steps: stepsAt(t),
            posted: t >= DONE_AT ? POSTED : '',
            replay: () => setT(0),
        }),
        [t]
    );
}
