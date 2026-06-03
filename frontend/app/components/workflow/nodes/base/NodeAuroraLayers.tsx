// Shared run-status "aurora" overlay drawn on top of every node by withNodeWrapper.
// Renders the rotating running sweep ring and the completed ring + glow + corner
// badge + one-shot pulse, sitting just outside the node box with a small gap.
// Centralising it here (one source of truth) means automation nodes AND the special
// node types (AI agent, conditional, switch, etc.) get an identical treatment
// without per-node code or the drift two implementations would cause.
// The overlay is intentionally rendered for ALL node types (via withNodeWrapper),
// and the completed/failed edge ring assumes the standard rounded-2xl (16px) node
// radius.

import { useEffect, useRef, useState } from 'react';
import { Check } from 'lucide-react';
import { useIsMobile } from '~/hooks/useIsMobile';

// The animating "aurora" sweep is the thicker ring that sits just OUTSIDE the box
// with a small gap (radius = node's 16px + |inset| to stay concentric; gap between
// the node edge and the ring's inner edge = |inset| - stroke = 2px).
const SWEEP_INSET = -5;
const SWEEP_RADIUS = 21;
const SWEEP_STROKE = 3;
// The completed / failed / pulse rings are a thin stroke hugging the node edge
// (no gap) — matching the original completed treatment.
const EDGE_INSET = 0;
const EDGE_RADIUS = 16;
const EDGE_STROKE = 1.5;

const SWEEP_CONIC =
    'conic-gradient(from 0deg, transparent 0%, rgba(255,255,255,0.12) 25%, #ffffff 50%, rgba(255,255,255,0.12) 75%, transparent 100%)';

// content-box XOR border-box → a stroke-only mask, so the rotating conic child shows
// through only the ring while the interior stays transparent (the node shows through).
const RING_MASK = {
    padding: SWEEP_STROKE,
    WebkitMask: 'linear-gradient(#000 0 0) content-box, linear-gradient(#000 0 0)',
    WebkitMaskComposite: 'xor',
    mask: 'linear-gradient(#000 0 0) content-box, linear-gradient(#000 0 0)',
    maskComposite: 'exclude',
} as const;

interface AuroraData {
    executionState?: string;
    _lastRunStatus?: string;
    configValid?: boolean;
    isReadOnly?: boolean;
}

export function NodeAuroraLayers({ data, selected, nodeType }: { data?: AuroraData; selected?: boolean; nodeType?: string }) {
    const isMobile = useIsMobile();
    const executionState = data?.executionState ?? 'idle';
    const isRunning = executionState === 'running';
    const isError = executionState === 'error';
    const lastRunStatus = data?._lastRunStatus;

    // A live error / config-invalid node owns its own badge + border (drawn by the node
    // itself), so the persisted completed/failed treatment yields to those.
    const blocked = isError || data?.configValid === false;
    const showCompleted = lastRunStatus === 'completed' && !isRunning && !blocked;
    const showFailed = lastRunStatus === 'error' && !isRunning && !isError && !blocked;
    // While selected, the node draws its own (scaled) selection border at the same
    // edge; the completed/failed status ring would sit just inside it and read as a
    // weird double border. So the ring yields to the selection border when selected
    // (the ✓ badge + chip still convey completion). The corner badge + pulse stay.
    const showStatusRing = !selected;

    // One-shot pulse: fire ONLY on a live running→completed transition. On mount,
    // reload, or reposition the node re-renders with completed already set, so there's
    // no transition and prevExec stays in sync → no spurious pulse.
    const [pingNonce, setPingNonce] = useState(0);
    const prevExec = useRef(executionState);
    useEffect(() => {
        if (prevExec.current === 'running' && executionState === 'completed') {
            setPingNonce((n) => n + 1);
        }
        prevExec.current = executionState;
    }, [executionState]);

    // MOBILE read-only previews (templates / share embeds) are perf-constrained —
    // the node itself drops blur/glow layers there, so the overlay opts out too.
    // DESKTOP read-only (execution-log replay, desktop public share) keeps the
    // aurora so completed nodes get their ✓ ring + corner badge — the primary
    // visual cue for "this node ran successfully in the past run."
    if (data?.isReadOnly === true && isMobile) return null;
    // Interface (UI) nodes aren't executable steps, so run-status visuals — the
    // completed/failed outline ring and the ✓ corner badge — don't apply to them.
    if (nodeType?.startsWith('interface-')) return null;
    if (!isRunning && !showCompleted && !showFailed) return null;

    const sweepRing = {
        position: 'absolute' as const,
        inset: SWEEP_INSET,
        borderRadius: SWEEP_RADIUS,
        pointerEvents: 'none' as const,
    };
    const edgeRing = {
        position: 'absolute' as const,
        inset: EDGE_INSET,
        borderRadius: EDGE_RADIUS,
        pointerEvents: 'none' as const,
    };

    return (
        <>
            {/* Running: an oversized conic rotates inside a STATIONARY masked ring — the
                mask never rotates, so the stroke stays a rounded rect (no spinning square). */}
            {isRunning && (
                <div className="overflow-hidden" style={{ ...sweepRing, ...RING_MASK }}>
                    <div
                        className="absolute"
                        style={{
                            inset: '-60%',
                            background: SWEEP_CONIC,
                            animation: 'node-run-sweep 2s linear infinite',
                        }}
                    />
                </div>
            )}

            {/* Completed: thin ring at the node edge + outer glow. Soft GRAY (zinc-300),
                deliberately not pure white — pure white is reserved for selection, so
                selecting a completed node brightens (gray → white) instead of dimming. */}
            {showCompleted && showStatusRing && (
                <div
                    style={{
                        ...edgeRing,
                        border: `${EDGE_STROKE}px solid rgba(212,212,216,0.7)`,
                        boxShadow: '0 0 18px rgba(212,212,216,0.28)',
                    }}
                />
            )}

            {/* Failed (rehydrated): subtle red ring — no badge/pulse, failures don't celebrate. */}
            {showFailed && showStatusRing && (
                <div
                    style={{
                        ...edgeRing,
                        border: `${EDGE_STROKE}px solid rgba(239,68,68,0.5)`,
                        boxShadow: '0 0 14px rgba(239,68,68,0.25)',
                    }}
                />
            )}

            {/* One-shot pulse on a live completion (keyed so a re-run replays it). */}
            {pingNonce > 0 && showCompleted && (
                <div
                    key={pingNonce}
                    style={{
                        ...edgeRing,
                        border: `${EDGE_STROKE}px solid #e4e4e7`,
                        animation: 'node-complete-ping 0.7s ease-out forwards',
                    }}
                />
            )}

            {/* Completed corner badge — straddles the node's top-right corner (half-in/out). */}
            {showCompleted && (
                <div
                    className="absolute z-20 flex items-center justify-center rounded-full"
                    style={{
                        // Straddle the corner ~half-in / half-out: center sits a few px
                        // inside the corner (-12 would center on the corner, leaving only
                        // a quarter overlapping — reads as "mostly out").
                        top: -9,
                        right: -9,
                        width: 24,
                        height: 24,
                        background: '#e4e4e7',
                        border: '2px solid #fafafa',
                        boxShadow: '0 0 10px rgba(255,255,255,0.6)',
                        animation: 'node-complete-pop 0.35s cubic-bezier(0.34,1.56,0.64,1)',
                    }}
                >
                    <Check className="w-3.5 h-3.5 text-black" strokeWidth={3} />
                </div>
            )}
        </>
    );
}
