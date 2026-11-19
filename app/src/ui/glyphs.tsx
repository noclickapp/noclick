// What a message to NoClick can carry, drawn for the composer's "+" and the pills a message wears. The actions are
// line glyphs in ink, the sidebar's own for Connections; an automation is the one thing NoClick draws in colour,
// the sidebar's Automations mark with its two steps filled in. Every other colour there is yours: an account wears
// its app's logo, an automation in a list the logo of what it runs on.
import { useId } from 'react';
import { FolderOpen, Paperclip, Plug } from 'lucide-react';

export const ACTION_GLYPHS = { upload: Paperclip, files: FolderOpen, account: Plug } as const;

/** How a magic wand is drawn: how wide it is, how long its light tip is, and the rays of light off the tip (their
 *  angles, 0 along the wand, and how long each is). */
export interface WandStyle {
    width: number;
    tipLength: number;
    rays: { angle: number; length: number }[];
}

/** A fan of `count` rays spread over `span` degrees past the tip, each `length` long; with `alternate`, every other
 *  ray is that much shorter. */
export const wandFan = (count: number, span: number, length: number, alternate = 0) =>
    Array.from({ length: count }, (_, i) => ({ angle: -span / 2 + (span * i) / (count - 1), length: length - (i % 2 ? alternate : 0) }));

/** A magic wand in the Magic Wand tool's manner, drawn upright and turned to lie bottom-left to top-right on lucide's
 *  24-unit grid: a straight stick with a solid handle, its tip in outline so it reads light against it, and short rays
 *  of light fanned off the tip, never a star. Takes `className` and `strokeWidth` the way a lucide icon does. */
export function MagicWand({ style, className, strokeWidth = 1.75 }: { style: WandStyle; className?: string; strokeWidth?: number }) {
    // Upright, before the turn: the wand stands on x 12 from its tip's end at y 5.4 down to 21.6.
    const { width: w, tipLength } = style;
    const [top, bottom, x0, x1] = [5.4, 21.6, 12 - w / 2, 12 + w / 2];
    const split = top + tipLength;
    // Rays leave from around the tip's rounded end, clear of its outline.
    const end = { x: 12, y: top + w / 2 };
    const clear = w / 2 + strokeWidth / 2 + 1.25;
    const n = (v: number) => v.toFixed(2);
    return (
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={strokeWidth} strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" className={className}>
            <g transform="rotate(45 12 12)">
                <rect x={x0} y={top} width={w} height={bottom - top} rx={w / 2} />
                <path d={`M${n(x0)} ${n(split)}H${n(x1)}V${n(bottom - w / 2)}A${n(w / 2)} ${n(w / 2)} 0 0 1 ${n(x0)} ${n(bottom - w / 2)}Z`} fill="currentColor" stroke="none" />
                {style.rays.map(({ angle, length }) => {
                    // Angle 0 points along the wand past its tip (up, before the turn).
                    const a = ((angle - 90) * Math.PI) / 180;
                    const at = (r: number) => `${n(end.x + Math.cos(a) * r)} ${n(end.y + Math.sin(a) * r)}`;
                    return <path key={angle} d={`M${at(clear)}L${at(clear + length)}`} />;
                })}
            </g>
        </svg>
    );
}

/** The builder's wand: a solid handle, the tip in outline and five even rays. */
export const BUILDER_WAND: WandStyle = { width: 3.5, tipLength: 6.2, rays: wandFan(5, 150, 2.3) };

/** The builder's mark, everywhere it shows: the sidebar's row, the canvas's tile, the phone bar's toggle, the panel. */
export function BuilderMark({ className, strokeWidth }: { className?: string; strokeWidth?: number }) {
    return <MagicWand style={BUILDER_WAND} className={className} strokeWidth={strokeWidth} />;
}

/** An automation: two steps and the edge between them. Sized by `className`; the edge takes the text colour. */
export function AutomationMark({ className }: { className?: string }) {
    const uid = useId().replace(/[^a-zA-Z0-9]/g, '');
    return (
        <svg viewBox="0 0 20 20" fill="none" aria-hidden="true" className={className}>
            <defs>
                <linearGradient id={`${uid}a`} x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0" stopColor="#b49cff" />
                    <stop offset="1" stopColor="#7c5cff" />
                </linearGradient>
                <linearGradient id={`${uid}b`} x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0" stopColor="#7fd4ff" />
                    <stop offset="1" stopColor="#2f9bff" />
                </linearGradient>
            </defs>
            <path d="M5.5 9.75v2.75a2 2 0 0 0 2 2h2.75" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
            <rect x="1.25" y="1.25" width="8.5" height="8.5" rx="2.5" fill={`url(#${uid}a)`} />
            <rect x="10.25" y="10.25" width="8.5" height="8.5" rx="2.5" fill={`url(#${uid}b)`} />
        </svg>
    );
}
