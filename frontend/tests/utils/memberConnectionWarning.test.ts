// A member who picks their own connection on someone else's workflow is asked, when they pick it, whether the
// workflow's automatic runs (which go as its owner) may use it. "Use it" sends their yes (lend), and the
// server's answer says whether it took; the owner's own picks ask nothing.
import { beforeEach, describe, expect, it, vi } from 'vitest';

const mocks = vi.hoisted(() => ({ send: vi.fn(), toast: vi.fn(), success: vi.fn(), error: vi.fn() }));
vi.mock('~/lib/socket-sender', () => ({ sendEventAsync: mocks.send }));
vi.mock('sonner', () => ({
    toast: Object.assign(mocks.toast, { success: mocks.success, error: mocks.error }),
}));

import { authorizeCredentialsForWorkflow } from '~/utils/credentialAutoSelect';

const flush = () => new Promise((resolve) => setTimeout(resolve, 0));
const CONSENT = 'Automatic runs of this workflow go as its owner. Let them use your "Shop WhatsApp"?';

describe('authorizeCredentialsForWorkflow', () => {
    beforeEach(() => {
        for (const fn of Object.values(mocks)) fn.mockReset();
    });

    it("asks a member whether the runs may use their connection, and sends their yes", async () => {
        mocks.send.mockResolvedValueOnce({ authorized: false, consent: CONSENT });
        authorizeCredentialsForWorkflow('wf-1', { whatsapp_qr: 'cred-1' });
        await flush();

        expect(mocks.toast).toHaveBeenCalledTimes(1);
        const [message, options] = mocks.toast.mock.calls[0];
        expect(message).toBe(CONSENT);
        expect(options.id).toBe('member-connection:cred-1');
        expect(options.action.label).toBe('Use it');

        mocks.send.mockResolvedValueOnce({ authorized: true, lent: true });
        options.action.onClick();
        await flush();

        expect(mocks.send.mock.calls[1][0]).toMatchObject({
            workflow_id: 'wf-1', credential_id: 'cred-1', lend: true,
        });
        expect(mocks.success).toHaveBeenCalledWith("This workflow's runs can use it now.", {
            id: 'member-connection:cred-1',
        });
    });

    it('says so when the yes did not take', async () => {
        mocks.send.mockResolvedValueOnce({ authorized: false, consent: CONSENT });
        authorizeCredentialsForWorkflow('wf-1', ['cred-1']);
        await flush();

        mocks.send.mockResolvedValueOnce({ authorized: false, lent: false });
        mocks.toast.mock.calls[0][1].action.onClick();
        await flush();

        expect(mocks.error).toHaveBeenCalledTimes(1);
        expect(mocks.success).not.toHaveBeenCalled();
    });

    it("asks nothing for the owner's own pick", async () => {
        mocks.send.mockResolvedValue({ authorized: true });
        authorizeCredentialsForWorkflow('wf-1', ['cred-1']);
        await flush();

        expect(mocks.toast).not.toHaveBeenCalled();
    });
});
