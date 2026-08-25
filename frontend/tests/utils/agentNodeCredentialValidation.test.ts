// @vitest-environment jsdom
//
// Regression tests for agent-node credential detection in the PURE validation
// path — hasUnconnectedCredentials, which drives the canvas node badge, the
// guided-setup step list, and validateWorkflowNode's `missing_credentials`
// issue.
//
// Before 2026-07-25 this path answered a blanket `false` for every agent node
// (a deliberate retreat from unreliable model-name guessing), so a CLI-harness
// agent with no credential was invisible to canvas validation entirely — and
// the config panel's banner, the other half of the story, exempted opencode and
// hermes because their sub-model's provider is usage-based. Nothing complained
// anywhere until the run died on the backend's credential gate.
//
// A CLI harness needs no provider inference to classify — the harness id alone
// settles it — so that case is now decided here. LLM-path models still defer to
// useAgentCredentialsRequired, which has the model catalog.

import { describe, expect, it } from 'vitest';

// nodeSchemas pulls the full generated schema set; the credential helpers only
// read NODE_SCHEMAS['agent'].properties.credentials, which is present there.
const { hasUnconnectedCredentials } = await import('~/components/workflow/NodeCredentials');

const agentNode = (config: Record<string, unknown>) => ({ config });

const missing = (config: Record<string, unknown>, credentialIds: Record<string, string> = {}) =>
    hasUnconnectedCredentials('agent', credentialIds, agentNode(config));

describe('hasUnconnectedCredentials — CLI-harness agent nodes', () => {
    it('flags every CLI harness with no credential linked', () => {
        for (const harness of ['codex', 'claude-code', 'opencode', 'openclaw', 'hermes']) {
            expect(missing({ model: harness }), harness).toBe(true);
        }
    });

    it('flags a wrapper harness regardless of which sub-model it resolves to', () => {
        // The usage-based provider behind the sub-model is exactly what used to
        // wave these through on the config-panel side.
        expect(missing({ model: 'hermes', hermes_agent_model: 'openrouter/x/y' })).toBe(true);
        expect(missing({ model: 'opencode', opencode_model: 'anthropic/claude-sonnet-4-5' })).toBe(true);
    });

    it('clears once a primary agent credential is linked', () => {
        expect(missing({ model: 'hermes' }, { agent_openrouter: 'c1' })).toBe(false);
        expect(missing({ model: 'codex' }, { agent_codex_oauth: 'c1' })).toBe(false);
    });

    it('does not count agent_env as satisfying the requirement', () => {
        // agent_env carries sandbox env vars, never auth — it rides the same
        // credentialIds map only so the pre-delete impact scan can see it.
        expect(missing({ model: 'hermes' }, { agent_env: 'c1' })).toBe(true);
    });

    it('reads the harness off model_type when config.model is unset', () => {
        expect(missing({ model_type: 'hermes_agent' })).toBe(true);
        expect(missing({ model_type: 'openclaw' })).toBe(true);
    });
});

describe('hasUnconnectedCredentials — LLM-path agent nodes stay deferred', () => {
    it('does not flag an LLM model (the catalog-backed hook owns that call)', () => {
        // Guessing a provider from the model id here caused false positives; the
        // config panel's hook resolves it properly against the model catalog.
        expect(missing({ model: 'openrouter/google/gemma-3-27b-it:free' })).toBe(false);
        expect(missing({ model: 'anthropic/claude-sonnet-4-5' })).toBe(false);
    });

    it('does not flag an agent with no model set at all', () => {
        expect(missing({})).toBe(false);
    });
});
