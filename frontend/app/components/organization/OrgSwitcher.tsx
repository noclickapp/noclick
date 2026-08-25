/**
 * Organization switcher dropdown component.
 * Shows current context (org name or username) and allows switching between organizations.
 * Uses useOrgContext for reactive state management - no page refresh needed on switch.
 */

import { useState, useEffect, useCallback } from 'react';
import { ChevronDown, Plus, Check, Settings, UserPlus } from 'lucide-react';
import {
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuItem,
    DropdownMenuSeparator,
    DropdownMenuTrigger,
} from '~/components/ui/dropdown-menu';
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
    userAvatarUrl?: string;
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

export function OrgSwitcher({ userEmail, userAvatarUrl }: OrgSwitcherProps) {
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
    const [switching, setSwitching] = useState(false);

    // Extract username from email (part before @)
    const username = userEmail.split('@')[0];

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

    return (
        <div className="flex items-center gap-2">
            {/* Logo */}
            <LogoMark className="w-5 h-5 flex-shrink-0" />

            <span className="text-foreground/25 text-xl">/</span>

            {/* Dropdown trigger with avatar */}
            <DropdownMenu open={isOpen} onOpenChange={setIsOpen}>
                <DropdownMenuTrigger
                    asChild
                    disabled={
                        switching || (loading && organizations.length === 0)
                    }
                >
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
                </DropdownMenuTrigger>

                <DropdownMenuContent
                    align="start"
                    sideOffset={8}
                    onCloseAutoFocus={(e) => e.preventDefault()}
                    className={cn(
                        'min-w-[220px] p-1.5',
                        'bg-popover/[0.98] dark:bg-zinc-900/98 backdrop-blur-xl',
                        'border border-border dark:border-white/10',
                        'shadow-xl dark:shadow-black/40',
                        'rounded-lg'
                    )}
                >
                    {/* Personal workspace */}
                    <DropdownMenuItem
                        onSelect={(e) => {
                            e.preventDefault();
                            if (orgContext.id && !switching) {
                                handleSwitchToPersonal();
                            }
                        }}
                        className={cn(
                            'flex items-center gap-3 px-2.5 py-2 rounded-md',
                            'transition-colors duration-100',
                            !orgContext.id
                                ? 'bg-foreground/10 cursor-default'
                                : 'cursor-pointer hover:bg-foreground/[0.04]',
                            'focus:bg-foreground/[0.06]'
                        )}
                    >
                        {userAvatarUrl ? (
                            <img
                                src={userAvatarUrl}
                                alt=""
                                className="w-6 h-6 rounded-full object-cover"
                                referrerPolicy="no-referrer"
                            />
                        ) : (
                            <div
                                className={cn(
                                    'w-6 h-6 rounded-full flex items-center justify-center text-[10px] font-medium',
                                    !orgContext.id
                                        ? 'bg-foreground/15 text-foreground'
                                        : 'bg-foreground/10 text-foreground/70'
                                )}
                            >
                                {getInitials(username)}
                            </div>
                        )}
                        <span
                            className={cn(
                                'text-sm flex-1 truncate font-medium',
                                !orgContext.id
                                    ? 'text-foreground'
                                    : 'text-muted-foreground dark:text-white/60'
                            )}
                        >
                            {username}
                        </span>
                        {!orgContext.id && (
                            <Check className="w-4 h-4 text-muted-foreground dark:text-white/70" />
                        )}
                    </DropdownMenuItem>

                    {/* Organizations */}
                    {organizations.length > 0 && (
                        <>
                            <DropdownMenuSeparator className="my-1.5 bg-foreground/[0.06]" />

                            {organizations.map((org) => (
                                <DropdownMenuItem
                                    key={org.id}
                                    onSelect={(e) => {
                                        e.preventDefault();
                                        if (
                                            org.id !== orgContext.id &&
                                            !switching
                                        ) {
                                            handleSwitchOrg(org.id);
                                        }
                                    }}
                                    className={cn(
                                        'flex items-center gap-3 px-2.5 py-2 rounded-md',
                                        'transition-colors duration-100',
                                        org.id === orgContext.id
                                            ? 'bg-foreground/10 cursor-default'
                                            : 'cursor-pointer hover:bg-foreground/[0.04]',
                                        'focus:bg-foreground/[0.06]'
                                    )}
                                >
                                    {org.icon_url ? (
                                        <img
                                            src={org.icon_url}
                                            alt={org.name}
                                            className="w-6 h-6 rounded-full object-cover"
                                        />
                                    ) : (
                                        <div
                                            className={cn(
                                                'w-6 h-6 rounded-full flex items-center justify-center text-[10px] font-medium',
                                                org.id === orgContext.id
                                                    ? 'bg-blue-500/25 text-blue-700 dark:text-blue-300'
                                                    : 'bg-blue-500/20 text-blue-600 dark:text-blue-400'
                                            )}
                                        >
                                            {getInitials(org.name)}
                                        </div>
                                    )}
                                    <span
                                        className={cn(
                                            'text-sm flex-1 truncate font-medium',
                                            org.id === orgContext.id
                                                ? 'text-foreground'
                                                : 'text-muted-foreground dark:text-white/60'
                                        )}
                                    >
                                        {org.name}
                                    </span>
                                    {org.id === orgContext.id && (
                                        <Check className="w-4 h-4 text-muted-foreground dark:text-white/70" />
                                    )}
                                </DropdownMenuItem>
                            ))}
                        </>
                    )}

                    {/* Create organization */}
                    <DropdownMenuSeparator className="my-1.5 bg-foreground/[0.06]" />

                    <DropdownMenuItem
                        onClick={() => {
                            setIsOpen(false);
                            setCreateModalOpen(true);
                        }}
                        className={cn(
                            'flex items-center gap-3 px-2.5 py-2 rounded-md cursor-pointer',
                            'text-muted-foreground dark:text-white/25 hover:text-foreground/80 hover:bg-foreground/[0.04]',
                            'transition-colors duration-100',
                            'focus:bg-foreground/[0.06] focus:text-foreground/80'
                        )}
                    >
                        <div className="w-6 h-6 rounded-full border border-dashed border-border dark:border-white/20 flex items-center justify-center">
                            <Plus className="w-3.5 h-3.5" />
                        </div>
                        <span className="text-sm">New organization</span>
                    </DropdownMenuItem>

                    {/* Manage organization/members */}
                    {orgContext.id ? (
                        <DropdownMenuItem
                            onClick={() => {
                                setIsOpen(false);
                                navigateToOrgSettings();
                            }}
                            className={cn(
                                'flex items-center gap-3 px-2.5 py-2 rounded-md cursor-pointer',
                                'text-muted-foreground dark:text-white/50 hover:text-foreground/80 hover:bg-foreground/[0.04]',
                                'transition-colors duration-100',
                                'focus:bg-foreground/[0.06] focus:text-foreground/80'
                            )}
                        >
                            <div className="w-6 h-6 rounded-full bg-foreground/5 flex items-center justify-center">
                                <Settings className="w-3.5 h-3.5" />
                            </div>
                            <span className="text-sm">Manage organization</span>
                        </DropdownMenuItem>
                    ) : (
                        <DropdownMenuItem
                            onClick={() => {
                                setIsOpen(false);
                                navigateToOrgSettings();
                            }}
                            className={cn(
                                'flex items-center gap-3 px-2.5 py-2 rounded-md cursor-pointer',
                                'text-muted-foreground dark:text-white/50 hover:text-foreground/80 hover:bg-foreground/[0.04]',
                                'transition-colors duration-100',
                                'focus:bg-foreground/[0.06] focus:text-foreground/80'
                            )}
                        >
                            <div className="w-6 h-6 rounded-full bg-foreground/5 flex items-center justify-center">
                                <Settings className="w-3.5 h-3.5" />
                            </div>
                            <span className="text-sm">Manage workspace</span>
                        </DropdownMenuItem>
                    )}
                </DropdownMenuContent>
            </DropdownMenu>

            <CreateOrganizationModal
                open={createModalOpen}
                onOpenChange={setCreateModalOpen}
            />
        </div>
    );
}
