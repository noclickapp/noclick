// An account the platform API lists (`GET /v1/connections`), as Connections shows it and acts on it: what keeps it from
// working in that API's words, the automations it names with it, and its check, rename and delete through its
// connection. What it goes by and its app's name come from whoever names accounts (the `connection.mark` slot).
import type { Connection } from 'noclick';
import { invalidateV1 } from '@/sdk/useV1';
import type { WorkflowRef } from '@/screens/resources/files';
import type { AccountNames } from '@/ui/slots';
import type { DeletesThrough } from './DeleteDialog';
import { accountSource, type AccountCredential, type CatalogApp, type ConnectedAccount } from './model';
import type { ProbeAsk } from './probe';

/** The prefix of the page's read of them: a write to one reads them again. */
export const CONNECTIONS_READ = 'connections?page';

/** Why an account stopped working, as the API says it. */
interface Disconnected {
    message: string;
    since: string | null;
}

function disconnectedOf(connection: Connection): Disconnected | null {
    const raw = connection.raw.disconnected;
    if (!raw || typeof raw !== 'object') return null;
    const said = raw as Record<string, unknown>;
    return { message: String(said.message), since: typeof said.since === 'string' ? said.since : null };
}

/** The account a connection is: an account connected in the app is `credential:<id>`, a named connection its own id. */
export const credentialIdOf = (connection: Connection): string => connection.id.replace(/^credential:/, '');

/** An account the API lists, in the shape the page's parts read. */
function credentialOf(connection: Connection, disconnected: Disconnected | null): AccountCredential {
    const shared = connection.shared;
    const health = connection.health;
    const movedFrom = connection.raw.moved_from;
    return {
        id: credentialIdOf(connection),
        name: connection.name,
        credential_type: connection.credentialType ?? '',
        metadata: movedFrom ? { moved_from: movedFrom } : {},
        created_at: String(connection.raw.created_at),
        updated_at: String(connection.raw.updated_at),
        access_type: !shared ? 'owner' : shared.with === 'workspace' ? 'shared_org' : 'shared',
        shared_by_name: shared?.byName ?? null,
        shared_by_email: shared?.byEmail ?? null,
        organization_id: connection.organizationId,
        revoked_at: disconnected ? disconnected.since : null,
        connection_healthy: health?.healthy ?? null,
        connection_hint: health?.hint ?? null,
    };
}

/** The facts a namer reads of a connection: its type, integration, name, the account it reaches and when it connected. */
export function namingFacts(connection: Connection) {
    return {
        credentialType: connection.credentialType ?? '',
        integration: connection.integration,
        name: connection.name,
        account: connection.account,
        connectedAt: String(connection.raw.connected_at ?? connection.raw.created_at),
    };
}

/** The automations that use it, as the API names them with the account. */
const workflowsOf = (connection: Connection): WorkflowRef[] =>
    connection.usedBy.filter((h) => h.kind === 'workflow').map((h) => ({ id: h.id, name: h.name, marks: h.marks }));

/** Its check: the connection's verify, answered in the provider's words. */
export function verifyAsk(connection: Connection): ProbeAsk {
    return async () => {
        const verified = await connection.verify();
        if (!verified) return { reachable: null, samples: [] };
        return {
            reachable: verified.reachable,
            samples: verified.samples as { label: string; value?: string | null }[],
            noun: verified.noun ?? undefined,
            total: verified.total,
            account_label: verified.accountLabel,
            proves: verified.proves ?? undefined,
            error: verified.error,
            hint: verified.hint,
        };
    };
}

/** Renames it, then reads the list again. */
export async function renameThrough(connection: Connection, name: string): Promise<void> {
    await connection.rename(name);
    invalidateV1(CONNECTIONS_READ);
}

// What the API calls each kind of holder, as a person does (its delete preview's words).
const NOUNS: Record<string, string> = { project: 'app', mcp_server: 'MCP server', phone_number: 'number' };

/** Deleting it: what loses it, read again as the dialog opens, and the delete itself. */
export function deletesThrough(connection: Connection): DeletesThrough {
    return {
        preview: async () => {
            const now = await connection.refresh();
            return {
                workflows: now.usedBy.filter((h) => h.kind === 'workflow').map((h) => ({ workflow_id: h.id, workflow_name: h.name })),
                holders: now.usedBy.filter((h) => h.kind !== 'workflow').map((h) => ({ kind: NOUNS[h.kind] ?? h.kind.replace(/_/g, ' '), id: h.id, name: h.name })),
            };
        },
        remove: async () => {
            await connection.delete();
            invalidateV1(CONNECTIONS_READ);
        },
    };
}

/** What an account the API lists is besides what the API says: its catalog app, how it's named, how it's connected again. */
export interface AccountMaking {
    service?: CatalogApp;
    names: AccountNames;
    reconnect: () => void;
}

/** One account the API lists, as the page shows it. It's checked only where its app is known (the provider is asked
 *  through that app's evidence), and renamed only when connected in the app: a named connection's name is how code
 *  finds it. */
export function accountOf(connection: Connection, { service, names, reconnect }: AccountMaking): ConnectedAccount {
    const disconnected = disconnectedOf(connection);
    const health = connection.health;
    const credential = credentialOf(connection, disconnected);
    return {
        credential,
        service,
        app: service?.label ?? names.app,
        line: names.line,
        aliases: names.aliases,
        source: accountSource(credential),
        problem: disconnected?.message ?? (health && !health.healthy ? health.hint || 'The connection dropped' : undefined),
        connection,
        usedBy: workflowsOf(connection),
        check: service ? verifyAsk(connection) : undefined,
        rename: connection.origin === 'app' ? (name) => renameThrough(connection, name) : undefined,
        deletes: deletesThrough(connection),
        reconnect,
    };
}
