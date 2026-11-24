// What whoever shows the Automations page (WorkflowBrowser) hands it: values, where a slot (../slots.ts) is a piece of
// the page. The client its store reads and writes /v1 with is handed to the store (`setWorkflowBrowserClient`).
import { createContext, useContext } from 'react';

/** What the page can be asked to do from elsewhere (a command palette's "New automation"). */
export type BrowserAction = 'create' | 'new-folder' | 'trash';

/** Something to do once the page is showing: open a workflow or a folder, or one of its actions. */
export type FlowIntent =
    | { kind: 'open'; workflow: { id: string; name: string } }
    | { kind: 'folder'; folderId: string }
    | { kind: 'action'; action: BrowserAction };

export interface WorkflowsHostValue {
    /** Hands a request to an assistant (the empty page's "Ask NoClick"); absent, no such button shows. */
    ask?: (text: string) => void;
    /** Whether a dialog holds the keyboard, so the page's bare-key shortcuts stand down. Absent: any open dialog. */
    keysHeld?: () => boolean;
    /** The address the page shows an open workflow at: query parameters it sets beside `workflow` (`set`) and ones it
     *  drops (`drop`), where the page shares its address with others. */
    address?: { set?: Record<string, string>; drop?: string[] };
    /** What was asked of the page before it mounted (an intent another screen left for it), taken once. */
    takePendingIntent?: () => FlowIntent | null;
}

export const WorkflowsHostContext = createContext<WorkflowsHostValue>({});

export function useWorkflowsHost(): WorkflowsHostValue {
    return useContext(WorkflowsHostContext);
}

/** Whether any dialog is open: the standard `keysHeld`. */
export function anyDialogOpen(): boolean {
    return typeof document !== 'undefined' && document.querySelector('[role="dialog"]') !== null;
}
