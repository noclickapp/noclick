// Supernormal brand symbol from the official API documentation logo.
// Black artwork in light mode, its white copy (supernormal-dark.svg) in dark mode.
import { forwardRef } from 'react';
import type { ImgHTMLAttributes } from 'react';
import { ThemedBrandImg } from '~/components/shared/ThemedBrandImg';

export const SupernormalIcon = forwardRef<HTMLImageElement, ImgHTMLAttributes<HTMLImageElement>>(
    (props, ref) => (
        <ThemedBrandImg {...props} ref={ref} light="/icons/supernormal.svg" dark="/icons/supernormal-dark.svg" />
    ),
);
SupernormalIcon.displayName = 'SupernormalIcon';
