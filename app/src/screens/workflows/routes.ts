// Where the workflows pages are in this app, and what the app's frame hands the page of one workflow.

/** The list of workflows. */
export const workflowsRoute = '/workflows';

/** One workflow's page. */
export const workflowRoute = (workflowId: string) => `${workflowsRoute}/${encodeURIComponent(workflowId)}`;

/** The workflow an address is the page of; null for any other address. */
export function workflowAt(pathname: string): string | null {
    const found = pathname.match(/^\/workflows\/([^/]+)\/?$/);
    return found ? decodeURIComponent(found[1]) : null;
}

/** What the frame's route hands the pages it draws: the builder beside an open workflow, which the frame holds. */
export interface ShellOutlet {
    builder?: { open: boolean; onOpenChange: (open: boolean) => void };
}
