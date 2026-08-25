import { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react';
import type { SetURLSearchParams } from 'react-router';
import { getInitialHasSeenWelcome, useOnboardingContext } from '~/hooks/useOnboarding';

interface UseWelcomeFlowParams {
    /** True when the URL has `?new=true`, i.e. the workflow was just created. */
    isNewWorkflow: boolean;
    /** Ref to the latest setSearchParams setter, so we can clean up ?new=true. */
    setSearchParamsRef: React.MutableRefObject<SetURLSearchParams>;
}

// Orchestrates the first-time-user welcome experience for a freshly created
// workflow: fires a confetti burst, clears the ?new=true URL param, and
// unblocks the FlowHelperView expansion gate.
//
// Consumers read `confettiTrigger` (increments on each welcome event) and
// `expansionBlocked` (blocks auto-expansion until the animation completes).
export function useWelcomeFlow({ isNewWorkflow, setSearchParamsRef }: UseWelcomeFlowParams) {
    const { completionData, hasLoaded, markWelcomeSeen } = useOnboardingContext();

    // The gate only defers FlowHelper auto-expansion until a NEW workflow's
    // welcome animation completes, so it only applies to new workflows. An
    // existing flow (e.g. a shared one opened via an invite) has no welcome to
    // wait for — never block it, or a brand-new user who joins someone else's
    // flow (no ?new=true, and no prior welcome) would be blocked forever and
    // could never open FlowHelper. Returning users on a new workflow (localStorage
    // has hasSeenWelcome) also unblock immediately; only first-time users on a new
    // workflow stay blocked until welcome completes.
    const [expansionBlocked, setExpansionBlocked] = useState(
        () => isNewWorkflow && getInitialHasSeenWelcome() !== true
    );

    const [confettiTrigger, setConfettiTrigger] = useState(0);
    const hasTriggeredWelcomeRef = useRef(false);

    const triggerWelcomeExperience = useCallback(() => {
        if (hasTriggeredWelcomeRef.current) return;
        hasTriggeredWelcomeRef.current = true;

        markWelcomeSeen();

        // Delay confetti until the browser is idle so it doesn't compete with
        // the workflow load; fall back to a small timeout for older browsers.
        const fireConfetti = () => setConfettiTrigger((prev) => prev + 1);
        if ('requestIdleCallback' in window) {
            requestIdleCallback(fireConfetti, { timeout: 300 });
        } else {
            setTimeout(fireConfetti, 150);
        }

        // Clean up the ?new=true URL param and unblock FlowHelper shortly after
        // the confetti starts playing.
        setTimeout(() => {
            setSearchParamsRef.current(
                (prev) => {
                    const newParams = new URLSearchParams(prev);
                    newParams.delete('new');
                    return newParams;
                },
                { replace: true }
            );
            setExpansionBlocked(false);
        }, 100);
    }, [markWelcomeSeen, setSearchParamsRef]);

    // Fast path: called synchronously before paint so `hasTriggeredWelcomeRef`
    // is set before anything renders — prevents the slow-path effect from
    // double-firing once the backend state resolves. The confetti/URL cleanup
    // inside triggerWelcomeExperience still defer to idle/timeout (intentional:
    // don't block paint on animation), so this is about guarding state, not
    // about visual timing.
    useLayoutEffect(() => {
        if (isNewWorkflow && getInitialHasSeenWelcome() !== true) {
            triggerWelcomeExperience();
        }
    }, [isNewWorkflow, triggerWelcomeExperience]);

    // Slow path: once the backend-loaded onboarding state is authoritative,
    // either fire welcome (first-time user on new workflow) or unblock
    // expansion (returning user whose localStorage cache was stale/missing).
    useEffect(() => {
        if (!hasLoaded) return;
        if (isNewWorkflow && !completionData.has_seen_welcome && !hasTriggeredWelcomeRef.current) {
            triggerWelcomeExperience();
        } else if (completionData.has_seen_welcome && expansionBlocked) {
            setExpansionBlocked(false);
        }
    }, [hasLoaded, completionData.has_seen_welcome, isNewWorkflow, triggerWelcomeExperience, expansionBlocked]);

    return { confettiTrigger, expansionBlocked };
}
