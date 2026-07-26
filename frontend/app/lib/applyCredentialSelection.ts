// The one path a credential pick takes into node data, shared by every surface
// that hosts NodeCredentials — the config panel's Credentials tab and the Run
// popup's inline credential block.
//
// Extracted because picking a credential is not just "write credentialIds":
// agent nodes carry theirs inline under a different key, collaborators need
// display-only hints to resolve the name without a refetch, and the backend
// will not authorize run-as-owner off the saved blob (it is presence-tainted),
// so the pick has to be reported separately. A second surface reimplementing
// two of those three would fail quietly — collaborator runs would lose access
// with nothing in the UI to show for it.
import { authorizeCredentialsForWorkflow, type CredentialDisplayMeta } from '~/utils/credentialAutoSelect';

/** Node data written by a credential pick — the caller passes this straight to
 *  its node-update path (handleNodeDataUpdate / onNodeDataUpdate). */
export interface CredentialNodeUpdate {
    credentialIds: Record<string, string>;
    /** Agent nodes only: credentials stored inline rather than in the store. */
    credentials?: { credentials: Record<string, unknown> } | null;
    /** Display-only, top-level so it rides the live sync and is stripped by
     *  buildSaveConfig — never persisted. */
    _credentialMeta?: Record<string, CredentialDisplayMeta>;
    _credentialRemoved?: string[];
}

export function buildCredentialNodeUpdate(
    newCredentialIds: Record<string, string>,
    credentialMeta?: Record<string, CredentialDisplayMeta>,
    credentialRemoved?: string[],
): CredentialNodeUpdate {
    const meta = {
        ...(credentialMeta ? { _credentialMeta: credentialMeta } : {}),
        ...(credentialRemoved?.length ? { _credentialRemoved: credentialRemoved } : {}),
    };

    if (newCredentialIds.__agent_credentials__ !== undefined) {
        const agentCredsJson = newCredentialIds.__agent_credentials__;
        const agentCredentials = agentCredsJson ? JSON.parse(agentCredsJson) : null;
        const regularCredentialIds = { ...newCredentialIds };
        delete regularCredentialIds.__agent_credentials__;
        return {
            credentialIds: regularCredentialIds,
            // Shape matches the backend AgentCredentials model.
            credentials:
                agentCredentials && Object.keys(agentCredentials).length > 0
                    ? { credentials: agentCredentials }
                    : null,
            ...meta,
        };
    }
    return { credentialIds: newCredentialIds, ...meta };
}

/**
 * Apply a credential pick: write it to the node AND report it as the trusted
 * owner-pick, which is what lets a collaborator's run resolve the owner's
 * credential. Call this instead of writing credentialIds directly.
 */
export function applyCredentialSelection(
    nodeId: string,
    workflowId: string | undefined,
    newCredentialIds: Record<string, string>,
    updateNodeData: (nodeId: string, data: Record<string, unknown>) => void,
    credentialMeta?: Record<string, CredentialDisplayMeta>,
    credentialRemoved?: string[],
): void {
    updateNodeData(
        nodeId,
        buildCredentialNodeUpdate(newCredentialIds, credentialMeta, credentialRemoved) as unknown as Record<string, unknown>,
    );
    const pickedIds = Object.entries(newCredentialIds)
        .filter(([k, v]) => k !== '__agent_credentials__' && !!v)
        .map(([, v]) => v);
    if (workflowId) authorizeCredentialsForWorkflow(workflowId, pickedIds);
}
