// Full-viewport dim + subtle blur that hugs the rounded shapes of the drawer
// and the chatbox. Rendered via portal from ChatDrawer when a drawer opts in
// via `emphasized: true`. The rect geometry is computed in useEmphasizedCutouts
// — this component just paints the mask.

import { cn } from '~/lib/utils';
import type { CutoutRects } from '~/hooks/useEmphasizedCutouts';

const BLUR_RADIUS = '0.5px';
const DIM_COLOR = 'rgba(0,0,0,0.55)';
const CUTOUT_RADIUS = 12;
const MASK_ID = 'emphasized-dim-mask';

/** Build an SVG data URI for CSS `mask-image` with luminance: white shows the
 * layer, black hides it. Used by the blur layer (CSS masks don't accept SVG
 * <mask> directly, only data-URI images). */
function buildMaskDataUrl(rects: CutoutRects): string {
    const round = Math.round;
    const dr = rects.drawer;
    const cb = rects.chatbox;
    const svg = `<svg xmlns='http://www.w3.org/2000/svg' width='100%25' height='100%25' preserveAspectRatio='none'>`
        + `<rect width='100%25' height='100%25' fill='white'/>`
        + `<rect x='${round(dr.x)}' y='${round(dr.y)}' width='${round(dr.width)}' height='${round(dr.height)}' rx='${CUTOUT_RADIUS}' ry='${CUTOUT_RADIUS}' fill='black'/>`
        + (cb ? `<rect x='${round(cb.x)}' y='${round(cb.y)}' width='${round(cb.width)}' height='${round(cb.height)}' rx='${CUTOUT_RADIUS}' ry='${CUTOUT_RADIUS}' fill='black'/>` : '')
        + `</svg>`;
    return `url("data:image/svg+xml;utf8,${svg}")`;
}

interface EmphasizedBackdropProps {
    cutoutRects: CutoutRects | null;
    /** Forwarded so the backdrop can catch drag events during resize. */
    isDragging: boolean;
    isResizable: boolean;
}

export function EmphasizedBackdrop({ cutoutRects, isDragging, isResizable }: EmphasizedBackdropProps) {
    const maskDataUrl = cutoutRects ? buildMaskDataUrl(cutoutRects) : undefined;
    const pointerClass = isDragging && isResizable
        ? 'pointer-events-auto cursor-ns-resize'
        : 'pointer-events-none';

    return (
        <>
            {/* Blur layer — masked to skip the cutouts */}
            <div
                className={cn('fixed inset-0 z-[60]', pointerClass)}
                style={{
                    backdropFilter: `blur(${BLUR_RADIUS})`,
                    WebkitBackdropFilter: `blur(${BLUR_RADIUS})`,
                    maskImage: maskDataUrl,
                    WebkitMaskImage: maskDataUrl,
                    maskMode: 'luminance',
                    WebkitMaskMode: 'luminance',
                    maskRepeat: 'no-repeat',
                    WebkitMaskRepeat: 'no-repeat',
                    maskSize: '100% 100%',
                    WebkitMaskSize: '100% 100%',
                }}
                aria-hidden="true"
            />
            {/* Dim layer — same cutout shape via SVG <mask>, sits above the blur */}
            <svg
                className={cn('fixed inset-0 z-[60] w-full h-full', pointerClass)}
                aria-hidden="true"
            >
                <defs>
                    <mask id={MASK_ID}>
                        <rect width="100%" height="100%" fill="white" />
                        {cutoutRects && (
                            <rect
                                x={cutoutRects.drawer.x}
                                y={cutoutRects.drawer.y}
                                width={cutoutRects.drawer.width}
                                height={cutoutRects.drawer.height}
                                rx={CUTOUT_RADIUS}
                                ry={CUTOUT_RADIUS}
                                fill="black"
                            />
                        )}
                        {cutoutRects?.chatbox && (
                            <rect
                                x={cutoutRects.chatbox.x}
                                y={cutoutRects.chatbox.y}
                                width={cutoutRects.chatbox.width}
                                height={cutoutRects.chatbox.height}
                                rx={CUTOUT_RADIUS}
                                ry={CUTOUT_RADIUS}
                                fill="black"
                            />
                        )}
                    </mask>
                </defs>
                <rect
                    width="100%"
                    height="100%"
                    fill={DIM_COLOR}
                    mask={`url(#${MASK_ID})`}
                />
            </svg>
        </>
    );
}
