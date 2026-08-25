// Verifies the OAuth credential dropdown only surfaces ChatGPT Plus
// (`agent_codex_oauth`) when the selected wrapper sub-model is in the
// daily-refreshed Codex CLI list. The bug this catches: a user with a
// Codex OAuth credential picks `openai/gpt-4.1` in OpenCode → form
// happily lets them save → sandbox launch errors out with "Model X
// isn't accessible via ChatGPT Plus OAuth". With this gate, the OAuth
// credential is hidden from the dropdown for unsupported sub-models so
// the misconfiguration can't be saved in the first place.

import { nc } from '~/lib/nc';
import { isChatGptPlusSupported } from '~/lib/agentCredentialModel';
import cliModels from '~/schemas/cli-models.json';

export default async function () {
    // ── Source-of-truth alignment: the FE gate must read from the
    //   daily-refreshed _cli_models.json. Hardcoded copies of the
    //   allowlist drift the moment OpenAI ships a new model; reading
    //   the JSON keeps the FE + backend + Codex node dropdown in lock-
    //   step (the JSON also powers the codex_model dropdown).
    const codexModels = cliModels.codex.models;
    nc.assert.truthy(
        Array.isArray(codexModels) && codexModels.length > 0,
        'Codex models list is non-empty in _cli_models.json',
    );
    for (const m of codexModels) {
        nc.assert.equal(
            isChatGptPlusSupported(m),
            true,
            `${m} should be accepted (it's in the daily-refreshed list)`,
        );
    }

    // ── Reject specific known-bad ids. These are pinned because they're
    //   the cases that caused user-facing bugs — gpt-4.1 was the model
    //   the user reported in the credential-model regression. If any of these end up in the
    //   JSON one day (unlikely — they aren't Codex models), the gate
    //   would change behavior and this assertion would flag it.
    const knownUnsupported = [
        'gpt-4.1',
        'gpt-4o',
        'gpt-3.5-turbo',
        'claude-sonnet-4',
        'totally-made-up',
        '',
    ];
    for (const m of knownUnsupported) {
        nc.assert.equal(
            codexModels.includes(m),
            false,
            `${m} should not be in the Codex list (sanity check)`,
        );
        nc.assert.equal(
            isChatGptPlusSupported(m),
            false,
            `${m} should be rejected by the OAuth gate`,
        );
    }

    return {
        codexModelCount: codexModels.length,
        sampleSupported: codexModels[0],
    };
}
