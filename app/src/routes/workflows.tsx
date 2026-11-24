// `/workflows`: the account's workflows (src/screens/workflows), the Automations page NoClick's app draws, read and
// changed with the app's key through the app's own server, as every screen's calls are: its folders and the workflows
// in each, made, renamed, moved, copied and trashed there, each opening on its page at `/workflows/<id>`. It reads
// again when the account's change stream says a workflow was made, changed or deleted, where the API serves the
// stream, and when the page comes back into view.
import { useMemo } from 'react';
import { AutomationsPage } from '@/screens/workflows/AutomationsPage';
import { useClient } from '@/sdk/client';
import { WorkLiveContext } from '@/sdk/live';
import { liveFromWatch, sdkLive } from '@/sdk/watchLive';
import type { Route } from './+types/workflows';

export const meta: Route.MetaFunction = () => [{ title: 'Automations · NoClick' }];

export default function Workflows() {
    const client = useClient();
    // Never on a timer: a stream the API doesn't serve leaves the page to its focus re-reads.
    const live = useMemo(() => liveFromWatch(sdkLive(client), { backstopMs: null }), [client]);
    return (
        <WorkLiveContext.Provider value={live}>
            <AutomationsPage />
        </WorkLiveContext.Provider>
    );
}
