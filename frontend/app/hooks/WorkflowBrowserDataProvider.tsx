// Provides a single shared instance of useWorkflowBrowserData to the whole
// authenticated dashboard subtree. Added so the global command palette can read
// the folder/workflow tree without mounting a second useWorkflowBrowserData
// instance — a second instance would re-subscribe the MCP socket listeners and
// double-apply create/delete/update events (corrupting workflow counts). The
// provider holds the hook state and renders {children} as-is, so the rest of the
// dashboard does not re-render when workflow data changes; only context
// consumers (WorkflowBrowser, CommandPalette) do.

import { createContext, useContext, type ReactNode } from 'react';
import { useWorkflowBrowserData } from '~/hooks/useWorkflowBrowserData';

type WorkflowBrowserDataStore = ReturnType<typeof useWorkflowBrowserData>;

const WorkflowBrowserDataContext =
    createContext<WorkflowBrowserDataStore | null>(null);

export function WorkflowBrowserDataProvider({
    scopeId,
    children,
}: {
    scopeId: string;
    children: ReactNode;
}) {
    const store = useWorkflowBrowserData(scopeId);
    return (
        <WorkflowBrowserDataContext.Provider value={store}>
            {children}
        </WorkflowBrowserDataContext.Provider>
    );
}

export function useWorkflowBrowserDataContext(): WorkflowBrowserDataStore {
    const ctx = useContext(WorkflowBrowserDataContext);
    if (!ctx) {
        throw new Error(
            'useWorkflowBrowserDataContext must be used within a WorkflowBrowserDataProvider'
        );
    }
    return ctx;
}
