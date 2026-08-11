// Opaque cover for the template-fork hand-off: from the dashboard's FIRST
// paint (the fork/setup flags are already in sessionStorage when navigation
// lands) until FlowCanvas consumes the setup flag and mounts the full-screen
// onboarding beneath it. Without this the user sees the workflow list, the
// navbar, and the canvas flash by between "Use this agent" and Setup.
// z-30: above the workspace chrome, below the full-screen setup (z-40, body
// portal) so the onboarding paints over the cover before it unmounts.

import { useEffect, useState } from 'react';
import { createPortal } from 'react-dom';
import { LogoMark } from '~/components/shared/LogoMark';
import { ThinkingOrb } from '~/components/shared/ThinkingOrb';

const FORK_KEY = 'noclick_fork_workflow_data';
const SETUP_KEY = 'noclick_open_setup_tab';
// Fail OPEN: if the hand-off dies (fork error with no dialog), the dashboard
// must become visible again rather than covering a silent failure forever.
const MAX_MS = 25_000;

export function SetupHandoffCover() {
    const [covering, setCovering] = useState<boolean>(() => {
        if (typeof window === 'undefined') return false;
        return Boolean(
            sessionStorage.getItem(FORK_KEY) || sessionStorage.getItem(SETUP_KEY)
        );
    });

    useEffect(() => {
        if (!covering) return;
        // Primary signal: FlowCanvas announces the moment it consumes the
        // setup flag and mounts the onboarding beneath us. The flag poll
        // below is only the backup - the relay's middle state can be shorter
        // than one poll interval.
        const onDone = () => window.setTimeout(() => setCovering(false), 400);
        document.addEventListener('noclick:setup-handoff-done', onDone);
        const started = Date.now();
        // The flags form a relay: fork data is consumed by the fork request,
        // the setup flag appears on success and is consumed by FlowCanvas as
        // the full-screen onboarding mounts. The cover drops one beat AFTER
        // that final consumption so the onboarding is already painted over it.
        let sawSetupFlag = sessionStorage.getItem(SETUP_KEY) !== null;
        const tick = window.setInterval(() => {
            const forkPending = sessionStorage.getItem(FORK_KEY) !== null;
            const setupPending = sessionStorage.getItem(SETUP_KEY) !== null;
            if (setupPending) sawSetupFlag = true;
            const done = sawSetupFlag && !setupPending && !forkPending;
            if (done || Date.now() - started > MAX_MS) {
                window.clearInterval(tick);
                window.setTimeout(() => setCovering(false), 400);
            }
        }, 250);
        return () => {
            window.clearInterval(tick);
            document.removeEventListener('noclick:setup-handoff-done', onDone);
        };
    }, [covering]);

    if (!covering || typeof document === 'undefined') return null;
    return createPortal(
        <div className="fixed inset-0 z-30 flex flex-col items-center justify-center gap-5 bg-background">
            <LogoMark className="h-9 w-9" />
            <div className="flex items-center gap-2.5 text-sm text-muted-foreground/80">
                <ThinkingOrb state="searching" />
                Preparing your agent
            </div>
        </div>,
        document.body
    );
}
