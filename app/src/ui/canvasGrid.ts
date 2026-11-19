// The workflow canvas's grid, the one place it's defined, so every surface that draws a canvas (the editor, a
// read-only view, a preview drawn as an image) stays visually identical.

/** Dark-zinc canvas surface (tailwind zinc-950). */
export const CANVAS_SURFACE = '#09090b';

// Grid geometry: an editor's grid component and a CSS tile (where no such component can be used) both derive from these.
export const CANVAS_GRID_GAP = 14; // spacing between marks (px @ zoom 1)
export const CANVAS_GRID_SIZE = 1; // cross mark extent (px)
// Theme-reactive: --canvas-grid is zinc-800 in dark and a light zinc-300 in light, so the grid stays subtle either way.
export const CANVAS_GRID_COLOR = 'hsl(var(--canvas-grid))';
// Literals for the data-URI CSS tile (which can't embed var()), one per theme.
export const CANVAS_GRID_HEX_DARK = '#27272a'; // zinc-800
export const CANVAS_GRID_HEX_LIGHT = '#d0d0d6';

// A CSS-tileable SVG of the same cross: a gap×gap cell with a centered "+" of extent CANVAS_GRID_SIZE.
const _c = encodeURIComponent(CANVAS_GRID_HEX_DARK);
const _cl = encodeURIComponent(CANVAS_GRID_HEX_LIGHT);
const _h = CANVAS_GRID_GAP / 2;
const _s = CANVAS_GRID_SIZE / 2;
export const CANVAS_GRID_CSS_BG = `url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='${CANVAS_GRID_GAP}' height='${CANVAS_GRID_GAP}'><path d='M ${_h} ${_h - _s} L ${_h} ${_h + _s} M ${_h - _s} ${_h} L ${_h + _s} ${_h}' stroke='${_c}' stroke-width='1' stroke-linecap='round'/></svg>")`;
export const CANVAS_GRID_CSS_BG_LIGHT = `url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='${CANVAS_GRID_GAP}' height='${CANVAS_GRID_GAP}'><path d='M ${_h} ${_h - _s} L ${_h} ${_h + _s} M ${_h - _s} ${_h} L ${_h + _s} ${_h}' stroke='${_cl}' stroke-width='1' stroke-linecap='round'/></svg>")`;
