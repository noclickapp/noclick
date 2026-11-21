// The app shell's slots: the places in its frame and sidebar a host may fill (src/slots.ts), each with what stands there
// otherwise. What a host keeps of its own (a workspace switcher, a card offering its texting lines, a balance and how
// it's added to, its own menu rows, its staff's tools) goes here; with none, the shell is the app's pages and the
// account.
import type { ComponentType, ReactNode } from 'react';
import { Code2 } from 'lucide-react';
import { slot } from '@/slots';
import type { AccountMenuSwitch, AccountMenuUser } from '@/ui/accountParts';
import type { ShellPageId } from './pages';
import type { Cmd } from './palette/layout';
import type { PaletteScope } from './palette/open';
import type { HoldingPage, PaletteEntry } from './palette/sources';
import { FeedbackAround, FeedbackMenuItem } from './feedback';
import { AccountName, accountOnApp, paletteOnApp } from './slotStandards';

// ── the sidebar ─────────────────────────────────────────────────────────────

/** The pages the sidebar lists, in the shell's order: those this app serves. The standard is the pages the open app
 *  has routes for; a host that serves them all lists them all. */
export const PAGES = slot<readonly ShellPageId[]>('shell.pages', ['chat', 'work', 'connections', 'resources']);

/** Atop the sidebar, beside search: the workspace. `onNavigate` closes a phone's sheet when it goes somewhere. The
 *  standard names the account and leads home. */
export const WORKSPACE = slot<ComponentType<{ user: AccountMenuUser; onNavigate?: () => void }>>('shell.workspace', AccountName);

/** At the sidebar's foot, while it's open: a card of the host's (an offer to text it from a phone). Nothing stands
 *  there. */
export const FOOT_CARD = slot<ComponentType | null>('shell.foot.card', null);

/** At the foot: the balance, kept mounted (hidden) on the rail, since what's there may listen for the app's events.
 *  Nothing stands there. */
export const FOOT_BALANCE = slot<ComponentType | null>('shell.foot.balance', null);

/** At the foot, under the balance, while the sidebar is open: a row of the host's. Nothing stands there. */
export const FOOT_INVITE = slot<ComponentType | null>('shell.foot.invite', null);

// ── the account ─────────────────────────────────────────────────────────────

/** Whose session the account is: its plan as the host knows it (null for a free account), and how it signs out.
 *  Hooks, called by the account row. The standard reads the plan from the platform API and signs out of this app. */
export interface AccountSession {
    usePlan: () => string | null;
    useSignOut: () => () => void;
}
export const ACCOUNT_SESSION = slot<AccountSession>('shell.account.session', accountOnApp);

/** First in the account menu: the other place this account works. The standard is this app's developer console. */
export const ACCOUNT_SWITCH = slot<AccountMenuSwitch | null>('shell.account.switchTo', { label: 'Developers', icon: Code2, to: '/developers' });

/** The account menu's billing rows, under its header. Nothing stands there. */
export const ACCOUNT_BILLING = slot<ComponentType | null>('shell.account.billing', null);

/** The account menu's rows of the host's own, above Community (a support chat). The standard sends NoClick feedback
 *  through the platform API (feedback.tsx). */
export const ACCOUNT_ITEMS = slot<ComponentType | null>('shell.account.items', FeedbackMenuItem);

/** The account menu's last rows, for the host's own people (its staff's tools); `go` opens one of its pages. Nothing
 *  stands there. */
export const ACCOUNT_STAFF = slot<ComponentType<{ go: (page: string) => void }> | null>('shell.account.staff', null);

/** Around the account row: what opens over it (a way to send the host feedback). The standard holds the feedback
 *  dialog the menu's row opens, so it stays open once the menu has closed. */
export const ACCOUNT_AROUND = slot<ComponentType<{ children: ReactNode }> | null>('shell.account.around', FeedbackAround);

// ── the frame ───────────────────────────────────────────────────────────────

/** A strip across the top of the page (a host's staff viewing as someone). Nothing stands there. */
export const BANNER = slot<ComponentType | null>('shell.banner', null);

// ── the command palette ─────────────────────────────────────────────────────

/** What the palette hands whoever builds its commands. */
export interface PaletteContext {
    open: boolean;
    /** What it shows: its commands, or the keyboard shortcuts. */
    page: 'root' | 'shortcuts';
    /** What registered sources add: places to go, and (`action`) things done in place. */
    registered: readonly PaletteEntry[];
    /** What pages handed over, by page. */
    held: Partial<Record<HoldingPage, readonly PaletteEntry[]>>;
    /** Narrows the palette to one section, its query cleared (an "Open …" command). */
    scopeTo: (scope: PaletteScope) => void;
    /** Shows the keyboard shortcuts. */
    showShortcuts: () => void;
}

export interface ShortcutItem {
    keys: string[];
    /** Pressed one after another (G then W), not together. */
    sequence?: boolean;
    label: string;
}

export interface ShortcutGroup {
    title: string;
    items: ShortcutItem[];
}

/** What the palette offers: its commands in order (a hook, called while it's mounted, with what's drawn beside it), the
 *  sections an "Open …" command narrows to (by the placeholder it shows), and the keyboard shortcuts it lists. */
export interface PaletteHost {
    useCommands: (palette: PaletteContext) => { commands: readonly Cmd[]; beside?: ReactNode };
    scopes: readonly { scope: PaletteScope; label: string }[];
    shortcuts: readonly ShortcutGroup[];
}

/** The ⌘K palette's commands. The standard goes to the pages this app serves (and Resources' kinds), to what its pages
 *  handed over, and offers the theme, the keyboard shortcuts and signing out. */
export const PALETTE = slot<PaletteHost>('shell.palette', paletteOnApp);
