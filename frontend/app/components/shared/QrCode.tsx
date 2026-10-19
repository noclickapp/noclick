// A QR code drawn as one SVG: dark squares on white (what every camera reads,
// in either theme) with rounded corner eyes, and an optional mark in the middle.
// A mark costs the code some of its error correction, so the code is encoded at
// the highest level and only data squares are cleared beneath it.
import { useMemo, type ReactNode } from 'react';
import { Loader2 } from 'lucide-react';
import { encode, QrCodeDataType } from 'uqr';
import { cn } from '~/lib/utils';

const QUIET = 2; // modules of white around the code
const MARK_SHARE = 0.22; // of the code's width, safely inside what level H recovers
// overflow-hidden drops the box's automatic minimum height, so the code inside can't make WebKit grow it past square.
const CARD = 'aspect-square overflow-hidden rounded-2xl bg-white p-1.5 shadow-[0_1px_2px_rgba(0,0,0,0.08)] ring-1 ring-black/[0.07] dark:ring-0';

/** The code's card with nothing to scan yet, the same size, while the code it will show is on its way. */
export function QrPlaceholder({ label, className }: { label: string; className?: string }) {
    return (
        <div role="status" aria-label={label} className={cn(CARD, 'grid place-items-center', className)}>
            <Loader2 className="h-5 w-5 animate-spin text-[#111113]/35" aria-hidden="true" />
        </div>
    );
}

export function QrCode({ value, label, mark, className }: { value: string; /** What it opens, for screen readers. */ label: string; mark?: ReactNode; className?: string }) {
    const marked = !!mark;
    const { size, path, eyes, hole } = useMemo(() => {
        const qr = encode(value, { ecc: marked ? 'H' : 'M', border: 0 });
        const n = qr.size;
        const hole = marked ? Math.ceil(n * MARK_SHARE) | 1 : 0; // odd, so it centres on a module
        const lo = (n - hole) / 2;
        let d = '';
        for (let y = 0; y < n; y++) {
            for (let x = 0; x < n; x++) {
                if (!qr.data[y][x] || qr.types[y][x] === QrCodeDataType.Position) continue;
                if (hole && x >= lo && x < lo + hole && y >= lo && y < lo + hole && qr.types[y][x] === QrCodeDataType.Data) continue;
                d += `M${x + QUIET} ${y + QUIET}h1v1h-1z`;
            }
        }
        return { size: n + QUIET * 2, path: d, eyes: [[0, 0], [n - 7, 0], [0, n - 7]] as const, hole };
    }, [value, marked]);

    return (
        <div role="img" aria-label={label} className={cn(CARD, className)}>
            {/* Square from its own width: WebKit resolves h-full here against the card's padded height, which drew
                the code too tall and pushed it down. */}
            <div className="relative aspect-square w-full">
                <svg viewBox={`0 0 ${size} ${size}`} className="absolute inset-0 h-full w-full" shapeRendering="crispEdges" aria-hidden="true">
                    <path d={path} fill="#111113" />
                    {eyes.map(([x, y]) => (
                        <g key={`${x}:${y}`} transform={`translate(${x + QUIET} ${y + QUIET})`} shapeRendering="geometricPrecision">
                            <path d="M2 0h3a2 2 0 0 1 2 2v3a2 2 0 0 1-2 2H2a2 2 0 0 1-2-2V2a2 2 0 0 1 2-2Zm0 1a1 1 0 0 0-1 1v3a1 1 0 0 0 1 1h3a1 1 0 0 0 1-1V2a1 1 0 0 0-1-1Z" fill="#111113" />
                            <rect x="2" y="2" width="3" height="3" rx="0.9" fill="#111113" />
                        </g>
                    ))}
                </svg>
                {mark && hole > 0 && (
                    <span className="absolute inset-0 grid place-items-center" aria-hidden="true">
                        <span className="grid aspect-square place-items-center" style={{ width: `${(hole / size) * 100}%` }}>
                            {mark}
                        </span>
                    </span>
                )}
            </div>
        </div>
    );
}
