// Per-account rollout of features that are built but not yet for everyone.
//
// Mirrors backend/utils/feature_gates.py, which is the enforcement point: this
// side only decides whether to show a surface. INTERNAL resolves through
// isInternalEmail — the module the self-hosted export replaces — so a feature
// reaches self-hosters when it flips to EVERYONE here and on the backend.
import { proxy, useSnapshot } from 'valtio';
import { isInternalEmail } from '~/lib/internalUsers';

type Rollout = 'internal' | 'everyone';

export const FEATURE_ROLLOUT = {
    // Verified phone linking (Settings → Phone) and the channels keyed on it.
    phone_channel: 'internal',
    // The account coordinator (Dashboard dock; later WhatsApp and calls).
    coordinator: 'internal',
} satisfies Record<string, Rollout>;

export type Feature = keyof typeof FEATURE_ROLLOUT;

export function isFeatureEnabled(feature: Feature, email: string | null | undefined): boolean {
    if ((FEATURE_ROLLOUT[feature] as Rollout) === 'everyone') return true;
    return !!email && isInternalEmail(email);
}

/** The signed-in user's email, published by the dashboard route on auth. */
export const featureGateState = proxy({ email: '' });

export function useFeatureGate(feature: Feature): boolean {
    const { email } = useSnapshot(featureGateState);
    return isFeatureEnabled(feature, email);
}
