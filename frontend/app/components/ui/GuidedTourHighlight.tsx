/**
 * GuidedTourHighlight - A spotlight component for guided tours.
 * Creates a dark overlay with an animated mono (white/silver) shimmer border around the target element.
 * Features a redesigned tooltip with video, title, description, and CTA button.
 */

import { useState, useEffect, useRef, useCallback, useId } from 'react';
import { createPortal } from 'react-dom';

export interface TourStep {
    /** CSS selector for the target element */
    target: string;
    /** Large title displayed below the video */
    title: string;
    /** 1-2 sentence description of what this element does */
    description: string;
    /** Text for the CTA button (e.g., "Click to open", "Got it") */
    buttonText: string;
    /** Optional custom illustration (HTML/SVG) for the top media tile. Takes
     *  precedence over videoSrc — use for simple steps that don't need a video. */
    media?: React.ReactNode;
    /** Optional path to a .webm video to display at the top */
    videoSrc?: string;
    /** Position of the tooltip relative to the highlighted element */
    placement?: 'top' | 'bottom' | 'left' | 'right';
    /** Optional padding around the target element */
    padding?: number;
    /** If true, draw border inside the target area (for edge-of-screen elements) */
    insetBorder?: boolean;
    /** If true, clicking the highlighted area advances the tour */
    advanceOnTargetClick?: boolean;
    /** Called when advancing FROM this step (before transitioning to next step) */
    action?: () => void | Promise<void>;
    /** Called when ENTERING this step (after transition, before showing highlight) */
    onEnter?: () => void;
}

interface GuidedTourHighlightProps {
    /** Array of steps in the tour */
    steps: TourStep[];
    /** Whether the tour is currently active */
    isActive: boolean;
    /** Callback when the tour is closed or completed */
    onClose: () => void;
    /** Callback when the tour is completed (all steps done) */
    onComplete?: () => void;
    /** Starting step index (default: 0) */
    startStep?: number;
    /** Callback that runs once when the tour starts (before first step) */
    onStart?: () => void;
}

interface TargetRect {
    top: number;
    left: number;
    width: number;
    height: number;
}

/**
 * Video player component with delayed loop (1.2s gap before replay).
 */
function TourVideo({ src }: { src: string }) {
    const videoRef = useRef<HTMLVideoElement>(null);

    useEffect(() => {
        const video = videoRef.current;
        if (!video) return;

        const handleEnded = () => {
            // Wait 1.2 seconds before replaying
            setTimeout(() => {
                if (videoRef.current) {
                    videoRef.current.currentTime = 0;
                    videoRef.current.play().catch(() => {});
                }
            }, 1200);
        };

        video.addEventListener('ended', handleEnded);
        return () => video.removeEventListener('ended', handleEnded);
    }, []);

    return (
        <video
            ref={videoRef}
            autoPlay
            muted
            playsInline
            className="w-full h-full object-cover"
        >
            <source src={src} type="video/webm" />
        </video>
    );
}

/**
 * Efficiently waits for an element to appear in the DOM using MutationObserver.
 * Returns immediately if element already exists.
 */
function waitForElement(selector: string, timeout = 5000): Promise<Element | null> {
    return new Promise((resolve) => {
        // Check if element already exists
        const existing = document.querySelector(selector);
        if (existing) {
            resolve(existing);
            return;
        }

        let timeoutId: ReturnType<typeof setTimeout>;

        const observer = new MutationObserver(() => {
            const element = document.querySelector(selector);
            if (element) {
                observer.disconnect();
                clearTimeout(timeoutId);
                resolve(element);
            }
        });

        observer.observe(document.body, {
            childList: true,
            subtree: true,
        });

        // Timeout fallback
        timeoutId = setTimeout(() => {
            observer.disconnect();
            // One final check before giving up
            resolve(document.querySelector(selector));
        }, timeout);
    });
}

export function GuidedTourHighlight({
    steps,
    isActive,
    onClose,
    onComplete,
    startStep = 0,
    onStart,
}: GuidedTourHighlightProps) {
    const [currentStep, setCurrentStep] = useState(startStep);
    const [targetRect, setTargetRect] = useState<TargetRect | null>(null);
    const [isVisible, setIsVisible] = useState(false);
    const [isTransitioning, setIsTransitioning] = useState(false);
    const [tooltipSize, setTooltipSize] = useState({ width: 420, height: 400 });
    const tooltipRef = useRef<HTMLDivElement>(null);
    // Per-instance suffix for SVG defs ids (mask/gradient/filter) so two tours
    // active at once can't collide — url(#id) would otherwise resolve to the
    // first match. (':' stripped: useId ids contain colons.)
    const uid = useId().replace(/:/g, '');

    const observerRef = useRef<ResizeObserver | null>(null);
    const animationFrameRef = useRef<number | null>(null);
    const mountedRef = useRef(true);

    // Track the activation state to prevent re-initialization on re-renders
    const activationIdRef = useRef(0);
    const currentActivationRef = useRef(0);

    // Use refs for callbacks to avoid stale closures and dependency issues
    const stepsRef = useRef(steps);
    const onCompleteRef = useRef(onComplete);
    const onCloseRef = useRef(onClose);
    const onStartRef = useRef(onStart);

    // Keep refs updated
    useEffect(() => {
        stepsRef.current = steps;
        onCompleteRef.current = onComplete;
        onCloseRef.current = onClose;
        onStartRef.current = onStart;
    });

    // Measure tooltip dimensions after it renders
    useEffect(() => {
        if (!tooltipRef.current || !isVisible) return;

        const measureTooltip = () => {
            if (tooltipRef.current) {
                const rect = tooltipRef.current.getBoundingClientRect();
                setTooltipSize({ width: rect.width, height: rect.height });
            }
        };

        // Measure after a brief delay to ensure content has rendered
        const timeoutId = setTimeout(measureTooltip, 50);

        // Also observe for size changes
        const observer = new ResizeObserver(measureTooltip);
        observer.observe(tooltipRef.current);

        return () => {
            clearTimeout(timeoutId);
            observer.disconnect();
        };
    }, [isVisible, currentStep]);

    const step = steps[currentStep];

    // Cleanup helper
    const cleanupTracking = useCallback(() => {
        if (animationFrameRef.current) {
            cancelAnimationFrame(animationFrameRef.current);
            animationFrameRef.current = null;
        }
        if (observerRef.current) {
            observerRef.current.disconnect();
            observerRef.current = null;
        }
    }, []);

    // Update target rect from element
    const updateTargetRect = useCallback((element: Element, padding: number) => {
        const rect = element.getBoundingClientRect();
        setTargetRect({
            top: rect.top - padding,
            left: rect.left - padding,
            width: rect.width + padding * 2,
            height: rect.height + padding * 2,
        });
    }, []);

    // Start tracking an element's position
    const startTrackingElement = useCallback((element: Element, padding: number) => {
        // Initial position
        updateTargetRect(element, padding);

        // Track position changes via animation frame
        const trackPosition = () => {
            if (!mountedRef.current) return;
            updateTargetRect(element, padding);
            animationFrameRef.current = requestAnimationFrame(trackPosition);
        };
        animationFrameRef.current = requestAnimationFrame(trackPosition);

        // Watch for element resize
        observerRef.current = new ResizeObserver(() => {
            updateTargetRect(element, padding);
        });
        observerRef.current.observe(element);
    }, [updateTargetRect]);

    // Initialize a step - find element and start tracking
    const initializeStep = useCallback(async (stepIndex: number, activationId: number) => {
        const stepData = stepsRef.current[stepIndex];
        if (!stepData) return;

        // Check if this activation is still current (prevents stale async operations)
        if (activationId !== currentActivationRef.current) return;

        cleanupTracking();
        setTargetRect(null);

        // Call onEnter for this step
        stepData.onEnter?.();

        // Wait for target element to appear
        const element = await waitForElement(stepData.target);

        // Check again after async operation
        if (!mountedRef.current || activationId !== currentActivationRef.current) return;

        if (element) {
            const padding = stepData.padding ?? 4;
            startTrackingElement(element, padding);
            // Small delay to ensure smooth transition
            setTimeout(() => {
                if (mountedRef.current && activationId === currentActivationRef.current) {
                    setIsVisible(true);
                    setIsTransitioning(false);
                }
            }, 50);
        } else {
            // Element not found - log warning
            console.warn(`Tour target not found: ${stepData.target}`);
            setIsTransitioning(false);
        }
    }, [cleanupTracking, startTrackingElement]);

    // Handle advancing to next step
    const handleNext = useCallback(async () => {
        if (isTransitioning) return;

        const currentStepData = stepsRef.current[currentStep];
        const isLastStep = currentStep >= stepsRef.current.length - 1;
        const activationId = currentActivationRef.current;

        setIsTransitioning(true);
        setIsVisible(false);

        // Call action for current step (e.g., open a panel)
        if (currentStepData?.action) {
            try {
                await currentStepData.action();
            } catch (error) {
                console.error('Tour step action failed:', error);
            }
        }

        // A step action can legitimately unmount this tour as a side effect
        // (e.g. the agent-chat step switches to the Interface tab, unmounting
        // the canvas subtree that renders the tour). Completion acts on the
        // still-mounted parent's state, so gate it only on the activation id
        // (a superseded tour) — NOT on mountedRef, or the tour would never be
        // marked done and would reappear when the user returns to the tab.
        if (activationId !== currentActivationRef.current) return;

        // Small delay for fade out animation
        await new Promise(resolve => setTimeout(resolve, 150));

        if (activationId !== currentActivationRef.current) return;

        if (isLastStep) {
            onCompleteRef.current?.();
            onCloseRef.current();
        } else {
            // Advancing to another step needs this component still mounted to
            // position the next target.
            if (!mountedRef.current) return;
            const nextStep = currentStep + 1;
            setCurrentStep(nextStep);
            await initializeStep(nextStep, activationId);
        }
    }, [currentStep, isTransitioning, initializeStep]);

    // Initialize tour when it becomes active - only react to isActive changes
    useEffect(() => {
        mountedRef.current = true;

        if (isActive) {
            // New activation - increment ID to invalidate any pending async operations
            activationIdRef.current += 1;
            currentActivationRef.current = activationIdRef.current;
            const activationId = activationIdRef.current;

            // Call onStart
            onStartRef.current?.();

            // Initialize first step
            setCurrentStep(startStep);
            initializeStep(startStep, activationId);
        } else {
            // Tour ended - invalidate current activation
            currentActivationRef.current = -1;
            setIsVisible(false);
            setTargetRect(null);
            setCurrentStep(startStep);
            cleanupTracking();
        }

        return () => {
            mountedRef.current = false;
            cleanupTracking();
        };
        // Only re-run when isActive changes - NOT when callbacks change
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [isActive]);

    if (!isActive || !step) return null;

    // Calculate tooltip position with smart edge detection
    // Ensures tooltip never overlaps with the highlighted target
    const getTooltipPosition = (): React.CSSProperties => {
        if (!targetRect) return { opacity: 0 };

        const placement = step.placement ?? 'bottom';
        const tooltipWidth = tooltipSize.width;
        // Use measured height, with a conservative fallback for first render
        // Video (420 × 9/16 = 236) + content (~150) = ~386, round up to 400
        const tooltipHeight = tooltipSize.height > 100 ? tooltipSize.height : 400;
        const tooltipOffset = 20;
        const edgePadding = 16;
        const viewportWidth = window.innerWidth;
        const viewportHeight = window.innerHeight;

        // Calculate available space in each direction (from target edge to viewport edge)
        const spaceAbove = targetRect.top - edgePadding;
        const spaceBelow = viewportHeight - targetRect.top - targetRect.height - edgePadding;
        const spaceLeft = targetRect.left - edgePadding;
        const spaceRight = viewportWidth - targetRect.left - targetRect.width - edgePadding;

        // Helper to clamp horizontal position (never overlap target horizontally for top/bottom)
        const clampLeftHorizontal = (left: number) => {
            const minLeft = edgePadding;
            const maxLeft = viewportWidth - tooltipWidth - edgePadding;
            return Math.max(minLeft, Math.min(maxLeft, left));
        };

        // Helper to clamp vertical position for left/right placement
        // Ensures tooltip doesn't overlap the target vertically
        const clampTopVertical = (top: number) => {
            const minTop = edgePadding;
            const maxTop = viewportHeight - tooltipHeight - edgePadding;
            return Math.max(minTop, Math.min(maxTop, top));
        };

        // Calculate centered positions
        const centeredLeft = targetRect.left + targetRect.width / 2 - tooltipWidth / 2;
        const centeredTop = targetRect.top + targetRect.height / 2 - tooltipHeight / 2;

        // Determine best vertical placement (top vs bottom)
        const getVerticalPlacement = (preferred: 'top' | 'bottom'): React.CSSProperties => {
            const neededSpace = tooltipHeight + tooltipOffset;

            // Check if preferred placement fits
            if (preferred === 'top' && spaceAbove >= neededSpace) {
                return {
                    top: targetRect.top - tooltipHeight - tooltipOffset,
                    left: clampLeftHorizontal(centeredLeft),
                };
            }
            if (preferred === 'bottom' && spaceBelow >= neededSpace) {
                return {
                    top: targetRect.top + targetRect.height + tooltipOffset,
                    left: clampLeftHorizontal(centeredLeft),
                };
            }

            // Preferred doesn't fit, try opposite
            if (preferred === 'top' && spaceBelow >= neededSpace) {
                return {
                    top: targetRect.top + targetRect.height + tooltipOffset,
                    left: clampLeftHorizontal(centeredLeft),
                };
            }
            if (preferred === 'bottom' && spaceAbove >= neededSpace) {
                return {
                    top: targetRect.top - tooltipHeight - tooltipOffset,
                    left: clampLeftHorizontal(centeredLeft),
                };
            }

            // Neither fits well, use whichever has more space
            if (spaceBelow >= spaceAbove) {
                return {
                    top: targetRect.top + targetRect.height + tooltipOffset,
                    left: clampLeftHorizontal(centeredLeft),
                };
            }
            return {
                top: Math.max(edgePadding, targetRect.top - tooltipHeight - tooltipOffset),
                left: clampLeftHorizontal(centeredLeft),
            };
        };

        // Determine best horizontal placement (left vs right)
        const getHorizontalPlacement = (preferred: 'left' | 'right'): React.CSSProperties => {
            const neededSpace = tooltipWidth + tooltipOffset;

            // Check if preferred placement fits
            if (preferred === 'left' && spaceLeft >= neededSpace) {
                return {
                    top: clampTopVertical(centeredTop),
                    left: targetRect.left - tooltipWidth - tooltipOffset,
                };
            }
            if (preferred === 'right' && spaceRight >= neededSpace) {
                return {
                    top: clampTopVertical(centeredTop),
                    left: targetRect.left + targetRect.width + tooltipOffset,
                };
            }

            // Preferred doesn't fit, try opposite
            if (preferred === 'left' && spaceRight >= neededSpace) {
                return {
                    top: clampTopVertical(centeredTop),
                    left: targetRect.left + targetRect.width + tooltipOffset,
                };
            }
            if (preferred === 'right' && spaceLeft >= neededSpace) {
                return {
                    top: clampTopVertical(centeredTop),
                    left: targetRect.left - tooltipWidth - tooltipOffset,
                };
            }

            // Neither horizontal fits, fall back to vertical placement
            return getVerticalPlacement('bottom');
        };

        switch (placement) {
            case 'top':
                return getVerticalPlacement('top');
            case 'bottom':
                return getVerticalPlacement('bottom');
            case 'left':
                return getHorizontalPlacement('left');
            case 'right':
                return getHorizontalPlacement('right');
        }
    };

    const content = (
        // While there's no spotlight target (target not yet found, or never found because
        // waitForElement timed out), the full-screen layer must NOT swallow clicks — otherwise
        // a tour whose target never appears (e.g. a node hidden in read-only/replay mode) leaves
        // an invisible overlay that locks the whole UI. Block clicks only once a target exists.
        <div
            className={`fixed inset-0 z-[9999] transition-opacity duration-200 ${
                isVisible ? 'opacity-100' : 'opacity-0'
            } ${targetRect ? '' : 'pointer-events-none'}`}
        >
            {/* Dark overlay with cutout for target */}
            <svg className="absolute inset-0 w-full h-full pointer-events-none">
                <defs>
                    <mask id={`tour-spotlight-mask-${uid}`}>
                        <rect x="0" y="0" width="100%" height="100%" fill="white" />
                        {targetRect && (
                            <rect
                                x={targetRect.left}
                                y={targetRect.top}
                                width={targetRect.width}
                                height={targetRect.height}
                                rx="12"
                                fill="black"
                            />
                        )}
                    </mask>
                </defs>
                <rect
                    x="0"
                    y="0"
                    width="100%"
                    height="100%"
                    fill="rgba(0, 0, 0, 0.75)"
                    mask={`url(#tour-spotlight-mask-${uid})`}
                />
            </svg>

            {/* Non-interactive backdrop - tour must be completed */}
            <div className="absolute inset-0" />

            {/* Clickable target overlay - advances tour when clicking the highlighted element */}
            {targetRect && step?.advanceOnTargetClick && !isTransitioning && (
                <div
                    className="absolute cursor-pointer rounded-xl hover:bg-foreground/5 transition-colors"
                    style={{
                        top: targetRect.top,
                        left: targetRect.left,
                        width: targetRect.width,
                        height: targetRect.height,
                    }}
                    onClick={(e) => {
                        e.stopPropagation();
                        handleNext();
                    }}
                />
            )}

            {/* Ember gradient border around target - SVG stroke approach for better compatibility */}
            {targetRect && (() => {
                const inset = step?.insetBorder;
                const strokeWidth = 3;
                const pulseStroke = 7; // peak stroke of the attention pulse (see <rect> animates)

                // Inset: border drawn inside the target (for edge-of-screen elements)
                // Normal: border drawn outside, hugging the target tightly
                if (inset) {
                    // Border inside: SVG matches target, rect inset by half stroke width.
                    // overflow:visible lets the blurred glow halo spill past the svg box.
                    return (
                        <svg
                            className="absolute pointer-events-none"
                            style={{
                                top: targetRect.top,
                                left: targetRect.left,
                                width: targetRect.width,
                                height: targetRect.height,
                                overflow: 'visible',
                            }}
                        >
                            <defs>
                                <linearGradient id={`mono-shimmer-inset-${uid}`} gradientUnits="userSpaceOnUse" x1="0%" y1="0%" x2="100%" y2="100%">
                                    <stop offset="0%" stopColor="#ffffff">
                                        <animate attributeName="stop-color" values="#ffffff;#d4d4d8;#a1a1aa;#e4e4e7;#ffffff" dur="1.8s" repeatCount="indefinite" />
                                    </stop>
                                    <stop offset="50%" stopColor="#d4d4d8">
                                        <animate attributeName="stop-color" values="#d4d4d8;#a1a1aa;#e4e4e7;#ffffff;#d4d4d8" dur="1.8s" repeatCount="indefinite" />
                                    </stop>
                                    <stop offset="100%" stopColor="#a1a1aa">
                                        <animate attributeName="stop-color" values="#a1a1aa;#e4e4e7;#ffffff;#d4d4d8;#a1a1aa" dur="1.8s" repeatCount="indefinite" />
                                    </stop>
                                </linearGradient>
                                {/* Static blur — only the glow rect's own stroke/opacity animate
                                    (SMIL on filter primitives is unreliable in Chrome). */}
                                <filter id={`tour-glow-inset-${uid}`} x="-75%" y="-75%" width="250%" height="250%">
                                    <feGaussianBlur stdDeviation="4" />
                                </filter>
                            </defs>
                            {/* Pulsing white glow halo — the main "notice me" cue. */}
                            <rect
                                x={strokeWidth / 2}
                                y={strokeWidth / 2}
                                width={targetRect.width - strokeWidth}
                                height={targetRect.height - strokeWidth}
                                rx="10"
                                ry="10"
                                fill="none"
                                stroke="#ffffff"
                                strokeWidth={6}
                                filter={`url(#tour-glow-inset-${uid})`}
                            >
                                <animate attributeName="stroke-width" values="4;12;4" dur="0.8s" repeatCount="indefinite" />
                                <animate attributeName="opacity" values="0.6;0.12;0.6" dur="0.8s" repeatCount="indefinite" />
                            </rect>
                            {/* Crisp gradient border that throbs in sync. */}
                            <rect
                                x={strokeWidth / 2}
                                y={strokeWidth / 2}
                                width={targetRect.width - strokeWidth}
                                height={targetRect.height - strokeWidth}
                                rx="10"
                                ry="10"
                                fill="none"
                                stroke={`url(#mono-shimmer-inset-${uid})`}
                                strokeWidth={strokeWidth}
                            >
                                <animate attributeName="opacity" values="1;0.65;1" dur="0.8s" repeatCount="indefinite" />
                            </rect>
                        </svg>
                    );
                }

                // Border outside: SVG extends beyond target, rect sized to hug target
                const padding = 4; // Gap between target and border
                // Size the svg for the MAX (pulsed) stroke so the rapid stroke-width
                // pulse below can't clip at the svg edge. The rect still hugs the
                // target+padding (its absolute position is unchanged).
                // overflow:visible lets the blurred glow halo render past the svg box.
                return (
                    <svg
                        className="absolute pointer-events-none"
                        style={{
                            top: targetRect.top - padding - pulseStroke / 2,
                            left: targetRect.left - padding - pulseStroke / 2,
                            width: targetRect.width + (padding + pulseStroke / 2) * 2,
                            height: targetRect.height + (padding + pulseStroke / 2) * 2,
                            overflow: 'visible',
                        }}
                    >
                        <defs>
                            <linearGradient id={`mono-shimmer-${uid}`} gradientUnits="userSpaceOnUse" x1="0%" y1="0%" x2="100%" y2="100%">
                                <stop offset="0%" stopColor="#ffffff">
                                    <animate attributeName="stop-color" values="#ffffff;#d4d4d8;#a1a1aa;#e4e4e7;#ffffff" dur="1.8s" repeatCount="indefinite" />
                                </stop>
                                <stop offset="50%" stopColor="#d4d4d8">
                                    <animate attributeName="stop-color" values="#d4d4d8;#a1a1aa;#e4e4e7;#ffffff;#d4d4d8" dur="1.8s" repeatCount="indefinite" />
                                </stop>
                                <stop offset="100%" stopColor="#a1a1aa">
                                    <animate attributeName="stop-color" values="#a1a1aa;#e4e4e7;#ffffff;#d4d4d8;#a1a1aa" dur="1.8s" repeatCount="indefinite" />
                                </stop>
                            </linearGradient>
                            {/* Static blur — only the glow rect's own stroke/opacity animate
                                (SMIL on filter primitives is unreliable in Chrome). */}
                            <filter id={`tour-glow-${uid}`} x="-75%" y="-75%" width="250%" height="250%">
                                <feGaussianBlur stdDeviation="4" />
                            </filter>
                        </defs>
                        {/* Pulsing white glow halo behind the border — the main attention cue. */}
                        <rect
                            x={pulseStroke / 2}
                            y={pulseStroke / 2}
                            width={targetRect.width + padding * 2}
                            height={targetRect.height + padding * 2}
                            rx="12"
                            ry="12"
                            fill="none"
                            stroke="#ffffff"
                            strokeWidth={6}
                            filter={`url(#tour-glow-${uid})`}
                        >
                            <animate attributeName="stroke-width" values="5;14;5" dur="0.8s" repeatCount="indefinite" />
                            <animate attributeName="opacity" values="0.65;0.1;0.65" dur="0.8s" repeatCount="indefinite" />
                        </rect>
                        {/* Crisp gradient border that throbs thicker in sync. */}
                        <rect
                            x={pulseStroke / 2}
                            y={pulseStroke / 2}
                            width={targetRect.width + padding * 2}
                            height={targetRect.height + padding * 2}
                            rx="12"
                            ry="12"
                            fill="none"
                            stroke={`url(#mono-shimmer-${uid})`}
                            strokeWidth={strokeWidth}
                        >
                            <animate attributeName="stroke-width" values={`${strokeWidth};${pulseStroke};${strokeWidth}`} dur="0.8s" repeatCount="indefinite" />
                        </rect>
                    </svg>
                );
            })()}

            {/* Redesigned Tooltip Card. Width shrinks on small/short viewports (vmin)
                while still honoring the global low-res root-font scaling at <=1366 via
                the rem bounds; caps at 26.25rem (=420px @16px root) so large screens are
                unchanged. Inline style (not a Tailwind class) so the clamp() is reliable. */}
            <div
                ref={tooltipRef}
                className="absolute pointer-events-auto z-10"
                style={{ ...getTooltipPosition(), width: 'clamp(20rem, 48vmin, 26.25rem)' }}
                onClick={(e) => e.stopPropagation()}
            >
                <div
                    className="rounded-2xl overflow-hidden"
                    style={{
                        background: 'linear-gradient(180deg, hsl(var(--secondary)) 0%, hsl(var(--popover)) 100%)',
                        boxShadow: '0 25px 50px -12px rgba(0, 0, 0, 0.5), 0 0 0 1px hsl(var(--border))',
                    }}
                >
                    {/* Media section: custom illustration > video > placeholder */}
                    <div className="relative w-full aspect-video bg-muted/50">
                        {step.media ? (
                            step.media
                        ) : step.videoSrc ? (
                            <TourVideo key={step.videoSrc} src={step.videoSrc} />
                        ) : (
                            /* Placeholder for video */
                            <div className="absolute inset-0 flex items-center justify-center">
                                <div className="text-muted-foreground/70 dark:text-zinc-600 text-xs font-medium">.webm</div>
                            </div>
                        )}
                    </div>

                    {/* Content section */}
                    <div className="px-5 py-4">
                        {/* Title */}
                        <h2 className="text-lg font-semibold text-foreground mb-1.5">
                            {step.title}
                        </h2>

                        {/* Description */}
                        <p className="text-sm text-muted-foreground mb-4">
                            {step.description}
                        </p>

                        {/* CTA button */}
                        <button
                            onClick={handleNext}
                            disabled={isTransitioning}
                            className="w-full py-3 px-4 rounded-lg text-sm font-medium bg-primary text-primary-foreground hover:bg-primary/90 active:bg-primary/80 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                        >
                            {step.buttonText}
                        </button>
                    </div>
                </div>
            </div>

        </div>
    );

    // Portal to document body to ensure proper z-index stacking
    return createPortal(content, document.body);
}
