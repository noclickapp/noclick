// What stands in the canvas's account slot (`canvas.step.accounts`, slots.ts) when no host fills it: a step's ways in,
// read from its type's schema on /v1; the account's connections; and a choice saved as the step's `set_connection`
// edit, with the client a `ClientProvider` above gives.
import { useCallback, useMemo } from 'react';
import { Connection, Workflow } from 'noclick';
import { requirementsFromSchema, runsOnNoClickKey, type StepSettings } from '@/lib/accountWays';
import { humanizeCredentialLabel } from '@/lib/credentialLabels';
import { useClient } from '@/sdk/client';
import { useV1 } from '@/sdk/useV1';
import { CONNECTIONS_READ, credentialIdOf } from '@/screens/connections/apiAccounts';
import { errorText } from '@/screens/console/pages/resources/shared';
import { useStepScope } from './form/reads';
import { knownStepType, useV1StepSchema } from './slotStandards';
import type { AccountWaysRead, StepAccount, StepAccountList } from './slots';

/** An agent's account is the AI account its model runs on: the key of the provider its model names
 *  (`openai/gpt-5.4-mini` runs on an `agent_openai` key), connected through `connect.model`. */
function modelWays(step: StepSettings): AccountWaysRead {
    const model = typeof step.config?.model === 'string' ? step.config.model : '';
    const provider = model.includes('/') ? model.slice(0, model.indexOf('/')) : null;
    if (!provider) {
        return { status: 'failed', message: `This agent’s model${model ? ` (${model})` : ''} names no provider, so the AI account it runs on can’t be chosen here: choose it on NoClick.` };
    }
    const app = humanizeCredentialLabel(provider);
    return {
        status: 'ready',
        ways: [{ credential_type: `agent_${provider}`, label: `${app} API key`, description: '' }],
        app,
        integration: provider,
        model: provider,
        optional: false,
    };
}

export function useV1AccountWays(type: string, step: StepSettings): AccountWaysRead {
    const client = useClient();
    const read = useV1StepSchema(type);
    return useMemo<AccountWaysRead>(() => {
        if (read.status !== 'ready') return read;
        if (type === 'agent') return modelWays(step);
        const known = knownStepType(client, type);
        return {
            status: 'ready',
            ways: read.schema ? requirementsFromSchema(read.schema) : [],
            app: known?.label ?? type,
            integration: known?.connection?.integration ?? null,
            model: null,
            optional: runsOnNoClickKey(read.schema, step),
        };
    }, [read, type, step, client]);
}

/** A connection the API lists, as the pickers list an account: one connected in the app by its credential's id (what a
 *  step keeps), a named one by its own. */
function accountOf(connection: Connection): StepAccount {
    const shared = connection.shared;
    const health = connection.health;
    const disconnected = connection.raw.disconnected as { since?: string | null } | null | undefined;
    return {
        id: credentialIdOf(connection),
        name: connection.name,
        credential_type: connection.credentialType ?? '',
        metadata: connection.account ? { verified_as: connection.account } : {},
        created_at: String(connection.raw.created_at),
        updated_at: String(connection.raw.updated_at),
        access_type: !shared ? 'owner' : shared.with === 'workspace' ? 'shared_org' : 'shared',
        shared_by_name: shared?.byName ?? null,
        shared_by_email: shared?.byEmail ?? null,
        revoked_at: disconnected ? (disconnected.since ?? String(connection.raw.updated_at)) : null,
        connection_healthy: health?.healthy ?? null,
        connection_hint: health?.hint ?? null,
    };
}

/** The pickers' read of the account's connections: under Connections' prefix, so a write there reads them again. */
const STEP_ACCOUNTS_READ = `${CONNECTIONS_READ}:step-accounts`;

export function useV1Accounts(): StepAccountList {
    const client = useClient();
    const read = useV1(STEP_ACCOUNTS_READ, () => Connection.list({ client }), { client });
    const accounts = useMemo(() => (read.data ?? []).map(accountOf), [read.data]);
    return {
        accounts,
        loading: read.loading,
        error: read.error === undefined ? null : `Your accounts couldn’t be read: ${errorText(read.error)}`,
        reload: read.refresh,
        // A step keeps a named connection's account by its credential's id, which the API doesn't name with it.
        namesEvery: false,
    };
}

/** Saves a step's account as the step's `set_connection` edit, by its id (the API finds a named connection by its own
 *  id, else the account connected in the app with that credential id); none takes the slot's off. A credential
 *  variable is a setting of the workflow's, never a connection, so it isn't saved here. */
export function useV1SaveAccount(): ((credentialType: string, credentialId: string | null) => Promise<void>) | null {
    const client = useClient();
    const scope = useStepScope();
    const workflowId = scope?.workflowId;
    const nodeId = scope?.nodeId;
    return useCallback(
        async (credentialType: string, credentialId: string | null) => {
            if (!workflowId || !nodeId) throw new Error('A step’s account is saved through its workflow and step: draw the pickers inside its form.');
            if (credentialId?.startsWith('{{')) throw new Error('A credential variable is chosen with the workflow’s settings, not saved as a step’s connection.');
            const step = Workflow.fromId(workflowId, { client }).step(nodeId);
            await step.setConnection(credentialId, { slot: credentialType });
        },
        [client, workflowId, nodeId]
    );
}
