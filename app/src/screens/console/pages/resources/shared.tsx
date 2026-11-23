// Pieces the four Resources panels share: the toolbar (limit line, user
// facet, the create action), a detail field row, the destructive confirm, the
// read-only "acts for" line for writes on an owned resource, and error text.
import { useContext, useState, type ReactNode } from 'react';
import { ConsoleContext } from '@/screens/console/hooks/useConsole';
import { HAIRLINE } from '@/ui/primitives';
import { cn } from '@/ui/utils';
import { useReportHeld } from '@/sdk/held';
import { invalidateV1 } from '@/sdk/useV1';
import { userLabel, type UserFilterValue } from '@/screens/console/lib/userFilter';
import { ConsoleButton } from '../../ui/Button';
import { ConsoleDialog } from '../../ui/ConsoleDialog';
import { ErrorPanel } from '../../ui/ErrorPanel';
import { PageActions } from '../../ui/PageHeader';
import { UserFacet } from '../../ui/UserFacet';
import { useUsers } from '../lookups';

export { errorText } from '@/screens/console/lib/errorText';

export interface PanelProps {
    user: UserFilterValue;
    setUser: (user: UserFilterValue) => void;
}

/** Above a kind's list: whose to show, and how close the account is to a limit. The kind's create action goes up beside the page title. */
export function PanelToolbar({ limit, user, setUser, action }: PanelProps & { limit?: ReactNode; action?: ReactNode }) {
    return (
        <>
            {action && <PageActions>{action}</PageActions>}
            <div className="mb-4 flex flex-wrap items-center gap-x-3 gap-y-2">
                <UserFacet value={user} onChange={setUser} />
                {limit && <p className="m-0 min-w-0 text-[13px] text-muted-foreground">{limit}</p>}
            </div>
        </>
    );
}

export function Field({ label, children }: { label: string; children: ReactNode }) {
    return (
        <div className="flex min-h-8 items-baseline gap-3 py-1">
            <dt className="w-28 shrink-0 text-[12px] text-muted-foreground">{label}</dt>
            <dd className="m-0 min-w-0 flex-1 text-[13px]">{children}</dd>
        </div>
    );
}

export function Section({ title, children, className }: { title: ReactNode; children: ReactNode; className?: string }) {
    return (
        <section className={className}>
            <h3 className="m-0 mb-2.5 text-[14px] font-semibold tracking-[-0.01em] text-foreground">{title}</h3>
            {children}
        </section>
    );
}

/**
 * A write on a resource a user owns acts for (and bills) that user: the
 * client sends the resource's own user, never the page filter. Shown read-only.
 */
export function ActsFor({ userId }: { userId: string | null }) {
    const users = useUsers();
    const suspended = !!userId && users.some((u) => u.id === userId && u.status === 'suspended');
    return (
        <div className="flex flex-col gap-1.5">
            <span className="text-[12px] font-medium text-muted-foreground">User</span>
            <span className={cn('flex h-9 items-center rounded-md border bg-foreground/[0.03] px-3 text-[13px]', HAIRLINE, userId ? 'text-foreground/85' : 'text-muted-foreground')}>
                {userLabel(userId)}
            </span>
            <span className="text-[12px] text-muted-foreground">
                {suspended ? 'This user is suspended, so writes are refused until they are reactivated.' : "Acts for this resource's user; its spend counts toward their cap and is billed to your account."}
            </span>
        </div>
    );
}

/** A destructive action behind a confirm: a red-outline button, the consequence stated. */
export function ConfirmAction({
    label,
    title,
    description,
    confirmLabel,
    onConfirm,
}: {
    label: string;
    title: string;
    description: ReactNode;
    confirmLabel: string;
    onConfirm: () => Promise<void>;
}) {
    const [open, setOpen] = useState(false);
    const [busy, setBusy] = useState(false);
    const [error, setError] = useState<unknown>(undefined);
    const reportHeld = useReportHeld(useContext(ConsoleContext));
    const run = async () => {
        setBusy(true);
        setError(undefined);
        try {
            await onConfirm();
            setOpen(false);
        } catch (e) {
            // Held for the account's owner: the dialog's done, and a toast follows it until it's done or not.
            if (reportHeld(e, title.replace(/\?$/, ''), () => invalidateV1(''))) setOpen(false);
            else setError(e);
        } finally {
            setBusy(false);
        }
    };
    return (
        <>
            <ConsoleButton variant="danger" size="sm" onClick={() => setOpen(true)}>
                {label}
            </ConsoleButton>
            <ConsoleDialog
                open={open}
                onOpenChange={setOpen}
                size="sm"
                title={title}
                description={description}
                footer={
                    <>
                        <ConsoleButton variant="ghost" onClick={() => setOpen(false)}>
                            Cancel
                        </ConsoleButton>
                        <ConsoleButton variant="danger" disabled={busy} onClick={() => void run()}>
                            {busy ? 'Working…' : confirmLabel}
                        </ConsoleButton>
                    </>
                }
            >
                {error !== undefined && <ErrorPanel error={error} />}
            </ConsoleDialog>
        </>
    );
}

export const INPUT =
    'h-9 w-full rounded-md border border-input bg-background px-3 text-[13px] text-foreground outline-none placeholder:text-[hsl(var(--placeholder))] focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-50';

export function LabeledInput({ label, id, children }: { label: string; id: string; children: ReactNode }) {
    return (
        <div className="flex flex-col gap-1.5">
            <label htmlFor={id} className="text-[12px] font-medium text-muted-foreground">
                {label}
            </label>
            {children}
        </div>
    );
}

export const sleep = (ms: number) => new Promise((resolve) => window.setTimeout(resolve, ms));
