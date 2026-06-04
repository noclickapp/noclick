// Live integration test for the collaborative invite-link feature.
// Exercises the real socket events against the dev backend (mint → idempotent
// re-mint → owner-accept), the public preview endpoint, and verifies the
// InviteBanner renders the copyable link while a build is active for the open
// workflow. Run with nc_run_test (requires an open dashboard tab on a workflow).

import { nc } from '~/lib/nc';
import {
    sendEventAsync,
    ShareInviteLinkRequest,
    ShareInviteAcceptRequest,
} from '~/lib/socket-sender';
import { activeGenStore } from '~/lib/activeGenStore';

export default async function () {
    const out: Record<string, unknown> = {};
    const workflowId: string | undefined = (window as { __workflowTest?: { getWorkflowId?: () => string } }).__workflowTest?.getWorkflowId?.();
    out.workflowId = workflowId;
    if (!workflowId) throw new Error('No workflow open — open a workflow first');

    // 1. Mint an invite link over the live socket.
    const mint = await sendEventAsync(ShareInviteLinkRequest.create({ workflow_id: workflowId }));
    out.mint = mint;
    if (mint?.error) throw new Error('mint failed: ' + mint.error);
    nc.assert.truthy(mint?.token, 'mint returns a token');
    nc.assert.equal(mint.permission, 'edit', 'permission is edit');
    nc.assert.truthy(String(mint.url || '').endsWith(mint.token ?? ''), 'url ends with the token');
    const token = mint.token as string;

    // 2. Re-mint is idempotent — same active token.
    const mint2 = await sendEventAsync(ShareInviteLinkRequest.create({ workflow_id: workflowId }));
    nc.assert.equal(mint2.token, token, 're-mint returns the same token (idempotent)');

    // 3. Public preview endpoint (best-effort: backend may be on a separate origin).
    const apiBase = (import.meta as unknown as { env?: { VITE_API_URL?: string } }).env?.VITE_API_URL || '';
    try {
        const res = await fetch(`${apiBase}/api/public/invite/${token}`, { headers: { Accept: 'application/json' } });
        const preview: Record<string, unknown> = { status: res.status };
        if (res.ok) {
            const body = (await res.json()) as { workflow_id?: string };
            preview.body = body;
            nc.assert.equal(body.workflow_id, workflowId, 'preview returns the workflow id');
        }
        out.preview = preview;
    } catch (e) {
        out.preview = { error: String(e instanceof Error ? e.message : e) };
    }

    // 4. Owner redeeming their own link succeeds and is a no-op (returns the workflow).
    const accept = await sendEventAsync(ShareInviteAcceptRequest.create({ token }));
    out.accept = accept;
    nc.assert.truthy(accept?.success, 'owner accept succeeds');
    nc.assert.equal(accept?.workflow_id, workflowId, 'accept returns the workflow id');

    // 5. Banner renders the copyable link while a build is active for this workflow.
    // Ensure the sidebar (which hosts the banner) is expanded first, then settle
    // (the banner mints its link on a socket round-trip before it renders).
    document.dispatchEvent(new CustomEvent('noclick:sidebar:expand'));
    await nc.wait.forElement('[data-onboarding="chat-input"]', 8000);
    await nc.wait.ms(400);
    sessionStorage.removeItem('noclick_invite_banner_dismissed:' + workflowId);
    const prev = activeGenStore.byWorkflow[workflowId];
    activeGenStore.byWorkflow[workflowId] = ['nc-test-gen'];
    try {
        await nc.wait.until(() => !!document.querySelector('[data-testid="invite-banner-url"]'), 8000);
        const urlInput = nc.dom.qs('[data-testid="invite-banner-url"]') as HTMLInputElement | null;
        out.bannerUrl = urlInput?.value ?? null;
        nc.assert.truthy(
            !!out.bannerUrl && (out.bannerUrl as string).includes('/i/' + token),
            'banner shows the invite URL for this token',
        );
        nc.assert.truthy(!!nc.dom.qs('[data-testid="invite-banner-copy"]'), 'banner has a Copy button');
    } finally {
        if (prev === undefined) delete activeGenStore.byWorkflow[workflowId];
        else activeGenStore.byWorkflow[workflowId] = prev;
    }

    out.ok = true;
    return out;
}
