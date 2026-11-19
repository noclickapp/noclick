// How big a workflow's steps are on the canvas, and how its connections are drawn: the one place these live, so a
// layout and a preview drawn as an image can't drift from the canvas.

/** Every connection's line: soft gray in light, white in dark, dashed. */
export const DEFAULT_EDGE_STYLE = {
    stroke: 'hsl(var(--canvas-edge))',
    strokeWidth: 3,
    opacity: 0.8,
    strokeDasharray: '5 5',
} as const;

/** Heights that differ from an automation step's, by node type. */
export const NODE_HEIGHT_MAP: Record<string, number> = {
    // Taller nodes - 'agent'
    agent: 140,
    // Sticky notes can vary, use generous default
    'sticky-note': 150,
    // Form inputs are taller
    'form-input': 120,
};

/** Widths that differ from an automation step's, by node type. */
export const NODE_WIDTH_MAP: Record<string, number> = {
    // An agent is wider (200px vs 90px for automation steps)
    agent: 200,
    // Sticky notes can be wider
    'sticky-note': 250,
};

export const DEFAULT_NODE_HEIGHT = 90; // Standard automation node height
export const DEFAULT_NODE_WIDTH = 90; // Standard automation node width
