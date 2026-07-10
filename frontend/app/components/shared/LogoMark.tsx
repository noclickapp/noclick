// Theme-aware NoClick mark. Dark mode keeps the bare white glyph (/logo.svg);
// light mode renders the app-icon treatment — a black circle with the white
// glyph inset at ~60% (mirroring /apple-touch-icon.png proportions). Pure CSS
// switching (two elements, dark:hidden/dark:block) so it is SSR-safe and flips
// instantly with the theme class. The sizing className lands on the circle in
// light and on the glyph in dark, so both render at the same box size.
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
        <>
            <span
                className={cn(
                    'inline-flex items-center justify-center rounded-full bg-black dark:hidden',
                    className
                )}
                aria-hidden={imgProps['aria-hidden']}
            >
                <img src="/logo.svg" alt={alt} className="h-[58%] w-[58%]" />
            </span>
            <img
                src="/logo.svg"
                alt={alt}
                className={cn('hidden dark:block', className)}
                {...imgProps}
            />
        </>
    );
}
