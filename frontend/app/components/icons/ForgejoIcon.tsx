// Original official colored SVG, with the supplied canvas filter preserved.
import { forwardRef, type CSSProperties, type ImgHTMLAttributes } from 'react';
const ForgejoIcon = forwardRef<HTMLImageElement, ImgHTMLAttributes<HTMLImageElement>>(
    ({ style, ...props }, ref) => (
        <img {...props} ref={ref} src="/icons/forgejo.svg" alt="" aria-hidden="true"
            style={{ ...style, '--brand-invert': 0, objectFit: 'contain' } as CSSProperties} />
    ),
);
ForgejoIcon.displayName = 'ForgejoIcon';
export default ForgejoIcon;
