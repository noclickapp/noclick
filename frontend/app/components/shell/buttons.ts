// The shell's two pill buttons: the one primary action on a surface, and its
// quieter neighbours.
export const BUTTON_PRIMARY =
    'inline-flex h-9 shrink-0 items-center gap-1.5 rounded-full bg-primary px-4 text-[13.5px] font-medium text-primary-foreground transition-opacity hover:opacity-90 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:pointer-events-none disabled:opacity-50';
export const BUTTON_SECONDARY =
    'inline-flex h-9 shrink-0 items-center gap-1.5 rounded-full bg-secondary px-4 text-[13.5px] font-medium text-foreground transition-colors hover:bg-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:pointer-events-none disabled:opacity-50 dark:bg-foreground/[0.07] dark:hover:bg-foreground/[0.11]';
// A dialog's way out (Cancel, Close), quieter than both.
export const BUTTON_GHOST =
    'inline-flex h-9 shrink-0 items-center gap-1.5 rounded-full px-3.5 text-[13.5px] text-muted-foreground transition-colors hover:bg-foreground/[0.06] hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:pointer-events-none disabled:opacity-50';
// The confirm that deletes or removes something, as the developer console's is: a red outline, never a filled alarm.
export const BUTTON_DANGER =
    'inline-flex h-9 shrink-0 items-center gap-1.5 rounded-full border border-red-600/40 px-4 text-[13.5px] font-medium text-red-600 transition-colors hover:bg-red-500/10 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:pointer-events-none disabled:opacity-50 dark:border-red-400/40 dark:text-red-400';
