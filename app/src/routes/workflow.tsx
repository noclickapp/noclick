// `/workflows/<id>`: one workflow's page (src/screens/workflows/WorkflowPage.tsx): its canvas with the panel of the
// step selected, its run log and a run's results, its Setup tab and its Test Run (`?tab=setup`, `?tab=test`), acting
// as the app's key through the app's own server. Another writer's change and a run's moves arrive through the
// account's change stream, where the API serves it. A key that may only look at the workflow gets it read-only. The
// builder beside it is the frame's (routes/shell.tsx): the page only opens it. The values of the workflow's variables
// are read by its owner and its editors as themselves, which the app's key isn't (`asOwner` left out): a variable that
// has one shows as saved and hidden.
import { useCallback, useMemo } from 'react';
import { useNavigate, useOutletContext, useParams, useSearchParams } from 'react-router';
import { Workflow } from 'noclick';
import { workflowsRoute, type ShellOutlet } from '@/screens/workflows/routes';
import { WorkflowPage, type WorkflowTab } from '@/screens/workflows/WorkflowPage';
import { useClient } from '@/sdk/client';
import { WorkLiveContext } from '@/sdk/live';
import { useV1 } from '@/sdk/useV1';
import { liveFromWatch, sdkLive } from '@/sdk/watchLive';
import type { Route } from './+types/workflow';

export const meta: Route.MetaFunction = () => [{ title: 'Workflow · NoClick' }];

const TABS: readonly WorkflowTab[] = ['canvas', 'setup', 'test'];

export default function WorkflowRoute() {
    const { id = '' } = useParams();
    const client = useClient();
    const navigate = useNavigate();
    const [params, setParams] = useSearchParams();
    const asked = params.get('tab');
    const tab = TABS.find((t) => t === asked) ?? 'canvas';
    const onTab = useCallback(
        (next: WorkflowTab) =>
            setParams((held) => {
                const out = new URLSearchParams(held);
                if (next === 'canvas') out.delete('tab');
                else out.set('tab', next);
                return out;
            }),
        [setParams]
    );
    const live = useMemo(() => liveFromWatch(sdkLive(client), { backstopMs: null }), [client]);
    // What it's called, for the page's head (the canvas reads the rest itself).
    const name = useV1(`workflow:${id}:name`, async () => (await Workflow.get(id, { client })).name, { client }).data;
    const { builder } = useOutletContext<ShellOutlet>() ?? {};
    return (
        <WorkLiveContext.Provider value={live}>
            <WorkflowPage key={id} workflowId={id} name={name} tab={tab} onTab={onTab} onBack={() => navigate(workflowsRoute)} builder={builder} />
        </WorkLiveContext.Provider>
    );
}
