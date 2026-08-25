// Mini-banner shown above ChatBox when the active conversation has a builder
// run flagged interrupted because its runtime ended before sending a terminal
// frame.
// On detection it AUTO-RESUMES: re-submits the original prompt via
// noclick:builder:retry (handled in NoClick), pinned to the dead run's own
// conversation so the backend loads that run's checkpoint instead of starting a
// fresh build. Delivery is CONFIRMED, not fire-and-forget: a single lost
// workflow:builder:edit must not lose the resume. Each attempt waits for the
// 'API' socket to
// be connected, emits, then waits a short window for the backend's
// active_gen:started ack; if it doesn't arrive it retries, bounded. No manual
// button — purely informational ("Resuming…", then it clears as the fresh run
// streams). Highest-priority sidebar banner; invite/quick-publish yield to it.
import { memo, useEffect, useMemo, useRef, useState } from 'react';
import { motion } from 'framer-motion';
import { Loader2, X } from 'lucide-react';
import { useSnapshot } from 'valtio';
import { activeGenStore, evictGen } from '~/lib/activeGenStore';
import { socketReceiver } from '~/lib/socket-receiver';
import { sidebarBannerStore } from '~/lib/sidebarBannerStore';
import { useDrawer } from '~/hooks/useDrawer';

// Bound how many distinct dead runs we'll auto-resume per conversation (so a
// backend that keeps dying can't loop forever).
const MAX_AUTO_RESUMES_PER_CONVERSATION = 3;
// After the single resume emit, how long to wait for the backend's
// active_gen:started ack before giving up on dropping the dead gen. Generous,
// because the ack crosses containers + the event relay; there is NO re-emit, so a
// long wait costs nothing (it only delays evicting an already-deduped dead gen).
const RESUME_CONFIRM_MS = 20000;
// Bounded wait for the 'API' socket to (re)connect before the emit.
const SOCKET_WAIT_MS = 8000;
const POLL_MS = 150;
// Per-conversation auto-resume count, session-scoped (survives the component's
// remount on conversation switch).
const autoResumeCounts = new Map<string, number>();

const sleep = (ms: number) => new Promise<void>((r) => setTimeout(r, ms));

// Wait until the 'API' socket is connected (getSocket kicks ensureSocketConnected,
// which triggers a reconnect when needed), bounded.
async function waitForApiConnected(ms: number): Promise<boolean> {
    const deadline = Date.now() + ms;
    while (Date.now() < deadline) {
        if (socketReceiver.getSocket('API')?.connected) return true;
        await sleep(POLL_MS);
    }
    return socketReceiver.getSocket('API')?.connected ?? false;
}

// True once the resume's fresh backend run has taken hold for this conversation:
// a gen that isn't one we already knew about, isn't the optimistic placeholder,
// and isn't itself interrupted/stopped — i.e. the backend sent active_gen:started.
function backendResumeTookHold(conversationId: string, knownIds: Set<string>): boolean {
    const ids = activeGenStore.byConversation[conversationId] || [];
    for (const id of ids) {
        if (knownIds.has(id) || id.startsWith('optimistic_')) continue;
        const g = activeGenStore.gens[id];
        if (g && !g.interrupted && !g.stopped) return true;
    }
    return false;
}

interface InterruptedRunBannerProps {
    /** The conversation currently shown in the chat. */
    conversationId?: string | null;
}

function InterruptedRunBannerImpl({ conversationId }: InterruptedRunBannerProps) {
    const snap = useSnapshot(activeGenStore);
    // Hide while a chat drawer (e.g. the "/" command drawer) is open — it opens
    // above the ChatBox and would render over the banner (mirrors InviteBanner).
    const { isOpen: drawerOpen } = useDrawer();
    const [dismissed, setDismissed] = useState(false);
    const [resuming, setResuming] = useState(false);
    const [resumeFailed, setResumeFailed] = useState(false);
    const handledRef = useRef<Set<string>>(new Set());

    // The latest interrupted (not user-stopped) gen for this conversation.
    const interruptedGen = useMemo(() => {
        if (!conversationId) return null;
        const ids = snap.byConversation[conversationId] || [];
        const matches = ids
            .map(id => snap.gens[id])
            .filter(g => g && g.interrupted && !g.stopped);
        return matches.length ? matches[matches.length - 1] : null;
    }, [conversationId, snap.byConversation, snap.gens]);
    const genId = interruptedGen?.gen_id;

    // A new conversation gets a clean slate.
    useEffect(() => {
        setDismissed(false);
        setResuming(false);
        setResumeFailed(false);
        handledRef.current = new Set();
    }, [conversationId]);

    // Auto-resume on detection (reconnect → watchdog/relay → interrupted), once per
    // dead run and within the per-conversation cap. Fires the resume EXACTLY
    // ONCE (no retry) — re-emitting on a slow ack spawned duplicate backend runs.
    // Drop the dead gen only once the resume's fresh run has taken hold.
    useEffect(() => {
        if (!genId || !conversationId || dismissed) return;
        if (handledRef.current.has(genId)) return;
        handledRef.current.add(genId);
        const deadGen = activeGenStore.gens[genId];
        const prompt = deadGen?.prompt;
        // Pin to the dead run's OWN conversation (not the ambient one) so the
        // backend loads that run's checkpoint instead of starting fresh.
        const resumeConversationId = deadGen?.conversation_id || conversationId;
        const used = autoResumeCounts.get(conversationId) || 0;
        if (!prompt || used >= MAX_AUTO_RESUMES_PER_CONVERSATION) return;
        autoResumeCounts.set(conversationId, used + 1);

        let cancelled = false;
        setResuming(true);

        (async () => {
            // Snapshot existing runs so we can detect the resume's fresh one.
            const knownIds = new Set(activeGenStore.byConversation[resumeConversationId] || []);
            await waitForApiConnected(SOCKET_WAIT_MS);
            if (cancelled) return;
            // Fire EXACTLY ONCE. socket.io buffers the emit across a reconnect, so
            // a single dispatch is delivered. Re-emitting on a slow ack used to
            // spawn DUPLICATE backend runs — the cross-container active_gen:started
            // lags past any short window, so each retry started another run →
            // multiple duplicate turns in the chat.
            document.dispatchEvent(new CustomEvent('noclick:builder:retry', {
                detail: { prompt, conversationId: resumeConversationId },
            }));
            // Wait (generously — the ack crosses containers + the relay) for the
            // resume to take hold, only so we can drop the dead gen. No re-emit on
            // timeout: a lingering interrupted gen self-heals when the resumed turn
            // commits, and the passive notice covers the rare true failure.
            const deadline = Date.now() + RESUME_CONFIRM_MS;
            let delivered = false;
            while (Date.now() < deadline && !cancelled) {
                if (backendResumeTookHold(resumeConversationId, knownIds)) { delivered = true; break; }
                await sleep(POLL_MS);
            }
            if (cancelled) return;
            setResuming(false);
            if (delivered) {
                evictGen(genId); // the resume's fresh run owns the chat now
            } else {
                setResumeFailed(true); // surface the passive "interrupted" notice
            }
        })();

        return () => { cancelled = true; };
    }, [genId, conversationId, dismissed]);

    // A still-present interrupted gen we did NOT auto-resume (no prompt, or the
    // run cap is spent), or one whose delivery retries were exhausted → show the
    // passive notice without resuming.
    const used = conversationId ? (autoResumeCounts.get(conversationId) || 0) : 0;
    const unresumable = !!interruptedGen && (!interruptedGen.prompt || used >= MAX_AUTO_RESUMES_PER_CONVERSATION);
    const show = !dismissed && !drawerOpen && (resuming || unresumable || resumeFailed);

    // Yield the slot for the lower-priority banners while this one is up.
    useEffect(() => {
        sidebarBannerStore.interruptedVisible = show;
        return () => { sidebarBannerStore.interruptedVisible = false; };
    }, [show]);

    if (!show) return null;

    return (
        <motion.div
            data-testid="interrupted-run-banner"
            className="px-3 pt-2 pb-1"
            initial={{ opacity: 0, filter: 'blur(10px)' }}
            animate={{ opacity: 1, filter: 'blur(0px)' }}
            transition={{ duration: 0.28, ease: 'easeOut' }}
        >
            <div className="flex items-center gap-2.5 rounded-xl border border-foreground/10 bg-foreground/[0.05] px-3.5 py-2.5 ring-1 ring-inset ring-foreground/[0.04] shadow-[0_4px_16px_-6px_rgba(0,0,0,0.5)] backdrop-blur-md">
                {resuming
                    ? <Loader2 className="h-3.5 w-3.5 shrink-0 animate-spin text-foreground/50" />
                    : <span className="h-1.5 w-1.5 shrink-0 rounded-full bg-amber-400/90" aria-hidden />}
                <span className="flex-1 min-w-0 text-[13px] leading-tight text-foreground/70">
                    {resuming ? 'Connection lost. Resuming…' : 'Connection lost. The run was interrupted.'}
                </span>
                <button
                    type="button"
                    aria-label="Dismiss"
                    onClick={() => setDismissed(true)}
                    className="shrink-0 rounded-md p-0.5 text-foreground/35 transition-colors hover:text-foreground/70"
                >
                    <X className="h-4 w-4" />
                </button>
            </div>
        </motion.div>
    );
}

export const InterruptedRunBanner = memo(InterruptedRunBannerImpl);
