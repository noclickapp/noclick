// AI Fill asks the drafter for one step without writing it, and its answer becomes the canvas's own node update:
// settings into the step's config (a removed one as null), its notes top-level, nothing when it drafted nothing.
import { describe, expect, it } from 'vitest';
import { NoClick } from 'noclick';
import { draftAsUpdate, draftStep } from './aiFill';

type Seen = { method: string; path: string; body: unknown };

function drafter(answer: Record<string, unknown>) {
    const seen: Seen[] = [];
    const fetch = (async (input: RequestInfo | URL, init?: RequestInit) => {
        const url = new URL(String(input));
        const body = init?.body ? JSON.parse(String(init.body)) : null;
        seen.push({ method: init?.method ?? 'GET', path: url.pathname, body });
        const json = (value: unknown) => new Response(JSON.stringify(value), { status: 200, headers: { 'content-type': 'application/json' } });
        if (url.pathname === '/v1/workflows/wf_1/drafts') {
            return json({ object: 'operation', id: 'op_draft', kind: 'workflow.draft', status: 'running' });
        }
        if (url.pathname.startsWith('/v1/operations/op_draft')) {
            return json({ object: 'operation', id: 'op_draft', kind: 'workflow.draft', status: 'succeeded', result: answer });
        }
        return new Response('{}', { status: 404 });
    }) as typeof window.fetch;
    return { client: new NoClick({ apiKey: 'nk_test', baseUrl: 'https://api.test', maxRetries: 0, fetch }), seen };
}

describe('AI Fill', () => {
    it('drafts one setting of one step, writing nothing, and reads back its draft', async () => {
        const draft = { drafted: true, error: null, changes: { settings: { subject: 'Weekly digest' } } };
        const { client, seen } = drafter({ steps: { send: draft } });
        expect(await draftStep(client, 'wf_1', 'send', 'single_field', 'subject')).toEqual(draft);
        expect(seen[0]).toEqual({
            method: 'POST',
            path: '/v1/workflows/wf_1/drafts',
            body: { steps: [{ id: 'send' }], mode: 'field', write: false, field: 'subject' },
        });
    });

    it('asks for the whole step without naming a setting', async () => {
        const { client, seen } = drafter({ steps: { send: { drafted: true, error: null, changes: null } } });
        await draftStep(client, 'wf_1', 'send', 'full');
        expect(seen[0].body).toEqual({ steps: [{ id: 'send' }], mode: 'full', write: false });
    });

    it('fails when the draft names no result for the step', async () => {
        const { client } = drafter({ steps: {} });
        await expect(draftStep(client, 'wf_1', 'send', 'fields')).rejects.toThrow('no result for this step');
    });

    it('becomes the step’s update: settings into its config, a removed one as null, its notes top-level', () => {
        expect(
            draftAsUpdate({
                drafted: true,
                error: null,
                changes: { operation: 'send_email', settings: { to: '{{ $("hook").email }}', cc: null, userFields: ['from'], goal: 'Mail the digest' } },
            })
        ).toEqual({
            operation: 'send_email',
            config: { to: '{{ $("hook").email }}', cc: null },
            userFields: ['from'],
            goal: 'Mail the digest',
        });
    });

    it('is nothing when the drafter changed nothing', () => {
        expect(draftAsUpdate({ drafted: false, error: null, changes: null })).toBeNull();
        expect(draftAsUpdate({ drafted: true, error: null, changes: { settings: {} } })).toBeNull();
    });
});
