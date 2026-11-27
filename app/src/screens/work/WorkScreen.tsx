// Work as a host mounts it: its client and live frames handed in, the values of `WorkContext`, and the copy this
// browser keeps of it (kept.ts) for `keptAs`'s account: the first open paints what Work showed when it was last open
// here, and Work leaving (or the page hiding) keeps it again.
import { useEffect, useMemo, useState } from 'react';
import type { NoClick } from 'noclick';
import { WorkLiveContext, type WorkLive } from '@/sdk/live';
import { keepWhenLeaving } from '@/lib/kept';
import { heldBy } from '@/screens/channels/useChannels';
import type { AccountMenuUser } from '@/ui/accountParts';
import { WorkClientContext } from './client';
import { WorkContext, type WorkContextValue } from './context';
import { keepWork, restoreWork } from './kept';
import { WorkLoading } from './notices';
import { useReadsAgainOnReset } from './rereads';
import { OWN, transportFor, Work } from './Work';

export interface WorkScreenProps {
    client: NoClick;
    live: WorkLive;
    /** The account whose copy this browser keeps; null keeps none. */
    keptAs: string | null;
    /** Who is looking, for the account menu Work draws. */
    user: AccountMenuUser;
    work?: WorkContextValue;
}

export function WorkScreen({ client, live, keptAs, user, work = {} }: WorkScreenProps) {
    const own = useMemo(() => transportFor(client, OWN, undefined), [client]);
    // What this browser kept is read before Work draws, unless this page already holds what Work read.
    const [restored, setRestored] = useState(() => keptAs === null || !!heldBy(own));
    useEffect(() => {
        if (restored || keptAs === null) return;
        let open = true;
        void restoreWork(keptAs, client, own).finally(() => open && setRestored(true));
        return () => {
            open = false;
        };
    }, [restored, keptAs, client, own]);
    useEffect(() => (keptAs === null ? undefined : keepWhenLeaving(() => keepWork(keptAs, client, own))), [keptAs, client, own]);
    if (!restored) return <WorkLoading />;
    return (
        <WorkContext.Provider value={work}>
            <WorkClientContext.Provider value={client}>
                <WorkLiveContext.Provider value={live}>
                    <ReadsAgainOnReset />
                    <Work user={user} />
                </WorkLiveContext.Provider>
            </WorkClientContext.Provider>
        </WorkContext.Provider>
    );
}

function ReadsAgainOnReset() {
    useReadsAgainOnReset();
    return null;
}
