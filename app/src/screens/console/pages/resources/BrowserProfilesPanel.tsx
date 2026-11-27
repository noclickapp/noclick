// Browser profiles: one person's sign-ins, which its user's browsers and
// agents browse with. The drawer (`?profile=`) says when it was last used, lists the sites it is signed
// in to (each can be forgotten), asks a person to sign in to another in a live
// browser, shows recent browser sessions (live ones link to the live view), and
// deletes the profile.
import { useEffect, useState } from 'react';
import { ArrowUpRight } from 'lucide-react';
import { HAIRLINE } from '@/ui/primitives';
import { cn } from '@/ui/utils';
import { Browser, BrowserProfile, NO_USER } from 'noclick';
import { NEW_SNIPPETS } from '@/screens/console/lib/snippets';
import type { StatusLook } from '@/screens/console/lib/status';
import { defaultWriteUser, userLabel } from '@/screens/console/lib/userFilter';
import { useConsole } from '@/screens/console/hooks/useConsole';
import { usePaged } from '@/sdk/usePaged';
import { invalidateV1, useV1 } from '@/sdk/useV1';
import { useSearchParam } from '@/screens/console/hooks/useQueryState';
import { recordRecent } from '@/screens/console/hooks/useRecent';
import { DataTable, type Column } from '../../ui/DataTable';
import { Drawer } from '../../ui/Drawer';
import { Folded, HeaderNote } from '../../ui/DrawerParts';
import { EmptyCode } from '../../ui/EmptyCode';
import { ErrorPanel } from '../../ui/ErrorPanel';
import { Money } from '../../ui/Money';
import { StatusPill } from '../../ui/StatusPill';
import { TimeCell } from '../../ui/TimeCell';
import { useAgentNames } from '../lookups';
import { ForgetSite, SignInToSite } from './BrowserDialogs';
import { NewInCode } from '../../NewInCode';
import { ConfirmAction, Field, PanelToolbar, Section, type PanelProps } from './shared';

/** How many recent sessions the drawer shows. */
const RECENT_SESSIONS = 5;

export function browserStatus(status: string): StatusLook {
    switch (status) {
        case 'starting':
            return { label: 'Starting', glyph: 'hollow', tone: 'ink' };
        case 'running':
            return { label: 'Running', glyph: 'live', tone: 'ink' };
        case 'closed':
            return { label: 'Closed', glyph: 'muted', tone: 'muted' };
        case 'failed':
            return { label: 'Failed', glyph: 'cross', tone: 'failure' };
        default:
            return { label: status, glyph: 'hollow', tone: 'muted' };
    }
}

function SiteRow({
    profile,
    domain,
    signedInAt,
    signedInBy,
    lastUsedAt,
    onForgotten,
}: {
    profile: BrowserProfile;
    domain: string;
    signedInAt: Date | null;
    /** Who is asked to sign in again when the site signs the profile out (designed). */
    signedInBy: string | null;
    lastUsedAt: Date | null;
    onForgotten: () => void;
}) {
    return (
        <li className={cn('flex items-center gap-3 px-3 py-2 text-[13px]')}>
            <span className="flex min-w-0 flex-1 flex-col">
                <span className="truncate font-mono text-[12px] text-foreground">{domain}</span>
                <span className="text-[12px] text-muted-foreground">
                    Signed in <TimeCell value={signedInAt} />
                    {signedInBy && <> by {signedInBy}</>}
                    {' · '}
                    {lastUsedAt ? (
                        <>
                            used <TimeCell value={lastUsedAt} />
                        </>
                    ) : (
                        'not used yet'
                    )}
                </span>
            </span>
            <ForgetSite profile={profile} domain={domain} onForgotten={onForgotten} />
        </li>
    );
}

function Sessions({ profile }: { profile: BrowserProfile }) {
    const { client } = useConsole();
    const agents = useAgentNames();
    const sessions = useV1(`browsers?profile=${profile.id}`, () =>
        Browser.listPage({ client, profile: profile.id, userFilter: profile.userId ?? NO_USER, limit: RECENT_SESSIONS })
    );
    return (
        <Section title="Recent sessions">
            {sessions.error !== undefined && !sessions.data ? (
                <ErrorPanel error={sessions.error} onRetry={() => void sessions.refresh()} />
            ) : !sessions.data ? (
                <div aria-busy className="h-16 animate-pulse rounded-lg bg-foreground/[0.04]" />
            ) : sessions.data.data.length ? (
                <ul aria-label="Recent sessions" className={'m-0 -mx-3 list-none p-0'}>
                    {sessions.data.data.map((b) => (
                        <li key={b.id} className={cn('flex items-center gap-3 px-3 py-2 text-[13px]')}>
                            <StatusPill look={browserStatus(b.status)} className="w-[5.5rem] shrink-0" />
                            <span className="flex min-w-0 flex-1 flex-col">
                                <span className="truncate" title={b.url ?? undefined}>
                                    {b.title || b.url || 'Blank page'}
                                </span>
                                <span className="truncate text-[12px] text-muted-foreground">
                                    {b.agentId ? (agents.get(b.agentId)?.name ?? b.agentId) : 'Your code'} · <TimeCell value={b.createdAt} />
                                </span>
                            </span>
                            {b.status === 'running' && b.liveUrl ? (
                                <a href={b.liveUrl} target="_blank" rel="noopener noreferrer" className="inline-flex shrink-0 items-center gap-1 text-[13px] font-medium text-foreground underline-offset-2 hover:underline">
                                    Watch live
                                    <ArrowUpRight className="h-3.5 w-3.5" />
                                </a>
                            ) : (
                                <Money usd={b.costUsd} className="shrink-0 text-muted-foreground" />
                            )}
                        </li>
                    ))}
                </ul>
            ) : (
                <p className="m-0 text-[13px] text-muted-foreground">No browser has used this profile yet.</p>
            )}
        </Section>
    );
}

function ProfileDrawer({ profileId, row, onClose }: { profileId: string | null; row?: BrowserProfile; onClose: () => void }) {
    const { client } = useConsole();
    const fetched = useV1(profileId && !row ? `browser_profiles/${profileId}` : null, () => BrowserProfile.get(profileId!, { client }));
    // Forgetting a site changes the profile in place: keep that object over a refetched row, and re-render.
    const [updated, setUpdated] = useState<BrowserProfile | null>(null);
    const [, setVersion] = useState(0);
    const profile = (updated?.id === profileId ? updated : null) ?? row ?? fetched.data;
    useEffect(() => {
        if (profile) recordRecent({ type: 'browser_profile', id: profile.id, label: profile.name, path: 'resources/browser-profiles', params: { profile: profile.id } });
    }, [profile?.id]); // eslint-disable-line react-hooks/exhaustive-deps
    const sites = profile?.sites ?? [];
    return (
        <Drawer
            open={profileId !== null}
            onOpenChange={(o) => !o && onClose()}
            kind="Browser profile"
            title={profile ? <span className="font-mono">{profile.name}</span> : undefined}
            id={profileId ?? undefined}
            status={
                profile ? (
                    <HeaderNote>
                        {sites.length ? `Signed in to ${sites.length === 1 ? '1 site' : `${sites.length} sites`}` : 'Signed in nowhere yet'} · last used <TimeCell value={profile.lastUsedAt} empty="never" />
                    </HeaderNote>
                ) : undefined
            }
            footer={
                profile ? (
                    <ConfirmAction
                        label="Delete profile"
                        title={`Delete ${profile.name}?`}
                        description="Every sign-in in it is deleted. Agents that browse with it are signed out of those sites until the person signs in to a new profile."
                        confirmLabel="Delete profile"
                        onConfirm={async () => {
                            await profile.delete();
                            invalidateV1('browser_profiles');
                            invalidateV1('account');
                            onClose();
                        }}
                    />
                ) : undefined
            }
        >
            {!profile && fetched.error !== undefined && <ErrorPanel error={fetched.error} onRetry={() => void fetched.refresh()} />}
            {profile && (
                <div className="flex flex-col gap-6">
                    <Section title="Signed in to">
                        {sites.length ? (
                            <ul aria-label="Signed in to" className={cn('m-0 -mx-3 mb-2 list-none p-0', HAIRLINE)}>
                                {sites.map((s) => (
                                    <SiteRow
                                        key={s.domain}
                                        profile={profile}
                                        domain={s.domain}
                                        signedInAt={s.signedInAt}
                                        signedInBy={s.signedInBy}
                                        lastUsedAt={s.lastUsedAt}
                                        onForgotten={() => {
                                            setUpdated(profile);
                                            setVersion((v) => v + 1);
                                            invalidateV1('browser_profiles');
                                        }}
                                    />
                                ))}
                            </ul>
                        ) : (
                            <p className="m-0 mb-2 text-[13px] text-muted-foreground">Not signed in anywhere yet.</p>
                        )}
                        <SignInToSite profile={profile} />
                    </Section>
                    <Sessions profile={profile} />
                    <Folded title="Details: its user, when it was made">
                        <dl className="m-0">
                            <Field label="User">{userLabel(profile.userId)}</Field>
                            <Field label="Created">
                                <TimeCell value={profile.createdAt} tier="absolute" />
                            </Field>
                        </dl>
                        <p className="m-0 text-[12px] text-muted-foreground">
                            {"A profile counts as a credential: it's kept encrypted with its user, never exported, and used only by that user's browsers and agents."}
                        </p>
                    </Folded>
                </div>
            )}
        </Drawer>
    );
}

function SitesCell({ profile }: { profile: BrowserProfile }) {
    const sites = profile.sites;
    if (!sites.length) return <span className="text-muted-foreground">None yet</span>;
    return (
        <span className="flex min-w-0 items-baseline gap-1.5">
            <span className="truncate font-mono text-[12px]">{sites[0].domain}</span>
            {sites.length > 1 && <span className="shrink-0 text-[12px] text-muted-foreground">+{sites.length - 1} more</span>}
        </span>
    );
}

export function BrowserProfilesPanel({ user, setUser }: PanelProps) {
    const { client } = useConsole();
    const [profileId, setProfile] = useSearchParam('profile');
    const paged = usePaged(`browser_profiles?${user}`, (cursor) => BrowserProfile.listPage({ client, userFilter: user, cursor, limit: 50 }), (p) => p.id);
    const columns: Column<BrowserProfile>[] = [
        { id: 'name', header: 'Name', cell: (p) => <span className="truncate font-medium text-foreground">{p.name}</span> },
        { id: 'sites', header: 'Signed in to', priority: 2, cell: (p) => <SitesCell profile={p} /> },
        {
            id: 'user',
            header: 'User',
            priority: 2,
            width: '8rem',
            cell: (p) => <span className={p.userId ? 'text-foreground/85' : 'text-muted-foreground'}>{userLabel(p.userId)}</span>,
        },
        { id: 'used', header: 'Last used', width: '7rem', cell: (p) => <TimeCell value={p.lastUsedAt} empty="Never" /> },
    ];
    return (
        <>
            <PanelToolbar
                user={user}
                setUser={setUser}
                action={<NewInCode kind="browser-profile" place={{ user: defaultWriteUser(user) }} label="New profile" />}
            />
            <DataTable
                rowMenu="profile"
                label="Browser profiles"
                columns={columns}
                rows={paged.rows}
                getRowId={(p) => p.id}
                loading={paged.loading}
                error={paged.error}
                onRetry={() => void paged.refresh()}
                onRowClick={(p) => setProfile(p.id, { push: true })}
                selectedId={profileId}
                nextCursor={paged.nextCursor}
                onLoadMore={() => void paged.loadMore()}
                loadingMore={paged.loadingMore}
                empty={
                    <EmptyCode
                        title="No browser profiles yet."
                        hint="A person signs in to a site once, in a live browser; your agents then use the site as them."
                        snippet={NEW_SNIPPETS['browser-profile']({ user: defaultWriteUser(user) })}
                    />
                }
            />
            <ProfileDrawer profileId={profileId} row={paged.rows.find((p) => p.id === profileId)} onClose={() => setProfile(null)} />
        </>
    );
}
