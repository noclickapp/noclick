// Shared chrome for the chat-sidebar nudge banners (sidebar banners): the
// rounded zinc card, a soft top glow, an animated hero band over the canvas dot-grid, the
// delayed "Don't show again" control, and the dismiss ✕. Each banner supplies its own hero
// art + body. Extracted so the two banners can't drift apart visually, and so the opt-out
// reveal timer lives with the card (which mounts only when its banner is shown), giving the
// "fade in after a few seconds" delay every time the banner appears.

import { useEffect, useState, type ReactNode } from 'react';
import { X } from 'lucide-react';
import { cn } from '~/lib/utils';

interface SidebarBannerCardProps {
    /** Animated art rendered inside the hero band (positioned absolutely within it). */
    hero: ReactNode;
    /** CSS color for the soft top radial glow (default: faint white). */
    glowColor?: string;
    /** Tailwind class for the hero band height (default: h-[112px]). */
    bandClassName?: string;
    /** Renders the dismiss (✕) when provided. */
    onDismiss?: () => void;
    /** Renders the subtle, delayed "Don't show again" control when provided. */
    onDontShowAgain?: () => void;
    /** Extra classes for the outer card (e.g. a fixed width in a popover). */
    className?: string;
    /** Title row + body (description, CTA, link, etc.). */
    children: ReactNode;
}

export function SidebarBannerCard({
    hero,
    glowColor = 'hsl(var(--foreground) / 0.10)',
    bandClassName = 'h-[112px]',
    onDismiss,
    onDontShowAgain,
    className,
    children,
}: SidebarBannerCardProps) {
    // The low-key opt-out reveals (fades in) only after the banner has been visible a few
    // seconds, so it doesn't compete with the banner up front.
    const [showOptOut, setShowOptOut] = useState(false);
    useEffect(() => {
        const t = setTimeout(() => setShowOptOut(true), 5000);
        return () => clearTimeout(t);
    }, []);

    return (
        <div
            className={cn(
                'relative overflow-hidden rounded-2xl border border-border dark:border-white/10 bg-card shadow-lg dark:shadow-[0_10px_34px_-8px_rgba(0,0,0,0.7)]',
                className
            )}
        >
            {/* Soft glow from the top */}
            <div
                aria-hidden
                className="pointer-events-none absolute inset-0"
                style={{
                    background: `radial-gradient(130% 90% at 50% -10%, ${glowColor}, transparent 55%)`,
                }}
            />

            {/* Hero band over a faint canvas dot-grid */}
            <div
                className={cn(
                    'relative overflow-hidden bg-[hsl(var(--canvas-bg))] dark:bg-[#0c0c10]',
                    bandClassName
                )}
                style={{
                    backgroundImage:
                        'radial-gradient(circle, hsl(var(--foreground) / 0.08) 1px, transparent 1px)',
                    backgroundSize: '13px 13px',
                }}
            >
                {hero}
                {/* Fade the band into the content below */}
                <div className="pointer-events-none absolute inset-x-0 bottom-0 h-8 bg-gradient-to-t from-card to-transparent" />
            </div>

            {/* Don't show again — top-left, blends into the dark band, fades in after a delay. */}
            {onDontShowAgain && (
                <button
                    type="button"
                    onClick={onDontShowAgain}
                    aria-hidden={!showOptOut}
                    tabIndex={showOptOut ? 0 : -1}
                    className={cn(
                        'absolute left-2 top-2 z-10 rounded-full px-2 py-1 text-[11px] font-medium text-foreground/35 transition-all duration-700 hover:bg-foreground/10 hover:text-foreground/80',
                        showOptOut
                            ? 'opacity-100'
                            : 'pointer-events-none opacity-0'
                    )}
                >
                    Don’t show again
                </button>
            )}

            {/* Dismiss */}
            {onDismiss && (
                <button
                    type="button"
                    onClick={onDismiss}
                    aria-label="Dismiss"
                    title="Dismiss"
                    className="absolute right-2 top-2 z-10 rounded-full p-1 text-muted-foreground transition-colors hover:bg-foreground/10 hover:text-foreground"
                >
                    <X className="h-3.5 w-3.5" />
                </button>
            )}

            {/* Content */}
            <div className="relative px-3.5 pb-3.5 pt-1.5">{children}</div>
        </div>
    );
}
