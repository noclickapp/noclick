// `/workflows`: the account's workflows (src/screens/workflows), read with the app's key through the app's own server,
// as every screen's calls are: the ones the key can open, under the account's folders, each a way into its page at
// `/workflows/<id>`, and a new one made by name. The list reads again when the account's change stream says a workflow
// was made, changed or deleted, where the API serves the stream, and when the page comes back into view.
import { useMemo } from 'react';
import { useNavigate } from 'react-router';
import { WorkflowsPage } from '@/screens/workflows/WorkflowsPage';
import { workflowRoute } from '@/screens/workflows/routes';
import { useClient } from '@/sdk/client';
import { WorkLiveContext } from '@/sdk/live';
import { liveFromWatch, sdkLive } from '@/sdk/watchLive';
import type { Route } from './+types/workflows';

export const meta: Route.MetaFunction = () => [{ title: 'Automations · NoClick' }];

export default function Workflows() {
    const client = useClient();
    const navigate = useNavigate();
    // Never on a timer: a stream the API doesn't serve leaves the page to its focus re-reads.
    const live = useMemo(() => liveFromWatch(sdkLive(client), { backstopMs: null }), [client]);
    return (
        <WorkLiveContext.Provider value={live}>
            <WorkflowsPage onOpen={(id) => navigate(workflowRoute(id))} />
        </WorkLiveContext.Provider>
    );
}
