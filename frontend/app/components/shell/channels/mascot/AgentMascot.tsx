// An agent drawn as NoClick's mascot on a disc of its own colour, wearing its live state: the kit's SVG (kit.ts),
// memoized per look and size, with each state's short loop as CSS keyframes on its parts. A mascot given no state
// rests, still; reduced motion stills every one.
import type { CSSProperties } from 'react';
import { cn } from '~/lib/utils';
import type { AgentHue } from '../types';
import { draw, generate, hash, STATES, tierOf, type MascotLook, type MascotState, type PropKey } from './kit';

export type { MascotState, PropKey };

/** Each hue's disc: one fill in both themes, under the white mascot (≥ 2.4:1) and against both pages (≥ 2:1). Every
 *  pair passes the data-viz palette validator with all pairs compared (normal vision ΔE ≥ 16.7, colour-blind ≥ 9.1).
 *  The one place agent colours are raw hex: the kit's deliberate exception to the theme tokens. */
export const AVATAR_HUE: Record<AgentHue, string> = {
    sky: '#0284c7',
    blue: '#1e40af',
    violet: '#7c3aed',
    purple: '#c084fc',
    fuchsia: '#701a75',
    pink: '#db2777',
    teal: '#14b8a6',
    emerald: '#047857',
};

// The loops. Every rule is scoped to a mascot and keyed by its state class, so a still one never moves.
export const MASCOT_MOTION_CSS = `.nc-mascot { --ph: 0s }
.nc-mascot .ncm-disc { display: block; width: 100%; height: 100%; border-radius: 9999px; overflow: hidden; background-color: var(--d); outline: 1px solid hsl(var(--foreground) / .1); outline-offset: -1px }
.nc-mascot .ncm-disc svg { display: block; width: 100%; height: 100% }
.nc-mascot.ncm-faded .ncm-disc { filter: saturate(.3); opacity: .72 }
.nc-mascot .ncm-ring { position: absolute; inset: -3px; border-radius: 9999px; border: 2px solid hsl(var(--foreground)); pointer-events: none }
.nc-mascot .ncm-dot { position: absolute; top: -2px; right: -2px; width: max(7px, 36%); height: max(7px, 36%); border-radius: 9999px; background: #ef4444; box-shadow: 0 0 0 1.5px hsl(var(--background)); pointer-events: none }
.nc-mascot .m-fig { transform-box: view-box; transform-origin: 50px 100px }
.nc-mascot .m-eyes, .nc-mascot .m-lids, .nc-mascot .m-t, .nc-mascot .m-z, .nc-mascot .m-spk, .nc-mascot .m-rd, .nc-mascot .m-typing circle { transform-box: fill-box; transform-origin: center }
.ncm-working .m-eyes { animation: ncm-glance 3.2s ease-in-out var(--ph) infinite }
.ncm-working .m-lids { animation: ncm-blink 3.2s linear var(--ph) infinite }
.ncm-working .m-t, .ncm-needs .m-t { animation: ncm-tick 1.6s ease-in-out var(--ph) infinite }
.ncm-needs .m-t { animation-duration: 1.2s }
.ncm-working .m-t2, .ncm-needs .m-t2 { animation-delay: calc(var(--ph) + .16s) }
.ncm-working .m-t3, .ncm-needs .m-t3 { animation-delay: calc(var(--ph) + .32s) }
.ncm-working .m-typing circle { animation: ncm-typing 1.6s ease-in-out var(--ph) infinite }
.ncm-working .m-typing circle:nth-child(2) { animation-delay: calc(var(--ph) + .2s) }
.ncm-working .m-typing circle:nth-child(3) { animation-delay: calc(var(--ph) + .4s) }
.ncm-waiting .m-fig { animation: ncm-breathe 3.6s ease-in-out var(--ph) infinite }
.ncm-waiting .m-lids { animation: ncm-blink 3.6s linear var(--ph) infinite }
.ncm-needs .m-fig { animation: ncm-bounce 2.4s ease-in-out var(--ph) infinite }
.ncm-asleep .m-fig { animation: ncm-breathe 4s ease-in-out var(--ph) infinite }
.ncm-asleep .m-z1 { animation: ncm-zz 4s ease-in-out var(--ph) infinite }
.ncm-asleep .m-z2 { animation: ncm-zz 4s ease-in-out calc(var(--ph) - 2s) infinite }
.ncm-done .m-fig { animation: ncm-hop 2.8s ease-in-out var(--ph) infinite }
.ncm-done .m-spk { animation: ncm-twinkle 2.8s ease-in-out var(--ph) infinite }
.ncm-failed .m-fig { animation: ncm-wobble 3.6s ease-in-out var(--ph) infinite }
@keyframes ncm-glance { 0%, 12% { transform: translateX(0) } 22%, 40% { transform: translateX(-1.7px) } 50%, 70% { transform: translateX(1.7px) } 80%, 100% { transform: translateX(0) } }
@keyframes ncm-blink { 0%, 88%, 100% { transform: scaleY(1) } 92% { transform: scaleY(.1) } 96% { transform: scaleY(1) } }
@keyframes ncm-tick { 0%, 100% { opacity: .3; transform: scale(.72) } 45% { opacity: 1; transform: scale(1) } }
@keyframes ncm-typing { 0%, 60%, 100% { transform: translateY(0) } 30% { transform: translateY(-1.4px) } }
@keyframes ncm-breathe { 0%, 100% { transform: scale(1, 1) } 50% { transform: scale(1.012, 1.024) } }
@keyframes ncm-bounce { 0%, 44%, 100% { transform: translateY(0) } 12% { transform: translateY(-4px) } 24% { transform: translateY(0) } 32% { transform: translateY(-1.4px) } }
@keyframes ncm-zz { 0% { opacity: 0; transform: translate(-1px, 3px) scale(.8) } 25%, 70% { opacity: 1 } 100% { opacity: 0; transform: translate(3px, -5px) scale(1.05) } }
@keyframes ncm-hop { 0%, 52%, 100% { transform: translateY(0) scale(1, 1) } 8% { transform: translateY(0) scale(1.03, .96) } 22% { transform: translateY(-4.5px) scale(.98, 1.03) } 36% { transform: translateY(0) scale(1.025, .975) } 44% { transform: translateY(0) scale(1, 1) } }
@keyframes ncm-twinkle { 0%, 100% { transform: scale(.7) rotate(0deg); opacity: .65 } 30% { transform: scale(1.1) rotate(45deg); opacity: 1 } 60% { transform: scale(.85) rotate(90deg); opacity: .85 } }
@keyframes ncm-wobble { 0%, 100% { transform: rotate(0deg) } 25% { transform: rotate(-2.2deg) } 75% { transform: rotate(2.2deg) } }
@media (prefers-reduced-motion: reduce) { .nc-mascot * { animation: none !important } }`;

/** Puts the loops on the page once (React 19 dedupes a style by its href). */
function MascotMotion() {
    return (
        <style href="nc-mascot-motion" precedence="default">
            {MASCOT_MOTION_CSS}
        </style>
    );
}

// One cache of looks and one of drawings, each dropping its least recently used past the limit.
const LIMIT = 600;
const LOOKS = new Map<string, MascotLook>();
const SVGS = new Map<string, string>();
function remember<T>(cache: Map<string, T>, key: string, make: () => T): T {
    const hit = cache.get(key);
    if (hit !== undefined) {
        cache.delete(key);
        cache.set(key, hit);
        return hit;
    }
    const value = make();
    cache.set(key, value);
    if (cache.size > LIMIT) cache.delete(cache.keys().next().value as string);
    return value;
}

/** The mascot's `<svg>` for one agent (`seed`: its id) in one state at one size, drawn once. */
export function mascotSvg(seed: string, props: readonly PropKey[], hue: AgentHue, state: MascotState, size: number, marks = true): string {
    const look = `${seed}\n${props.join(',')}\n${hue}`;
    const p = remember(LOOKS, look, () => generate(seed, props, hue));
    return remember(SVGS, `${look}\n${state}\n${size}\n${marks}`, () => draw(p, state, size, { marks }));
}

/** Where in its loop a mascot starts, from its seed, so agents side by side never move in step. */
const phaseOf = (seed: string, state: MascotState) => `-${(((hash(seed + state) % 1000) / 1000) * STATES[state].loop).toFixed(2)}s`;

/** `size` picks the level of detail, so it is the size drawn; the box's own size comes from `className`. `marks: false`
 *  leaves the state's marks out (a ring round it already says the state). */
export function AgentMascot({ seed, hue, props, state, size, marks = true, className }: { seed: string; hue: AgentHue; props: readonly PropKey[]; state?: MascotState; size: number; marks?: boolean; className?: string }) {
    const shown = state ?? 'waiting';
    const xs = tierOf(size) === 'xs';
    const style = { '--d': AVATAR_HUE[hue], '--ph': phaseOf(seed, shown) } as CSSProperties;
    return (
        <span
            aria-hidden
            data-mascot={shown}
            data-still={state ? undefined : ''}
            className={cn('nc-mascot relative inline-flex shrink-0 select-none rounded-full', state && `ncm-${state}`, xs && state === 'asleep' && 'ncm-faded', className)}
            style={style}
        >
            <MascotMotion />
            <span className="ncm-disc" dangerouslySetInnerHTML={{ __html: mascotSvg(seed, props, hue, shown, size, marks) }} />
            {xs && marks && state === 'needs' && <span className="ncm-ring" />}
            {xs && marks && state === 'failed' && <span className="ncm-dot" />}
        </span>
    );
}
