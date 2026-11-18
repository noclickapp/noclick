// Renders a brand icon from pre-serialized markup (an <img> or <svg> HTML string
// the host renders on its server from its node catalog), so a page shows node and
// brand icons without loading the components that draw them. Its colour rule: a
// text-* class applies as a class, a raw hex or rgb value as style.color, and ''
// leaves a multicolour mark as it is.
import { type ComponentType, type CSSProperties, useId, useMemo } from 'react';
import { cn } from '@/ui/utils';

interface SerializedIconProps {
    /** Pre-rendered icon markup (SerializedNodeMeta.iconHtml). */
    html: string;
    /** Tailwind `text-*` class, a raw hex/rgb value, or '' for multicolor marks. */
    iconColor?: string;
    /** Sizing/extra classes for the wrapper; the child img/svg fills it. */
    className?: string;
    style?: CSSProperties;
    /** Let <img> glyphs keep their intrinsic aspect ratio (height from className,
     *  width auto) instead of filling a forced square. Bare icon rows use this so
     *  tall/wide marks don't carry contain-fit side margins that read as uneven
     *  gaps. Inline <svg> glyphs keep the square fill (no reliable intrinsic ratio). */
    autoWidth?: boolean;
}

// Inlined SVG brand icons (e.g. Google Sheets, Telegram) carry gradient/clip ids
// baked in server-side, so many instances on one page share ids like "«R0»" and
// every `url(#«R0»)` resolves to the FIRST match in the DOM — later icons then
// render with the wrong or an empty gradient. Scope each id (and its url()/href
// references) to this instance so the gradients stay unique.
function scopeSvgIds(html: string, uid: string): string {
    const ids = Array.from(html.matchAll(/\bid="([^"]+)"/g), (m) => m[1]);
    if (ids.length === 0) return html;
    let out = html;
    for (const id of ids) {
        const esc = id.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
        const scoped = `${id}-${uid}`;
        out = out
            .replace(new RegExp(`id="${esc}"`, 'g'), `id="${scoped}"`)
            .replace(
                new RegExp(`url\\((['"]?)#${esc}\\1\\)`, 'g'),
                `url($1#${scoped}$1)`
            )
            .replace(
                new RegExp(`(xlink:href|href)="#${esc}"`, 'g'),
                `$1="#${scoped}"`
            );
    }
    return out;
}

/** The file an image-based mark shows in one theme: of a light/dark pair (a `dark:hidden` image and a
 *  `hidden dark:block` one), the one for that theme; else its only image. For surfaces that draw the file
 *  themselves rather than the markup. */
export function serializedImgSrc(html: string, dark: boolean): string | undefined {
    const imgs = html.match(/<img\b[^>]*>/g) ?? [];
    const shown = dark ? /\sclass="[^"]*\bdark:block\b/ : /\sclass="[^"]*\bdark:hidden\b/;
    return (imgs.find((tag) => shown.test(tag)) ?? imgs[0])?.match(/\ssrc="([^"]+)"/)?.[1];
}

export function SerializedIcon({
    html,
    iconColor,
    className,
    style,
    autoWidth = false,
}: SerializedIconProps) {
    // useId is stable across SSR/hydration, so the scoped markup matches.
    const uid = useId().replace(/[^a-zA-Z0-9]/g, '');
    const scopedHtml = useMemo(
        () => (html ? scopeSvgIds(html, uid) : ''),
        [html, uid]
    );
    if (!html) return null;
    // Default to the foreground; text-* applies as a class (svg currentColor
    // inherits it; img ignores it), a raw value applies via color.
    const c = iconColor || 'text-foreground';
    const isTw = c.startsWith('text-');
    return (
        <span
            className={cn(
                // The wrapper carries the size; the serialized img/svg fills it
                // (its own width/height attrs, e.g. react-icons' 1em, are overridden).
                'inline-flex items-center justify-center [&>svg]:w-full [&>svg]:h-full',
                autoWidth
                    ? '[&>img]:h-full [&>img]:w-auto'
                    : '[&>img]:w-full [&>img]:h-full',
                className,
                isTw && c
            )}
            style={!isTw && c ? { ...style, color: c } : style}
            dangerouslySetInnerHTML={{ __html: scopedHtml }}
        />
    );
}

/** A pre-rendered icon (from the node icon registry) as an icon component, for surfaces that draw icons as components
 *  (passing className and style); the child img/svg fills the sized wrapper. */
export function serializedIconComponent(html: string): ComponentType<{ className?: string; style?: CSSProperties }> {
    return function NodeBrandIcon({ className, style }) {
        return (
            <span
                className={cn(
                    'inline-flex items-center justify-center [&>img]:w-full [&>img]:h-full [&>svg]:w-full [&>svg]:h-full',
                    className
                )}
                style={style}
                dangerouslySetInnerHTML={{ __html: html }}
            />
        );
    };
}
