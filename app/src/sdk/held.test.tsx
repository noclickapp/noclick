// @vitest-environment happy-dom
// A call NoClick holds for the account's owner, as the screen that made it follows it: the 402 read as a held call
// (never another approval), where it went in words, then its state on the approval's frames alone: waiting, approved and
// running, then done with the call's answer, or declined, expired or withdrawn with why. Nothing asks on a timer: the
// only reads are one when it's held, one on each frame or reset, and, approved, one wait the server holds to its end.
import { act, cleanup, render, screen } from '@testing-library/react';
import { ApprovalRequired, NoClick, NoClickError } from 'noclick';
import { afterEach, describe, expect, it } from 'vitest';
import { ClientProvider } from '@/sdk/client';
import { createWorkLive, WorkLiveContext, type WorkLive } from '@/sdk/live';
import { HeldCallNotice } from '@/ui/HeldCallNotice';
import { followHeldCall, heldCallOf, sentWords, type HeldCall, type HeldState } from './held';

afterEach(cleanup);

const HELD = { approval_id: 'apr_1', operation_id: 'op_held', sent_to: ['email'], summary: 'Release +1 567 483 3618', status: 'awaiting_approval' };

function required(details: Record<string, unknown> = HELD): ApprovalRequired {
    return new ApprovalRequired('It waits for the account’s owner.', { details });
}

/** An operation as the API answers it. */
const op = (status: string, extra: Record<string, unknown> = {}) => ({ object: 'operation', id: 'op_held', kind: 'gate.held_call', status, ...extra });

/** A client whose API answers the held call's reads from `answers` in turn (the last one again once they run out),
 *  holding each wait until `release()`; `reads` lists what was asked. */
function api(answers: Record<string, unknown>[]) {
    const reads: string[] = [];
    const queue = [...answers];
    let release: (() => void) | null = null;
    const fetch: typeof globalThis.fetch = async (input) => {
        const url = new URL(typeof input === 'string' ? input : input instanceof URL ? input.href : input.url);
        reads.push(url.pathname);
        if (url.pathname.endsWith('/wait')) await new Promise<void>((done) => (release = done));
        const body = queue.length > 1 ? queue.shift()! : queue[0];
        return new Response(JSON.stringify(body), { status: 200, headers: { 'Content-Type': 'application/json' } });
    };
    return {
        client: new NoClick({ apiKey: 'a-fixture-holds-no-key', baseUrl: 'https://api.test', fetch, maxRetries: 0 }),
        reads,
        release: () => release?.(),
    };
}

const settle = () => act(async () => void (await new Promise((done) => setTimeout(done, 0))));

function follow(client: NoClick, live: WorkLive, held: HeldCall) {
    const states: HeldState[] = [];
    const follower = followHeldCall(client, live, held, (state) => states.push(state));
    return { states, follower };
}

describe('a held call', () => {
    it('is read from a 402 that holds the call itself, never from another approval or error', () => {
        expect(heldCallOf(required())).toEqual({
            approvalId: 'apr_1',
            operationId: 'op_held',
            sentTo: ['email'],
            approver: null,
            summary: 'Release +1 567 483 3618',
            status: 'awaiting_approval',
        });
        // An approval of something else (a tool call an agent's policy asks about) has no call to run.
        expect(heldCallOf(required({ approval_id: 'apr_2' }))).toBeNull();
        expect(heldCallOf(new NoClickError('Not found.'))).toBeNull();
        expect(heldCallOf(new Error('boom'))).toBeNull();
    });

    it('says where it went, in words', () => {
        const at = (sent_to: string[], extra = {}) => sentWords(heldCallOf(required({ ...HELD, sent_to, ...extra }))!);
        expect(at(['email'])).toBe('Sent to the account’s owner to approve, by email.');
        expect(at(['whatsapp', 'email'])).toBe('Sent to the account’s owner to approve, on WhatsApp and by email.');
        expect(at(['web'])).toContain('on its card in their NoClick chat');
        expect(at([])).toContain('couldn’t reach the account’s owner');
        expect(at(['email'], { approver: { kind: 'user', name: 'Ana' } })).toBe('Sent to Ana to approve.');
    });

    it('waits on the approval’s frame, then settles into the call’s answer with one wait', async () => {
        const { client, reads, release } = api([op('awaiting_human'), op('succeeded', { result: { status: 200, response: { id: 'num_1', number: '+15674833618' } } })]);
        const live = createWorkLive();
        const { states, follower } = follow(client, live, heldCallOf(required())!);
        await settle();
        expect(states.map((s) => s.phase)).toEqual(['waiting']);
        expect(reads).toEqual(['/v1/operations/op_held']);

        // Another approval's frame moves nothing.
        live.deliver('platform:resource', { kind: 'approval', id: 'apr_other', status: 'approved' });
        await settle();
        expect(reads).toHaveLength(1);

        live.deliver('platform:resource', { kind: 'approval', id: 'apr_1', status: 'approved' });
        await settle();
        expect(states.at(-1)).toEqual({ phase: 'running' });
        expect(reads.at(-1)).toBe('/v1/operations/op_held/wait');
        release();
        await settle();
        expect(states.at(-1)).toEqual({ phase: 'done', status: 200, response: { id: 'num_1', number: '+15674833618' } });
        expect(reads).toHaveLength(2);
        // Settled, it hears nothing more.
        live.deliver('reset', { why: 'stream' });
        await settle();
        expect(reads).toHaveLength(2);
        follower.stop();
    });

    it('says the owner declined it, in NoClick’s words, on its frame', async () => {
        const { client } = api([
            op('awaiting_human'),
            op('failed', { error: { type: 'policy_denied', message: 'The person declined it. Their note: not this one.' } }),
        ]);
        const live = createWorkLive();
        const { states } = follow(client, live, heldCallOf(required())!);
        await settle();
        live.deliver('platform:resource', { kind: 'approval', id: 'apr_1', status: 'declined' });
        await settle();
        expect(states.at(-1)).toEqual({ phase: 'declined', message: 'The person declined it. Their note: not this one.' });
    });

    it('says it was declined when its frame lands before the call is failed', async () => {
        const { client } = api([op('awaiting_human')]);
        const live = createWorkLive();
        const { states } = follow(client, live, heldCallOf(required())!);
        await settle();
        live.deliver('platform:resource', { kind: 'approval', id: 'apr_1', status: 'expired' });
        await settle();
        expect(states.at(-1)).toEqual({ phase: 'expired', message: 'Nobody approved it in time.' });
    });

    it('reads where it stands again on a reset, for a frame it missed', async () => {
        const { client, reads } = api([op('awaiting_human'), op('canceled', { error: { type: 'canceled', message: 'The approval was withdrawn.' } })]);
        const live = createWorkLive();
        const { states } = follow(client, live, heldCallOf(required())!);
        await settle();
        live.deliver('reset', { why: 'stream' });
        await settle();
        expect(reads).toEqual(['/v1/operations/op_held', '/v1/operations/op_held']);
        expect(states.at(-1)?.phase).toBe('canceled');
    });

    it('approved already, waits for its answer at once', async () => {
        const { client, reads, release } = api([op('succeeded', { result: { status: 204, response: null } })]);
        const { states } = follow(client, createWorkLive(), heldCallOf(required({ ...HELD, status: 'approved' }))!);
        await settle();
        expect(states).toEqual([{ phase: 'running' }]);
        expect(reads).toEqual(['/v1/operations/op_held/wait']);
        release();
        await settle();
        expect(states.at(-1)?.phase).toBe('done');
    });
});

describe('its notice', () => {
    it('says it went to the owner and where, then that it’s done, and hears where it ended', async () => {
        const { client, release } = api([op('awaiting_human'), op('succeeded', { result: { status: 200, response: { id: 'num_1' } } })]);
        const live = createWorkLive();
        const ended: HeldState[] = [];
        render(
            <ClientProvider client={client}>
                <WorkLiveContext.Provider value={live}>
                    <HeldCallNotice held={heldCallOf(required())!} what="Buy +1 567 483 3618" done="+1 567 483 3618 is yours" onSettled={(s) => ended.push(s)} />
                </WorkLiveContext.Provider>
            </ClientProvider>
        );
        await settle();
        const notice = screen.getByTestId('held-call');
        expect(notice.getAttribute('role')).toBe('status');
        expect(notice.textContent).toContain('Buy +1 567 483 3618: waiting for approval');
        expect(notice.textContent).toContain('Sent to the account’s owner to approve, by email. It goes ahead once they approve it.');
        // The approval link reaches the owner, never this page.
        expect(notice.querySelector('a')).toBeNull();

        act(() => live.deliver('platform:resource', { kind: 'approval', id: 'apr_1', status: 'approved' }));
        await settle();
        expect(screen.getByTestId('held-call').textContent).toContain('approved');
        release();
        await settle();
        expect(screen.getByTestId('held-call').textContent).toBe('+1 567 483 3618 is yours');
        expect(ended.map((s) => s.phase)).toEqual(['done']);
    });
});
