// Run account-file detail pages in the real Chromium integration suite.
// The shared nc test can also exercise the local app without changing account data.
import { expect, it } from 'vitest';
import verifyFileDetail from '../nc/resources-file-detail.test';

it('previews, downloads and guards deletion of same-named account files by resource id', async () => {
    expect(await verifyFileDetail()).toEqual({ preview: true, download: true, confirm: true, duplicateNames: true });
});
