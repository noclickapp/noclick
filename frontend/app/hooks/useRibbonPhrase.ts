// Tiny hook that rotates through a list of placeholder phrases on a fixed
// interval. Extracted so FlowCanvasEmptyState and HeroPromptShowcase can share
// the same animated typing-ribbon UX.

import { useEffect, useState } from 'react';

export function useRibbonPhrase(phrases: string[], paused: boolean, intervalMs = 2900): { phrase: string; tick: number } {
    const [tick, setTick] = useState(0);
    useEffect(() => {
        if (paused) return;
        const id = setInterval(() => {
            // Hidden tabs don't need a rotating placeholder — each rotation
            // remounts the animated phrase (DOM churn rrweb records, and on
            // iOS a fresh set of composited layers). Hold the phrase instead.
            if (document.hidden) return;
            setTick(t => t + 1);
        }, intervalMs);
        return () => clearInterval(id);
    }, [paused, intervalMs]);
    return { phrase: phrases[tick % phrases.length], tick };
}
