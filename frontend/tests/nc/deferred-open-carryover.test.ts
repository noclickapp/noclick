// Verifies the shared deferred-open carry-over helper that standardizes how
// invite / scaffold (agent+mcp+connect) / fork / hero-prompt intents survive the
// sign-in + onboarding round-trip. The post-onboarding blank-create yields while
// any of these is staged (hasPendingDeferredOpen), and each consumer clears the
// onboarding latch (clearPostOnboardingFlow). Regression guard for built
// agents/mcps/connections being dropped when a new user passes through onboarding.

import { nc } from '~/lib/nc';
import {
    hasPendingDeferredOpen,
    clearPostOnboardingFlow,
    FORK_DATA_KEY,
    HERO_PROMPT_KEY,
    POST_ONBOARDING_FLOW_KEY,
} from '~/lib/deferredOpen';
import { PENDING_INVITE_KEY } from '~/lib/inviteLink';
import { SCAFFOLD_DATA_KEY } from '~/lib/agentScaffold';

export default async function () {
    const TRIGGER_KEYS = [PENDING_INVITE_KEY, SCAFFOLD_DATA_KEY, FORK_DATA_KEY, HERO_PROMPT_KEY];
    const ALL_KEYS = [...TRIGGER_KEYS, POST_ONBOARDING_FLOW_KEY];

    // Snapshot + clear so we don't disturb a real staged intent in this session.
    const saved: Record<string, string | null> = {};
    for (const k of ALL_KEYS) {
        saved[k] = sessionStorage.getItem(k);
        sessionStorage.removeItem(k);
    }

    try {
        // Nothing staged -> no yield.
        nc.assert.falsy(hasPendingDeferredOpen(), 'no deferred-open when nothing staged');

        // Each trigger key independently makes the post-onboarding create yield.
        for (const k of TRIGGER_KEYS) {
            sessionStorage.setItem(k, k === SCAFFOLD_DATA_KEY ? '{"workflowData":{}}' : 'x');
            nc.assert.truthy(hasPendingDeferredOpen(), `staged ${k} should yield`);
            sessionStorage.removeItem(k);
            nc.assert.falsy(hasPendingDeferredOpen(), `cleared ${k} should not yield`);
        }

        // The onboarding latch alone is NOT a deferred-open intent.
        sessionStorage.setItem(POST_ONBOARDING_FLOW_KEY, 'true');
        nc.assert.falsy(hasPendingDeferredOpen(), 'post-onboarding latch is not a deferred-open intent');

        // clearPostOnboardingFlow drops the latch (how each consumer cancels the blank-create).
        clearPostOnboardingFlow();
        nc.assert.equal(sessionStorage.getItem(POST_ONBOARDING_FLOW_KEY), null, 'latch cleared');
    } finally {
        // Restore the session exactly as it was.
        for (const k of ALL_KEYS) {
            if (saved[k] === null) sessionStorage.removeItem(k);
            else sessionStorage.setItem(k, saved[k] as string);
        }
    }

    return { ok: true, triggerKeys: TRIGGER_KEYS };
}
