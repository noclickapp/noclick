// The account menu's parts that read no app state: who you are, your avatar, a plan's name and the rows' styling.
// Pages that only show an account import them from here, clear of the menu itself.
import type { ComponentType } from 'react';
import { Avatar, AvatarFallback, AvatarImage } from '@/ui/avatar';
import { userInitials } from '@/lib/userDisplay';

// Shared account-menu row styling so every item stays consistent: a quiet wash on the menu's surface, radius nested
// in its p-1.5. duration-75 overrides the base transition-colors (150ms) for a snappier hover.
export const ACCOUNT_MENU_ITEM =
    'min-h-9 rounded-[10px] cursor-pointer duration-75 text-foreground hover:bg-foreground/[0.07] focus:bg-foreground/[0.07] focus:text-foreground';

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

/** "Pro plan", "Free plan": the plan as the account menu and sidebar name it. */
export function planLabel(plan: string | null): string {
    return plan ? `${plan.charAt(0).toUpperCase()}${plan.slice(1)} plan` : 'Free plan';
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
