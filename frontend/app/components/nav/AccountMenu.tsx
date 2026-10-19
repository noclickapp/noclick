// The account menu: who you are and your plan, then Settings, the host's billing
// items (hosted only: plans are a hosted-service concept), theme and log out.
import type { ComponentType, ReactNode } from 'react';
import { useNavigate } from 'react-router';
import { LogOut, Settings as SettingsIcon, SunMoon } from 'lucide-react';
import { ThemeSwitch } from '~/components/shared/ThemeSwitch';
import { Avatar, AvatarFallback, AvatarImage } from '~/components/ui/avatar';
import {
    DropdownMenuContent,
    DropdownMenuGroup,
    DropdownMenuItem,
    DropdownMenuSeparator,
} from '~/components/ui/dropdown-menu';
import { MENU_SEPARATOR, MENU_SURFACE } from '~/components/shell/menus';
import { useOrgContext } from '~/hooks/useOrgContext';
import { useValtioState } from '~/hooks/useValtioState';
import { cn } from '~/lib/utils';
import { userInitials } from '~/lib/userDisplay';

// Shared account-menu row styling so every item stays consistent: a quiet wash on the menu's surface, radius nested
// in its p-1.5. duration-75 overrides the base transition-colors (150ms) for a snappier hover.
export const ACCOUNT_MENU_ITEM =
    'min-h-9 rounded-[10px] cursor-pointer duration-75 text-foreground hover:bg-foreground/[0.07] focus:bg-foreground/[0.07] focus:text-foreground';
const ACCOUNT_MENU_ITEM_DANGER =
    'min-h-9 rounded-[10px] cursor-pointer duration-75 text-red-600 hover:bg-red-500/10 hover:text-red-700 focus:bg-red-500/10 focus:text-red-700 dark:text-red-400 dark:hover:text-red-300 dark:focus:text-red-300';

/** The other place this account works (the app ↔ the developer console), first in the menu. */
export interface AccountMenuSwitch {
    label: string;
    icon: ComponentType<{ className?: string }>;
    to: string;
}

export interface AccountMenuUser {
    email: string;
    /** Name for display; the email is empty for a phone-only account. */
    display_name?: string;
    avatar_url?: string;
}

type Tier = 'free' | 'plus' | 'pro' | 'enterprise';

/** "Pro plan", "Free plan": the plan as the account menu and sidebar name it. */
export function planLabel(plan: string | null): string {
    return plan ? `${plan.charAt(0).toUpperCase()}${plan.slice(1)} plan` : 'Free plan';
}

/** The paid plan to badge (personal first, then org); null for fully-free accounts. */
export function useAccountPlan(): Tier | null {
    const [orgContext] = useOrgContext();
    const [personalTier] = useValtioState<Tier>('global', 'personal_subscription_tier', 'free');
    if (personalTier !== 'free') return personalTier;
    const orgTier = orgContext.subscription_tier;
    return orgTier === 'pro' || orgTier === 'enterprise' ? orgTier : null;
}

export function AccountAvatar({ user, className }: { user: AccountMenuUser; className?: string }) {
    return (
        <Avatar className={className}>
            {user.avatar_url ? <AvatarImage src={user.avatar_url} alt="" /> : null}
            <AvatarFallback className="bg-foreground/[0.1] text-xs font-medium text-foreground/85">
                {userInitials({ email: user.email, name: user.display_name })}
            </AvatarFallback>
        </Avatar>
    );
}

export function AccountMenuContent({
    user,
    onOpenSettings,
    onLogout,
    plan,
    switchTo,
    align = 'end',
    side,
    sideOffset = 8,
    billing,
    children,
}: {
    user: AccountMenuUser;
    /** The app's Settings; a host with its own (the developer console) leaves the row out. */
    onOpenSettings?: () => void;
    /** Signs out where the host keeps its session; the app's own by default. */
    onLogout?: () => void;
    /** The plan as the host knows it, in place of the app's (the console reads its account). */
    plan?: string | null;
    switchTo?: AccountMenuSwitch;
    align?: 'start' | 'end';
    side?: 'top' | 'bottom' | 'right';
    sideOffset?: number;
    /** The host's billing rows, under Settings. */
    billing?: ReactNode;
    /** Surface-specific rows, above the theme picker. */
    children?: ReactNode;
}) {
    const navigate = useNavigate();
    const accountPlan = useAccountPlan();

    const handleLogout = async () => {
        if (onLogout) return onLogout();
        await fetch('/dashboard', { method: 'POST', body: new FormData() });
        navigate('/auth/login');
    };

    return (
        <DropdownMenuContent
            className={cn('w-72 rounded-2xl p-1.5 duration-100', MENU_SURFACE)}
            align={align}
            side={side}
            sideOffset={sideOffset}
            data-onboarding="user-menu-dropdown"
        >
            <div className="flex items-center gap-2.5 px-2 py-2">
                <AccountAvatar user={user} className="h-9 w-9 shrink-0" />
                <div className="min-w-0 flex-1">
                    <div className="break-all text-sm font-medium leading-snug text-foreground">{user.email || user.display_name}</div>
                    <div className="mt-0.5 text-xs text-muted-foreground dark:text-white/60">
                        {planLabel(plan === undefined ? accountPlan : plan)}
                    </div>
                </div>
            </div>
            <DropdownMenuSeparator className={MENU_SEPARATOR} />
            <DropdownMenuGroup>
                {switchTo && (
                    <DropdownMenuItem className={ACCOUNT_MENU_ITEM} onClick={() => navigate(switchTo.to)}>
                        <switchTo.icon className="mr-2 h-4 w-4 text-muted-foreground" />
                        <span>{switchTo.label}</span>
                    </DropdownMenuItem>
                )}
                {onOpenSettings && (
                    <DropdownMenuItem className={ACCOUNT_MENU_ITEM} onClick={onOpenSettings} data-onboarding="settings">
                        <SettingsIcon className="mr-2 h-4 w-4 text-muted-foreground" />
                        <span>Settings</span>
                    </DropdownMenuItem>
                )}
                {billing}
                {children}
                {/* preventDefault keeps the menu open so the flip is visible */}
                <DropdownMenuItem className={cn(ACCOUNT_MENU_ITEM, 'cursor-default focus:bg-transparent')} onSelect={(e) => e.preventDefault()}>
                    <SunMoon className="mr-2 h-4 w-4 text-muted-foreground" />
                    <span>Theme</span>
                    <ThemeSwitch className="ml-auto" />
                </DropdownMenuItem>
            </DropdownMenuGroup>
            <DropdownMenuSeparator className={MENU_SEPARATOR} />
            <DropdownMenuItem className={ACCOUNT_MENU_ITEM_DANGER} onClick={handleLogout}>
                <LogOut className="mr-2 h-4 w-4" />
                <span>Log out</span>
            </DropdownMenuItem>
        </DropdownMenuContent>
    );
}
