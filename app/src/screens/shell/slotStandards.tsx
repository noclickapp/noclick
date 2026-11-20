// What stands in the shell's slots (slots.ts) when no host fills them: each works on the platform API alone.
import { signOut } from '@/lib/signOut';
import { userDisplayName } from '@/lib/userDisplay';
import { readAccountStatus } from '@/screens/account/status';
import { useClient } from '@/sdk/client';
import { useV1 } from '@/sdk/useV1';
import type { AccountMenuUser } from '@/ui/accountParts';
import { LogoMark } from '@/ui/LogoMark';
import type { AccountSession } from './slots';

/** The workspace as the account's own name, beside NoClick's mark lined up with the sidebar's icons below. */
export function AccountName({ user }: { user: AccountMenuUser }) {
    return (
        <div className="flex min-w-0 items-center gap-1">
            <LogoMark className="ml-[13px] h-[18px] w-[18px] shrink-0" alt="NoClick" />
            <span className="truncate px-1.5 text-[14px] font-semibold tracking-[-0.01em] text-foreground">{userDisplayName({ email: user.email, name: user.display_name }, 'NoClick')}</span>
        </div>
    );
}

/** The account the app's key acts in, as the platform API reads it. */
function useStatus() {
    const client = useClient();
    return useV1('status', (signal) => readAccountStatus(client, signal), { client });
}

/** The account's plan as the platform API names it, and signing out of this app (forgetting what it kept of the
 *  account in this browser first). */
export const accountOnApp: AccountSession = {
    usePlan: () => useStatus().data?.plan?.name ?? null,
    useSignOut: () => {
        const account = useStatus().data?.account.id;
        return () => void signOut(account);
    },
};
