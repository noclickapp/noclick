// Brand-icon files whose rendered art is entirely light (white / near-white) —
// designed for the old dark node bodies, they vanish on the now-light bodies and
// chips in light mode. Rendered with `invert dark:invert-0`: a dark mark on light,
// unchanged white on dark. Derived by scanning public/icons for marks whose every
// VISIBLE fill has luminance > 0.7 — including mask-based marks (cal-com renders a
// masked white tile; its lone #000 lives inside a <mask> and never paints). Keep
// in sync if new all-white brand SVGs are added.
export const MONOCHROME_LIGHT_ICONS = new Set([
    'attio',
    // NOT clickhouse (#FCFF74 light yellow) or intercom (#6AFDEF light cyan): the
    // luminance>0.7 heuristic caught light COLORS, not white — inverting them
    // flips the hue (yellow->blue, cyan->dark-red). They keep their brand color.
    'extend',
    'launchdarkly',
    'notion',
    'parallel',
    'pinecone',
    'resend',
    'sigma',
    'zendesk',
    // cal-com renders a masked WHITE tile (the #000 is only inside its <mask>),
    // so it reads as a blank square on a light node — invert flips it to a tile.
    'cal-com',
    // NOT openclaw_marker: it's white claw art WITH a red #f70514 accent, so invert
    // flips the red to CYAN. Left un-inverted — the red claw stays visibly red on a
    // light chip (AgentModelIcon still chips it for the node body). NOT hermes_marker
    // either: a gold/amber/bronze "H" (#FFD700…) whose hue inverts to blue.
]);

/** The class that inverts a monochrome-light mark in light mode (via `.brand-mono`,
 *  which composes with inline filters), keyed by an icon src/path or bare slug.
 *  '' for colored / two-tone marks. */
export function monochromeIconClass(srcOrSlug: string | undefined): string {
    if (!srcOrSlug) return '';
    const slug = srcOrSlug
        .split('/')
        .pop()!
        .replace(/\.svg.*$/i, '')
        .replace(/\?.*$/, '');
    return MONOCHROME_LIGHT_ICONS.has(slug) ? 'brand-mono' : '';
}

/** Same, reading the src out of a serialized `<img …src="…">` markup string. */
export function monochromeIconClassFromHtml(html: string): string {
    const m = html.match(/<img[^>]*\ssrc="([^"]+)"/i);
    return m ? monochromeIconClass(m[1]) : '';
}
