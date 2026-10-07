// Original official SVG includes its own system color-scheme styles; no recoloring.
import { forwardRef, type CSSProperties, type ImgHTMLAttributes } from 'react';
const STACKITDNSIcon = forwardRef<HTMLImageElement, ImgHTMLAttributes<HTMLImageElement>>(
    ({ style, ...props }, ref) => (
        <img {...props} ref={ref} src="/icons/stackitdns.svg" alt="" aria-hidden="true"
            style={{ ...style, '--brand-invert': 0, objectFit: 'contain' } as CSSProperties} />
    ),
);
STACKITDNSIcon.displayName = 'STACKITDNSIcon';
export default STACKITDNSIcon;
