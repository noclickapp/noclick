// Console-wide token overrides, set on the shell and on every surface the
// console portals out of it (dialogs, drawers, the palette).

/** The surface a drawer or dialog stands on, as the app's own dialogs do: its sunken near-black in dark (never a lighter grey), white in light over the off-white page. */
export const SHEET_SURFACE = 'bg-card dark:bg-sunken';

/** Its edge: a hairline in light, a step stronger in dark, where the sheet and the page are both near-black. */
export const SHEET_EDGE = 'border-border dark:border-foreground/[0.12]';

/** Placeholders lifted to 4.5:1 on the console's surfaces, tinted fields included (the app's own token is dimmer on purpose). */
export const READABLE_PLACEHOLDERS = '[--placeholder:240_4%_40%] dark:[--placeholder:240_5%_56%]';
