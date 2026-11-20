// One motion family for the usage page: going in eases out, coming back eases in and out, both short. Everything that
// moves when "Where it goes" drills reads it from here, so the list, the days and the charges move as one. With
// Reduce Motion the movement goes and a quick crossfade stays, so a change still reads as one.
import { createContext, useContext, useMemo, useRef, type ReactNode } from 'react';
import { MotionConfig, useReducedMotionConfig, type Transition } from 'framer-motion';

/** Into a level: a quick start that settles. */
export const EASE_IN = [0.22, 1, 0.36, 1] as const;
/** Back out of one: symmetric, so it reads as the same path reversed. */
export const EASE_OUT = [0.65, 0, 0.35, 1] as const;
export const DURATION_IN = 0.3;
export const DURATION_OUT = 0.26;
/** Reduce Motion: no movement, only this fade. */
export const FADE: Transition = { duration: 0.16, ease: 'easeOut' };

export type Direction = 1 | -1;

export interface UsageMotion {
    /** 1 going deeper, -1 coming back. */
    dir: Direction;
    reduced: boolean;
    /** The transition for this move. */
    t: Transition;
    /** A delay inside this move, scaled to its duration (0 when reduced). */
    after: (fraction: number) => number;
}

const Ctx = createContext<UsageMotion>({ dir: 1, reduced: false, t: { duration: DURATION_IN, ease: EASE_IN }, after: (f) => f * DURATION_IN });

export const useUsageMotion = () => useContext(Ctx);

function Provider({ depth, children }: { depth: number; children: ReactNode }) {
    const reduced = !!useReducedMotionConfig();
    // The direction is the last move's: deeper or shallower than the depth before it.
    const last = useRef({ depth, dir: 1 as Direction });
    if (depth !== last.current.depth) last.current = { depth, dir: depth > last.current.depth ? 1 : -1 };
    const dir = last.current.dir;
    const value = useMemo<UsageMotion>(() => {
        const duration = dir > 0 ? DURATION_IN : DURATION_OUT;
        return {
            dir,
            reduced,
            t: reduced ? FADE : { duration, ease: dir > 0 ? EASE_IN : EASE_OUT },
            after: (fraction) => (reduced ? 0 : fraction * duration),
        };
    }, [dir, reduced]);
    return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

/** The page's motion: `reducedMotion` is 'user' in the product (the OS decides); the lab can force the fallback. */
export function UsageMotionProvider({ depth, reducedMotion = 'user', children }: { depth: number; reducedMotion?: 'user' | 'always' | 'never'; children: ReactNode }) {
    return (
        <MotionConfig reducedMotion={reducedMotion}>
            <Provider depth={depth}>{children}</Provider>
        </MotionConfig>
    );
}
