// Microsoft's four squares. Simple Icons carries no Microsoft mark and the
// single-colour Bootstrap glyph is not the logo, so the mark is drawn here.
import type { CSSProperties } from 'react';

export default function MicrosoftIcon({ className, style }: { className?: string; style?: CSSProperties }) {
    return (
        <svg viewBox="0 0 24 24" className={className} style={style} aria-hidden="true">
            <rect x="1" y="1" width="10.5" height="10.5" fill="#F25022" />
            <rect x="12.5" y="1" width="10.5" height="10.5" fill="#7FBA00" />
            <rect x="1" y="12.5" width="10.5" height="10.5" fill="#00A4EF" />
            <rect x="12.5" y="12.5" width="10.5" height="10.5" fill="#FFB900" />
        </svg>
    );
}
