// The agent_env credential shares the node's credentialIds map with the model
// credential. Every "switch model / swap credential" path purges `agent_*` keys to
// keep one provider credential at a time — so without isPrimaryAgentCredentialKey
// those purges silently delete the user's sandbox env vars, and the mismatch
// validator reports "the linked credential is for env". These pin both.

import { describe, expect, it } from 'vitest';
import {
    AGENT_ENV_CREDENTIAL_TYPE,
    isPrimaryAgentCredentialKey,
    staleCredentialKeysForProvider,
    validateAgentCredentialsForModel,
} from '~/lib/agentCredentialModel';

describe('isPrimaryAgentCredentialKey', () => {
    it('treats provider credentials as primary', () => {
        for (const k of ['agent_anthropic', 'agent_openrouter', 'agent_claude_code_oauth']) {
            expect(isPrimaryAgentCredentialKey(k)).toBe(true);
        }
    });

    it('treats the env bundle as secondary', () => {
        expect(isPrimaryAgentCredentialKey(AGENT_ENV_CREDENTIAL_TYPE)).toBe(false);
    });

    it('ignores non-agent keys', () => {
        expect(isPrimaryAgentCredentialKey('google_sheets_oauth')).toBe(false);
    });
});

describe('staleCredentialKeysForProvider', () => {
    it('never marks the env credential stale when the model provider changes', () => {
        const stale = staleCredentialKeysForProvider(
            { agent_openai: 'uuid-old', [AGENT_ENV_CREDENTIAL_TYPE]: 'uuid-env' },
            'anthropic' as never
        );
        expect(stale).not.toContain(AGENT_ENV_CREDENTIAL_TYPE);
        expect(stale).toContain('agent_openai');
    });
});

describe('validateAgentCredentialsForModel', () => {
    it('does not mistake the env bundle for a wrong-provider credential', () => {
        const msg = validateAgentCredentialsForModel({
            effectiveProvider: 'anthropic',
            usageBased: true,
            credentialIds: { [AGENT_ENV_CREDENTIAL_TYPE]: 'uuid-env' },
        });
        // usage-based + no primary credential linked ⇒ safe to dispatch
        expect(msg).toBeNull();
    });

    it('still flags a genuine provider mismatch', () => {
        const msg = validateAgentCredentialsForModel({
            effectiveProvider: 'anthropic',
            usageBased: true,
            credentialIds: { agent_openai: 'uuid-a', [AGENT_ENV_CREDENTIAL_TYPE]: 'uuid-env' },
        });
        expect(msg).toMatch(/openai/);
    });
});
