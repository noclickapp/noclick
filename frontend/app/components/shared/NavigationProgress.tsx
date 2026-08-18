// Global thin top-edge progress bar for client-side route transitions. Remix
// renders nothing (no URL change, no visual feedback) until the destination
// route's loader responds, so a slow loader makes nav links feel dead — this
// gives sub-frame click feedback for any navigation slower than SHOW_DELAY_MS.
import { useNavigation } from 'react-router';
import type { CSSProperties } from 'react';
import { useEffect, useState } from 'react';

// Navigations that resolve faster than this never show the bar (prefetched
// routes, warm edge-cache hits) — avoids a distracting flash on snappy navs.
const SHOW_DELAY_MS = 120;

type Phase = 'idle' | 'active' | 'done';

const PHASE_STYLES: Record<Phase, CSSProperties> = {
    idle: { width: '0%', opacity: 0, transition: 'none' },
    // Fast initial sweep that decays toward 90% — perceived progress while the
    // loader round-trip is in flight, without ever falsely completing.
    active: {
        width: '90%',
        opacity: 1,
        transition: 'width 12s cubic-bezier(0.08, 0.82, 0.17, 1)',
    },
    done: {
        width: '100%',
        opacity: 0,
        transition: 'width 250ms ease-out, opacity 300ms ease-in 250ms',
    },
};

export function NavigationProgress() {
    const navigation = useNavigation();
    const navigating = navigation.state !== 'idle';
    const [phase, setPhase] = useState<Phase>('idle');

    useEffect(() => {
        if (navigating) {
            const t = setTimeout(() => setPhase('active'), SHOW_DELAY_MS);
            return () => clearTimeout(t);
        }
        // Finished: complete the bar only if it actually appeared.
        setPhase((p) => (p === 'active' ? 'done' : 'idle'));
    }, [navigating]);

    // Reset after the completion animation so the next slow nav starts from 0.
    useEffect(() => {
        if (phase !== 'done') return;
        const t = setTimeout(() => setPhase('idle'), 600);
        return () => clearTimeout(t);
    }, [phase]);

    return (
        <div
            aria-hidden
            data-nc-nav-progress={phase}
            className="pointer-events-none fixed inset-x-0 top-0 z-[100]"
        >
            <div className="h-0.5 bg-primary" style={PHASE_STYLES[phase]} />
        </div>
    );
}
