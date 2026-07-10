// Brand-icon files whose art is entirely light (white / near-white) — designed
// for the old dark node bodies, they vanish on the now-light bodies and chips in
// light mode. Rendered with `invert dark:invert-0`: a dark glyph on light,
// unchanged white on dark. Derived by scanning public/icons for marks whose every
// fill has luminance > 0.7 (two-tone marks that carry their own dark, e.g.
// cal-com, are excluded — they read fine on white). Keep in sync if new all-white
// brand SVGs are added.
export const MONOCHROME_LIGHT_ICONS = new Set([
    'attio',
    'clickhouse',
    'extend',
    'intercom',
    'launchdarkly',
    'notion',
    'parallel',
    'pinecone',
    'resend',
    'sigma',
    'zendesk',
    // Agent-harness markers (white-on-dark art), shown in card chips.
    'openclaw_marker',
    'hermes_marker',
]);

/** The Tailwind class to invert a monochrome-light mark in light mode, keyed by
 *  an icon src/path or bare slug. '' for colored / two-tone marks. */
export function monochromeIconClass(srcOrSlug: string | undefined): string {
    if (!srcOrSlug) return '';
    const slug = srcOrSlug
        .split('/')
        .pop()!
        .replace(/\.svg.*$/i, '')
        .replace(/\?.*$/, '');
    return MONOCHROME_LIGHT_ICONS.has(slug) ? 'invert dark:invert-0' : '';
}

/** Same, reading the src out of a serialized `<img …src="…">` markup string. */
export function monochromeIconClassFromHtml(html: string): string {
    const m = html.match(/<img[^>]*\ssrc="([^"]+)"/i);
    return m ? monochromeIconClass(m[1]) : '';
}
