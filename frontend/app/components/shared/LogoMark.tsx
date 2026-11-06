// Theme-aware NoClick mark. The bare glyph (/logo.svg is pure white) — kept as-is
// in dark; in light a full invert recolors it to pure black (white → #000).
// (Previously this rendered a black-circle app-icon treatment in light; reverted
// to the plain glyph per design.)
import { cn } from '~/lib/utils';

/** The mark's weight sits up and left of its box (the solid arrow), so set in a circle or a tile it reads off-centre.
 *  This moves it halfway from its box's middle to its ink's, as a share of its own size: the whole way (6.4%) reads
 *  low and right at small sizes, and none high and left (compared at 18px, 38px and 180px). */
export const MARK_IN_A_SHAPE = 'translate-x-[3.2%] translate-y-[3.2%]';

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
