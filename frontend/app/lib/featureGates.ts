// Per-account rollout of features that are built but not yet for everyone.
//
// Mirrors backend/utils/feature_gates.py, which is the enforcement point: this
// side only decides whether to show a surface. INTERNAL resolves through
// isInternalEmail — the module the self-hosted export replaces — so a feature
// reaches self-hosters when it flips to EVERYONE here and on the backend.
// Single accounts piloting an INTERNAL feature are let in by `allowAccounts`,
// which the hosted bootstrap calls; the staff list is never a rollout list.
import { proxy, useSnapshot } from 'valtio';
import { isInternalEmail } from '~/lib/internalUsers';

type Rollout = 'internal' | 'everyone';

export const FEATURE_ROLLOUT = {
    // Verified phone linking (Settings → Phone) and the channels keyed on it.
    phone_channel: 'everyone',
    // The account coordinator, on every channel.
    coordinator: 'everyone',
    // Buying phone numbers for the Phone node.
    phone_numbers: 'everyone',
} satisfies Record<string, Rollout>;

export type Feature = keyof typeof FEATURE_ROLLOUT;

const FEATURE_ALLOWLIST = new Map<Feature, Set<string>>();

/** Let these accounts use an INTERNAL feature ahead of its launch. */
export function allowAccounts(feature: Feature, emails: readonly string[]): void {
    const allowed = FEATURE_ALLOWLIST.get(feature) ?? new Set<string>();
    for (const email of emails) allowed.add(email.trim().toLowerCase());
    FEATURE_ALLOWLIST.set(feature, allowed);
}

export function isFeatureEnabled(feature: Feature, email: string | null | undefined): boolean {
    if ((FEATURE_ROLLOUT[feature] as Rollout) === 'everyone') return true;
    if (!email) return false;
    return isInternalEmail(email) || (FEATURE_ALLOWLIST.get(feature)?.has(email.toLowerCase()) ?? false);
}

/** The signed-in user's email, published by the dashboard route on auth. */
export const featureGateState = proxy({ email: '' });

export function useFeatureGate(feature: Feature): boolean {
    const { email } = useSnapshot(featureGateState);
    return isFeatureEnabled(feature, email);
}
