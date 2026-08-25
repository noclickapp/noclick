/**
 * Standalone SendButton — circular send/stop affordance shared by the chat
 * input and prompt-style inputs (HeroPromptShowcase, FlowCanvasEmptyState).
 * Lives in its own file so importing it from the public landing page does not
 * drag in ChatBox's transitive socket/workflow/registry dependencies.
 */

import { memo } from 'react';
import { ArrowUp, Square } from 'lucide-react';
import { cn } from '~/lib/utils';

interface SendButtonProps {
    onClick: () => void;
    hasContent: boolean;
    isWaitingForResponse: boolean;
    showBorder: boolean;
    onInterrupt?: () => void;
    size?: 'sm' | 'lg';
}

export const SendButton = memo(
    ({
        onClick,
        hasContent,
        isWaitingForResponse,
        showBorder,
        onInterrupt,
        size = 'sm',
    }: SendButtonProps) => {
        const isEnabled = hasContent && !isWaitingForResponse;
        const showStopIcon = isWaitingForResponse;
        // Sizing mirrors the chat ratios (icon ≈ 0.58 × button) so 'lg' is just a scaled-up
        // version of the chat send button. 'sm': 24px button / 14px icon. 'lg': 36px button / 20px icon.
        const sizeClasses = size === 'lg' ? 'w-9 h-9' : 'w-6 h-6';
        const iconSize = size === 'lg' ? 'w-5 h-5' : 'w-3.5 h-3.5';
        const stopIconSize = size === 'lg' ? 'w-4 h-4' : 'w-3 h-3';

        return (
            <button
                onClick={showStopIcon ? onInterrupt : onClick}
                disabled={!showStopIcon && !hasContent}
                className={cn(
                    'p-0 rounded-full relative',
                    'flex items-center justify-center',
                    sizeClasses,
                    'transition-all duration-300 ease-out',
                    showStopIcon
                        ? // A dark filled circle (charcoal in light, zinc-900 in dark) with
                          // a white spinner + square — mirrors the enabled button and the
                          // dark-mode loading look. The white comes from the button's text
                          // color, which the spinner picks up via currentColor.
                          'text-primary-foreground bg-primary hover:bg-primary/90 dark:text-foreground dark:bg-card dark:hover:bg-accent'
                        : isEnabled
                          ? 'text-primary-foreground bg-primary hover:bg-primary/90 dark:text-foreground dark:bg-card dark:hover:bg-accent'
                          : // Dark pinned to the original (bg-muted was darker than
                            // the old zinc-700/50 blend); light keeps bg-muted.
                            'text-muted-foreground dark:text-zinc-500 bg-muted dark:bg-zinc-700/50 cursor-not-allowed'
                )}
                style={{
                    boxShadow:
                        showBorder || showStopIcon
                            ? '0 0 0 1.5px hsl(var(--send-ring))'
                            : '0 0 0 1.5px transparent',
                    transition:
                        'box-shadow 200ms cubic-bezier(0.25, 0.46, 0.45, 0.94), background-color 200ms ease-out, color 200ms ease-out',
                }}
                aria-label={showStopIcon ? 'Stop generation' : 'Send message'}
            >
                {showStopIcon && (
                    <>
                        {/* Spinner ring sits 1.5px OUTSIDE the fill, on the panel. Uses
                            --send-beam (mid-gray in light, white in dark) so it reads on
                            the panel AND stays distinct from the dark fill — a near-black
                            beam merged into the charcoal circle and looked like a bulge.
                            Track = faint full ring. */}
                        <div
                            className="absolute -inset-[1.5px] rounded-full"
                            style={{ background: 'hsl(var(--send-beam) / 0.4)' }}
                        />
                        {/* Rotating highlight — a SMALL bright segment (not a wide arc)
                            so it reads as a dot orbiting the ring, not a lump bulging
                            off the circle. */}
                        <div
                            className="absolute -inset-[1.5px] rounded-full animate-spin"
                            style={{
                                background:
                                    'conic-gradient(from 0deg at 50% 50%, transparent 0deg, hsl(var(--send-beam)) 24deg, transparent 46deg)',
                                animation: 'spin 1s linear infinite',
                            }}
                        />
                        {/* Inner circle covers the button center, leaving the 1.5px
                            spinner ring; matches the button fill (charcoal / zinc-900). */}
                        <div className="absolute inset-0 rounded-full bg-primary dark:bg-card" />
                    </>
                )}
                {showStopIcon ? (
                    <Square
                        className={cn(
                            stopIconSize,
                            'relative z-10 fill-current'
                        )}
                        strokeWidth={0}
                    />
                ) : (
                    <ArrowUp
                        className={cn(iconSize, 'relative z-10')}
                        strokeWidth={2}
                    />
                )}
            </button>
        );
    }
);
SendButton.displayName = 'SendButton';
