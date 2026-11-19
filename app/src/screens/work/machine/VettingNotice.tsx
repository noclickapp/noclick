// What Machines says above its rows while NoClick's company check waits or was declined: under review (a machine
// rented meanwhile starts once it's approved, nothing charged before), or declined with NoClick's reason and Send
// again, which sends the company's details once more from the same card the rent confirm shows.
import { useState } from 'react';
import { toast } from 'sonner';
import { Clock, ShieldAlert } from 'lucide-react';
import { invalidateV1 } from '@/sdk/useV1';
import {
    getMachineAccess,
    requestMachineAccess,
} from '@/sdk/owner';
import {
    BUTTON_GHOST,
    BUTTON_PRIMARY,
    BUTTON_SECONDARY,
} from '@/ui/buttons';
import { ShellDialog } from '@/ui/ShellDialog';
import { cn } from '@/ui/utils';
import { useWorkV1 } from '../agents/reads';
import { useWorkClient } from '../client';
import { VETTING_KEY } from './reads';
import { VettingCard, vettingReady, type VettingDraft } from './VettingCard';
import { useOwnerOnly } from '@/screens/console/ownerOnly';

const SMALL_SECONDARY = BUTTON_SECONDARY.replace('h-9', 'h-8').replace(
    'px-4',
    'px-3'
);

export function VettingNotice() {
    const access = useWorkV1(VETTING_KEY, (c) => getMachineAccess(c));
    const [again, setAgain] = useState(false);
    // Only the account's owner, signed in, sends it again (screens/console/ownerOnly.ts).
    const asks = useOwnerOnly()('machineAccess');
    const a = access.data;
    if (!a || (a.status !== 'pending' && a.status !== 'rejected')) return null;
    const company = a.company_name || 'your company';
    return (
        <div
            className={cn(
                'mb-4 flex flex-wrap items-start gap-3 rounded-2xl px-4 py-3 text-[13.5px]',
                a.status === 'rejected'
                    ? 'bg-red-500/[0.07]'
                    : 'bg-foreground/[0.04]'
            )}
            data-testid="vetting-notice"
            role="status"
        >
            {a.status === 'rejected' ? (
                <ShieldAlert
                    className="mt-0.5 h-4 w-4 shrink-0 text-red-600 dark:text-red-400"
                    strokeWidth={1.75}
                />
            ) : (
                <Clock
                    className="mt-0.5 h-4 w-4 shrink-0 text-muted-foreground"
                    strokeWidth={1.75}
                />
            )}
            <p className="min-w-0 flex-1 leading-snug">
                {a.status === 'rejected' ? (
                    <>
                        <span className="font-medium">
                            NoClick couldn’t approve {company}.
                        </span>{' '}
                        {a.reason} Nothing was charged.
                    </>
                ) : (
                    <>
                        NoClick is checking {company} before its first machine,
                        usually within a day. A machine you rent meanwhile
                        starts the moment it’s approved; nothing is charged
                        before.
                    </>
                )}
            </p>
            {a.status === 'rejected' && asks && (
                <button
                    type="button"
                    onClick={() => setAgain(true)}
                    className={SMALL_SECONDARY}
                >
                    Send again
                </button>
            )}
            {again && (
                <SendAgain
                    start={{
                        company_name: a.company_name ?? '',
                        website: a.website ?? '',
                        country: a.country ?? '',
                        use_case: a.use_case ?? '',
                    }}
                    onClose={() => setAgain(false)}
                />
            )}
        </div>
    );
}

function SendAgain({
    start,
    onClose,
}: {
    start: VettingDraft;
    onClose: () => void;
}) {
    const client = useWorkClient();
    const [draft, setDraft] = useState(start);
    const [busy, setBusy] = useState(false);
    const send = async () => {
        setBusy(true);
        try {
            await requestMachineAccess(client, {
                ...draft,
                country: draft.country.trim().toUpperCase(),
                accept_usage_policy: true,
            });
            toast('Sent again', {
                description: 'NoClick looks again, usually within a day.',
            });
            onClose();
        } catch (error) {
            toast('Couldn’t send it', {
                description:
                    error instanceof Error ? error.message : String(error),
            });
        } finally {
            setBusy(false);
            invalidateV1(VETTING_KEY);
            invalidateV1('resources:machines/vetting');
        }
    };
    return (
        <ShellDialog
            open
            onOpenChange={(o) => !o && onClose()}
            dismissible={!busy}
            title="Send it to NoClick again"
            description="Say more about the company or what its agents will do, and NoClick looks again."
            mark={<ShieldAlert className="h-5 w-5" strokeWidth={1.75} />}
            testId="vetting-again"
            footer={
                <>
                    <button
                        type="button"
                        onClick={onClose}
                        className={BUTTON_GHOST}
                    >
                        Cancel
                    </button>
                    <button
                        type="button"
                        disabled={busy || !vettingReady(draft)}
                        onClick={() => void send()}
                        className={BUTTON_PRIMARY}
                    >
                        {busy ? 'Sending…' : 'Send again'}
                    </button>
                </>
            }
        >
            <div className="grid gap-2 pb-2">
                <VettingCard value={draft} onChange={setDraft} editable />
                <p className="text-[12.5px] leading-snug text-muted-foreground">
                    Sending this accepts the machines usage policy: no crypto
                    mining, network scanning or bulk email.
                </p>
            </div>
        </ShellDialog>
    );
}
