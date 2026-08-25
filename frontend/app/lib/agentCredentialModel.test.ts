/**
 * Tests for validateAgentCredentialsForModel — the chat pre-flight credential gate.
 *
 * Regression: it rejected valid subscription-OAuth credentials (e.g.
 * agent_claude_code_oauth for claude_code — "The linked credential is for
 * claude-code-oauth, but this model routes through claude_code") because it matched
 * agent_<provider> exactly. It now delegates to getAgentCredentialIdForProvider —
 * the same resolver the credentials form + backend loader use — so the gate accepts
 * every credential they do (direct keys, OAuth aliases, opencode cross-aliases).
 */
import { describe, it, expect } from 'vitest';

import { ModelProvider } from '~/types/provider';

import {
  agentAllowsUsageBased,
  staleCredentialKeysForProvider,
  validateAgentCredentialsForModel,
  validateAgentSendCredentials,
  getAgentEffectiveModel,
  seedWrapperSubmodel,
  WRAPPER_SUBMODEL_DEFAULT_BY_MODEL,
} from './agentCredentialModel';
import { CLI_MODEL_PROVIDER } from '~/lib/agentChat';
import agentSchema from '~/schemas/nodes/agent.json';

const v = (
  effectiveProvider: string | null,
  credentialIds: Record<string, string>,
  usageBased = false,
) => validateAgentCredentialsForModel({ effectiveProvider, usageBased, credentialIds });

describe('validateAgentCredentialsForModel', () => {
  it('accepts a direct agent_<provider> credential', () => {
    expect(v('claude_code', { agent_claude_code: 'c1' })).toBeNull();
    expect(v('openrouter', { agent_openrouter: 'c1' })).toBeNull();
  });

  it('accepts a subscription-OAuth alias (the reported bug)', () => {
    expect(v('claude_code', { agent_claude_code_oauth: 'c1' })).toBeNull();
    expect(v('codex', { agent_codex_oauth: 'c1' })).toBeNull();
  });

  it('accepts opencode cross-aliases (anthropic←claude_code_oauth, openai←codex_oauth)', () => {
    expect(v('anthropic', { agent_claude_code_oauth: 'c1' })).toBeNull();
    expect(v('openai', { agent_codex_oauth: 'c1' })).toBeNull();
  });

  it('flags a genuine mismatch', () => {
    const msg = v('claude_code', { agent_slack: 'c1' });
    expect(msg).toContain('slack');
    expect(msg).toContain('claude_code');
  });

  it('allows credential-less runs only for usage-based providers', () => {
    expect(v('openrouter', {}, true)).toBeNull();
    expect(v('openrouter', {}, false)).toContain('needs a openrouter credential');
  });

  it('returns null when no provider resolved', () => {
    expect(v(null, { agent_slack: 'c1' })).toBeNull();
  });

  it('flags the original reported bug (openrouter model, stale agent_claude_code)', () => {
    // usage-based still flags a WRONG linked cred — the backend would forward it and 401.
    const err = v('openrouter', { agent_claude_code: 'abc' }, true);
    expect(err).toContain('openrouter');
    expect(err).toContain('claude-code');
  });

  it('ignores empty-string credential entries (delete-and-not-rebind shape)', () => {
    expect(v('openrouter', { agent_claude_code: '' }, true)).toBeNull();
  });

  it('allows credential-less opencode sends (opencode ships truly-free models)', () => {
    expect(v('opencode', {}, true)).toBeNull();
  });
});

describe('validateAgentSendCredentials — send-path policy (CLI harnesses are BYOK)', () => {
  // Catalog stub standing in for getModelById + inferProviderFromPrefix.
  const resolveProvider = (m: string) =>
    m.startsWith('openrouter/') ? 'openrouter' : m.startsWith('gpt') ? 'openai' : null;
  const send = (
    sendModel: string,
    config: Record<string, unknown>,
    credentialIds: Record<string, string>,
  ) => validateAgentSendCredentials({ sendModel, config, credentialIds, resolveProvider });

  it('flags a credential-less openrouter sub-model under a CLI harness (the reported gap)', () => {
    // openrouter is usage-based on the LLM path, but CLI harnesses always BYOK
    // — without a credential the run dies on the backend's OPENROUTER_API_KEY
    // error, so the pre-flight must flag it BEFORE the send.
    const err = send(
      'opencode',
      { opencode_model: 'openrouter/google/gemma-3-27b-it:free' },
      {},
    );
    expect(err).toContain('openrouter credential');
  });

  it('accepts the same sub-model once an openrouter credential is linked', () => {
    expect(send(
      'opencode',
      { opencode_model: 'openrouter/google/gemma-3-27b-it:free' },
      { agent_openrouter: 'c1' },
    )).toBeNull();
  });

  it('still allows credential-less usage-based providers on the in-process LLM path', () => {
    expect(send('openrouter/google/gemma-3-27b-it:free', {}, {})).toBeNull();
  });
});

describe('agentAllowsUsageBased — the one platform-billing rule', () => {
  it('exempts nothing when the provider is unresolved', () => {
    expect(agentAllowsUsageBased('openrouter/x', null)).toBe(false);
  });

  it('honors the provider flag on the in-process LLM path', () => {
    expect(agentAllowsUsageBased('openrouter/x', ModelProvider.OPENROUTER)).toBe(true);
    expect(agentAllowsUsageBased('groq/x', ModelProvider.GROQ)).toBe(false);
  });

  it('overrides the flag for every CLI harness', () => {
    // The harness is judged on its OWN id, so a usage-based provider reached
    // through a sandbox wrapper stays BYOK.
    for (const harness of Object.keys(CLI_MODEL_PROVIDER)) {
      expect(agentAllowsUsageBased(harness, ModelProvider.OPENROUTER), harness).toBe(false);
    }
  });

  it('treats an unrecoverable legacy CLI conversation as BYOK', () => {
    // legacy/cli means "some CLI, we don't know which" — assume BYOK rather
    // than hand it a platform-billing exemption it may not be entitled to.
    expect(agentAllowsUsageBased('legacy/cli', ModelProvider.OPENROUTER)).toBe(false);
  });
});

describe('WRAPPER_SUBMODEL_DEFAULT_BY_MODEL', () => {
  // Pin the schema-derived defaults against agent.json so a backend Pydantic
  // default change (which regenerates the schema) is caught here rather than
  // silently seeding a stale model.
  const defaultFor = (field: string): unknown => {
    const defs = (agentSchema as { $defs?: Record<string, any> }).$defs ?? {};
    for (const variant of Object.values(defs)) {
      const d = variant?.properties?.[field]?.default;
      if (d !== undefined) return d;
    }
    return undefined;
  };

  it('resolves every wrapper default straight from the schema', () => {
    expect(WRAPPER_SUBMODEL_DEFAULT_BY_MODEL.openclaw).toBe(defaultFor('openclaw_model'));
    expect(WRAPPER_SUBMODEL_DEFAULT_BY_MODEL.opencode).toBe(defaultFor('opencode_model'));
    expect(WRAPPER_SUBMODEL_DEFAULT_BY_MODEL.hermes).toBe(defaultFor('hermes_agent_model'));
  });

  it('every default is a concrete, non-empty model id', () => {
    for (const v of Object.values(WRAPPER_SUBMODEL_DEFAULT_BY_MODEL)) {
      expect(typeof v).toBe('string');
      expect(v.length).toBeGreaterThan(0);
    }
  });
});

describe('getAgentEffectiveModel', () => {
  it('resolves an explicitly-set wrapper sub-model to that provider model', () => {
    expect(
      getAgentEffectiveModel('openclaw', { openclaw_model: 'anthropic/claude-sonnet-4-5' }),
    ).toBe('anthropic/claude-sonnet-4-5');
  });

  it('falls back to the wrapper DEFAULT sub-model (not the bare id) when unset', () => {
    // The bug: an empty sub-model resolved to the bare "openclaw", mislabeling
    // the credential and demanding a nonexistent agent_openclaw key.
    expect(getAgentEffectiveModel('openclaw', {})).toBe(WRAPPER_SUBMODEL_DEFAULT_BY_MODEL.openclaw);
    expect(getAgentEffectiveModel('opencode', {})).toBe(WRAPPER_SUBMODEL_DEFAULT_BY_MODEL.opencode);
    expect(getAgentEffectiveModel('hermes', {})).toBe(WRAPPER_SUBMODEL_DEFAULT_BY_MODEL.hermes);
  });

  it('treats an empty-string sub-model the same as unset', () => {
    expect(getAgentEffectiveModel('openclaw', { openclaw_model: '   ' })).toBe(
      WRAPPER_SUBMODEL_DEFAULT_BY_MODEL.openclaw,
    );
  });

  it('returns a non-wrapper model unchanged', () => {
    expect(getAgentEffectiveModel('openrouter/openai/gpt-4o-mini', {})).toBe(
      'openrouter/openai/gpt-4o-mini',
    );
  });
});

describe('seedWrapperSubmodel', () => {
  it('seeds the default sub-model for a wrapper with no sub-model set', () => {
    expect(seedWrapperSubmodel('openclaw', {})).toEqual({
      openclaw_model: WRAPPER_SUBMODEL_DEFAULT_BY_MODEL.openclaw,
    });
    expect(seedWrapperSubmodel('opencode')).toEqual({
      opencode_model: WRAPPER_SUBMODEL_DEFAULT_BY_MODEL.opencode,
    });
  });

  it('is a no-op when the sub-model is already set (respects the user pick)', () => {
    expect(seedWrapperSubmodel('openclaw', { openclaw_model: 'anthropic/claude-sonnet-4-5' })).toEqual({});
  });

  it('reads the sub-model from a nested config shape', () => {
    expect(seedWrapperSubmodel('openclaw', { config: { openclaw_model: 'openai/gpt-5' } })).toEqual({});
  });

  it('is a no-op for non-wrapper models and empty input', () => {
    expect(seedWrapperSubmodel('openrouter/openai/gpt-4o-mini', {})).toEqual({});
    expect(seedWrapperSubmodel(undefined)).toEqual({});
    expect(seedWrapperSubmodel('')).toEqual({});
  });
});

describe('staleCredentialKeysForProvider', () => {
  const s = (linked: Record<string, string>, provider: string) =>
    staleCredentialKeysForProvider(linked, provider as ModelProvider);

  it('keeps a valid OAuth-alias credential (the reported reset-to-none bug)', () => {
    expect(s({ agent_claude_code_oauth: 'c1' }, 'claude_code')).toEqual([]);
    expect(s({ agent_codex_oauth: 'c1' }, 'codex')).toEqual([]);
    expect(s({ agent_claude_code_oauth: 'c1' }, 'anthropic')).toEqual([]); // cross-alias
  });

  it('keeps a direct credential', () => {
    expect(s({ agent_openrouter: 'c1' }, 'openrouter')).toEqual([]);
  });

  it('flags a genuinely stale credential after a provider switch', () => {
    expect(s({ agent_claude_code: 'c1' }, 'openrouter')).toEqual(['agent_claude_code']);
  });

  it('keeps the valid credential and flags only the rest', () => {
    expect(s({ agent_claude_code_oauth: 'c1', agent_slack: 'c2' }, 'claude_code')).toEqual(['agent_slack']);
  });
});
