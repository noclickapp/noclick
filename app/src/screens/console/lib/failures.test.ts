// A failed run in words and its fix, from what the API says of it (its error and `failed_on`): never an API route in
// the words, and the fix the console's one rule gives the same error anywhere, done in place where Logs can.
import { describe, expect, it } from 'vitest';
import { CredentialDisconnected, InvalidRequest, NoClickError, PaymentRequired, SpendCapExceeded, SpendingPaused, type FailedOn, type JsonObject } from 'noclick';
import type { FixPlace } from './failureFix';
import { failureWords, plainWords, touched } from './failures';

const place: FixPlace = {
    href: (path = '', params = {}) => `/developers/${path}${Object.keys(params).length ? `?${new URLSearchParams(params as Record<string, string>)}` : ''}`,
    site: 'https://noclick.com',
    agentName: (id) => ({ ag_1: 'support-bot', ag_2: 'concierge' })[id] ?? null,
    keyName: (id) => (id === 'key_1' ? 'analytics' : null),
};

const CLASSES: Record<string, typeof NoClickError> = {
    spend_cap_exceeded: SpendCapExceeded,
    payment_required: PaymentRequired,
    credential_disconnected: CredentialDisconnected,
    spending_paused: SpendingPaused,
    invalid_request: InvalidRequest,
};

/** An error as the SDK reads one off a failed operation. */
function error(type: string, message: string, details: JsonObject = {}): NoClickError {
    const made = new (CLASSES[type] ?? NoClickError)(message, { details });
    made.type = type;
    return made;
}

const words = (e: NoClickError, on: FailedOn | null, count: number | null = 3) => failureWords(e, on, count, place);

describe('failureWords', () => {
    it('says which cap stopped the runs, and raises it in place', () => {
        const cap = error('spend_cap_exceeded', "The user's spend cap of $20 this month is used up.", { scope: 'user', scope_id: 'globex', cap: 20, spent: 20.41, resets_at: '2026-10-01T00:00:00Z' });
        expect(words(cap, { object: 'cap', scope: 'user', id: 'globex' })).toEqual({
            what: '3 runs stopped at globex’s cap',
            detail: 'globex has used its $20 cap this month; it resets Oct 1.',
            fix: {
                label: 'Raise globex’s cap',
                href: '/developers/users/globex',
                external: false,
                inPlace: { kind: 'cap', scope: 'user', id: 'globex', who: 'globex', noun: 'cap', cap: 20, spent: 20.41 },
            },
        });
        const budget = words(error('spend_cap_exceeded', 'Used up.', { scope: 'agent', scope_id: 'ag_1', cap: 50 }), { object: 'cap', scope: 'agent', id: 'ag_1' }, null);
        expect([budget.what, budget.fix?.label]).toEqual(['Stopped at support-bot’s budget', 'Raise support-bot’s budget']);
        const key = words(error('spend_cap_exceeded', 'Used up.', { scope: 'key', scope_id: 'key_1', cap: 20 }), { object: 'cap', scope: 'key', id: 'key_1' });
        expect([key.what, key.detail]).toEqual(['3 runs stopped at the analytics key’s cap', 'The analytics key has used its $20 cap this month.']);
        // The account's own cap is raised where its owner sets it.
        expect(words(error('spend_cap_exceeded', 'The account’s cap is reached.', { scope: 'account', cap: 100 }), { object: 'cap', scope: 'account', id: null }).fix).toEqual({
            label: 'Raise the monthly cap',
            href: 'https://noclick.com/dashboard?tab=settings&section=billing',
            external: true,
        });
    });

    it('tells a model key out of credits at its provider from the account out of funds', () => {
        const provider = error('payment_required', 'Your Claude account has no API credits.', {
            reason: 'provider_out_of_funds',
            connection: 'credential:c1',
            connection_name: 'Claude key',
            billing_url: 'https://platform.claude.com/settings/billing',
        });
        expect(words(provider, { object: 'connection', id: 'credential:c1' }, 2)).toEqual({
            what: '2 runs stopped: Claude key is out of credits',
            detail: 'Your Claude account has no API credits.',
            fix: { label: 'Add credits', href: 'https://platform.claude.com/settings/billing', external: true },
        });
        const funds = words(error('payment_required', "Your account can't pay for this: $0.00 left. Add funds in the console."), { object: 'account', id: null });
        expect(funds.fix).toEqual({ label: 'Add funds', href: 'https://noclick.com/dashboard?action=topup', external: true });
    });

    it('reconnects a disconnected connection in place, and resumes a paused user', () => {
        expect(words(error('credential_disconnected', "The 'gmail' connection is disconnected.", { connection: 'gmail' }), { object: 'connection', id: 'gmail' }, 1)).toEqual({
            what: '1 run couldn’t use gmail: it’s disconnected',
            detail: null,
            fix: { label: 'Reconnect gmail', href: '/developers/resources/connections', external: false, inPlace: { kind: 'reconnect', connection: 'gmail' } },
        });
        expect(words(error('spending_paused', 'Paused.', { user_id: 'acme' }), { object: 'user', id: 'acme' }).fix?.inPlace).toEqual({ kind: 'resume', userId: 'acme' });
    });

    it('opens what a run failed on where its error names no fix', () => {
        const build = words(error('build_failed', 'Build step failure.', { deployment_id: 'dep_1' }), { object: 'app', id: 'app_1' }, 1);
        expect(build.fix?.href).toBe('/developers/resources/apps/app_1?deployment=dep_1');
        const step = words(error('platform_error', "Step 'sheets' failed: bad range.", { reason: 'run_failed' }), { object: 'workflow', id: 'wf_1' });
        expect([step.what, step.fix?.label, step.fix?.href]).toEqual(['3 runs failed at a step', 'Open the workflow', 'https://noclick.com/dashboard?workflow=wf_1']);
        const refused = words(error('invalid_request', "The connection holds a ChatGPT plan, which doesn't run 'gpt-6'."), { object: 'agent', id: 'ag_2' }, 1);
        expect([refused.what, refused.fix?.label]).toEqual(['1 run was refused for its settings', 'Open concierge']);
    });

    it("says NoClick's own failures are its own, with nothing to fix", () => {
        const cut = error('platform_error', 'NoClick restarted while this was running.', { reason: 'interrupted' });
        expect([words(cut, null, 1).what, words(cut, null, null).what, words(cut, null).fix]).toEqual([
            '1 run was cut off when NoClick restarted',
            'Cut off when NoClick restarted',
            null,
        ]);
        expect(words(error('platform_error', 'The operation failed unexpectedly.'), null)).toEqual({ what: '3 runs failed on NoClick’s side', detail: null, fix: null });
    });
});

it('leaves out of the words every sentence naming an API route', () => {
    expect(plainWords("The user's cap is used up. Raise it with PATCH /v1/users/{id}, or wait. Reconnect it (POST .../connect_links).")).toBe("The user's cap is used up.");
    expect(plainWords('Read the workflow (GET /v1/workflows/{id}).')).toBeNull();
});

it('names who a cause touched in a few words', () => {
    const none = { agentIds: [], agentCount: 0, userIds: [], userCount: 0, keyIds: [], keyCount: 0 };
    expect(touched({ ...none, agentIds: ['ag_1'], agentCount: 1, userIds: ['globex'], userCount: 1 }, place)).toBe('support-bot for globex');
    expect(touched({ ...none, agentIds: ['ag_1', 'ag_2'], agentCount: 3, userIds: ['a', 'b'], userCount: 2 }, place)).toBe('support-bot and 2 more for 2 users');
    expect(touched({ ...none, keyIds: ['key_1'], keyCount: 1 }, place)).toBe('the analytics key');
});
