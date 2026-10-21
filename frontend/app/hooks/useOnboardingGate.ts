import { useEffect, useRef, useState } from 'react';
import { SCAFFOLD_DATA_KEY } from '~/lib/agentScaffold';
import {
    isOnboardingPersisted,
    markOnboardingPersisted,
} from '~/lib/onboardingLocal';

export type OnboardingGate = 'pending' | 'questionnaire' | 'dashboard';

/** Whether the dashboard opens on the onboarding questionnaire.
 *
 *  The token's `onboarding_completed` claim is all the server knows. This browser can know more, in storage the server
 *  never sees: an invite being redeemed (its redemption onboards the joiner), an agent or MCP set up from its page
 *  (it opens that workflow instead), or the marker an earlier onboarding left behind a token minted before it. So a
 *  user the claim calls un-onboarded is `pending` until hydration, on the server and in the browser's first render
 *  alike, and only then does the browser decide. Deciding in the first render drew the questionnaire on the server
 *  and the dashboard in the browser, and React threw the server's page away.
 *
 *  `onPersisted` runs when an invite redemption or a scaffold reports the onboarding row written, so the caller can
 *  refresh the token whose claim then flips. */
export function useOnboardingGate(
    userId: string,
    claimed: boolean,
    onPersisted: () => void
) {
    const [hydrated, setHydrated] = useState(false);
    // Instant reveal after the questionnaire is submitted.
    const [completed, setCompleted] = useState(false);
    // Invite joiners arrive from /i/<token> with the redemption pending; a failed one un-suppresses the questionnaire,
    // since the server never created the joiner's onboarding row.
    const [pendingInvite, setPendingInvite] = useState(
        () =>
            typeof window !== 'undefined' &&
            !!sessionStorage.getItem('noclick_pending_invite')
    );
    // The scaffold sits in sessionStorage from the marketing page through sign-in until WorkflowBrowser materializes it
    // (which persists the skip server-side, so later sessions don't ask either).
    const [scaffold] = useState(
        () =>
            typeof window !== 'undefined' &&
            !!sessionStorage.getItem(SCAFFOLD_DATA_KEY)
    );
    // Durable backstop for a stale token: a crash and re-login can serve one minted before the onboarding row existed.
    const [persisted] = useState(
        () => typeof window !== 'undefined' && isOnboardingPersisted(userId)
    );
    const persistedRef = useRef(onPersisted);
    persistedRef.current = onPersisted;

    useEffect(() => setHydrated(true), []);

    useEffect(() => {
        const onRedeemed = () => {
            setCompleted(true);
            markOnboardingPersisted(userId);
            persistedRef.current();
        };
        const onFailed = () => setPendingInvite(false);
        document.addEventListener('noclick:invite:onboarded', onRedeemed);
        document.addEventListener('noclick:onboarding:persisted', onRedeemed);
        document.addEventListener('noclick:invite:onboard-failed', onFailed);
        return () => {
            document.removeEventListener(
                'noclick:invite:onboarded',
                onRedeemed
            );
            document.removeEventListener(
                'noclick:onboarding:persisted',
                onRedeemed
            );
            document.removeEventListener(
                'noclick:invite:onboard-failed',
                onFailed
            );
        };
    }, [userId]);

    const complete = () => {
        setCompleted(true);
        markOnboardingPersisted(userId);
    };

    let gate: OnboardingGate = 'dashboard';
    if (!claimed && !completed) {
        if (!hydrated) gate = 'pending';
        else if (!pendingInvite && !scaffold && !persisted)
            gate = 'questionnaire';
    }
    return { gate, complete };
}
