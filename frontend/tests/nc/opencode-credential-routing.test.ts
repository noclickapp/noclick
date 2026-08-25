// Live integration test: opencode wrapper → sub-model → provider cascade.
//
// Verifies the full chain that the AgentCredentialsForm relies on:
//   1. getAgentEffectiveModel sees opencode_model and returns the sub-model
//   2. inferProviderFromPrefix maps the sub-model prefix to a provider
//   3. PROVIDER_METADATA[provider] has the right requiredApiKeys + providerURL
//   4. allowUsageBased is false for OPENCODE (credentials mandatory)
//
// Catches the class of regressions where the routing breaks silently —
// e.g. the wrapper map forgetting opencode, the prefix function not
// recognising opencode/*, or someone restoring allowUsageBased=true.

import { nc } from '~/lib/nc';
import {
    getAgentEffectiveModel,
    inferProviderFromPrefix,
} from '~/lib/agentCredentialModel';
import { ModelProvider, getProviderMetadata } from '~/types/provider';

export default async function () {
    // ── OpenCode + Zen sub-model: stays on OPENCODE ──────────────────────
    const zenConfig = { model: 'opencode', opencode_model: 'opencode/mimo-v2-flash-free' };
    const zenEffective = getAgentEffectiveModel(zenConfig.model, zenConfig);
    nc.assert.equal(zenEffective, 'opencode/mimo-v2-flash-free', 'Zen sub-model surfaces in effectiveModel');
    nc.assert.equal(inferProviderFromPrefix(zenEffective), ModelProvider.OPENCODE, 'opencode/* prefix → OPENCODE provider');

    // ── OpenCode + Anthropic sub-model: routes to ANTHROPIC ──────────────
    const anthropicConfig = { model: 'opencode', opencode_model: 'anthropic/claude-sonnet-4-5' };
    const anthropicEffective = getAgentEffectiveModel(anthropicConfig.model, anthropicConfig);
    nc.assert.equal(anthropicEffective, 'anthropic/claude-sonnet-4-5', 'Anthropic sub-model surfaces in effectiveModel');
    nc.assert.equal(inferProviderFromPrefix(anthropicEffective), ModelProvider.ANTHROPIC, 'anthropic/* prefix → ANTHROPIC provider');

    // ── OpenCode + OpenAI sub-model: routes to OPENAI ────────────────────
    const openaiConfig = { model: 'opencode', opencode_model: 'openai/gpt-5' };
    nc.assert.equal(
        inferProviderFromPrefix(getAgentEffectiveModel(openaiConfig.model, openaiConfig)),
        ModelProvider.OPENAI,
        'openai/* prefix → OPENAI provider',
    );

    // ── Bare wrapper (no sub-model picked yet): falls back to the wrapper's
    //    DEFAULT sub-model (a real provider-prefixed id), which infers OPENCODE ──
    const bareConfig = { model: 'opencode' };
    const bareEffective = getAgentEffectiveModel(bareConfig.model, bareConfig);
    nc.assert.equal(
        inferProviderFromPrefix(bareEffective),
        ModelProvider.OPENCODE,
        'no sub-model → wrapper default → OPENCODE provider',
    );

    // ── OPENCODE provider metadata: single key + mandatory + dashboard URL ──
    const opencodeMeta = getProviderMetadata(ModelProvider.OPENCODE);
    nc.assert.truthy(opencodeMeta, 'OPENCODE metadata exists');
    nc.assert.equal(opencodeMeta!.requiredApiKeys?.length, 1, 'OPENCODE has exactly one credential alternative');
    nc.assert.equal(opencodeMeta!.requiredApiKeys?.[0].length, 1, 'that alternative has one env var');
    nc.assert.equal(opencodeMeta!.requiredApiKeys?.[0][0], 'OPENCODE_API_KEY', 'env var is OPENCODE_API_KEY');
    nc.assert.equal(opencodeMeta!.allowUsageBased, false, 'OPENCODE credentials are mandatory');
    nc.assert.equal(opencodeMeta!.providerURL, 'https://opencode.ai/auth', 'OPENCODE dashboard URL points at Zen auth');

    // ── ANTHROPIC keeps its own metadata (sub-model routing reuses it) ───
    const anthropicMeta = getProviderMetadata(ModelProvider.ANTHROPIC);
    nc.assert.truthy(anthropicMeta?.providerURL?.includes('anthropic'), 'ANTHROPIC dashboard URL points to anthropic');
    nc.assert.equal(anthropicMeta!.requiredApiKeys?.[0][0], 'ANTHROPIC_API_KEY', 'ANTHROPIC field is its own key');

    // ── Hermes wrapper still works (regression guard) ────────────────────
    const hermesConfig = { model: 'hermes', hermes_agent_model: 'openrouter/anthropic/claude-3.5-sonnet' };
    nc.assert.equal(
        inferProviderFromPrefix(getAgentEffectiveModel(hermesConfig.model, hermesConfig)),
        ModelProvider.OPENROUTER,
        'hermes + openrouter/* still routes to OPENROUTER',
    );

    // ── All 12 OpenCode picker prefixes resolve to a known provider ──────
    // Catches the original bug ("GitHub Models tab just doesn't work"):
    // any sub-model OpenCode can produce must land on a ModelProvider
    // that PROVIDER_METADATA has an entry for, with a non-empty
    // requiredApiKeys + providerURL.
    const openCodeSubModelCases: Array<[string, ModelProvider, string]> = [
        ['anthropic/claude-sonnet-4-5',          ModelProvider.ANTHROPIC,     'ANTHROPIC_API_KEY'],
        ['openai/gpt-5',                         ModelProvider.OPENAI,        'OPENAI_API_KEY'],
        ['google/gemini-2.0-flash',              ModelProvider.GEMINI,        'GEMINI_API_KEY'],
        ['xai/grok-beta',                        ModelProvider.XAI,           'XAI_API_KEY'],
        ['groq/llama-3.3-70b',                   ModelProvider.GROQ,          'GROQ_API_KEY'],
        ['deepseek/deepseek-chat',               ModelProvider.DEEPSEEK,      'DEEPSEEK_API_KEY'],
        ['mistral/mistral-large',                ModelProvider.MISTRAL,       'MISTRAL_API_KEY'],
        ['openrouter/anthropic/claude-3.5-sonnet', ModelProvider.OPENROUTER,  'OPENROUTER_API_KEY'],
        ['opencode/mimo-v2-flash-free',          ModelProvider.OPENCODE,      'OPENCODE_API_KEY'],
        ['opencode-go/some-go-model',            ModelProvider.OPENCODE,      'OPENCODE_API_KEY'],
        ['github-models/gpt-5',                  ModelProvider.GITHUB_MODELS, 'GITHUB_TOKEN'],
        ['nvidia/nemotron-3-super-120b-a12b',    ModelProvider.NVIDIA,        'NVIDIA_API_KEY'],
    ];
    for (const [subModel, expectedProvider, expectedKey] of openCodeSubModelCases) {
        const inferred = inferProviderFromPrefix(subModel);
        nc.assert.equal(inferred, expectedProvider, `prefix routing for ${subModel}`);
        const meta = getProviderMetadata(inferred!);
        nc.assert.truthy(meta, `PROVIDER_METADATA exists for ${expectedProvider}`);
        nc.assert.truthy(meta!.providerURL, `${expectedProvider} has a dashboard URL`);
        nc.assert.equal(
            meta!.requiredApiKeys?.[0]?.[0],
            expectedKey,
            `${expectedProvider} first required key is ${expectedKey}`,
        );
    }

    // ── OpenCode-Go reuses OPENCODE's credential type (key sharing) ──────
    // The user's existing OPENCODE credential MUST surface for opencode-go/
    // sub-models because they share OPENCODE_API_KEY. Catches a regression
    // where someone reintroduces a separate OPENCODE_GO enum entry.
    nc.assert.equal(
        inferProviderFromPrefix('opencode-go/anything'),
        ModelProvider.OPENCODE,
        'opencode-go/* folds into OPENCODE for credential reuse',
    );

    return {
        zenEffective,
        anthropicEffective,
        opencodeKey: opencodeMeta!.requiredApiKeys?.[0][0],
        opencodeUsageBased: opencodeMeta!.allowUsageBased,
        opencodeDashboardUrl: opencodeMeta!.providerURL,
        subModelCoverage: openCodeSubModelCases.length,
        allChecksPassed: true,
    };
}
