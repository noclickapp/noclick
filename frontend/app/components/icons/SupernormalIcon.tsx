// Supernormal's bolt in its brand blue, as its homepage draws it; reads on both themes.
import { forwardRef } from 'react';
import type { ImgHTMLAttributes } from 'react';
import { ThemedBrandImg } from '~/components/shared/ThemedBrandImg';

export const SupernormalIcon = forwardRef<HTMLImageElement, ImgHTMLAttributes<HTMLImageElement>>(
    (props, ref) => (
        <ThemedBrandImg {...props} ref={ref} light="/icons/supernormal.svg" />
    ),
);
SupernormalIcon.displayName = 'SupernormalIcon';
