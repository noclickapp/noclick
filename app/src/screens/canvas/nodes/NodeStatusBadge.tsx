// Corner status badge for workflow nodes — a solid, filled pill with a bare glyph:
// a ✕ for an execution error (red), a ! for incomplete config (amber), or a ✓ for a
// completed run (near-white). One source of truth for all three corner marks, shared
// by the desktop AutomationNode + NodeAuroraLayers AND the mobile ForkCanvas cards,
// so the failed/completed marks render identically on every canvas (no drift).
// Presentational only: callers keep their own show/hide conditions and just pick the
// variant. `style` lets a caller layer on extras (e.g. NodeAuroraLayers' pop animation).
import { Check, X } from 'lucide-react';

export type NodeStatusVariant = 'error' | 'incomplete' | 'completed';

const VARIANT_STYLE: Record<NodeStatusVariant, React.CSSProperties> = {
    error: { background: 'rgb(239, 68, 68)', boxShadow: '0 0 10px rgba(239, 68, 68, 0.55)' },
    incomplete: { background: 'rgb(245, 158, 11)', boxShadow: '0 0 8px rgba(245, 158, 11, 0.45)' },
    // Soft foreground-tinted fill + foreground ring + background-colored glyph — matches
    // the live-run ✓ treatment. Deliberately not full foreground (that's reserved for selection).
    completed: { background: 'hsl(var(--foreground) / 0.9)', border: '2px solid hsl(var(--foreground))', boxShadow: '0 0 10px hsl(var(--foreground) / 0.6)' },
};

export function NodeStatusBadge({ variant, style }: { variant: NodeStatusVariant; style?: React.CSSProperties }) {
    return (
        <div
            className="absolute -top-2 -right-2 z-20 flex items-center justify-center"
            style={{ width: 24, height: 24, borderRadius: '50%', ...VARIANT_STYLE[variant], ...style }}
        >
            {variant === 'error' && <X className="w-3.5 h-3.5 text-white" strokeWidth={3} />}
            {variant === 'incomplete' && <span className="text-sm font-bold leading-none text-white">!</span>}
            {variant === 'completed' && <Check className="w-3.5 h-3.5 text-background" strokeWidth={3} />}
        </div>
    );
}
