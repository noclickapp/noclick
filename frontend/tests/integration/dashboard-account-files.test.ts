// Run personal attachment navigation in the real Chromium integration suite.
// The shared nc test can also exercise the local app without changing account data.
import { expect, it } from 'vitest';
import verifyAccountFiles from '../nc/dashboard-account-files.test';

it('previews and manages personal attachments alongside workflow files', async () => {
    expect(await verifyAccountFiles()).toEqual({ preview: true, download: true, delete: true, duplicateNames: true });
});
