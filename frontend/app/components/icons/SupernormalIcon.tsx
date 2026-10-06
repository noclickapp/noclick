// Exact Supernormal icon from its official API documentation's public asset.
// Normalize its dark source before the real canvas filter and preserve proportions.
import { forwardRef } from 'react';
import type { ImgHTMLAttributes } from 'react';

export const SupernormalIcon = forwardRef<HTMLImageElement, ImgHTMLAttributes<HTMLImageElement>>(
    ({ className, style, ...props }, ref) => (
        <img {...props} ref={ref} src="/icons/supernormal.svg" alt="" className={`brand-mono ${className || ''}`}
            style={{ ...style, objectFit: 'contain', filter: `invert(1) ${style?.filter || 'invert(var(--brand-invert, 0))'}` }} />
    ),
);
SupernormalIcon.displayName = 'SupernormalIcon';
