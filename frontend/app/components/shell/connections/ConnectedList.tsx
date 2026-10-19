// The accounts on one Connections tab (yours, your organization's, or shared
// with you) as the same tiles the app catalog uses: the app, then the account
// in words you'd recognise. A broken account says what's wrong and puts
// Reconnect in reach; any tile opens the account.
import { Building2, ChevronRight, Plug, Users, type LucideIcon } from 'lucide-react';
import { BrandIcon } from '~/components/shared/BrandIcon';
import { openCreateCredential } from '~/components/shared/popups/CreateCredentialDialog';
import type { CredentialInfo } from '~/types/socket-events.generated';
import { getCredentialIcon } from '~/utils/credentialIcons';
import { fuzzyFilter } from '~/utils/fuzzySearch';
import { lastConnectionProbe } from '~/hooks/useConnectionProbe';
import { cn } from '~/lib/utils';
import { BUTTON_PRIMARY } from '../buttons';
import type { AccountSource, ConnectedAccount } from './accounts';
import { agentMark } from './aiAccounts';
import { TILE_GRID, Tile, TileSkeletons } from '../Tile';

/** An account's glyph: its app's icon, or (an agent key with none registered) its provider's rather than a generic key. */
export function accountIcon(credential: CredentialInfo) {
    const registered = getCredentialIcon(credential.credential_type, credential.metadata);
    const agent = registered.hasServiceIcon ? undefined : agentMark(credential.credential_type);
    const hasServiceIcon = registered.hasServiceIcon || !!agent;
    return {
        Icon: agent?.Icon ?? registered.Icon,
        iconColor: (agent ? agent.iconColor : registered.iconColor) || (hasServiceIcon ? 'text-foreground' : 'text-muted-foreground'),
    };
}

export function AccountMark({ credential, size = 'md' }: { credential: CredentialInfo; size?: 'md' | 'lg' }) {
    const { Icon, iconColor } = accountIcon(credential);
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
export function sourceLine(account: ConnectedAccount): string | null {
    const c = account.credential;
    if (account.source === 'shared') return `Shared by ${c.shared_by_name || c.shared_by_email || 'a teammate'}`;
    if (account.source === 'organization') return 'Your organization';
    return null;
}

export function reconnect(credential: CredentialInfo) {
    openCreateCredential({ credentialType: credential.credential_type, credentialId: credential.id, reconnect: true });
}

export function AccountTile({ account, onOpen }: { account: ConnectedAccount; onOpen: () => void }) {
    const { credential, app } = account;
    // A check run earlier this session counts too: the provider refusing it is as definitive as a revocation.
    const probe = lastConnectionProbe(credential.id);
    const problem = account.problem ?? (probe?.status === 'done' && probe.result.reachable === false ? `${app} turned it down` : undefined);
    const sharer = account.source === 'shared' ? credential.shared_by_name || credential.shared_by_email : null;
    return (
        <Tile
            mark={<AccountMark credential={credential} />}
            title={app}
            detail={problem ? <span className="text-red-600 dark:text-red-400">{problem}</span> : sharer ? `${sharer} · ${account.line}` : account.line}
            label={`${app}, ${account.line}`}
            onOpen={onOpen}
            testId="connected-account"
            trailing={
                problem && account.source === 'connected' ? (
                    <button
                        type="button"
                        onClick={(event) => {
                            event.stopPropagation();
                            reconnect(credential);
                        }}
                        className="inline-flex h-8 shrink-0 items-center rounded-full bg-primary px-3.5 text-[13px] font-medium text-primary-foreground transition-opacity hover:opacity-90 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                    >
                        Reconnect
                    </button>
                ) : (
                    <ChevronRight className="h-4 w-4 shrink-0 text-transparent transition-colors group-hover:text-muted-foreground group-focus-visible:text-muted-foreground" />
                )
            }
        />
    );
}

const EMPTY: Record<AccountSource, { icon: LucideIcon; title: string; body: string }> = {
    connected: { icon: Plug, title: 'No accounts yet', body: 'Connect an app and your agents and automations can act in it.' },
    shared: { icon: Users, title: 'Nothing shared with you yet', body: 'When a teammate shares an account with you, it shows up here, ready for your automations.' },
    organization: { icon: Building2, title: 'Nothing shared with your organization', body: 'Accounts shared with everyone in your organization show up here.' },
};

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
    onOpen: (credentialId: string) => void;
    onBrowse: () => void;
}) {
    if (!accounts.length) {
        if (!loaded) return <TileSkeletons count={6} />;
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
    const shown = fuzzyFilter(accounts, query, (a) => [
        { text: a.app.toLowerCase(), weight: 1, fuzzy: true },
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
