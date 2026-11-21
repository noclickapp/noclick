// The accounts on one Connections tab (yours, your workspace's, or shared with you) as the tiles the catalog uses: each
// account's mark, whose it is, what keeps it from working (a check this session counts too) and the way to reconnect it.
import type { ReactNode } from 'react';
import { useSlot } from '@/slots';
import { fuzzyFilter } from '@/lib/fuzzySearch';
import { movedFrom } from '@/lib/movedFrom';
import { BrandIcon } from '@/ui/BrandIcon';
import { CONNECTION_MARK } from '@/ui/slots';
import { TILE_GRID, TileSkeletons } from '@/ui/Tile';
import { cn } from '@/ui/utils';
import { AccountTile as Tile, NoAccounts } from './AccountTile';
import type { AccountCredential, ConnectedAccount } from './model';
import { lastConnectionProbe } from './probe';
import type { AccountSource } from './views';

/** An account's mark: its app's glyph, else its AI company's, as whoever draws marks has them. */
export function AccountMark({ credential, size = 'md' }: { credential: Pick<AccountCredential, 'credential_type' | 'metadata' | 'revoked_at'>; size?: 'md' | 'lg' }) {
    const { Icon, iconColor } = useSlot(CONNECTION_MARK).accountGlyph(credential);
    return (
        <span
            className={cn(
                'grid shrink-0 place-items-center bg-foreground/[0.05]',
                size === 'lg' ? 'h-12 w-12 rounded-2xl ring-1 ring-inset ring-foreground/[0.06]' : 'h-10 w-10 rounded-xl',
                credential.revoked_at && 'opacity-50'
            )}
        >
            <BrandIcon Icon={Icon} iconColor={iconColor} className={size === 'lg' ? 'h-6 w-6' : 'h-[22px] w-[22px]'} />
        </span>
    );
}

/** Whose the account is, when it isn't yours. */
export function sourceLine(account: Pick<ConnectedAccount, 'source' | 'credential'>): string | null {
    const c = account.credential;
    if (account.source === 'shared') return `Shared by ${c.shared_by_name || c.shared_by_email || 'a teammate'}`;
    if (account.source === 'organization') return 'Your organization';
    return null;
}

/** `trailing` and `badge` replace the tile's own Reconnect and add beside its name, for a reader who only looks. */
export function AccountTile({ account, onOpen, trailing, badge }: { account: ConnectedAccount; onOpen: () => void; trailing?: ReactNode; badge?: ReactNode }) {
    const { credential, app } = account;
    // A check run earlier this session counts too: the provider refusing it is as definitive as a revocation.
    const probe = lastConnectionProbe(credential.id);
    const problem = account.problem ?? (probe?.status === 'done' && probe.result.reachable === false ? `${app} turned it down` : undefined);
    return (
        <Tile
            account={{
                app,
                line: account.line,
                sharer: account.source === 'shared' ? credential.shared_by_name || credential.shared_by_email : null,
                // One an agent's move brought over says so, so it's found to take its access away.
                movedFrom: movedFrom(credential.metadata?.moved_from),
                problem,
            }}
            mark={<AccountMark credential={credential} />}
            onOpen={onOpen}
            // Only its owner reconnects an account.
            onReconnect={account.source === 'connected' ? account.reconnect : undefined}
            trailing={trailing}
            badge={badge}
        />
    );
}

export function ConnectedList({
    accounts,
    source,
    query,
    loaded,
    onOpen,
    onBrowse,
}: {
    /** This tab's accounts. */
    accounts: ConnectedAccount[];
    source: AccountSource;
    query: string;
    loaded: boolean;
    onOpen: (accountId: string) => void;
    onBrowse: () => void;
}) {
    if (!accounts.length) {
        if (!loaded) return <TileSkeletons count={6} />;
        return <NoAccounts source={source} onBrowse={onBrowse} />;
    }
    const shown = fuzzyFilter(accounts, query, (a) => [
        { text: a.app.toLowerCase(), weight: 1, fuzzy: true },
        ...(a.aliases ?? []).map((alias) => ({ text: alias.toLowerCase(), weight: 1, fuzzy: true })),
        { text: a.line.toLowerCase(), weight: 0.9, fuzzy: true },
        { text: a.credential.name.toLowerCase(), weight: 0.8, fuzzy: true },
        { text: (a.credential.shared_by_name || a.credential.shared_by_email || '').toLowerCase(), weight: 0.5, fuzzy: false },
    ]);
    if (!shown.length) return <p className="py-16 text-center text-[14px] text-muted-foreground">No account matches “{query.trim()}”.</p>;
    return (
        <div className={TILE_GRID} data-testid="connected-accounts">
            {shown.map((account) => (
                <AccountTile key={account.credential.id} account={account} onOpen={() => onOpen(account.credential.id)} />
            ))}
        </div>
    );
}
