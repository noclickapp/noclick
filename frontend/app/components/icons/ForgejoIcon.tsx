// Original official colored SVG, with the supplied canvas filter preserved.
import { forwardRef, type ImgHTMLAttributes } from 'react';
const ForgejoIcon = forwardRef<HTMLImageElement, ImgHTMLAttributes<HTMLImageElement>>(
    ({ style, ...props }, ref) => (
        <img {...props} ref={ref} src="/icons/forgejo.svg" alt="" aria-hidden="true"
            style={{ ...style, objectFit: 'contain' }} />
    ),
);
ForgejoIcon.displayName = 'ForgejoIcon';
export default ForgejoIcon;
