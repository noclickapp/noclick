// A failure's way out, as the one button a person presses: what the error itself carries (a link to pay, to connect,
// the provider's billing page for a key out of credits) or the console's page that lifts it (the cap that was reached,
// the paused user, the rule that refused it); for a run, also what the run failed on (`failedOn`: its app's build, its
// workflow, its agent). One rule for the error panel (a call the console made) and Logs (a run that failed). Where a
// page can do the fix itself (Logs' FixButton), `inPlace` says how: raise the cap in a dialog, make the connection a
// new link, resume the user's spending; the error panel follows `href`. Null where nothing a person does fixes it
// (NoClick's own failures); the error's words then say what happened.
import { CredentialDisconnected, NeedsConnection, NoClickError, PaymentRequired, PlanRequired, PolicyDenied, SpendCapExceeded, SpendingPaused, type FailedOn } from 'noclick';
import type { HrefParams } from '@/screens/console/hooks/useConsole';
import { addFundsUrl, billingSettingsUrl, pricingUrl, workflowUrl } from './site';
import { userPath } from './userFilter';

/** A fix a page does in place, instead of following the fix's link. */
export type InPlaceFix =
    | { kind: 'cap'; scope: 'user' | 'key' | 'agent' | 'project'; id: string; who: string; noun: 'cap' | 'budget'; cap: number | null; spent: number | null }
    | { kind: 'reconnect'; connection: string }
    | { kind: 'resume'; userId: string };

export interface FailureFix {
    label: string;
    href: string;
    /** On NoClick's own site or the error's own link, so it opens apart from the console. */
    external: boolean;
    inPlace?: InPlaceFix;
}

/** Where the console is and what it links to, as the error panel reads them from the console's context; the names it
 *  has read, for a label that names the thing ("Raise support-bot’s budget"). */
export interface FixPlace {
    href: (path?: string, params?: HrefParams) => string;
    site: string;
    agentName?: (id: string) => string | null;
    keyName?: (id: string) => string | null;
}

const detail = (error: NoClickError, key: string): string | undefined => (typeof error.details[key] === 'string' ? (error.details[key] as string) : undefined);

/** Whose a cap is, as a person names it: "globex", "support-bot", "the analytics key", "the app". */
export function capOwner(error: SpendCapExceeded, place: Pick<FixPlace, 'agentName' | 'keyName'>): { who: string; noun: 'cap' | 'budget' } {
    const id = detail(error, 'scope_id');
    switch (error.scope) {
        case 'user':
            return { who: id ?? 'the user', noun: 'cap' };
        case 'key': {
            const name = id ? place.keyName?.(id) : null;
            return { who: name ? `the ${name} key` : 'the key', noun: 'cap' };
        }
        case 'agent':
            return { who: (id && place.agentName?.(id)) || 'the agent', noun: 'budget' };
        case 'project':
            return { who: detail(error, 'project') ?? 'the app', noun: 'budget' };
        default:
            return { who: 'the account', noun: 'cap' };
    }
}

/** A cap that was reached: raised in place, else on the page where it's raised. */
function capFix(error: SpendCapExceeded, place: FixPlace): FailureFix {
    const { href, site } = place;
    const id = detail(error, 'scope_id');
    const { who, noun } = capOwner(error, place);
    const raise = (scope: 'user' | 'key' | 'agent' | 'project', at: string, ref: string): FailureFix => ({
        label: `Raise ${who}’s ${noun}`,
        href: at,
        external: false,
        inPlace: { kind: 'cap', scope, id: ref, who, noun, cap: error.cap ?? null, spent: error.spent ?? null },
    });
    switch (error.scope) {
        case 'key':
            if (id) return raise('key', href('keys', { key: id }), id);
            break;
        case 'user':
            if (id) return raise('user', href(userPath(id)), id);
            break;
        case 'agent':
            if (id) return raise('agent', href(`agents/${encodeURIComponent(id)}`), id);
            break;
        case 'project': {
            const app = detail(error, 'project_id') ?? id;
            if (app) return raise('project', href('resources/apps', { app }), app);
            break;
        }
    }
    return { label: 'Raise the monthly cap', href: billingSettingsUrl(site), external: true };
}

/** What a run failed on, opened where it's changed, when its error names no fix of its own. */
function failedOnFix(error: NoClickError | null, on: FailedOn | null, place: FixPlace): FailureFix | null {
    if (!on?.id) return null;
    switch (on.object) {
        case 'agent':
            return { label: `Open ${place.agentName?.(on.id) ?? 'the agent'}`, href: place.href(`agents/${encodeURIComponent(on.id)}`), external: false };
        case 'app': {
            const deployment = error ? detail(error, 'deployment_id') : undefined;
            return deployment
                ? { label: 'See the build log', href: place.href('resources/apps', { app: on.id, tab: 'deployments', deployment }), external: false }
                : { label: 'Open the app', href: place.href('resources/apps', { app: on.id }), external: false };
        }
        case 'workflow':
            return { label: 'Open the workflow', href: workflowUrl(place.site, on.id), external: true };
        default:
            return null;
    }
}

export function failureFix(error: unknown, place: FixPlace, on: FailedOn | null = null): FailureFix | null {
    const api = error instanceof NoClickError ? error : null;
    if (error instanceof PaymentRequired && error.details.reason === 'provider_out_of_funds') {
        // The model key's own account is out of credits at its provider: nothing of NoClick's to pay.
        const billing = detail(error, 'billing_url');
        return billing ? { label: 'Add credits', href: billing, external: true } : null;
    }
    if (error instanceof PaymentRequired || error instanceof PlanRequired) {
        const offer = error.offers[0];
        if (offer) return { label: offer.kind === 'plan' ? 'Choose a plan' : 'Add funds', href: offer.url, external: true };
        return error instanceof PaymentRequired ? { label: 'Add funds', href: addFundsUrl(place.site), external: true } : { label: 'See the plans', href: pricingUrl(place.site), external: true };
    }
    if (error instanceof SpendCapExceeded) return capFix(error, place);
    if (error instanceof SpendingPaused) {
        // Its `action` is what the user is shown; what lifts it is resuming them.
        const user = detail(error, 'user_id');
        return user ? { label: `Resume ${user}’s spending`, href: place.href(userPath(user)), external: false, inPlace: { kind: 'resume', userId: user } } : null;
    }
    if (error instanceof CredentialDisconnected || error instanceof NeedsConnection) {
        const label = `${error instanceof CredentialDisconnected ? 'Reconnect' : 'Connect'}${error.connection ? ` ${error.connection}` : ''}`;
        if (error.connectUrl) return { label, href: error.connectUrl, external: true };
        return error.connection ? { label, href: place.href('resources/connections'), external: false, inPlace: { kind: 'reconnect', connection: error.connection } } : null;
    }
    if (error instanceof PolicyDenied) return { label: 'Open approval rules', href: place.href('approval-rules'), external: false };
    return failedOnFix(api, on, place);
}
