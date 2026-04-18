// Loading animation shown on the Interface tab while the agentic builder is
// constructing an interface. The wireframe (sidebar + header + hero + two-up)
// matches the original InterfaceSkeleton silhouette so the eventual handoff
// to a real interface block reads as a fill-in. Outer cards morph proportions,
// inner pills/dots/avatar morph in scale, and an opaque-RGB shimmer layered
// with `mix-blend-mode: lighten` plays across each surface (no alpha
// quantization, no banding).
//
// Currently always-on whenever the Interface tab shows its empty-state. Next
// step: gate this on detection of <add_node type="interface-html-react"> from
// the agentic builder stream.

import React from 'react';
import '~/styles/interface-building.css';

const SURFACE = 'rounded-xl border border-zinc-800/40 bg-gradient-to-b from-zinc-900/30 to-zinc-900/10 relative overflow-hidden';
const PILL = 'rounded-full bg-zinc-800/40';
const DOT = 'rounded-full bg-zinc-800/50';

const MORPH_CYCLE = 4400;
const INNER_CYCLE = 2200;
// Sync the shimmer cycle to the morph cycle so the bell enters/exits in
// lockstep with the card resize. With drift (e.g. shimmer 6s, morph 4.4s),
// the parent width changes mid-sweep and the bell appears to vanish.
const SHIMMER_CYCLE = MORPH_CYCLE;
const MORPH_EASING = 'cubic-bezier(0.65,0,0.35,1)';

// Shimmer overlay that sits inside each surface. Sweep via background-position
// on a very wide gradient (450%) — the bell is bigger than the viewport, so
// the visible portion is always a slice of a smooth slope, never a defined
// band with a leading/trailing edge. Mix-blend-mode 'lighten' clips the dark
// half (no-op) and only the gradual brightening shows through. Opaque RGB
// stops only — no alpha quantization.
function ShimmerOverlay({ delayMs = 0, durationMs = SHIMMER_CYCLE }: { delayMs?: number; durationMs?: number }) {
    return (
        <div
            className="absolute inset-0 pointer-events-none"
            style={{
                background:
                    'linear-gradient(90deg, rgb(0,0,0) 0%, rgb(0,0,0) 25%, rgb(15,15,15) 50%, rgb(0,0,0) 75%, rgb(0,0,0) 100%)',
                backgroundSize: '450% 100%',
                animation: `ifa-shimmer-pos ${durationMs}ms ease-in-out infinite`,
                animationDelay: `${delayMs}ms`,
                mixBlendMode: 'lighten',
            }}
        />
    );
}

function MorphPill({ width, height = 'h-1.5', morph, delay = 0 }: { width: string; height?: string; morph: 'grow' | 'shrink'; delay?: number }) {
    return (
        <div
            className={`${PILL} ${height} ${width}`}
            style={{
                animation: `${morph === 'grow' ? 'ifa-pill-grow' : 'ifa-pill-shrink'} ${INNER_CYCLE}ms ease-in-out infinite`,
                animationDelay: `${delay}ms`,
                transformOrigin: 'left center',
            }}
        />
    );
}

function MorphDot({ delay = 0 }: { delay?: number }) {
    return <div className={`${DOT} w-1.5 h-1.5`} style={{ animation: `ifa-dot-pulse ${INNER_CYCLE}ms ease-in-out infinite`, animationDelay: `${delay}ms` }} />;
}

function MorphAvatar({ delay = 0 }: { delay?: number }) {
    return <div className="w-6 h-6 rounded-full bg-zinc-800/50" style={{ animation: `ifa-avatar-pulse ${INNER_CYCLE}ms ease-in-out infinite`, animationDelay: `${delay}ms` }} />;
}

export function InterfaceBuildingAnimation() {
    return (
        <div className="absolute inset-0 overflow-hidden pointer-events-none select-none">
            <div className="absolute inset-0 p-5 flex gap-3.5">
                {/* Sidebar — width morphs */}
                <div
                    className={`${SURFACE} shrink-0 p-4 flex flex-col gap-5`}
                    style={{ width: 180, animation: `ifa-sidebar-resize ${MORPH_CYCLE}ms ${MORPH_EASING} infinite` }}
                >
                    <div className="flex items-center gap-2.5">
                        <div className="w-6 h-6 rounded-md bg-zinc-800/50" />
                        <MorphPill width="w-20" height="h-2" morph="grow" delay={0} />
                    </div>
                    <div className="flex flex-col gap-3 mt-1">
                        <MorphPill width="w-3/4" morph="grow" delay={120} />
                        <MorphPill width="w-2/3" morph="shrink" delay={240} />
                        <MorphPill width="w-4/5" morph="grow" delay={360} />
                        <MorphPill width="w-1/2" morph="shrink" delay={480} />
                    </div>
                    <ShimmerOverlay delayMs={0} />
                </div>

                {/* Main column */}
                <div className="flex-1 min-w-0 flex flex-col gap-3.5">
                    {/* Header — height morphs */}
                    <div
                        className={`${SURFACE} shrink-0 px-4 flex items-center justify-between`}
                        style={{ height: 48, animation: `ifa-header-resize ${MORPH_CYCLE}ms ${MORPH_EASING} infinite` }}
                    >
                        <MorphPill width="w-28" height="h-2" morph="grow" delay={200} />
                        <div className="flex items-center gap-3">
                            <MorphDot delay={300} />
                            <MorphDot delay={400} />
                            <MorphAvatar delay={500} />
                        </div>
                        <ShimmerOverlay delayMs={250} />
                    </div>

                    {/* Hero */}
                    <div className={`${SURFACE} flex-1 min-h-0`}>
                        <ShimmerOverlay delayMs={500} />
                    </div>

                    {/* Two-up row — proportions swap, total height morphs */}
                    <div
                        className="flex gap-3.5 shrink-0"
                        style={{ height: 80, animation: `ifa-bottom-row-resize ${MORPH_CYCLE}ms ${MORPH_EASING} infinite` }}
                    >
                        <div
                            className={`${SURFACE} basis-0 min-w-0`}
                            style={{ flexGrow: 4, animation: `ifa-flex-3-to-2 ${MORPH_CYCLE}ms ${MORPH_EASING} infinite` }}
                        >
                            <ShimmerOverlay delayMs={700} />
                        </div>
                        <div
                            className={`${SURFACE} basis-0 min-w-0`}
                            style={{ flexGrow: 1, animation: `ifa-flex-2-to-3 ${MORPH_CYCLE}ms ${MORPH_EASING} infinite` }}
                        >
                            <ShimmerOverlay delayMs={900} />
                        </div>
                    </div>
                </div>
            </div>
        </div>
    );
}
