// Verifies the invite banner's persistence/dismissal AND the corrected
// once-guarantee, now that the flags are SERVER-BACKED (cross-device) via the
// generic seen-once store (useSeenOnce → user_onboarding_completion.data.seen_once),
// mirrored to the `noclick:onboarding_completion` localStorage blob:
//  - armed by the empty-canvas builder:submit → shows, and PERSISTS without an
//    active generation,
//  - "Don't show again" sets seen_once.invite_banner_disabled, hides the banner,
//    and triggers the find-the-link walkthrough,
//  - seen_once.invite_walkthrough is persisted ONLY once the tour is completed
//    ("Got it"), NOT at dispatch,
//  - stays suppressed on a later re-arm.
//
// PRECONDITION: the test user's server-side seen_once flags start false (reset via
// the DB / the end-of-test reset below). Banner mount/unmount is rAF-independent
// (pure React), so it's asserted via layout height, not opacity (rAF is paused in
// a backgrounded tab). seen_once writes are read from the mirror blob, which the
// OnboardingProvider updates from context shortly after each change.
import { nc } from '~/lib/nc';
import { sendEventAsync } from '~/lib/socket-sender';
import { OnboardingCompletionUpdateRequest } from '~/types/socket-events.generated';

const MIRROR = 'noclick:onboarding_completion';

function bannerMounted(): boolean {
    const b = document.querySelector('[data-testid="invite-banner"]') as HTMLElement | null;
    return !!b && b.getBoundingClientRect().height > 4;
}

function walkthroughVisible(): boolean {
    return !!Array.from(document.querySelectorAll('h2,h3,div,p')).find((e) =>
        (e.textContent || '').includes('Your invite link lives here'),
    );
}

function seenOnce(): Record<string, boolean> {
    try {
        return (JSON.parse(localStorage.getItem(MIRROR) || '{}').seen_once as Record<string, boolean>) || {};
    } catch {
        return {};
    }
}

async function resetSeenOnceServer() {
    await sendEventAsync(
        OnboardingCompletionUpdateRequest.create({
            request_id: crypto.randomUUID(),
            data: { seen_once: { invite_walkthrough: false, invite_banner_disabled: false } },
        }),
    ).catch(() => {});
}

export default async function () {
    const wf: string = (window as { __workflowTest?: { getWorkflowId?: () => string } }).__workflowTest!.getWorkflowId!();
    const out: Record<string, unknown> = {};
    sessionStorage.removeItem('noclick_invite_banner_dismissed:' + wf);

    document.dispatchEvent(new CustomEvent('noclick:sidebar:expand'));
    await nc.wait.forElement('[data-onboarding="chat-input"]', 8000);

    // 1. Arm via empty-canvas build submit → banner mounts (no active gen needed).
    document.dispatchEvent(new CustomEvent('noclick:builder:submit', { detail: { prompt: 'demo' } }));
    await nc.wait.until(() => bannerMounted(), 10000);
    out.shownOnArm = bannerMounted();
    out.dontShowAgainPresent = !!Array.from(document.querySelectorAll('button')).find((b) => /don.t show again/i.test(b.textContent || ''));

    // 2. Persists with NO build in flight.
    await nc.wait.ms(700);
    out.persistsWithoutBuild = bannerMounted();

    // 3. "Don't show again" → persists seen_once.invite_banner_disabled, unmounts
    //    the banner, and triggers the find-the-link walkthrough (~360ms later).
    const btn = Array.from(document.querySelectorAll('button')).find((b) => /don.t show again/i.test(b.textContent || ''));
    (btn as HTMLElement | undefined)?.click();
    await nc.wait.until(() => !bannerMounted(), 4000).catch(() => {});
    out.hiddenAfterDontShow = !bannerMounted();
    await nc.wait.ms(200); // let the provider mirror context → localStorage
    out.disabledInBlob = seenOnce().invite_banner_disabled === true;

    await nc.wait.until(() => walkthroughVisible(), 6000).catch(() => {});
    out.walkthroughTriggered = walkthroughVisible();
    // Not seen just because dispatched/shown — only on completion.
    out.seenBeforeComplete = seenOnce().invite_walkthrough === true;

    // 4. Complete the tour ("Got it") → NOW seen_once.invite_walkthrough persists.
    const gotIt = Array.from(document.querySelectorAll('button')).find((b) => (b.textContent || '').trim() === 'Got it');
    (gotIt as HTMLElement | undefined)?.click();
    await nc.wait.until(() => seenOnce().invite_walkthrough === true, 4000).catch(() => {});
    out.seenAfterComplete = seenOnce().invite_walkthrough === true;

    // 5. Re-arm → banner must NOT reappear (disabled).
    document.dispatchEvent(new CustomEvent('noclick:builder:submit', { detail: { prompt: 'again' } }));
    await nc.wait.ms(700);
    out.suppressedOnReArm = !bannerMounted();

    // Cleanup: reset server + mirror so a normal reload / re-run behaves fresh.
    await resetSeenOnceServer();
    try {
        const blob = JSON.parse(localStorage.getItem(MIRROR) || '{}');
        delete blob.seen_once;
        localStorage.setItem(MIRROR, JSON.stringify(blob));
    } catch {
        // ignore
    }
    return out;
}
