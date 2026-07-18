// Durable, per-user localStorage marker recording that the user's onboarding
// row was persisted server-side. The dashboard's questionnaire gate reads it as
// a backstop for stale JWTs: a crash + re-login can serve a token minted before
// the onboarding row existed, which re-showed the questionnaire and re-ran its
// post-onboarding side effects (auto blank-workflow create) on an already
// onboarded user (2026-07-16 scaffold-trial incident).

const KEY_PREFIX = 'noclick_onboarding_persisted:';

export function markOnboardingPersisted(userId: string): void {
    try {
        localStorage.setItem(KEY_PREFIX + userId, 'true');
    } catch {
        // Storage unavailable (private mode / quota) — the JWT claim still gates.
    }
}

export function isOnboardingPersisted(userId: string): boolean {
    try {
        return localStorage.getItem(KEY_PREFIX + userId) === 'true';
    } catch {
        return false;
    }
}
