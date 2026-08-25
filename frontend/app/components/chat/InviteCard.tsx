// Shared visual for the collaborative invite link: a band of named collaborator
// cursors drifting over the canvas dot-grid, a clear title, and a conspicuous
// copyable link. Reused by InviteBanner (the inline sidebar banner shown during
// an empty-canvas build) and by the FlowCanvas invite popup (so people can find
// the link later). Mints/fetches the workflow's invite link itself via the
// share:invite_link socket event.

import { useEffect, useRef, useState } from 'react';
import { motion } from 'framer-motion';
import { Link2, Copy, Check } from 'lucide-react';
import { toast } from 'sonner';
import { sendEventAsync, ShareInviteLinkRequest } from '~/lib/socket-sender';
import { useAnalytics } from '~/lib/analytics';
import { EVENTS } from '~/lib/analytics-events';
import { SidebarBannerCard } from '~/components/chat/SidebarBannerCard';

// Cursor glyph path lifted verbatim from CollaborativeCursors / the landing
// bento animation so the banner matches the real on-canvas cursors.
const CURSOR_PATH =
    'M5.5 3.21V20.8c0 .45.54.67.85.35l4.86-4.86a.5.5 0 0 1 .35-.15h6.87c.48 0 .72-.58.38-.92L6.35 2.85a.5.5 0 0 0-.85.36Z';

// Collaborator cursors drifting across the canvas (viewBox 0 0 300 112).
interface DriftCursorSpec {
    name: string;
    color: string;
    xs: number[];
    ys: number[];
    duration: number;
    delay: number;
}
const CURSORS: DriftCursorSpec[] = [
    { name: 'You', color: '#a5b4fc', xs: [44, 150, 248, 120, 44], ys: [40, 22, 46, 58, 40], duration: 16, delay: 0 },
    { name: 'Maya', color: '#6ee7b7', xs: [250, 140, 52, 176, 250], ys: [24, 50, 30, 56, 24], duration: 19, delay: 0.25 },
    { name: 'Sam', color: '#7dd3fc', xs: [150, 232, 70, 150], ys: [56, 30, 48, 56], duration: 14, delay: 0.5 },
];

function DriftCursor({ name, color, xs, ys, duration, delay }: DriftCursorSpec) {
    const chipW = name.length * 5 + 12;
    return (
        <motion.g
            initial={{ opacity: 0, x: xs[0], y: ys[0] }}
            animate={{ opacity: 1, x: xs, y: ys }}
            transition={{
                x: { duration, repeat: Infinity, ease: 'easeInOut' },
                y: { duration, repeat: Infinity, ease: 'easeInOut' },
                opacity: { duration: 0.6, delay },
            }}
        >
            {/* Pointer glyph: tip is at the group origin (top-left). */}
            <g transform="translate(-3, -2) scale(0.82)">
                <path
                    d={CURSOR_PATH}
                    fill={color}
                    stroke="#fff"
                    strokeWidth="1.4"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    style={{ filter: 'drop-shadow(0 1px 2px rgba(0,0,0,0.6))' }}
                />
            </g>
            {/* Name chip hangs just BELOW the glyph (which ends ~y15) with a little
                left margin, so it sits tucked under the cursor body, never the tip. */}
            <g transform="translate(8, 16)">
                <rect width={chipW} height={13} rx={3.5} fill={color} style={{ filter: 'drop-shadow(0 1px 2px rgba(0,0,0,0.4))' }} />
                <text x={chipW / 2} y={9.4} textAnchor="middle" fill="#0b0b0f" fontSize="8" fontWeight={700} fontFamily="system-ui">
                    {name}
                </text>
            </g>
        </motion.g>
    );
}

function CollaboratorAnimation() {
    return (
        <svg viewBox="0 0 300 112" className="h-full w-full" preserveAspectRatio="xMidYMid slice" aria-hidden>
            {CURSORS.map((c) => (
                <DriftCursor key={c.name} {...c} />
            ))}
        </svg>
    );
}

interface InviteCardProps {
    /** Workflow to mint/fetch the invite link for. */
    workflowId?: string;
    /** When provided, renders a dismiss (✕) button that calls this. */
    onDismiss?: () => void;
    /** Extra classes for the outer card (e.g. a fixed width in the popup). */
    className?: string;
    /** When provided, renders a subtle "Don't show again" control. */
    onDontShowAgain?: () => void;
    /** Where this card is rendered (for analytics): 'banner' | 'canvas_popover'. */
    source?: string;
}

export function InviteCard({ workflowId, onDismiss, className, onDontShowAgain, source }: InviteCardProps) {
    const { logActivity } = useAnalytics();
    const [token, setToken] = useState<string | null>(null);
    const [mintFailed, setMintFailed] = useState(false);
    const [copied, setCopied] = useState(false);

    // Mint (or fetch) the invite link exactly ONCE per real workflow id. The ref
    // survives re-renders AND StrictMode's mount/cleanup/remount double-invoke, and
    // we ignore a transient `undefined` workflowId (it flickers during an
    // empty-canvas build as the editor/builder stores settle). Without this the
    // mint re-fired on every workflowId churn and spammed `share:invite_link`
    // (rate-limited 2/sec) — the rate-limited rejections then latched
    // "Link unavailable". A genuine workflow switch (new id) re-mints.
    const attemptedForRef = useRef<string | null>(null);
    useEffect(() => {
        if (!workflowId || attemptedForRef.current === workflowId) return;
        attemptedForRef.current = workflowId;
        setToken(null);
        setMintFailed(false);
        // Guard the result on the REF (not a cleanup-set `cancelled` flag): in
        // StrictMode the discarded first run's cleanup would set such a flag true,
        // and the once-per-id guard then blocks any replacement request — leaving
        // the mint stuck on "Creating link…". Comparing the ref to the captured id
        // instead applies the result iff the workflow hasn't changed since, which
        // survives StrictMode and still discards a stale result after a switch.
        sendEventAsync(ShareInviteLinkRequest.create({ workflow_id: workflowId }))
            .then((res) => {
                if (attemptedForRef.current !== workflowId) return;
                if (res?.token) setToken(res.token);
                else setMintFailed(true);
            })
            .catch((err) => {
                if (attemptedForRef.current !== workflowId) return;
                console.error('Failed to mint invite link:', err);
                setMintFailed(true);
            });
    }, [workflowId]);

    const inviteUrl = token
        ? typeof window !== 'undefined'
            ? `${window.location.origin}/i/${token}`
            : `/i/${token}`
        : '';

    const handleCopy = async () => {
        if (!inviteUrl) return;
        try {
            await navigator.clipboard.writeText(inviteUrl);
            setCopied(true);
            toast.success('Invite link copied');
            // Key share-intent signal: the user copied the link to send it out.
            logActivity(EVENTS.INVITE_LINK_COPIED, { workflow_id: workflowId, source });
            setTimeout(() => setCopied(false), 2000);
        } catch (err) {
            console.error('Failed to copy invite link:', err);
            toast.error('Failed to copy link');
        }
    };

    return (
        <SidebarBannerCard
            hero={<CollaboratorAnimation />}
            onDismiss={onDismiss}
            onDontShowAgain={onDontShowAgain}
            className={className}
        >
            <div className="mb-1 flex items-center gap-2">
                <h3 className="text-[18px] font-semibold leading-snug text-foreground">Share this flow to build together</h3>
                <span className="inline-flex items-center gap-1 rounded-full bg-emerald-400/15 px-1.5 py-0.5 text-[9px] font-semibold uppercase tracking-wide text-emerald-700 dark:text-emerald-300">
                    <span className="h-1 w-1 rounded-full bg-emerald-400" />
                    Live
                </span>
            </div>
            <p className="mb-3 text-[13px] leading-snug text-muted-foreground">
                Anyone who opens the link joins{' '}
                <span className="font-medium text-foreground">this exact flow</span> and edits with you in real time.
            </p>

            {/* Conspicuous link + copy CTA (white) */}
            <div className="flex items-stretch gap-2">
                <button
                    type="button"
                    onClick={handleCopy}
                    disabled={!token}
                    title={token ? 'Click to copy' : undefined}
                    className="group flex min-w-0 flex-1 items-center gap-2 rounded-xl border border-foreground/25 bg-background/40 px-3 py-2 text-left ring-1 ring-inset ring-foreground/5 transition-colors hover:border-foreground/45 hover:bg-background/55 disabled:cursor-default"
                >
                    <Link2 className="h-3.5 w-3.5 shrink-0 text-foreground/80" />
                    {token ? (
                        <input
                            readOnly
                            value={inviteUrl}
                            data-testid="invite-banner-url"
                            tabIndex={-1}
                            className="pointer-events-none w-full truncate bg-transparent font-mono text-[12px] font-medium text-foreground outline-none"
                        />
                    ) : (
                        <span className="truncate font-mono text-[12px] text-muted-foreground dark:text-zinc-500">
                            {mintFailed ? 'Link unavailable' : 'Creating link…'}
                        </span>
                    )}
                </button>
                <button
                    type="button"
                    onClick={handleCopy}
                    disabled={!token}
                    data-testid="invite-banner-copy"
                    className="inline-flex shrink-0 items-center gap-1.5 rounded-xl bg-primary px-3.5 text-[12.5px] font-semibold text-primary-foreground shadow-sm transition-all hover:bg-foreground/90 active:scale-[0.98] disabled:opacity-50"
                >
                    {copied ? <Check className="h-3.5 w-3.5" /> : <Copy className="h-3.5 w-3.5" />}
                    {copied ? 'Copied' : 'Copy link'}
                </button>
            </div>
        </SidebarBannerCard>
    );
}
