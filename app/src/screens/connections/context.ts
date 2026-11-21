// What whoever shows Connections hands it besides its client (ConsoleProviders gives that, with `site`, `actsAs` and who
// is signed in). A missing value means the page does without: no team workspace, NoClick's own MCP server, an
// automation opened on NoClick in a new tab.
import { createContext, useContext } from 'react';

export interface ConnectionsContextValue {
    /** The team workspace the page shows (its organization's id), where accounts shared with that team are listed too,
     *  under a Workspace tab. Absent: the account's own, with no Workspace tab. */
    teamWorkspace?: string | null;
    /** NoClick's MCP server, which "Use NoClick from your AI apps" sets up: its address and one line under the guide's
     *  title. Absent: NoClick's own. */
    mcp?: { url: string; intro: string };
    /** Opens an automation that uses an account. Absent: its canvas on NoClick, in a new tab. */
    openWorkflow?: (workflow: { id: string; name: string }) => void;
    /** Told when an account was renamed or deleted here, so the host's other lists of accounts read them again. */
    changed?: (change: { accountId: string; deleted?: boolean }) => void;
}

export const ConnectionsContext = createContext<ConnectionsContextValue>({});

export function useConnectionsContext(): ConnectionsContextValue {
    return useContext(ConnectionsContext);
}
