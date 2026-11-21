// `/usage`: what each thing cost, as it was used (src/screens/usage), read with the app's key through the app's own
// server, as every screen's calls are. A key reads the money behind it without auto top-up or friends' credit, so the
// balance shows as read, with NoClick's page for adding funds, and the headline says when the balance runs out at this
// pace, never that work stops. It reads again when the account's change stream says the account was charged, where
// the API serves the stream, and when the page comes back into view.
import { useMemo } from 'react';
import { UsagePage } from '@/screens/usage/UsagePage';
import { useClient } from '@/sdk/client';
import { WorkLiveContext } from '@/sdk/live';
import { liveFromWatch, sdkLive } from '@/sdk/watchLive';
import type { Route } from './+types/usage';

export const meta: Route.MetaFunction = () => [{ title: 'Usage · NoClick' }];

export default function Usage() {
    const client = useClient();
    // Never on a timer: a stream the API doesn't serve leaves the page to its focus re-reads.
    const live = useMemo(() => liveFromWatch(sdkLive(client), { backstopMs: null }), [client]);
    return (
        <WorkLiveContext.Provider value={live}>
            {/* The page scrolls inside the frame, framed as NoClick's own app frames it. */}
            <div className="h-full overflow-y-auto">
                <div className="mx-auto max-w-[1080px] px-4 py-8">
                    <UsagePage />
                </div>
            </div>
        </WorkLiveContext.Provider>
    );
}
