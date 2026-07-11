// Theme-aware NoClick mark. The bare glyph (/logo.svg is pure white) — kept as-is
// in dark; in light a partial invert recolors it to CHARCOAL (white → ~#333 at
// invert(0.8), not pure black). (Previously this rendered a black-circle app-icon
// treatment in light; reverted to the plain glyph per design.)
import { cn } from '~/lib/utils';

export function LogoMark({
    className,
    alt = 'NoClick',
    ...imgProps
}: { className?: string; alt?: string } & Omit<
    React.ImgHTMLAttributes<HTMLImageElement>,
    'src' | 'className' | 'alt'
>) {
    return (
        <img
            src="/logo.svg"
            alt={alt}
            className={cn('[filter:invert(0.8)] dark:[filter:invert(0)]', className)}
            {...imgProps}
        />
    );
}
