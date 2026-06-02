// Corner status badge for workflow nodes — a solid, filled pill (mirrors the
// completed "✓" badge in NodeAuroraLayers) with a bare white glyph: a ✕ for an
// execution error (red) or a ! for incomplete config (amber). Replaces the old
// outline icon-inside-a-ring look that read as hollow concentric circles.
// Presentational only: callers keep their own show/hide conditions and just
// pick the variant.
import { X } from 'lucide-react';

export function NodeStatusBadge({ variant }: { variant: 'error' | 'incomplete' }) {
    const isError = variant === 'error';
    return (
        <div
            className="absolute -top-2 -right-2 z-20 flex items-center justify-center"
            style={{
                width: 24,
                height: 24,
                borderRadius: '50%',
                background: isError ? 'rgb(239, 68, 68)' : 'rgb(245, 158, 11)',
                boxShadow: isError
                    ? '0 0 10px rgba(239, 68, 68, 0.55)'
                    : '0 0 8px rgba(245, 158, 11, 0.45)',
            }}
        >
            {isError ? (
                <X className="w-3.5 h-3.5 text-white" strokeWidth={3} />
            ) : (
                <span className="text-sm font-bold leading-none text-white">!</span>
            )}
        </div>
    );
}
