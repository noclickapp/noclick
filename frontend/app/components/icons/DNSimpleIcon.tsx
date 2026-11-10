// DNSimple's mark (its site's pinned-tab icon) in the brand blue its mask-icon link names; reads on both themes.
import { forwardRef, type ImgHTMLAttributes } from 'react';
import { ThemedBrandImg } from '~/components/shared/ThemedBrandImg';
const DNSimpleIcon = forwardRef<HTMLImageElement, ImgHTMLAttributes<HTMLImageElement>>(
    (props, ref) => (
        <ThemedBrandImg {...props} ref={ref} light="/icons/dnsimple-brand-vector.svg" />
    ),
);
DNSimpleIcon.displayName = 'DNSimpleIcon';
export default DNSimpleIcon;

