// A member who picks their own connection on someone else's workflow is told, when they pick it, that the
// workflow's automatic runs (which go as its owner) can't use it. The server's authorize reply carries the
// warning; picking it again doesn't stack a second toast.
import { beforeEach, describe, expect, it, vi } from 'vitest';

const mocks = vi.hoisted(() => ({ send: vi.fn(), warning: vi.fn() }));
vi.mock('~/lib/socket-sender', () => ({ sendEventAsync: mocks.send }));
vi.mock('sonner', () => ({ toast: { warning: mocks.warning } }));

import { authorizeCredentialsForWorkflow } from '~/utils/credentialAutoSelect';

const flush = () => new Promise((resolve) => setTimeout(resolve, 0));

describe('authorizeCredentialsForWorkflow', () => {
    beforeEach(() => {
        mocks.send.mockReset();
        mocks.warning.mockReset();
    });

    it("shows the server's warning for a member's own connection", async () => {
        mocks.send.mockResolvedValue({ authorized: false, warning: 'Your "Shop WhatsApp" won\'t work…' });

        authorizeCredentialsForWorkflow('wf-1', { whatsapp_qr: 'cred-1' });
        await flush();

        expect(mocks.warning).toHaveBeenCalledWith('Your "Shop WhatsApp" won\'t work…', {
            id: 'member-connection:cred-1',
        });
    });

    it("says nothing for the owner's own pick", async () => {
        mocks.send.mockResolvedValue({ authorized: true });

        authorizeCredentialsForWorkflow('wf-1', ['cred-1']);
        await flush();

        expect(mocks.warning).not.toHaveBeenCalled();
    });
});
