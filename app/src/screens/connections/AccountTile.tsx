// A connected account as Connections' tabs list it: the app, then the account in words you'd recognise, whose it
// is and the computer an agent's move brought it from. A broken one says what's wrong and puts Reconnect in reach;
// any tile opens the account. And what a tab says while it holds none.
import type { ReactNode } from 'react';
import { Building2, ChevronRight, Plug, Users, type LucideIcon } from 'lucide-react';
import type { MovedFrom } from '@/lib/movedFrom';
import { BUTTON_PRIMARY } from '@/ui/buttons';
import { Tile } from '@/ui/Tile';
import { cn } from '@/ui/utils';
import type { AccountSource } from './views';

/** What a tile says of an account. */
export interface AccountFacts {
    /** Its app, else its kind of key. */
    app: string;
    /** What tells it apart from another of its app's: its login or email, else its name or when it was added. */
    line: string;
    /** Who shared it, where it's shared with you. */
    sharer?: string | null;
    /** The computer an agent's move brought it from. */
    movedFrom?: MovedFrom | null;
    /** What keeps it from working, when something is known to. */
    problem?: string;
}

/** `onReconnect` puts Reconnect on a broken account's tile (one only its owner reconnects has none); `trailing` and
 *  `badge` replace the tile's own action and add beside its name, for a reader who only looks. */
export function AccountTile({
    account,
    mark,
    onOpen,
    onReconnect,
    trailing,
    badge,
}: {
    account: AccountFacts;
    mark: ReactNode;
    onOpen: () => void;
    onReconnect?: () => void;
    trailing?: ReactNode;
    badge?: ReactNode;
}) {
    const { app, line, sharer, movedFrom, problem } = account;
    return (
        <Tile
            mark={mark}
            title={app}
            detail={problem ? <span className="text-red-600 dark:text-red-400">{problem}</span> : [sharer, line, movedFrom ? `moved from ${movedFrom.host ?? 'a computer'}` : null].filter(Boolean).join(' · ')}
            badge={badge}
            label={`${app}, ${line}`}
            onOpen={onOpen}
            testId="connected-account"
            trailing={
                trailing ??
                (problem && onReconnect ? (
                    <button
                        type="button"
                        onClick={(event) => {
                            event.stopPropagation();
                            onReconnect();
                        }}
                        className="inline-flex h-8 shrink-0 items-center rounded-full bg-primary px-3.5 text-[13px] font-medium text-primary-foreground transition-opacity hover:opacity-90 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                    >
                        Reconnect
                    </button>
                ) : (
                    <ChevronRight className="h-4 w-4 shrink-0 text-transparent transition-colors group-hover:text-muted-foreground group-focus-visible:text-muted-foreground" />
                ))
            }
        />
    );
}

const EMPTY: Record<AccountSource, { icon: LucideIcon; title: string; body: string }> = {
    connected: { icon: Plug, title: 'No accounts yet', body: 'Connect an app and your agents and automations can act in it.' },
    shared: { icon: Users, title: 'Nothing shared with you yet', body: 'When a teammate shares an account with you, it shows up here, ready for your automations.' },
    organization: { icon: Building2, title: 'Nothing shared with your organization', body: 'Accounts shared with everyone in your organization show up here.' },
};

/** A tab with no accounts on it; yours offers the catalog. */
export function NoAccounts({ source, onBrowse }: { source: AccountSource; onBrowse: () => void }) {
    const empty = EMPTY[source];
    const Icon = empty.icon;
    return (
        <div className="flex flex-col items-center px-6 py-20 text-center">
            <span className="grid h-12 w-12 place-items-center rounded-2xl bg-foreground/[0.05] ring-1 ring-inset ring-foreground/[0.06]">
                <Icon className="h-5 w-5 text-foreground/70" strokeWidth={1.75} />
            </span>
            <p className="mt-4 text-[15px] font-medium text-foreground">{empty.title}</p>
            <p className="mt-1 max-w-sm text-balance text-[14px] text-muted-foreground">{empty.body}</p>
            {source === 'connected' && (
                <button type="button" onClick={onBrowse} className={cn(BUTTON_PRIMARY, 'mt-5')}>
                    Browse apps
                </button>
            )}
        </div>
    );
}
