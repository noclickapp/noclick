// Inline invite banner shown above ChatBox after a flow is started from the
// EMPTY canvas. It turns the build into a viral moment — a copyable link that
// lets others join and collaborate on the SAME flow live. Armed by the
// `noclick:builder:submit` event (dispatched only by FlowCanvasEmptyState) and
// then HELD until the user dismisses it manually (it intentionally does NOT
// disappear when the AI response finishes). It transitions in/out with the same
// particle-blur as the empty state. On dismiss it runs a one-time coachmark
// pointing at the canvas invite button (see FlowCanvas) so people can find the
// link later. A "Don't show again" control globally suppresses it so it isn't
// shown on every new flow. The visual lives in the shared InviteCard.

import { memo, useCallback, useEffect, useRef, useState } from 'react';
import { motion } from 'framer-motion';
import { useSnapshot } from 'valtio';
import { InviteCard } from '~/components/chat/InviteCard';
import { INVITE_WALKTHROUGH_EVENT } from '~/lib/inviteWalkthrough';
import { useSeenOnce, useHasSeenOnce } from '~/hooks/useSeenOnce';
import { useDrawer } from '~/hooks/useDrawer';
import { sidebarBannerStore } from '~/lib/sidebarBannerStore';
import { useAnalytics } from '~/lib/analytics';
import { EVENTS } from '~/lib/analytics-events';

interface InviteBannerProps {
    /** The workflow currently being edited/built in the sidebar. */
    workflowId?: string;
}

// Per-workflow "dismissed for this flow" flag — intentionally ephemeral
// (sessionStorage), NOT a cross-device "seen once" preference.
const dismissKey = (workflowId: string) => `noclick_invite_banner_dismissed:${workflowId}`;

function InviteBannerImpl({ workflowId }: InviteBannerProps) {
    const { logActivity } = useAnalytics();
    // Server-backed, cross-device preferences (see useSeenOnce):
    //  - bannerDisabled: the global "Don't show again".
    //  - walkthroughSeen: whether the find-the-link tour has run. Read-only here —
    //    it's marked seen by FlowCanvas, and only once the tour actually completes.
    const [bannerDisabled, markBannerDisabled] = useSeenOnce('invite_banner_disabled');
    const walkthroughSeen = useHasSeenOnce('invite_walkthrough');
    // Hide while a chat drawer (e.g. the "/" command drawer) is open — it opens in the
    // space above the ChatBox and would otherwise render over the banner.
    const { isOpen: drawerOpen } = useDrawer();
    // Yield to the higher-priority interrupted-run banner when it's up.
    const { interruptedVisible } = useSnapshot(sidebarBannerStore);
    // Armed when an empty-canvas build is submitted; HELD until manual dismiss.
    const [armed, setArmed] = useState(false);
    const [dismissed, setDismissed] = useState(false);

    // Ask the canvas to run the find-the-link coachmark, unless it's already been
    // seen. We do NOT mark it "seen" here — FlowCanvas writes that only once the
    // spotlight actually displays, so a screen that can't show it (e.g. mobile,
    // where the canvas invite button is hidden) doesn't burn the user's one-time
    // walkthrough. Delayed so the banner is gone before the spotlight appears.
    const triggerWalkthrough = useCallback(() => {
        if (walkthroughSeen) return;
        setTimeout(() => document.dispatchEvent(new CustomEvent(INVITE_WALKTHROUGH_EVENT)), 360);
    }, [walkthroughSeen]);

    // Reset per-workflow state + read the persisted per-workflow dismissed flag.
    useEffect(() => {
        setArmed(false);
        setDismissed(
            !!workflowId &&
                typeof window !== 'undefined' &&
                sessionStorage.getItem(dismissKey(workflowId)) === 'true',
        );
    }, [workflowId]);

    // Arm on the empty-canvas build submit (FlowCanvasEmptyState is the only
    // dispatcher). Once armed the banner stays put — it does NOT hide when the
    // generation finishes; only a manual dismiss closes it.
    useEffect(() => {
        const onSubmit = () => setArmed(true);
        document.addEventListener('noclick:builder:submit', onSubmit);
        return () => document.removeEventListener('noclick:builder:submit', onSubmit);
    }, []);

    // Dismiss for THIS flow (the ✕). Runs the one-time find-the-link walkthrough.
    const handleDismiss = () => {
        setDismissed(true);
        if (workflowId) sessionStorage.setItem(dismissKey(workflowId), 'true');
        logActivity(EVENTS.INVITE_BANNER_DISMISSED, { workflow_id: workflowId });
        triggerWalkthrough();
    };

    // Never show on any future flow (cross-device). Still runs the one-time
    // walkthrough so the user learns where the invite button lives before opting out.
    const handleDontShowAgain = () => {
        markBannerDisabled();
        logActivity(EVENTS.INVITE_BANNER_DONT_SHOW_AGAIN, { workflow_id: workflowId });
        triggerWalkthrough();
    };

    const show = !!workflowId && armed && !dismissed && !bannerDisabled && !drawerOpen && !interruptedVisible;
    // Publish visibility so the lower-priority quick-publish banner yields the slot while
    // this one is up (only one sidebar banner shows at a time).
    useEffect(() => {
        sidebarBannerStore.inviteVisible = show;
        return () => { sidebarBannerStore.inviteVisible = false; };
    }, [show]);
    // Fire "shown" once per appearance (re-arms when hidden, e.g. on workflow switch).
    const shownRef = useRef(false);
    useEffect(() => {
        if (show && !shownRef.current) {
            shownRef.current = true;
            logActivity(EVENTS.INVITE_BANNER_SHOWN, { workflow_id: workflowId });
        } else if (!show) {
            shownRef.current = false;
        }
    }, [show, workflowId, logActivity]);
    if (!show) return null;

    // No AnimatePresence: the particle-blur IN plays on mount, and dismissing
    // simply unmounts the banner. Unmount is a pure React reconciliation (no
    // exit animation), so it's instant and clean — no leftover node or blank
    // gap, and it doesn't depend on requestAnimationFrame (which an exit
    // animation would, and which is paused in backgrounded tabs).
    return (
        <motion.div
            data-testid="invite-banner"
            className="px-3 pt-2 pb-1"
            initial={{ opacity: 0, filter: 'blur(10px)' }}
            animate={{ opacity: 1, filter: 'blur(0px)' }}
            transition={{ duration: 0.28, ease: 'easeOut' }}
        >
            <InviteCard workflowId={workflowId} onDismiss={handleDismiss} onDontShowAgain={handleDontShowAgain} source="banner" />
        </motion.div>
    );
}

export const InviteBanner = memo(InviteBannerImpl);
