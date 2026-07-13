// Theme-aware NoClick mark. The bare glyph (/logo.svg is pure white) — kept as-is
// in dark; in light a full invert recolors it to pure black (white → #000).
// (Previously this rendered a black-circle app-icon treatment in light; reverted
// to the plain glyph per design.)
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
            className={cn('[filter:invert(1)] dark:[filter:invert(0)]', className)}
            {...imgProps}
        />
    );
}
