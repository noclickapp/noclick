// The shell's menus (the account, the workspace, the composer's "+") share the composer's surface: near-black in
// dark with a hairline ring and a lit top edge, not the stock grey popover.
export const MENU_SURFACE =
    'border-0 bg-composer text-foreground ring-1 ring-inset ring-border shadow-[0_18px_48px_-18px_rgba(0,0,0,0.28)] dark:ring-foreground/[0.09] dark:shadow-[inset_0_1px_0_hsl(var(--foreground)/0.06),0_24px_56px_-20px_rgba(0,0,0,0.9)]';

/** A rule between a menu's groups, edge to edge inside its p-1.5. */
export const MENU_SEPARATOR = '-mx-1.5 my-1.5 bg-border dark:bg-foreground/[0.08]';
