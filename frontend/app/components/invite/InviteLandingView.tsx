// The invite landing experience (/i/<token>) for logged-out visitors.
// Black canvas-style background (FlowCanvas dot-grid on pure black). LEFT = a
// clean, minimal invite context (inviter, headline, the workflow being shared).
// RIGHT = the real auth panel (Google + email/password + Turnstile), given more
// room. No flow animation, no "Live"/"editing now" signals.

import { useState } from 'react';
import { motion } from 'framer-motion';
import { InviteAuthPanel } from '~/components/invite/InviteAuthPanel';
import { LogoMark } from '~/components/shared/LogoMark';

interface InviteLandingViewProps {
    ownerName: string;
    ownerAvatar: string;
    workflowName: string;
    csrfToken: string;
}

export function InviteLandingView({
    ownerName,
    ownerAvatar,
    workflowName,
    csrfToken,
}: InviteLandingViewProps) {
    const [avatarOk, setAvatarOk] = useState(true);
    const initial = (ownerName || 'S').trim().charAt(0).toUpperCase() || 'S';
    const firstName = (ownerName || '').split(' ')[0] || ownerName || 'them';

    return (
        <div className="relative min-h-screen w-full overflow-hidden bg-background font-sans text-foreground antialiased selection:bg-foreground/15">
            {/* Canvas-style dot grid on pure black — prominent */}
            <div
                aria-hidden
                className="pointer-events-none absolute inset-0"
                style={{
                    backgroundImage:
                        'radial-gradient(circle, hsl(var(--foreground) / 0.10) 1.2px, transparent 1.2px)',
                    backgroundSize: '24px 24px',
                }}
            />
            {/* Vignette — ease the edges back toward black */}
            <div
                aria-hidden
                className="pointer-events-none absolute inset-0 bg-[radial-gradient(130%_110%_at_50%_26%,transparent_55%,hsl(var(--background)_/_0.72))]"
            />

            <div className="relative z-10 mx-auto flex min-h-screen w-full max-w-[1340px] flex-col lg:flex-row">
                {/* -------------------- LEFT: invite context -------------------- */}
                <div className="flex w-full flex-col px-8 pt-8 sm:px-12 lg:w-1/2 lg:px-16">
                    <a href="/" className="flex items-center gap-2.5">
                        <LogoMark className="h-8 w-8" />
                        <span className="text-2xl font-bold tracking-tight text-foreground">
                            NoClick
                        </span>
                    </a>

                    <div className="flex flex-1 flex-col justify-center py-12">
                        <motion.div
                            initial={{ opacity: 0, y: 14, filter: 'blur(6px)' }}
                            animate={{ opacity: 1, y: 0, filter: 'blur(0px)' }}
                            transition={{
                                duration: 0.6,
                                ease: [0.22, 1, 0.36, 1],
                            }}
                            className="w-full max-w-[460px]"
                        >
                            {/* Inviter — name featured */}
                            <div className="mb-7 flex items-center gap-3.5">
                                {avatarOk && ownerAvatar ? (
                                    <img
                                        src={ownerAvatar}
                                        alt={ownerName}
                                        onError={() => setAvatarOk(false)}
                                        className="rounded-full border border-foreground/15 object-cover"
                                        style={{
                                            height: '3.25rem',
                                            width: '3.25rem',
                                        }}
                                    />
                                ) : (
                                    <div
                                        className="flex items-center justify-center rounded-full border border-foreground/15 bg-secondary text-xl font-semibold text-foreground"
                                        style={{
                                            height: '3.25rem',
                                            width: '3.25rem',
                                        }}
                                    >
                                        {initial}
                                    </div>
                                )}
                                <div className="leading-tight">
                                    <p className="text-[19px] font-semibold tracking-tight text-foreground">
                                        {ownerName}
                                    </p>
                                    <p className="mt-0.5 text-[13.5px] text-muted-foreground">
                                        invited you to collaborate
                                    </p>
                                </div>
                            </div>

                            <h1 className="text-[2.4rem] font-semibold leading-[1.08] tracking-tight text-foreground sm:text-[2.9rem]">
                                Build together
                                <br className="hidden sm:block" /> with{' '}
                                {firstName}
                            </h1>
                            <p className="mt-4 max-w-[420px] text-[15.5px] leading-relaxed text-muted-foreground">
                                Join {firstName} on the exact same flow and edit
                                it side by side. No fork, no copy — one shared
                                workspace.
                            </p>

                            {/* Workflow pill (text only — no icon, no animation) */}
                            <div className="mt-8 flex w-full max-w-[440px] flex-col rounded-2xl border border-foreground/10 bg-sunken px-5 py-4">
                                <p className="text-[11px] font-medium uppercase tracking-wider text-muted-foreground/70 dark:text-zinc-500">
                                    Shared workflow
                                </p>
                                <p className="mt-1 truncate text-[21px] font-semibold tracking-tight text-foreground">
                                    {workflowName}
                                </p>
                            </div>
                        </motion.div>
                    </div>

                    <div className="pb-8 pt-4">
                        <p className="max-w-[440px] text-[13.5px] leading-relaxed text-muted-foreground/70 dark:text-zinc-500">
                            New to NoClick? It’s where teams build internal
                            tools, interfaces, AI agents, and automations
                            together — visually, on one shared canvas, in real
                            time.
                        </p>
                    </div>
                </div>

                {/* -------------------- RIGHT: auth -------------------- */}
                <div className="relative flex w-full items-center justify-center px-8 pb-14 pt-4 sm:px-12 lg:w-1/2 lg:py-12">
                    <InviteAuthPanel
                        csrfToken={csrfToken}
                        ownerName={ownerName}
                    />
                </div>
            </div>
        </div>
    );
}
