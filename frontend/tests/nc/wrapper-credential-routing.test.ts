// Live integration test: every CLI-sandbox wrapper now renders a
// dynamic per-sub-model credential field with mandatory creds.
//
// Mirror of opencode-credential-routing.test.ts but extended across
// OpenClaw + Hermes — verifies they got the same treatment.

import { nc } from '~/lib/nc';
import {
    getAgentEffectiveModel,
    inferProviderFromPrefix,
} from '~/lib/agentCredentialModel';
import { ModelProvider, getProviderMetadata } from '~/types/provider';
import { isCliAgentModel } from '~/lib/agentChat';

export default async function () {
    // ── OpenClaw + Hermes bare-wrapper defaults: single recommended key,
    //   mandatory (allowUsageBased: false). Both default to OpenRouter
    //   since that's the typical routing path for these wrappers.
    for (const wrapper of [ModelProvider.OPENCLAW, ModelProvider.HERMES_AGENT]) {
        const meta = getProviderMetadata(wrapper);
        nc.assert.truthy(meta, `${wrapper} metadata exists`);
        nc.assert.equal(
            meta!.requiredApiKeys?.length,
            1,
            `${wrapper} has one credential alternative (was 3 before)`,
        );
        nc.assert.equal(
            meta!.requiredApiKeys?.[0]?.length,
            1,
            `${wrapper} alternative has one env var`,
        );
        nc.assert.equal(
            meta!.requiredApiKeys?.[0]?.[0],
            'OPENROUTER_API_KEY',
            `${wrapper} default key is OPENROUTER_API_KEY`,
        );
        nc.assert.equal(
            meta!.allowUsageBased,
            false,
            `${wrapper} credentials are mandatory (no NoClick fallback in sandbox)`,
        );
        nc.assert.truthy(
            meta!.providerURL?.includes('openrouter'),
            `${wrapper} dashboard URL points at OpenRouter`,
        );
    }

    // ── Sub-model field switching: OpenClaw + openclaw_model=anthropic/*
    //   routes the form to ANTHROPIC provider, same as OpenCode does.
    const openclawAnthropic = {
        model: 'openclaw',
        openclaw_model: 'anthropic/claude-sonnet-4-5',
    };
    nc.assert.equal(
        inferProviderFromPrefix(
            getAgentEffectiveModel(openclawAnthropic.model, openclawAnthropic),
        ),
        ModelProvider.ANTHROPIC,
        'OpenClaw + anthropic/* sub-model → ANTHROPIC field',
    );

    const hermesOpenai = {
        model: 'hermes',
        hermes_agent_model: 'openai/gpt-5',
    };
    nc.assert.equal(
        inferProviderFromPrefix(
            getAgentEffectiveModel(hermesOpenai.model, hermesOpenai),
        ),
        ModelProvider.OPENAI,
        'Hermes + openai/* sub-model → OPENAI field',
    );

    const hermesXai = {
        model: 'hermes',
        hermes_agent_model: 'xai/grok-beta',
    };
    nc.assert.equal(
        inferProviderFromPrefix(
            getAgentEffectiveModel(hermesXai.model, hermesXai),
        ),
        ModelProvider.XAI,
        'Hermes + xai/* sub-model → XAI API-key field',
    );

    // ── Wrapper-context allowUsageBased override: forces creds to be
    //   mandatory for any provider reached via a CLI wrapper, regardless
    //   of the upstream provider's standalone allowUsageBased setting.
    nc.assert.equal(
        isCliAgentModel('openclaw'),
        true,
        'OpenClaw is a CLI agent — wrapper-context override applies',
    );
    nc.assert.equal(
        isCliAgentModel('hermes'),
        true,
        'Hermes is a CLI agent — wrapper-context override applies',
    );

    return {
        openclawDefaultKey:
            getProviderMetadata(ModelProvider.OPENCLAW)!.requiredApiKeys?.[0]?.[0],
        hermesDefaultKey:
            getProviderMetadata(ModelProvider.HERMES_AGENT)!.requiredApiKeys?.[0]?.[0],
        openclawDashboardUrl:
            getProviderMetadata(ModelProvider.OPENCLAW)!.providerURL,
        hermesDashboardUrl:
            getProviderMetadata(ModelProvider.HERMES_AGENT)!.providerURL,
        allChecksPassed: true,
    };
}
