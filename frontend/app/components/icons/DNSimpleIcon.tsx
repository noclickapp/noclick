// Displays the exact original inline SVG from DNSimple's official v2 guide.
// Source-black artwork is converted to the shared white-mark convention before theme/disabled filters.
import { forwardRef, type CSSProperties, type ImgHTMLAttributes } from 'react';
const DNSimpleIcon = forwardRef<HTMLImageElement, ImgHTMLAttributes<HTMLImageElement>>(
    ({ style, className, ...props }, ref) => (
        <img {...props} ref={ref} src="/icons/dnsimple.svg" alt="" aria-hidden="true"
            className={['brand-mono', className].filter(Boolean).join(' ')}
            style={{ ...style, objectFit: 'contain', filter: 'invert(1) ' + (style?.filter || 'invert(var(--brand-invert, 0))') } as CSSProperties} />
    ),
);
DNSimpleIcon.displayName = 'DNSimpleIcon';
export default DNSimpleIcon;

