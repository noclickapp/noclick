// The account menu as drawn: who you are and your plan, then the other place this account works, Settings, the host's
// billing items, the surface's own rows, theme and log out. It reads no app state: whoever draws it hands it the plan
// and how to log out (the developer console from the account it reads).
import type { ReactNode } from 'react';
import { useNavigate } from 'react-router';
import { LogOut, Settings as SettingsIcon, SunMoon } from 'lucide-react';
import { ThemeSwitch } from '@/ui/ThemeSwitch';
import { DropdownMenuContent, DropdownMenuGroup, DropdownMenuItem, DropdownMenuSeparator } from '@/ui/dropdown-menu';
import { MENU_SEPARATOR, MENU_SURFACE } from '@/ui/menus';
import { cn } from '@/ui/utils';
import { ACCOUNT_MENU_ITEM, AccountAvatar, planLabel, type AccountMenuSwitch, type AccountMenuUser } from '@/ui/accountParts';

const ACCOUNT_MENU_ITEM_DANGER =
    'min-h-9 rounded-[10px] cursor-pointer duration-75 text-red-600 hover:bg-red-500/10 hover:text-red-700 focus:bg-red-500/10 focus:text-red-700 dark:text-red-400 dark:hover:text-red-300 dark:focus:text-red-300';

export interface AccountMenuBodyProps {
    user: AccountMenuUser;
    /** The paid plan as the host knows it; null for a free account. */
    plan: string | null;
    /** Signs out where the host keeps its session. */
    onLogout: () => void;
    /** The app's Settings; a host with its own (the developer console) leaves the row out. */
    onOpenSettings?: () => void;
    switchTo?: AccountMenuSwitch;
    align?: 'start' | 'end';
    side?: 'top' | 'bottom' | 'right';
    sideOffset?: number;
    /** The host's billing rows, under Settings. */
    billing?: ReactNode;
    /** Surface-specific rows, above the theme picker. */
    children?: ReactNode;
}

export function AccountMenuBody({ user, plan, onLogout, onOpenSettings, switchTo, align = 'end', side, sideOffset = 8, billing, children }: AccountMenuBodyProps) {
    const navigate = useNavigate();
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
                    <div className="mt-0.5 text-xs text-muted-foreground dark:text-white/60">{planLabel(plan)}</div>
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
            <DropdownMenuItem className={ACCOUNT_MENU_ITEM_DANGER} onClick={() => onLogout()}>
                <LogOut className="mr-2 h-4 w-4" />
                <span>Log out</span>
            </DropdownMenuItem>
        </DropdownMenuContent>
    );
}
