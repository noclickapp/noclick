// Shared run-status ring colors for executed nodes, so the completed/failed border
// treatment is identical on the desktop canvas (NodeAuroraLayers overlay) and the
// mobile ForkCanvas (GenericCard). Leaf module (no React imports) so the perf-sensitive
// ForkCanvas can pull the values without dragging in the overlay component's deps.
//
// Completed is a soft foreground tint (deliberately not full foreground — that's reserved
// for selection); failed is a muted red. The glow is a single box-shadow (cheap) rather
// than a blur layer.

export const RUN_RING_STROKE = 1.5;

export const RUN_RING = {
    completed: { border: 'hsl(var(--foreground) / 0.7)', glow: '0 0 18px hsl(var(--foreground) / 0.28)' },
    error: { border: 'rgba(239, 68, 68, 0.6)', glow: '0 0 14px rgba(239, 68, 68, 0.25)' },
    // Incomplete config — amber, mirroring the desktop AutomationNode border/shadow.
    incomplete: { border: 'rgba(245, 158, 11, 0.55)', glow: '0 0 14px rgba(245, 158, 11, 0.2)' },
} as const;
