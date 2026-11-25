// The shell's text field, which stands on its own under its label (a form never sits inside a card), and the quiet
// link that goes under one ("Get a key ↗").
export const FIELD =
    'h-10 w-full rounded-xl border border-border bg-transparent px-3.5 text-[14px] text-foreground outline-none transition-colors placeholder:text-[hsl(var(--placeholder))] focus:border-foreground/25 disabled:opacity-60 dark:border-foreground/[0.1] dark:focus:border-foreground/25';

/** A one-line field as a pill: a short name, a search. */
export const PILL_FIELD = FIELD.replace('rounded-xl', 'rounded-full');

/** A page's search on a phone, as a phone's own are: a filled pill with no border, a finger tall, its text 16px (under
 *  that, iOS zooms the page into a field as it's focused). It goes after the field's own classes; a laptop keeps them. */
export const PHONE_SEARCH =
    'max-md:h-10 max-md:rounded-full max-md:border-transparent max-md:bg-foreground/[0.08] max-md:text-[16px] max-md:focus:border-transparent max-md:focus:bg-foreground/[0.11] max-md:dark:border-transparent max-md:dark:focus:border-transparent';
/** The same where the pill is a label around its field (the field inside is bare). */
export const PHONE_SEARCH_BOX =
    'max-md:h-10 max-md:border-transparent max-md:bg-foreground/[0.08] max-md:focus-within:border-transparent max-md:focus-within:bg-foreground/[0.11] max-md:dark:border-transparent';

export const QUIET_LINK =
    'inline-flex items-center gap-1 rounded-md text-muted-foreground transition-colors hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring';

// A field's label: sentence case, above it.
export const FIELD_LABEL = 'mb-1.5 block text-[13px] font-medium text-foreground/85';
