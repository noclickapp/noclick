// Freshsales (Freshworks CRM) brand logo icon component.
// react-icons has no SiFreshsales, so this wraps the official brand SVG served from
// /public/icons/freshsales.svg — used by the Freshsales node component.

import type { CSSProperties } from 'react';

export function FreshsalesIcon({ className, style }: { className?: string; style?: CSSProperties }) {
    return <img src="/icons/freshsales.svg" alt="" className={className} style={style} />;
}
