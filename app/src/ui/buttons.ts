// The shell's two pill buttons: the one primary action on a surface, and its
// quieter neighbours. On a phone each is a finger's 40px tall.
export const BUTTON_PRIMARY =
    'inline-flex h-9 shrink-0 items-center gap-1.5 rounded-full max-md:h-10 bg-primary px-4 text-[13.5px] font-medium text-primary-foreground transition-opacity hover:opacity-90 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:pointer-events-none disabled:opacity-50';
export const BUTTON_SECONDARY =
    'inline-flex h-9 shrink-0 items-center gap-1.5 rounded-full max-md:h-10 bg-secondary px-4 text-[13.5px] font-medium text-foreground transition-colors hover:bg-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:pointer-events-none disabled:opacity-50 dark:bg-foreground/[0.07] dark:hover:bg-foreground/[0.11]';
// A dialog's way out (Cancel, Close), quieter than both.
export const BUTTON_GHOST =
    'inline-flex h-9 shrink-0 items-center gap-1.5 rounded-full max-md:h-10 px-3.5 text-[13.5px] text-muted-foreground transition-colors hover:bg-foreground/[0.06] hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:pointer-events-none disabled:opacity-50';
// The confirm that deletes or removes something, as the developer console's is: a red outline, never a filled alarm.
export const BUTTON_DANGER =
    'inline-flex h-9 shrink-0 items-center gap-1.5 rounded-full max-md:h-10 border border-red-600/40 px-4 text-[13.5px] font-medium text-red-600 transition-colors hover:bg-red-500/10 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:pointer-events-none disabled:opacity-50 dark:border-red-400/40 dark:text-red-400';
// A control smaller than a fingertip answers taps across at least 40px around its middle, looking no different. The
// control must be positioned (`relative`, or already `absolute`) and must not clip its overflow.
export const TAP_AREA = "after:absolute after:left-1/2 after:top-1/2 after:h-full after:min-h-10 after:w-full after:min-w-10 after:-translate-x-1/2 after:-translate-y-1/2 after:content-['']";
// A small outlined pill on a row (Connect, Buy, New), beside the row's own tap target.
export const BUTTON_OUTLINE_SM = `relative inline-flex h-8 shrink-0 items-center rounded-full px-3.5 text-[13px] font-medium text-foreground ring-1 ring-inset ring-border transition-colors hover:bg-foreground/[0.06] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:pointer-events-none disabled:opacity-50 dark:ring-foreground/[0.14] ${TAP_AREA}`;
// A quiet action in a line of text (Never mind, Connect another account, Ask someone who can): text that underlines on
// hover, no pill.
export const INLINE_ACTION =
    'self-start rounded-sm text-[13px] text-foreground underline-offset-4 transition-colors hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring';
