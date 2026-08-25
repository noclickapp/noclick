// Verifies the canvas invite button, its popup (shared InviteCard), and the
// first-close walkthrough spotlight.
//
// The walkthrough's "seen" state is now server-backed (useSeenOnce →
// user_onboarding_completion.data.seen_once.invite_walkthrough), read by the
// FlowCanvas re-guard off the onboarding context. So this test depends on that
// flag being false at page load (the context re-fetches it on mount); it resets
// the server flag at the end for repeatability.
import { nc } from '~/lib/nc';
import { activeGenStore } from '~/lib/activeGenStore';
import { sendEventAsync } from '~/lib/socket-sender';
import { OnboardingCompletionUpdateRequest } from '~/types/socket-events.generated';

export default async function () {
    const wf: string = (window as { __workflowTest?: { getWorkflowId?: () => string } }).__workflowTest!.getWorkflowId!();
    const out: Record<string, unknown> = {};

    // Hide the inline banner so its testids don't collide with the popup's.
    delete activeGenStore.byWorkflow[wf];
    await nc.wait.ms(400);

    // 1. Invite button exists on the canvas controls.
    const btn = document.querySelector('[data-tour-target="invite-button"]') as HTMLElement | null;
    out.inviteButtonPresent = !!btn;

    // 2. Walkthrough fires and spotlights the button. (Assumes seen=false at
    //    page load — see header; the re-guard reads the server-backed context.)
    document.dispatchEvent(new CustomEvent('noclick:invite:show-walkthrough'));
    await nc.wait.until(
        () => !!Array.from(document.querySelectorAll('div,h2,h3,p')).find((e) => (e.textContent || '').includes('Your invite link lives here')),
        6000,
    ).catch(() => {});
    out.walkthroughVisible = !!Array.from(document.querySelectorAll('div,h2,h3,p')).find((e) => (e.textContent || '').includes('Your invite link lives here'));
    const gotIt = Array.from(document.querySelectorAll('button')).find((b) => (b.textContent || '').trim() === 'Got it');
    if (gotIt) (gotIt as HTMLElement).click();
    await nc.wait.ms(500);

    // 3. Click the invite button → popover renders the InviteCard with the link.
    btn?.click();
    await nc.wait.until(() => !!document.querySelector('[data-testid="invite-banner-url"]'), 8000).catch(() => {});
    out.popupUrl = (document.querySelector('[data-testid="invite-banner-url"]') as HTMLInputElement | null)?.value ?? null;

    // Reset the server flag (the "Got it" above marked it seen) so a re-run shows it again.
    await sendEventAsync(
        OnboardingCompletionUpdateRequest.create({
            request_id: crypto.randomUUID(),
            data: { seen_once: { invite_walkthrough: false } },
        }),
    ).catch(() => {});

    return out;
}
