// What stands in the shell's slots (slots.ts) when no host fills them: each works on the platform API alone.
import { useMemo } from 'react';
import { Link, useNavigate } from 'react-router';
import { signOut } from '@/lib/signOut';
import { userDisplayName } from '@/lib/userDisplay';
import { readAccountStatus } from '@/screens/account/status';
import { KINDS, resourceAddress, type KindId } from '@/screens/resources/kinds';
import { useClient } from '@/sdk/client';
import { useV1 } from '@/sdk/useV1';
import { useSlot } from '@/slots';
import type { AccountMenuUser } from '@/ui/accountParts';
import { LogoMark } from '@/ui/LogoMark';
import { useTheme } from '@/ui/useTheme';
import { SHELL_PAGES } from './pages';
import { asCmd, heldCommands, registeredEntries, shortcutsCommand, signOutCommand, themeCommands } from './palette/commands';
import type { Cmd } from './palette/layout';
import type { PaletteEntry } from './palette/sources';
import { ACCOUNT_SESSION, PAGES, type AccountSession, type PaletteContext, type PaletteHost, type ShortcutGroup } from './slots';

/** The workspace as the account's own name, beside NoClick's mark lined up with the sidebar's icons below. It leads
 *  to the app's home, the account at a glance. */
export function AccountName({ user, onNavigate }: { user: AccountMenuUser; onNavigate?: () => void }) {
    return (
        <Link to="/" onClick={onNavigate} className="flex min-w-0 items-center gap-1 rounded-xl py-1.5 transition-colors hover:bg-foreground/[0.05]">
            <LogoMark className="ml-[13px] h-[18px] w-[18px] shrink-0" alt="NoClick" />
            <span className="truncate px-1.5 text-[14px] font-semibold tracking-[-0.01em] text-foreground">{userDisplayName({ email: user.email, name: user.display_name }, 'NoClick')}</span>
        </Link>
    );
}

/** The account the app's key acts in, as the platform API reads it. */
function useStatus() {
    const client = useClient();
    return useV1('status', (signal) => readAccountStatus(client, signal), { client });
}

/** The account's plan as the platform API names it, and signing out of this app (forgetting what it kept of the
 *  account in this browser first). */
export const accountOnApp: AccountSession = {
    usePlan: () => useStatus().data?.plan?.name ?? null,
    useSignOut: () => {
        const account = useStatus().data?.account.id;
        return () => void signOut(account);
    },
};

// ── the command palette ─────────────────────────────────────────────────────

const APP_SHORTCUTS: ShortcutGroup[] = [
    {
        title: 'General',
        items: [
            { keys: ['mod', 'K'], label: 'Open command palette' },
            { keys: ['mod', '/'], label: 'Open keyboard shortcuts' },
            { keys: ['mod', '\\'], label: 'Toggle sidebar' },
            { keys: ['esc'], label: 'Close command palette' },
        ],
    },
];

/** A page's route in this app. */
export const pageRoute = (id: string) => `/${id}`;

/** Resources' route at one of its addresses (resourceAddress: a kind's list, an item). */
export function resourcesRoute(address: Record<string, string | null>): string {
    const params = Object.entries(address).filter((entry): entry is [string, string] => entry[1] !== null);
    return `${pageRoute('resources')}?${new URLSearchParams(params)}`;
}

/** Resources' route for one kind's list. */
export const kindRoute = (kind: KindId) => resourcesRoute(resourceAddress(kind));

/** The app's own commands: its served pages and Resources' kinds, what its pages handed over, a registered source's
 *  places and commands, the theme, the keyboard shortcuts and signing out. */
function useAppCommands(palette: PaletteContext): { commands: readonly Cmd[] } {
    const navigate = useNavigate();
    const served = useSlot(PAGES);
    const [theme, setTheme] = useTheme();
    const signOut = useSlot(ACCOUNT_SESSION).useSignOut();
    const { held, registered, showShortcuts } = palette;
    const commands = useMemo(() => {
        const pages: PaletteEntry[] = SHELL_PAGES.filter((page) => served.includes(page.id)).map((page) => ({
            id: `nav:${page.id}`,
            label: page.label,
            icon: page.icon,
            keywords: page.keywords,
            browse: true,
            run: () => navigate(pageRoute(page.id)),
        }));
        const kinds: PaletteEntry[] = served.includes('resources')
            ? KINDS.map((kind) => ({ id: `nav:resources:${kind.id}`, label: kind.label, context: 'Resources', icon: kind.icon, keywords: kind.keywords, about: kind.empty, run: () => navigate(kindRoute(kind.id)) }))
            : [];
        return [
            ...heldCommands(held),
            ...[...pages, ...kinds, ...registeredEntries(registered, false)].map(asCmd('Go to')),
            ...registeredEntries(registered, true).map(asCmd('Account')),
            ...themeCommands(theme, setTheme),
            shortcutsCommand(showShortcuts),
            signOutCommand(signOut),
        ];
    }, [navigate, served, held, registered, theme, setTheme, showShortcuts, signOut]);
    return { commands };
}

/** The palette as the open app has it: what it serves, and no category to narrow to. */
export const paletteOnApp: PaletteHost = { useCommands: useAppCommands, scopes: [], shortcuts: APP_SHORTCUTS };
