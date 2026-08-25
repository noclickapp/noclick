// Renders a brand icon from pre-serialized markup (an <img> or <svg> HTML string
// produced server-side from the node registry by lib/nodeCatalog.server). This lets
// public marketing pages (integrations, templates) show node/brand icons WITHOUT
// importing the heavy node registry into the client bundle. It mirrors BrandIcon's
// color rule exactly (text-* class vs raw hex via style.color vs multicolor) so
// icons look identical to the in-app surfaces that use BrandIcon directly.
import { type CSSProperties, useId, useMemo } from 'react';
import { cn } from '~/lib/utils';
import { monochromeIconClassFromHtml } from '~/lib/monochromeIcons';

interface SerializedIconProps {
    /** Pre-rendered icon markup from nodeCatalog.server (SerializedNodeMeta.iconHtml). */
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
// render with the wrong/empty gradient (the "partial logo" bug). Scope each id
// (and its url()/href references) to this instance so the gradients stay unique.
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
    // Same rule as BrandIcon: default to white, text-* applies as a class (svg
    // currentColor inherits it; img ignores it), a raw value applies via color.
    const c = iconColor || 'text-foreground';
    const isTw = c.startsWith('text-');
    // All-white brand marks (notion, resend, …) invert to a dark glyph in light
    // mode so they don't vanish on light node bodies / chips; unchanged on dark.
    // The node's own Icon component may already bake `brand-mono` into its markup
    // (renderToStaticMarkup keeps the class), so applying it AGAIN on the wrapper
    // would double-invert — two nested filter:invert(1) cancel out and the mark
    // renders as a blank white tile on light chips (the cal-com bug). Add the
    // wrapper invert only when the injected markup doesn't already carry it.
    const monoInvert = /class=["'][^"']*\bbrand-mono\b/.test(scopedHtml)
        ? ''
        : monochromeIconClassFromHtml(scopedHtml);
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
                monoInvert,
                isTw && c
            )}
            style={!isTw && c ? { ...style, color: c } : style}
            dangerouslySetInnerHTML={{ __html: scopedHtml }}
        />
    );
}
