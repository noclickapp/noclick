// Displays the exact original inline SVG from DNSimple's official v2 guide.
// Black artwork in light mode, its white copy (dnsimple-dark.svg) in dark mode.
import { forwardRef, type ImgHTMLAttributes } from 'react';
import { ThemedBrandImg } from '~/components/shared/ThemedBrandImg';
const DNSimpleIcon = forwardRef<HTMLImageElement, ImgHTMLAttributes<HTMLImageElement>>(
    (props, ref) => (
        <ThemedBrandImg {...props} ref={ref} light="/icons/dnsimple.svg" dark="/icons/dnsimple-dark.svg" />
    ),
);
DNSimpleIcon.displayName = 'DNSimpleIcon';
export default DNSimpleIcon;

