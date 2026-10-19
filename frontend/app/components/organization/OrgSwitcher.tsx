/**
 * Organization switcher dropdown component.
 * Shows current context (org name or username) and allows switching between organizations.
 * Uses useOrgContext for reactive state management - no page refresh needed on switch.
 */

import { useState, useEffect, useCallback, type ReactNode } from 'react';
import { ChevronDown, Plus, Check, Settings } from 'lucide-react';
import {
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuItem,
    DropdownMenuLabel,
    DropdownMenuSeparator,
    DropdownMenuTrigger,
} from '~/components/ui/dropdown-menu';
import { ACCOUNT_MENU_ITEM } from '~/components/nav/AccountMenu';
import { MENU_SEPARATOR, MENU_SURFACE } from '~/components/shell/menus';
import { useOrganization } from '~/hooks/useOrganization';
import { useOrgContext } from '~/hooks/useOrgContext';
import { useValtioState } from '~/hooks/useValtioState';
import { useCachedValtioState } from '~/hooks/useCachedValtioState';
import { CreateOrganizationModal } from './CreateOrganizationModal';
import { navigateToOrgSettings } from '~/lib/navigation';
import { cn } from '~/lib/utils';
import { LogoMark } from '~/components/shared/LogoMark';

interface OrgSwitcherProps {
    userEmail: string;
    /** Shown when there is no email (a phone-only account). */
    userLabel?: string;
    userAvatarUrl?: string;
    /** `sidebar`: the app sidebar's header, the mark and the workspace's name
     *  beside NoClick's mark (plan and avatar live with the account at its foot). */
    variant?: 'navbar' | 'sidebar';
}

interface UserOrg {
    id: string;
    name: string;
    slug: string;
    icon_url: string | null;
    subscription_tier: 'free' | 'plus' | 'pro' | 'enterprise';
    role: 'owner' | 'admin' | 'member';
    is_primary: boolean;
}

const ROLE_LABEL: Record<UserOrg['role'], string> = { owner: 'Owner', admin: 'Admin', member: 'Member' };
// The footer's icons sit in a tile-wide slot, so every row's text starts on one line.
const SLOT = 'grid h-7 w-7 shrink-0 place-items-center text-muted-foreground';

/** A personal workspace goes by its person's name; a phone-only account's label is its number, which is no name. */
function personalWorkspaceName(label: string): string {
    return !label || label.startsWith('+') ? 'Personal' : label;
}

/** "AR" for Acme Robotics; a one-word name (or an email) gives its first two letters, as the account avatar does. */
function tileInitials(name: string): string {
    const words = name.trim().split(/\s+/);
    return (words.length > 1 ? words[0][0] + words[1][0] : name.slice(0, 2)).toUpperCase();
}

/** A workspace's picture, or its initials on a neutral tile (never a brand colour); round for a person. */
export function WorkspaceTile({ name, iconUrl, round = false, className }: { name: string; iconUrl?: string | null; round?: boolean; className?: string }) {
    const box = cn('h-7 w-7 shrink-0', round ? 'rounded-full' : 'rounded-lg', className);
    return iconUrl ? (
        <img src={iconUrl} alt="" className={cn(box, 'object-cover')} referrerPolicy="no-referrer" />
    ) : (
        <span className={cn('grid place-items-center bg-foreground/[0.08] text-[11px] font-medium text-foreground/85 ring-1 ring-inset ring-foreground/[0.06]', box)}>
            {tileInitials(name)}
        </span>
    );
}

/** A workspace to switch to: its tile, its name over who you are in it, and a check on the one you're in. */
function WorkspaceItem({ tile, name, line, current, onSwitch }: { tile: ReactNode; name: string; line: string; current: boolean; onSwitch: () => void }) {
    return (
        <DropdownMenuItem
            onSelect={(e) => {
                e.preventDefault();
                if (!current) onSwitch();
            }}
            className={cn(ACCOUNT_MENU_ITEM, 'gap-2.5 py-1.5', current && 'cursor-default')}
        >
            {tile}
            <span className="min-w-0 flex-1">
                <span className="block truncate text-[14px] leading-5 text-foreground">{name}</span>
                <span className="block truncate text-[12px] leading-4 text-muted-foreground">{line}</span>
            </span>
            {current && <Check className="text-foreground" strokeWidth={2} />}
        </DropdownMenuItem>
    );
}

export function OrgSwitcher({ userEmail, userLabel, userAvatarUrl, variant = 'navbar' }: OrgSwitcherProps) {
    const { listMyOrganizations, switchOrganization, loading } =
        useOrganization();
    const [orgContext, setOrgContext] = useOrgContext();
    // Persist org list to IndexedDB so dropdown renders instantly on refresh (SWR pattern)
    const [organizations, setOrganizations] = useCachedValtioState<UserOrg[]>(
        'global',
        'my_organizations',
        [] as UserOrg[],
        true
    );
    const [isOpen, setIsOpen] = useState(false);
    const [createModalOpen, setCreateModalOpen] = useState(false);
    const [switching] = useState(false);

    // Extract username from email (part before @)
    const username = userEmail.split('@')[0] || userLabel || '';

    // Find current organization from list
    const currentOrg = organizations.find((org) => org.id === orgContext.id);

    // Display name: org name if in org, otherwise username
    const displayName = currentOrg?.name || username;

    // Get initials for avatar (first 2 chars)
    const getInitials = (name: string) => name.slice(0, 2).toUpperCase();

    // Fetch organizations on mount and sync context with the primary org
    useEffect(() => {
        const fetchOrgs = async () => {
            const orgs = await listMyOrganizations();
            if (orgs) {
                setOrganizations(orgs);

                // Sync context with primary org from backend (handles first load & ensures consistency)
                // listMyOrganizations excludes personal workspace orgs, so no primary = in personal workspace
                const primaryOrg = orgs.find((o) => o.is_primary);
                if (primaryOrg) {
                    // Only update if different to avoid unnecessary re-renders
                    if (
                        orgContext.id !== primaryOrg.id ||
                        orgContext.role !== primaryOrg.role ||
                        orgContext.subscription_tier !==
                            primaryOrg.subscription_tier
                    ) {
                        setOrgContext({
                            id: primaryOrg.id,
                            role: primaryOrg.role,
                            subscription_tier: primaryOrg.subscription_tier,
                            isPersonalWorkspace: false,
                        });
                    }
                } else if (
                    orgContext.id !== null ||
                    !orgContext.isPersonalWorkspace
                ) {
                    // No primary org from list = in personal workspace
                    setOrgContext({
                        id: null,
                        role: 'owner',
                        subscription_tier: null,
                        isPersonalWorkspace: true,
                    });
                }
            }
        };
        fetchOrgs();
        // eslint-disable-next-line react-hooks/exhaustive-deps -- orgContext excluded to prevent re-fetch loops (effect writes to it)
    }, [listMyOrganizations]);

    const handleSwitchOrg = useCallback(
        async (orgId: string) => {
            if (orgId === orgContext.id || switching) return;

            // Optimistic: update context immediately so UI switches instantly
            const targetOrg = organizations.find((o) => o.id === orgId);
            const prevContext = { ...orgContext };
            setOrgContext({
                id: orgId,
                role: targetOrg?.role || 'member',
                subscription_tier: targetOrg?.subscription_tier || 'free',
                isPersonalWorkspace: false,
            });
            setIsOpen(false);

            // Confirm with backend in background
            const success = await switchOrganization(orgId);
            if (!success) {
                // Rollback on failure
                setOrgContext(prevContext);
            }
        },
        [
            orgContext,
            switchOrganization,
            switching,
            organizations,
            setOrgContext,
        ]
    );

    const handleSwitchToPersonal = useCallback(async () => {
        if (!orgContext.id || switching) return;

        // Optimistic: update context immediately
        const prevContext = { ...orgContext };
        setOrgContext({
            id: null,
            role: 'owner',
            subscription_tier: null,
            isPersonalWorkspace: true,
        });
        setIsOpen(false);

        // Confirm with backend in background
        const success = await switchOrganization('');
        if (!success) {
            // Rollback on failure
            setOrgContext(prevContext);
        }
    }, [orgContext, switchOrganization, switching, setOrgContext]);

    // Read personal subscription tier (always from user_billing, regardless of org context)
    const [personalTier] = useValtioState<
        'free' | 'plus' | 'pro' | 'enterprise'
    >('global', 'personal_subscription_tier', 'free');

    // Effective tier: org tier if in org context, otherwise personal tier
    const effectiveTier = currentOrg?.subscription_tier || personalTier;

    // Current avatar: org icon in an organization, otherwise the user's avatar.
    const currentAvatar = currentOrg ? currentOrg.icon_url : userAvatarUrl;
    const currentInitials = currentOrg
        ? getInitials(currentOrg.name)
        : getInitials(username);

    const personalName = personalWorkspaceName(userLabel || username);
    const personalTile = (className?: string) => <WorkspaceTile name={userEmail || userLabel || ''} iconUrl={userAvatarUrl} round className={className} />;

    return (
        <div className={cn('flex items-center', variant === 'sidebar' ? 'min-w-0 gap-1' : 'gap-2')}>
            {/* The brand beside the workspace, its mark lined up with the sidebar's icons below. */}
            {variant === 'sidebar' && <LogoMark className="ml-[13px] h-[18px] w-[18px] shrink-0" alt="NoClick" />}
            {variant === 'navbar' && (
                <>
                    {/* Logo */}
                    <LogoMark className="w-5 h-5 flex-shrink-0" />

                    <span className="text-foreground/25 text-xl">/</span>
                </>
            )}

            {/* Dropdown trigger with avatar */}
            <DropdownMenu open={isOpen} onOpenChange={setIsOpen}>
                <DropdownMenuTrigger
                    asChild
                    disabled={
                        switching || (loading && organizations.length === 0)
                    }
                >
                    {variant === 'sidebar' ? (
                        <button
                            type="button"
                            title={currentOrg?.name ?? personalName}
                            className={cn(
                                'group flex h-10 min-w-0 items-center gap-2 rounded-xl px-1.5 text-foreground transition-colors hover:bg-foreground/[0.05] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring data-[state=open]:bg-foreground/[0.05]',
                                (switching || (loading && organizations.length === 0)) && 'cursor-not-allowed opacity-50'
                            )}
                        >
                            {currentOrg ? <WorkspaceTile name={currentOrg.name} iconUrl={currentOrg.icon_url} className="h-6 w-6 rounded-md text-[10px]" /> : personalTile('h-6 w-6 text-[10px]')}
                            <span className="truncate text-[14px] font-semibold tracking-[-0.01em]">{currentOrg?.name ?? personalName}</span>
                            <ChevronDown className={cn('-ml-1 h-3 w-3 shrink-0 text-muted-foreground transition-transform duration-150', isOpen && 'rotate-180')} />
                        </button>
                    ) : (
                        <button
                            className={cn(
                                'flex items-center gap-2 py-1 transition-all duration-150',
                                'text-foreground hover:text-foreground',
                                'focus:outline-none focus-visible:outline-none',
                                (switching ||
                                    (loading && organizations.length === 0)) &&
                                    'opacity-50 cursor-not-allowed'
                            )}
                        >
                            {/* Avatar */}
                            {currentAvatar ? (
                                <img
                                    src={currentAvatar}
                                    alt=""
                                    className="w-6 h-6 rounded-full object-cover flex-shrink-0"
                                    referrerPolicy="no-referrer"
                                />
                            ) : (
                                <div
                                    className={cn(
                                        'w-6 h-6 rounded-full flex items-center justify-center text-[10px] font-medium flex-shrink-0',
                                        currentOrg
                                            ? 'bg-blue-500/20 text-blue-600 dark:text-blue-400'
                                            : 'bg-foreground/10 text-muted-foreground dark:text-white/60'
                                    )}
                                >
                                    {currentInitials}
                                </div>
                            )}
                            <div className="flex flex-col items-start">
                                <span className="text-sm font-medium max-w-[120px] truncate leading-tight">
                                    {displayName}
                                </span>
                                <span
                                    className={cn(
                                        'text-[10px] font-medium capitalize tracking-wide leading-tight',
                                        effectiveTier === 'enterprise' &&
                                            'text-purple-600/80 dark:text-purple-400/80',
                                        effectiveTier === 'pro' &&
                                            'text-blue-600/80 dark:text-blue-400/80',
                                        effectiveTier === 'plus' &&
                                            'text-amber-600/80 dark:text-amber-400/80',
                                        effectiveTier === 'free' &&
                                            'text-foreground/35'
                                    )}
                                >
                                    {effectiveTier}
                                </span>
                            </div>
                            <ChevronDown
                                className={cn(
                                    'w-3 h-3 text-foreground/40 transition-transform duration-150',
                                    isOpen && 'rotate-180'
                                )}
                            />
                        </button>
                    )}
                </DropdownMenuTrigger>

                <DropdownMenuContent align="start" sideOffset={8} onCloseAutoFocus={(e) => e.preventDefault()} className={cn('w-72 rounded-2xl p-1.5 duration-100', MENU_SURFACE)}>
                    <DropdownMenuLabel className="px-2 pb-1 pt-1.5 text-[12px] font-medium text-muted-foreground">Workspaces</DropdownMenuLabel>
                    <WorkspaceItem
                        tile={personalTile()}
                        name={personalName}
                        line="Personal workspace"
                        current={!orgContext.id}
                        onSwitch={handleSwitchToPersonal}
                    />
                    {organizations.map((org) => (
                        <WorkspaceItem
                            key={org.id}
                            tile={<WorkspaceTile name={org.name} iconUrl={org.icon_url} />}
                            name={org.name}
                            line={ROLE_LABEL[org.role]}
                            current={org.id === orgContext.id}
                            onSwitch={() => handleSwitchOrg(org.id)}
                        />
                    ))}
                    <DropdownMenuSeparator className={MENU_SEPARATOR} />
                    <DropdownMenuItem
                        className={cn(ACCOUNT_MENU_ITEM, 'gap-2.5')}
                        onClick={() => {
                            setIsOpen(false);
                            setCreateModalOpen(true);
                        }}
                    >
                        <span className={SLOT}>
                            <Plus />
                        </span>
                        New workspace
                    </DropdownMenuItem>
                    <DropdownMenuItem
                        className={cn(ACCOUNT_MENU_ITEM, 'gap-2.5')}
                        onClick={() => {
                            setIsOpen(false);
                            navigateToOrgSettings();
                        }}
                    >
                        <span className={SLOT}>
                            <Settings />
                        </span>
                        Workspace settings
                    </DropdownMenuItem>
                </DropdownMenuContent>
            </DropdownMenu>

            <CreateOrganizationModal
                open={createModalOpen}
                onOpenChange={setCreateModalOpen}
            />
        </div>
    );
}
