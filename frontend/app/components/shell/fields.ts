// The shell's text field, which stands on its own under its label (a form never sits inside a card), and the quiet
// link that goes under one ("Get a key ↗").
export const FIELD =
    'h-10 w-full rounded-xl border border-border bg-transparent px-3.5 text-[14px] text-foreground outline-none transition-colors placeholder:text-[hsl(var(--placeholder))] focus:border-foreground/25 disabled:opacity-60 dark:border-foreground/[0.1] dark:focus:border-foreground/25';

export const QUIET_LINK =
    'inline-flex items-center gap-1 rounded-md text-muted-foreground transition-colors hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring';

// A field's label: sentence case, above it.
export const FIELD_LABEL = 'mb-1.5 block text-[13px] font-medium text-foreground/85';
