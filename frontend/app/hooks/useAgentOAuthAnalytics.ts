// Funnel instrumentation for the harness subscription-OAuth flows (Connect
// with a Claude account or ChatGPT). One shared hook so both components emit
// identical event/property shapes and failures can be
// diagnosed by provider and stage.

import { useMemo } from 'react';
import { useAnalytics } from '~/lib/analytics';
import { EVENTS } from '~/lib/analytics-events';

export type AgentOAuthProvider = 'claude_code' | 'codex';
export type AgentOAuthStage = 'start' | 'exchange' | 'poll';

export function useAgentOAuthAnalytics(provider: AgentOAuthProvider) {
    const { logActivity } = useAnalytics();
    return useMemo(
        () => ({
            started: () => logActivity(EVENTS.AGENT_OAUTH_STARTED, { provider }),
            completed: () => logActivity(EVENTS.AGENT_OAUTH_COMPLETED, { provider }),
            failed: (stage: AgentOAuthStage, message?: string) =>
                logActivity(EVENTS.AGENT_OAUTH_FAILED, {
                    provider,
                    stage,
                    message: (message || '').slice(0, 200),
                }),
        }),
        [logActivity, provider],
    );
}
