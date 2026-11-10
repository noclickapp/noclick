// Original official SVG includes its own system color-scheme styles; no recoloring.
import { forwardRef, type ImgHTMLAttributes } from 'react';
const STACKITDNSIcon = forwardRef<HTMLImageElement, ImgHTMLAttributes<HTMLImageElement>>(
    ({ style, ...props }, ref) => (
        <img {...props} ref={ref} src="/icons/stackitdns.svg" alt="" aria-hidden="true"
            style={{ ...style, objectFit: 'contain' }} />
    ),
);
STACKITDNSIcon.displayName = 'STACKITDNSIcon';
export default STACKITDNSIcon;
