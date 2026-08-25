// Hook to determine if an agent node requires credentials based on its selected model.
// Uses the same logic as AgentCredentialsForm for consistency.

import { useMemo } from 'react';
import { useModels } from '~/hooks/useModels';
import {
    agentAllowsUsageBased,
    getAgentEffectiveModel,
    getAgentSelectedModel,
    getAgentCredentialIdForProvider,
    inferProviderFromPrefix,
    type AgentConfigRecord,
} from '~/lib/agentCredentialModel';

interface UseAgentCredentialsRequiredResult {
    /** Whether credentials are required for this model (provider doesn't support usage-based billing) */
    credentialsRequired: boolean;
    /** Whether the provider supports usage-based billing */
    allowUsageBased: boolean;
    /** The detected provider name */
    provider: string | null;
}

/**
 * Determines if an agent node requires credentials based on the selected model.
 * Uses the models database to look up the provider and check if usage-based billing is available.
 *
 * @param model - The model ID (e.g., "openrouter/openai/gpt-4o-mini", "anthropic.claude-opus-4:0")
 * @param credentialIds - Node credential mapping; only the active provider's key counts
 */
export function useAgentCredentialsRequired(
    model: string | undefined,
    credentialIds: Record<string, string>,
    config?: AgentConfigRecord
): UseAgentCredentialsRequiredResult {
    const { getModelById } = useModels();
    // A wrapper harness bills against its SUB-model's provider but is exempt
    // from usage-based billing by its own identity, so both are needed.
    const selectedModel = getAgentSelectedModel(model, config);
    const effectiveModel = getAgentEffectiveModel(model, config);

    return useMemo(() => {
        const provider =
            getModelById(effectiveModel)?.provider ??
            inferProviderFromPrefix(effectiveModel);

        // Model not found in database - default to requiring credentials to be safe
        if (!provider) {
            return { credentialsRequired: true, allowUsageBased: false, provider: null };
        }

        const allowUsageBased = agentAllowsUsageBased(selectedModel, provider);
        const hasCredentials = Boolean(
            getAgentCredentialIdForProvider(credentialIds, provider)
        );
        return {
            credentialsRequired: !allowUsageBased && !hasCredentials,
            allowUsageBased,
            provider,
        };
    }, [selectedModel, effectiveModel, credentialIds, getModelById]);
}
