// The dashboard's surface classes, apart from its primitives (which carry the credential and node icon resolvers) so a
// page that only borders or hovers like the dashboard doesn't load those.
export const SURFACE =
    'rounded-xl border border-border bg-card [--surface:hsl(var(--card))] dark:border-foreground/[0.08] dark:bg-foreground/[0.02] dark:[--surface:color-mix(in_srgb,hsl(var(--foreground))_2%,hsl(var(--background)))]';
export const HAIRLINE = 'border-border dark:border-foreground/[0.08]';
export const ROW_HOVER = 'transition-colors hover:bg-foreground/[0.03]';
