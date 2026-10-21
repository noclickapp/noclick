// Connections' tabs: every app, then the accounts you can use (yours, your workspace's, shared with you). One table
// the page's tabs and the command palette read.
import type { AccountSource } from './accounts';

export type ConnectionsView = 'all' | AccountSource;

export const CONNECTIONS_VIEWS: readonly {
    id: ConnectionsView;
    label: string;
    /** Other words people use for it, which the command palette matches. */
    keywords: string;
    /** Only in a workspace with members. */
    organization?: boolean;
}[] = [
    { id: 'all', label: 'All apps', keywords: 'apps catalog integrations connect new app browse' },
    { id: 'connected', label: 'Connected', keywords: 'connected accounts my accounts credentials' },
    { id: 'organization', label: 'Workspace', keywords: 'workspace accounts organization team org', organization: true },
    { id: 'shared', label: 'Shared with me', keywords: 'shared accounts' },
];

/** The tabs a workspace shows: Workspace only in an organization. */
export function connectionsViews(inOrganization: boolean) {
    return CONNECTIONS_VIEWS.filter((v) => !v.organization || inOrganization);
}

/** Connections' address for a tab, as `navigateToTab` params: All apps is the page's bare address. */
export function connectionsAddress(view: ConnectionsView): Record<string, string | null> {
    return { view: view === 'all' ? null : view, account: null };
}
