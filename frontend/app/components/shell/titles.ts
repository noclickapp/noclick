// The app's big headings, set in the landing page's serif (Instrument Serif: one weight, so never a faux bold) so
// the app and the site read as one product. The sidebar and everything smaller stay in the sans.
import '@fontsource/instrument-serif/400.css';
import '@fontsource/instrument-serif/400-italic.css';

/** The serif, for a heading that sets its own size (the chat's headline). */
export const DISPLAY = 'font-display font-normal tracking-[-0.015em]';

/** A page's title. 1.15 leaves the serif's descenders inside the line box, which a truncated title clips to. */
export const PAGE_TITLE = `${DISPLAY} text-[34px] leading-[1.15] text-foreground`;
