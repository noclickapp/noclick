// A brand mark served as an image file, with an optional second file for dark mode.
// A part of a mark that would vanish on one theme's tile is recoloured in a file of
// its own for that theme rather than by a CSS filter: a filter reaches only the
// surfaces that apply it, and inverts a brand's colours along with the part that
// needed it.
import { forwardRef, type ImgHTMLAttributes } from 'react';
import { cn } from '~/lib/utils';

export type ThemedBrandImgProps = Omit<ImgHTMLAttributes<HTMLImageElement>, 'src'> & {
    /** The file shown in light mode, and in dark mode when there's no `dark`. */
    light: string;
    /** The file shown in dark mode. */
    dark?: string;
};

export const ThemedBrandImg = forwardRef<HTMLImageElement, ThemedBrandImgProps>(
    ({ light, dark, className, style, alt = '', ...rest }, ref) => {
        // Decorative unless it's named.
        const shared = {
            'aria-hidden': alt ? undefined : true,
            ...rest,
            style: { objectFit: 'contain' as const, ...style },
        };
        if (!dark) return <img {...shared} alt={alt} ref={ref} src={light} className={className} />;
        return (
            <>
                <img {...shared} alt={alt} ref={ref} src={light} className={cn(className, 'dark:hidden')} />
                <img {...shared} alt={alt} src={dark} className={cn(className, 'hidden dark:block')} />
            </>
        );
    },
);
ThemedBrandImg.displayName = 'ThemedBrandImg';
