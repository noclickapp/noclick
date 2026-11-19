// The moment a stage of long work goes from current to done: its live dot turns into a check (FreshCheck, Draw, Pop
// or Ring), the rail under it fills toward the next stage, how long it took settles in beside it, and the next stage's
// dot comes alive. Timing lives in the thread's motion (sc-*).
import { useRef } from 'react';
import { LiveDot } from '@/ui/chat/primitives';
import type { WorkStage } from './workView';

/** Stages that just changed: the one that just finished, the one that just came alive. */
export interface FreshStages {
    done: string[];
    live: string[];
}

// How long a change counts as fresh, in real time (the animation is shorter; this only outlasts it).
const FRESH_MS = 1400;

export const stageKey = (stage: WorkStage) => `${stage.name}-${stage.start}`;

/** Which stages changed since the last render, held fresh for a moment, so a stage reached while playing animates and
 *  one already reached when the view opens doesn't. `explicit` stands in for the detection (to replay a moment). */
export function useFreshStages(stages: WorkStage[], explicit?: FreshStages): FreshStages {
    const seen = useRef<Map<string, WorkStage['state']> | null>(null);
    const until = useRef(new Map<string, { kind: 'done' | 'live'; at: number }>());
    if (explicit) return explicit;
    const now = performance.now();
    if (seen.current) {
        for (const stage of stages) {
            const before = seen.current.get(stageKey(stage));
            if (stage.state === 'done' && before === 'current') until.current.set(stageKey(stage), { kind: 'done', at: now + FRESH_MS });
            if (stage.state === 'current' && before !== 'current') until.current.set(stageKey(stage), { kind: 'live', at: now + FRESH_MS });
        }
    }
    seen.current = new Map(stages.map((s) => [stageKey(s), s.state]));
    const fresh: FreshStages = { done: [], live: [] };
    for (const [key, mark] of until.current) {
        if (mark.at < now) until.current.delete(key);
        else fresh[mark.kind].push(key);
    }
    return fresh;
}

/** The next stage's dot, coming alive once the rail reaches it. */
export function FreshLive() {
    return (
        <span className="sc-alive inline-flex">
            <LiveDot className="h-2 w-2" />
        </span>
    );
}
