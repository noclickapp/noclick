// The account's workflows as this app shows them: the Automations page (./browser) acting as the app's key, over the
// app's client, in the account's own workspace. A workflow opens on its own page (`openWorkflow`, by default this app's
// `/workflows/<id>`). What changes elsewhere reaches it through the account's change stream, where the API serves it,
// and when the page comes back into view.
import { useCallback, useEffect, useLayoutEffect, useMemo } from 'react';
import { useSearchParams } from 'react-router';
import { useClient } from '@/sdk/client';
import { useWorkFrames } from '@/sdk/live';
import { WorkflowBrowser } from './browser/WorkflowBrowser';
import { WorkflowBrowserDataProvider } from './browser/WorkflowBrowserDataProvider';
import { WorkflowsHostContext, type WorkflowsHostValue } from './browser/context';
import { fetchTree, setWorkflowBrowserClient } from './browser/workflowBrowserStore';

/** The account's own workspace, the only one a key lists. */
export const ACCOUNT_SCOPE = 'personal';

export interface AutomationsPageProps {
    /** Opens a workflow's page; by default this app's own. */
    onOpen?: (workflowId: string) => void;
}

export function AutomationsPage({ onOpen }: AutomationsPageProps) {
    const client = useClient();
    // Before the page's first reads, which its children's effects make.
    useLayoutEffect(() => {
        setWorkflowBrowserClient(client);
        return () => setWorkflowBrowserClient(null);
    }, [client]);
    const again = useCallback(() => fetchTree(ACCOUNT_SCOPE), []);
    useWorkFrames('platform:resource', (frame) => {
        if (frame.kind === 'workflow') again();
    });
    useWorkFrames('reset', again);
    useEffect(() => {
        const shown = () => {
            if (document.visibilityState === 'visible') again();
        };
        window.addEventListener('focus', again);
        document.addEventListener('visibilitychange', shown);
        return () => {
            window.removeEventListener('focus', again);
            document.removeEventListener('visibilitychange', shown);
        };
    }, [again]);
    const [, setParams] = useSearchParams();
    // A workflow its host opens leaves the page's address as the list's, so the list is what comes back.
    const host = useMemo<WorkflowsHostValue>(
        () => ({
            openWorkflow: onOpen && ((workflowId: string) => {
                setParams((params) => {
                    params.delete('workflow');
                    return params;
                }, { replace: true });
                onOpen(workflowId);
            }),
        }),
        [onOpen, setParams]
    );
    return (
        <WorkflowsHostContext.Provider value={host}>
            <WorkflowBrowserDataProvider scopeId={ACCOUNT_SCOPE}>
                <WorkflowBrowser scopeId={ACCOUNT_SCOPE} />
            </WorkflowBrowserDataProvider>
        </WorkflowsHostContext.Provider>
    );
}
