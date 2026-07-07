// Single source of truth for the ReactFlow canvas grid so every surface — the
// editor, the read-only viewer, the agent-scaffold auth preview, the marketing
// showcase — stays visually identical. Added after the style drifted (the editor
// was restyled but the read-only canvas kept the old gap/color).

import { Background, BackgroundVariant } from '@xyflow/react';

/** Dark-zinc canvas surface (tailwind zinc-950). Apply to the product canvases;
    the auth-page preview deliberately runs a touch lighter (#0f0f12). */
export const CANVAS_SURFACE = '#09090b';

// Grid geometry — the ONE place these live. Both the xyflow <Background> below
// and the custom ForkCanvas CSS tile (which can't use xyflow's component) derive
// from these, so the mobile/fork grid can't drift from the editor grid.
export const CANVAS_GRID_GAP = 14; // spacing between marks (px @ zoom 1)
export const CANVAS_GRID_SIZE = 1; // cross mark extent (px)
export const CANVAS_GRID_COLOR = '#27272a'; // zinc-800

// CSS-tileable SVG matching the xyflow cross above, for ForkCanvas's CSS-grid
// layer. A gap×gap cell with a centered "+" of extent CANVAS_GRID_SIZE.
const _c = CANVAS_GRID_COLOR.replace('#', '%23');
const _h = CANVAS_GRID_GAP / 2;
const _s = CANVAS_GRID_SIZE / 2;
export const CANVAS_GRID_CSS_BG = `url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='${CANVAS_GRID_GAP}' height='${CANVAS_GRID_GAP}'><path d='M ${_h} ${_h - _s} L ${_h} ${_h + _s} M ${_h - _s} ${_h} L ${_h + _s} ${_h}' stroke='${_c}' stroke-width='1' stroke-linecap='round'/></svg>")`;

export function CanvasBackground() {
    return (
        <Background
            gap={CANVAS_GRID_GAP}
            size={CANVAS_GRID_SIZE}
            color={CANVAS_GRID_COLOR}
            variant={BackgroundVariant.Cross}
        />
    );
}
