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
    // CLI agent sandboxes reach their model through the credential proxy.
    credential_proxy: 'everyone',
    // Automatic refills of a prepaid balance, enforced where accounts enrol.
    auto_topup: 'everyone',
    // The Free and Member plans in place of Plus/Pro and credits.
    free_member: 'everyone',
    // The account's coordinator as an ordinary platform agent (the chat talks to it over /v1).
    coordinator_agent: 'everyone',
} satisfies Record<string, Rollout>;

export type Feature = keyof typeof FEATURE_ROLLOUT;

const FEATURE_ALLOWLIST = new Map<Feature, Set<string>>();

/** Let these accounts use an INTERNAL feature ahead of its launch; an entry starting with "@" lets in every address at that domain. */
export function allowAccounts(feature: Feature, emails: readonly string[]): void {
    const allowed = FEATURE_ALLOWLIST.get(feature) ?? new Set<string>();
    for (const email of emails) allowed.add(email.trim().toLowerCase());
    FEATURE_ALLOWLIST.set(feature, allowed);
}

export function isFeatureEnabled(feature: Feature, email: string | null | undefined): boolean {
    if ((FEATURE_ROLLOUT[feature] as Rollout) === 'everyone') return true;
    if (!email) return false;
    if (isInternalEmail(email)) return true;
    const allowed = FEATURE_ALLOWLIST.get(feature);
    const address = email.toLowerCase();
    const at = address.lastIndexOf('@');
    return !!allowed && (allowed.has(address) || (at >= 0 && allowed.has(address.slice(at))));
}

/** The signed-in user's email, published by the dashboard route on auth (`known` once it has been). */
export const featureGateState = proxy({ email: '', known: false });

export function useFeatureGate(feature: Feature): boolean {
    const { email } = useSnapshot(featureGateState);
    return isFeatureEnabled(feature, email);
}

/** Whether the signed-in account's gates are known yet: a surface that is one thing or another by gate waits for it. */
export function useFeatureGatesKnown(): boolean {
    return useSnapshot(featureGateState).known;
}
