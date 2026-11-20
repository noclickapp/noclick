// The app shell's slots: the places in its frame and sidebar a host may fill (src/slots.ts), each with what stands there
// otherwise. What a host keeps of its own (a workspace switcher, a card offering its texting lines, a balance and how
// it's added to, its own menu rows, its staff's tools) goes here; with none, the shell is the app's pages and the
// account.
import type { ComponentType, ReactNode } from 'react';
import { Code2 } from 'lucide-react';
import { slot } from '@/slots';
import type { AccountMenuSwitch, AccountMenuUser } from '@/ui/accountParts';
import type { ShellPageId } from './pages';
import { AccountName, accountOnApp } from './slotStandards';

// ── the sidebar ─────────────────────────────────────────────────────────────

/** The pages the sidebar lists, in the shell's order: those this app serves. The standard is the pages the open app
 *  has routes for; a host that serves them all lists them all. */
export const PAGES = slot<readonly ShellPageId[]>('shell.pages', ['chat', 'work', 'resources']);

/** Atop the sidebar, beside search: the workspace. The standard names the account. */
export const WORKSPACE = slot<ComponentType<{ user: AccountMenuUser }>>('shell.workspace', AccountName);

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

/** The account menu's rows of the host's own, above Community (a support chat). Nothing stands there. */
export const ACCOUNT_ITEMS = slot<ComponentType | null>('shell.account.items', null);

/** The account menu's last rows, for the host's own people (its staff's tools); `go` opens one of its pages. Nothing
 *  stands there. */
export const ACCOUNT_STAFF = slot<ComponentType<{ go: (page: string) => void }> | null>('shell.account.staff', null);

/** Around the account row: what opens over it (a way to send the host feedback). Nothing stands there. */
export const ACCOUNT_AROUND = slot<ComponentType<{ children: ReactNode }> | null>('shell.account.around', null);

// ── the frame ───────────────────────────────────────────────────────────────

/** A strip across the top of the page (a host's staff viewing as someone). Nothing stands there. */
export const BANNER = slot<ComponentType | null>('shell.banner', null);
