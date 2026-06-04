// Generic per-user "show this once" primitive for onboarding coachmarks and
// product announcements. Server-backed (cross-device) and added with no backend
// work: it rides the EXISTING OnboardingProvider — every flag loads in the
// single onboarding:completion:get that provider already fires, and writes go
// through its generic deep-merging onboarding:completion:update. Flags live
// under user_onboarding_completion.data.seen_once.{key}.
//
// The onboarding context is the single source of truth; the provider mirrors it
// to localStorage for synchronous, flash-free reads on the next load. Shipping a
// new one-time moment later is one line: const [seen, markSeen] = useSeenOnce('my_key').

import { useCallback } from 'react';
import { useOnboardingContext } from '~/hooks/useGetStartedChecklist';

// The known set of one-time keys. Add one line per future coachmark/announcement.
export type SeenOnceKey =
    | 'invite_walkthrough' // find-the-link tour — marked seen ONLY when it actually completes
    | 'invite_banner_disabled'; // "Don't show again" on the inline invite banner

export function useSeenOnceState(key: SeenOnceKey) {
    // completionData is seeded synchronously from the localStorage mirror, so the
    // read below is correct on first paint (no flash). hasLoaded === server get resolved.
    const { completionData, setCompletionData, hasLoaded, updateBackend } = useOnboardingContext();

    const seen = completionData.seen_once?.[key] === true; // missing key => false

    const markSeen = useCallback(() => {
        let didUpdate = false;
        setCompletionData((prev) => {
            if (prev.seen_once?.[key]) return prev; // idempotent: no re-emit
            didUpdate = true;
            return { ...prev, seen_once: { ...(prev.seen_once ?? {}), [key]: true } };
        });
        // Backend write outside the state updater (updaters must be pure), matching
        // the existing markComplete/markWelcomeSeen idiom. The provider's cache
        // effect mirrors the new blob to localStorage automatically.
        setTimeout(() => {
            if (didUpdate) updateBackend({ seen_once: { [key]: true } });
        }, 0);
    }, [key, setCompletionData, updateBackend]);

    return { seen, markSeen, hydrated: hasLoaded } as const;
}

export function useSeenOnce(key: SeenOnceKey): [boolean, () => void] {
    const { seen, markSeen } = useSeenOnceState(key);
    return [seen, markSeen];
}

// Read-only sugar for "should I show X?" call sites that don't own the mark.
export const useHasSeenOnce = (key: SeenOnceKey): boolean => useSeenOnceState(key).seen;
