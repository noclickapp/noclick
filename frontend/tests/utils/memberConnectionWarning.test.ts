// A member who picks their own connection on someone else's workflow shares it with the workflow's automatic
// runs (which go as its owner) by picking it, and is told so with an Undo that takes it back (``withdraw``).
// The owner's own picks say nothing.
import { beforeEach, describe, expect, it, vi } from 'vitest';

const mocks = vi.hoisted(() => ({ send: vi.fn(), success: vi.fn(), info: vi.fn(), error: vi.fn() }));
vi.mock('~/lib/socket-sender', () => ({ sendEventAsync: mocks.send }));
vi.mock('sonner', () => ({
    toast: Object.assign(vi.fn(), { success: mocks.success, info: mocks.info, error: mocks.error }),
}));

import { authorizeCredentialsForWorkflow } from '~/utils/credentialAutoSelect';

const flush = () => new Promise((resolve) => setTimeout(resolve, 0));
const SHARED = 'Shared your "Shop WhatsApp" with this workflow';
const DETAIL = 'Anyone who can edit the workflow can make it act as you.';
// The click keeps the toast open (it becomes the answer), so the handler gets sonner's event.
const click = { preventDefault: vi.fn() };

describe('authorizeCredentialsForWorkflow', () => {
    beforeEach(() => {
        for (const fn of Object.values(mocks)) fn.mockReset();
        click.preventDefault.mockReset();
    });

    it('tells a member their pick shared it, and Undo takes it back', async () => {
        mocks.send.mockResolvedValueOnce({ authorized: true, shared: SHARED, shared_detail: DETAIL });
        authorizeCredentialsForWorkflow('wf-1', { whatsapp_qr: 'cred-1' });
        await flush();

        expect(mocks.send.mock.calls[0][0]).toMatchObject({ workflow_id: 'wf-1', credential_id: 'cred-1' });
        expect(mocks.send.mock.calls[0][0].withdraw).toBeFalsy();
        expect(mocks.success).toHaveBeenCalledTimes(1);
        const [message, options] = mocks.success.mock.calls[0];
        expect(message).toBe(SHARED);
        expect(options.id).toBe('member-connection:cred-1');
        expect(options.description).toBe(DETAIL);
        expect(options.action.label).toBe('Undo');

        mocks.send.mockResolvedValueOnce({ authorized: false, withdrawn: true });
        options.action.onClick(click);
        await flush();

        expect(click.preventDefault).toHaveBeenCalled();
        expect(mocks.send.mock.calls[1][0]).toMatchObject({
            workflow_id: 'wf-1', credential_id: 'cred-1', withdraw: true,
        });
        // The same toast turns into the answer: its detail and button go, and it closes by itself.
        expect(mocks.info).toHaveBeenCalledWith(
            "Not shared. This workflow's automatic runs can't use it; pick it again to share it.",
            { id: 'member-connection:cred-1', duration: 6000, description: undefined, action: undefined },
        );
    });

    it('says it is still shared when the Undo never reached NoClick', async () => {
        mocks.send.mockResolvedValueOnce({ authorized: true, shared: SHARED, shared_detail: DETAIL });
        authorizeCredentialsForWorkflow('wf-1', ['cred-1']);
        await flush();

        mocks.send.mockRejectedValueOnce(new Error('offline'));
        mocks.success.mock.calls[0][1].action.onClick(click);
        await flush();

        expect(mocks.error).toHaveBeenCalledTimes(1);
        expect(mocks.error.mock.calls[0][0]).toMatch(/still shared/);
        expect(mocks.info).not.toHaveBeenCalled();
    });

    it("says nothing for the owner's own pick", async () => {
        mocks.send.mockResolvedValue({ authorized: true });
        authorizeCredentialsForWorkflow('wf-1', ['cred-1']);
        await flush();

        expect(mocks.success).not.toHaveBeenCalled();
    });
});
