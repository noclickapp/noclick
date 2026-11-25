// The SDK client for server code (loaders and actions that read NoClick before a page renders): it holds the app's
// key. Screens never use it; they call useClient(), whose client goes through the key proxy.
import { Account, APIConnectionError, NoClick, NoClickError, Unauthenticated, type ClientOptions } from 'noclick';
import { noclickApiKey, type AppConfig, type ConfigProblem } from './config.server';

export function serverClient(config: AppConfig, options: Omit<ClientOptions, 'apiKey' | 'baseUrl'> = {}): NoClick {
    return new NoClick({ ...options, apiKey: noclickApiKey(), baseUrl: config.apiUrl });
}

/** How long an answer about a key NoClick gave is kept: one that works for a minute, one that doesn't for a few
 *  seconds, so the page opens by itself soon after the account's owner says yes. */
const WORKS_MS = 60_000;
const REFUSED_MS = 5_000;
/** What NoClick's API says when it refuses a key it gave an app: `account_key_waiting`, `_declined`, `_revoked`… */
const GIVEN_KEY_REASON = 'account_key_';
let lastAsked: { of: string; at: number; problem: ConfigProblem | null } | null = null;

/**
 * Why a key NoClick itself gave the app doesn't work yet, as a setup problem to show in place of the app: it waits
 * for the account's owner to approve it, they said no, or it was taken away. Null when it works, when the key is one
 * somebody set (the app's own screens then say what the API refuses), and when the API couldn't be asked: nothing is
 * known then, so the app goes on and its own calls say what they meet.
 *
 * Deployed on NoClick's app hosting, this app is given its key by the platform (noclick.json says which scopes it
 * asks for), and the key starts working, with no new release, the moment the owner approves it.
 */
export async function givenKeyProblem(config: AppConfig, fetchImpl: typeof fetch = fetch): Promise<ConfigProblem | null> {
    if (!config.keyGiven) return null;
    const key = noclickApiKey();
    const of = `${config.apiUrl} ${key}`;
    const now = Date.now();
    if (lastAsked !== null && lastAsked.of === of && now - lastAsked.at < (lastAsked.problem ? REFUSED_MS : WORKS_MS)) return lastAsked.problem;
    let problem: ConfigProblem | null = null;
    try {
        await Account.status({ client: new NoClick({ apiKey: key, baseUrl: config.apiUrl, fetch: fetchImpl, maxRetries: 0 }) });
    } catch (error) {
        if (error instanceof APIConnectionError || !(error instanceof NoClickError)) {
            // The error's name and code only: its message, or the request it describes, may carry the key.
            const reason = (error as { cause?: { code?: unknown } }).cause?.code ?? (error as Error).name;
            console.error(`This app couldn't ask NoClick's API whether the key NoClick gave it works yet (${String(reason)}).`);
            return null;
        }
        const reason = error.details.reason;
        if (error instanceof Unauthenticated && typeof reason === 'string' && reason.startsWith(GIVEN_KEY_REASON)) {
            problem = {
                name: 'NOCLICK_API_KEY',
                problem: `is given to this app by NoClick, and doesn’t work yet. ${error.message}`.trim(),
                fix: `${error.nextStep ? `${error.nextStep} ` : ''}There is nothing to paste: this page opens the app once the key works.`,
                given: true,
            };
        }
    }
    lastAsked = { of, at: now, problem };
    return problem;
}
