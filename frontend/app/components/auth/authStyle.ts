// The sign-in surfaces' shared look, for the pages and the popup in both editions: serif headings, pill buttons and
// quiet inputs on theme tokens, so they read in light and dark.
import { TAP_AREA } from '~/components/shell/buttons';
export const AUTH_TITLE_CLASS = 'font-display font-normal leading-[0.95] tracking-[-0.02em] text-foreground';

export const AUTH_INPUT_CLASS =
    'h-12 w-full rounded-2xl border border-foreground/10 bg-foreground/[0.03] px-4 text-[15px] text-foreground outline-none transition-colors placeholder:text-foreground/40 focus:border-foreground/30 focus-visible:ring-0 focus-visible:ring-offset-0';

export const AUTH_PRIMARY_BUTTON_CLASS =
    'relative flex h-12 w-full items-center justify-center rounded-full bg-foreground text-[15px] font-medium text-background transition-colors hover:bg-foreground/85 disabled:cursor-not-allowed disabled:opacity-50';

/** A way to sign in (Google, phone, email, SSO): a quiet pill, so the one primary action stays the solid one. */
export const AUTH_OPTION_BUTTON_CLASS =
    'flex h-12 w-full items-center justify-center gap-2.5 rounded-full bg-foreground/[0.06] text-[15px] font-medium text-foreground transition-colors hover:bg-foreground/[0.1] disabled:cursor-not-allowed disabled:opacity-70';

export const AUTH_LABEL_CLASS = 'mb-2 block text-[13px] font-medium text-foreground/60';

/** A text link: its words alone, and a fingertip's tap (40px) around them on a phone. */
export const AUTH_LINK_CLASS = `relative font-medium text-foreground transition-opacity hover:opacity-70 ${TAP_AREA}`;
/** A quieter text link (Forgot password?, Enterprise SSO), with the same tap. */
export const AUTH_QUIET_LINK_CLASS = `relative text-foreground/60 transition-colors hover:text-foreground dark:text-foreground/55 ${TAP_AREA}`;
