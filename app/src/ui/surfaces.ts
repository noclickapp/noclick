// The surface classes the app's lists and cards share, apart from the primitives (which carry the node marks) so a page
// that only borders or hovers like them doesn't load those.
export const SURFACE =
    'rounded-xl border border-border bg-card [--surface:hsl(var(--card))] dark:border-foreground/[0.08] dark:bg-foreground/[0.02] dark:[--surface:color-mix(in_srgb,hsl(var(--foreground))_2%,hsl(var(--background)))]';
export const HAIRLINE = 'border-border dark:border-foreground/[0.08]';
export const ROW_HOVER = 'transition-colors hover:bg-foreground/[0.03]';
