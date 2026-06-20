// Centralizes the "deferred-open" carry-over flows. A marketing/landing page (or
// the /i invite route) stashes an intent in sessionStorage and routes the visitor
// to /dashboard, where WorkflowBrowser materializes it once the socket connects:
//   - invite redeem      (PENDING_INVITE_KEY) -> opens the shared flow
//   - agent/MCP scaffold (SCAFFOLD_DATA_KEY)  -> creates the pre-wired agent / mcp
//   - template fork      (FORK_DATA_KEY)      -> forks the source workflow
//   - hero prompt        (HERO_PROMPT_KEY)    -> blank flow + auto-sent prompt
//
// They share one rule that previously only the invite flow honored: while ANY is
// staged, the post-onboarding auto-create (a fresh BLANK workflow for a just-
// onboarded user) must YIELD — otherwise it races/overwrites the intended open.
// That race is exactly why a built agent/mcp/connection was lost when a new user
// had to pass through onboarding before landing on the dashboard.
// hasPendingDeferredOpen() is the single yield predicate; clearPostOnboardingFlow()
// is the shared latch reset each consumer calls when it takes over.
//
// Kept server-free (imports only tiny key constants) so it rides the authed app
// bundle. Deliberately NOT imported by perf-sensitive public/landing routes —
// FORK_DATA_KEY / HERO_PROMPT_KEY are mirrored by their writers there.

import { PENDING_INVITE_KEY } from '~/lib/inviteLink';
import { SCAFFOLD_DATA_KEY } from '~/lib/agentScaffold';

// Writer lives in PublicWorkflowView (template fork deferred-open).
export const FORK_DATA_KEY = 'noclick_fork_workflow_data';
// Writer lives in the landing hero + integration connect pages.
export const HERO_PROMPT_KEY = 'noclick:hero-prompt';
// Latch set by OnboardingQuestionnaire to auto-open a blank workflow once the
// freshly onboarded user reaches the dashboard.
export const POST_ONBOARDING_FLOW_KEY = 'noclick_post_onboarding_flow';

const DEFERRED_OPEN_KEYS = [
    PENDING_INVITE_KEY,
    SCAFFOLD_DATA_KEY,
    FORK_DATA_KEY,
    HERO_PROMPT_KEY,
] as const;

/** True when a deferred-open intent is staged for the dashboard to materialize.
 *  The post-onboarding blank-create yields to it (the intent's own consumer
 *  opens the right workflow instead). */
export function hasPendingDeferredOpen(): boolean {
    if (typeof window === 'undefined') return false;
    return DEFERRED_OPEN_KEYS.some((key) => sessionStorage.getItem(key) !== null);
}

/** Clear the post-onboarding auto-create latch — called by whichever consumer
 *  (a deferred-open flow, or the blank-create itself) takes over, so it can't
 *  also fire. */
export function clearPostOnboardingFlow(): void {
    if (typeof window === 'undefined') return;
    sessionStorage.removeItem(POST_ONBOARDING_FLOW_KEY);
}
