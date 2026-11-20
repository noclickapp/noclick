// The app's frame with its sidebar and its ⌘K palette: the one shell every app built on these screens draws its pages
// in. Where each page lives is the host's, handed in as `places`: this app's are routes (src/routes/shell.tsx), NoClick's
// own app keeps its `?tab=` addresses. What the host keeps in the frame (a workspace switcher, a balance, a banner)
// fills the shell's slots (slots.ts).
import type { KindId } from '@/screens/resources/kinds';
import type { AccountMenuUser } from '@/ui/accountParts';
import { AppShell, type AppShellProps } from './AppShell';
import { CommandPalette } from './palette/CommandPalette';
import { openCommandPalette } from './palette/open';
import { ShellSidebarContent } from './ShellSidebar';

/** Where the host's pages are: which is open, and how to go to one. */
export interface ShellPlaces {
    /** The page open now: one of the shell's by its id, or a host's own (none marked). */
    current: string;
    /** Goes to a page: one of the shell's, or one of the host's own (its staff's). */
    go: (page: string) => void;
    /** Goes to Resources' overview (null) or one kind's list. */
    goKind: (kind: KindId | null) => void;
}

export interface AppFrameProps extends Omit<AppShellProps, 'sidebar'> {
    /** The account at the sidebar's foot. */
    user: AccountMenuUser;
    places: ShellPlaces;
}

export function AppFrame({ user, places, ...frame }: AppFrameProps) {
    return (
        <>
            <CommandPalette />
            <AppShell
                {...frame}
                sidebar={(at) => (
                    <ShellSidebarContent
                        {...at}
                        user={user}
                        onSearch={() => openCommandPalette()}
                        builder={frame.builderToggle}
                        current={places.current}
                        onPage={places.go}
                        onKind={places.goKind}
                    />
                )}
            />
        </>
    );
}
