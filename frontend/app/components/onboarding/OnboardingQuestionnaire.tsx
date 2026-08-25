/**
 * Full-screen onboarding questionnaire component.
 * Collects user information for personalization and analytics.
 * Blocks dashboard access until completed. Questions are placeholders - customize before launch.
 */

import { useState, useEffect } from 'react';
import { createBrowserSupabaseClient } from '~/lib/supabase';
import { sendEventAsync, OnboardingSubmitRequest } from '~/lib/socket-sender';
import { POST_ONBOARDING_FLOW_KEY } from '~/lib/deferredOpen';
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '~/components/ui/card';
import { Button } from '~/components/ui/button';
import {
    ChevronRight,
    ChevronLeft,
    Briefcase,
    Megaphone,
    Phone,
    Headphones,
    Scale,
    Compass,
    Code,
    Calculator,
    Video,
    Palette,
    MoreHorizontal,
    Check,
    type LucideIcon,
} from 'lucide-react';
import type { ComponentType } from 'react';

/**
 * Custom SVG illustration for the "Workflows & automations" option.
 * A trigger node flows into an action node, which fans out to two
 * outputs — reads like the NoClick canvas. Uses currentColor so the
 * strokes and fills pick up the card's text color (and animate to
 * white when the card is selected).
 */
function WorkflowsIllustration({ className }: { className?: string }) {
    return (
        <svg
            className={className}
            viewBox="0 0 160 100"
            fill="none"
            xmlns="http://www.w3.org/2000/svg"
        >
            {/* Edges — drawn first so the nodes sit on top of them */}
            <path d="M46 50 H 62" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" opacity="0.7" />
            <path d="M106 50 C 118 50, 118 28, 130 28" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" opacity="0.7" />
            <path d="M106 50 C 118 50, 118 72, 130 72" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" opacity="0.7" />

            {/* Trigger node (left) */}
            <rect x="10" y="36" width="36" height="28" rx="8" stroke="currentColor" strokeWidth="2.5" />
            <circle cx="28" cy="50" r="4.5" fill="currentColor" />

            {/* Action node (center) */}
            <rect x="62" y="33" width="44" height="34" rx="9" stroke="currentColor" strokeWidth="2.5" />
            <rect x="70" y="44" width="28" height="3.5" rx="1.75" fill="currentColor" opacity="0.75" />
            <rect x="70" y="53" width="18" height="3.5" rx="1.75" fill="currentColor" opacity="0.4" />

            {/* Upper output */}
            <rect x="130" y="16" width="26" height="24" rx="7" stroke="currentColor" strokeWidth="2.5" />
            <circle cx="143" cy="28" r="3.5" fill="currentColor" opacity="0.75" />

            {/* Lower output */}
            <rect x="130" y="60" width="26" height="24" rx="7" stroke="currentColor" strokeWidth="2.5" />
            <circle cx="143" cy="72" r="3.5" fill="currentColor" opacity="0.4" />
        </svg>
    );
}

/**
 * Custom SVG illustration for the "Websites & interfaces" option.
 * An app window with a sidebar, hero block, and content cards — reads
 * as a built interface. Uses currentColor + opacity so it picks up the
 * card's text color (and animates to white when selected).
 */
function InterfacesIllustration({ className }: { className?: string }) {
    return (
        <svg
            className={className}
            viewBox="0 0 160 100"
            fill="none"
            xmlns="http://www.w3.org/2000/svg"
        >
            {/* Window frame */}
            <rect x="6" y="10" width="148" height="80" rx="9" stroke="currentColor" strokeWidth="2.5" />

            {/* Title bar */}
            <line x1="6" y1="26" x2="154" y2="26" stroke="currentColor" strokeWidth="2" opacity="0.7" />
            <circle cx="16" cy="18" r="2" fill="currentColor" />
            <circle cx="24" cy="18" r="2" fill="currentColor" />
            <circle cx="32" cy="18" r="2" fill="currentColor" />
            <rect x="44" y="14.5" width="74" height="7" rx="3.5" fill="currentColor" opacity="0.22" />

            {/* Sidebar */}
            <rect x="14" y="34" width="32" height="48" rx="5" fill="currentColor" opacity="0.16" />
            <rect x="20" y="41" width="20" height="4" rx="2" fill="currentColor" opacity="0.5" />
            <rect x="20" y="50" width="20" height="4" rx="2" fill="currentColor" opacity="0.5" />
            <rect x="20" y="59" width="14" height="4" rx="2" fill="currentColor" opacity="0.5" />

            {/* Hero block */}
            <rect x="54" y="34" width="92" height="28" rx="5" fill="currentColor" opacity="0.55" />

            {/* Content cards */}
            <rect x="54" y="67" width="43" height="15" rx="4" fill="currentColor" opacity="0.3" />
            <rect x="103" y="67" width="43" height="15" rx="4" fill="currentColor" opacity="0.3" />
        </svg>
    );
}

/**
 * Animated success checkmark with drawing effect.
 * Shows a circle that draws itself, then a checkmark appears inside.
 */
function SuccessAnimation() {
    const [showCheck, setShowCheck] = useState(false);

    useEffect(() => {
        // Delay checkmark to appear after circle draws
        const timer = setTimeout(() => setShowCheck(true), 250);
        return () => clearTimeout(timer);
    }, []);

    return (
        <div className="flex flex-col items-center justify-center gap-8 animate-in fade-in duration-200">
            {/* Inline keyframes for drawing animations */}
            <style>{`
                @keyframes draw-circle {
                    to { stroke-dashoffset: 0; }
                }
                @keyframes draw-check {
                    to { stroke-dashoffset: 0; }
                }
            `}</style>

            <div className="relative w-28 h-28">
                {/* Animated circle */}
                <svg className="w-28 h-28 -rotate-90" viewBox="0 0 100 100">
                    <circle
                        cx="50"
                        cy="50"
                        r="45"
                        fill="none"
                        stroke="hsl(var(--foreground) / 0.1)"
                        strokeWidth="2"
                    />
                    <circle
                        cx="50"
                        cy="50"
                        r="45"
                        fill="none"
                        stroke="hsl(var(--foreground))"
                        strokeWidth="2"
                        strokeLinecap="round"
                        strokeDasharray="283"
                        strokeDashoffset="283"
                        style={{ animation: 'draw-circle 0.35s ease-out forwards' }}
                    />
                </svg>

                {/* Animated checkmark */}
                <svg
                    className="absolute inset-0 w-28 h-28"
                    viewBox="0 0 100 100"
                >
                    <path
                        d="M28 52 L42 66 L72 36"
                        fill="none"
                        stroke="hsl(var(--foreground))"
                        strokeWidth="3"
                        strokeLinecap="round"
                        strokeLinejoin="round"
                        strokeDasharray="65"
                        strokeDashoffset="65"
                        style={{
                            animation: showCheck ? 'draw-check 0.25s ease-out forwards' : 'none'
                        }}
                    />
                </svg>
            </div>

            <div className="text-center">
                <h2 className="text-3xl font-light tracking-tight text-foreground mb-2">You're all set!</h2>
                <p className="text-lg text-muted-foreground/70 dark:text-zinc-500 font-light">Taking you to your dashboard</p>
            </div>
        </div>
    );
}

interface OnboardingQuestionnaireProps {
    env: { SUPABASE_URL: string; SUPABASE_ANON_KEY: string };
    onComplete?: () => void;
}

interface QuestionOption {
    value: string;
    label: string;
    icon?: LucideIcon | ComponentType<{ className?: string }>;
    image?: string; // Path to image in /onboarding/ folder
    // Custom SVG component rendered like an image (tall card, large visual).
    // Use this when you want a richer illustration than a flat lucide icon.
    illustration?: ComponentType<{ className?: string }>;
}

interface Question {
    id: string;
    title: string;
    subtitle?: string;
    type: 'single' | 'multi';
    options: QuestionOption[];
}

const QUESTIONS: Question[] = [
    {
        id: 'build_type',
        title: 'What are you here to build?',
        subtitle: 'Select one — we\'ll start you on the right canvas',
        type: 'single',
        options: [
            { value: 'interface', label: 'Websites & interfaces', illustration: InterfacesIllustration },
            { value: 'workflow', label: 'Workflows & automations', illustration: WorkflowsIllustration },
        ],
    },
    {
        id: 'usage_type',
        title: 'How are you planning to use NoClick?',
        subtitle: 'Select one',
        type: 'single',
        options: [
            { value: 'personal', label: 'Personal', image: '/onboarding/personal.webp' },
            { value: 'organization', label: 'Organization', image: '/onboarding/work.webp' },
        ],
    },
    {
        id: 'role',
        title: 'What best describes your role?',
        subtitle: 'Select one',
        type: 'single',
        options: [
            { value: 'consultant', label: 'Consultant', icon: Briefcase },
            { value: 'marketing', label: 'Marketing', icon: Megaphone },
            { value: 'sales', label: 'Sales Service', icon: Phone },
            { value: 'support', label: 'Customer Support', icon: Headphones },
            { value: 'people_legal', label: 'People or Legal', icon: Scale },
            { value: 'leadership', label: 'Leadership', icon: Compass },
            { value: 'engineering', label: 'Engineering or Data', icon: Code },
            { value: 'ops_finance', label: 'Ops and Finance', icon: Calculator },
            { value: 'creator', label: 'Creator', icon: Video },
            { value: 'design_product', label: 'Design or Product', icon: Palette },
            { value: 'other', label: 'Other', icon: MoreHorizontal },
        ],
    },
    {
        id: 'company_size',
        title: 'How many people work at your organization?',
        subtitle: 'Select one',
        type: 'single',
        options: [
            { value: '1', label: 'Just Me', image: '/onboarding/1.webp' },
            { value: '2-10', label: '2-10', image: '/onboarding/2_10.webp' },
            { value: '11-50', label: '11-50', image: '/onboarding/11_50.webp' },
            { value: '51-500', label: '51-500', image: '/onboarding/51_500.webp' },
            { value: '501-5000', label: '501-5000', image: '/onboarding/501_5000.webp' },
            { value: '5001+', label: '5001+', image: '/onboarding/5001.webp' },
        ],
    },
];

export function OnboardingQuestionnaire({ env, onComplete }: OnboardingQuestionnaireProps) {
    const [currentStep, setCurrentStep] = useState(0);
    const [responses, setResponses] = useState<Record<string, string | string[]>>({});
    const [isSubmitting, setIsSubmitting] = useState(false);
    const [displayStep, setDisplayStep] = useState(0); // For smooth progress bar
    const [transitionPhase, setTransitionPhase] = useState<'idle' | 'exiting' | 'entering'>('idle');
    const [slideDirection, setSlideDirection] = useState<'forward' | 'backward'>('forward');

    const currentQuestion = QUESTIONS[currentStep];
    const isLastStep = currentStep === QUESTIONS.length - 1;
    const isFirstStep = currentStep === 0;

    const transitionToStep = (nextStep: number) => {
        const direction = nextStep > currentStep ? 'forward' : 'backward';
        setSlideDirection(direction);
        setTransitionPhase('exiting');
        setDisplayStep(nextStep); // Update progress bar immediately for smooth animation

        // Wait for exit animation, then change content
        setTimeout(() => {
            setCurrentStep(nextStep);
            // Set entering position (no transition yet)
            setTransitionPhase('entering');

            // On next frame, animate to final position
            requestAnimationFrame(() => {
                requestAnimationFrame(() => {
                    setTransitionPhase('idle');
                });
            });
        }, 150);
    };

    // Calculate transform classes based on phase and direction
    const getTransitionClasses = () => {
        if (transitionPhase === 'exiting') {
            // Exit: slide out in direction of travel
            return slideDirection === 'forward'
                ? 'opacity-0 -translate-x-16'  // Slide left when going forward
                : 'opacity-0 translate-x-16';   // Slide right when going backward
        }
        if (transitionPhase === 'entering') {
            // Enter: start position (no transition applied yet)
            return slideDirection === 'forward'
                ? 'opacity-0 translate-x-16 !duration-0'   // Start from right
                : 'opacity-0 -translate-x-16 !duration-0'; // Start from left
        }
        // Idle: final position
        return 'opacity-100 translate-x-0';
    };

    const handleSingleSelect = (value: string) => {
        // Compute next responses locally so the auto-submit path below sees the
        // freshly-selected value. The setTimeout callback captures handleSubmit
        // from this render, whose `responses` closure is pre-update — so without
        // this override the latest answer would be missing from the submit payload.
        const nextResponses = { ...responses, [currentQuestion.id]: value };
        setResponses(nextResponses);

        // Auto-advance after a brief delay to show selection
        setTimeout(() => {
            if (currentStep < QUESTIONS.length - 1) {
                transitionToStep(currentStep + 1);
            } else {
                handleSubmit(nextResponses);
            }
        }, 100);
    };

    const handleMultiSelect = (value: string) => {
        setResponses(prev => {
            const current = (prev[currentQuestion.id] as string[]) || [];
            if (current.includes(value)) {
                return { ...prev, [currentQuestion.id]: current.filter(v => v !== value) };
            } else {
                return { ...prev, [currentQuestion.id]: [...current, value] };
            }
        });
    };

    const canProceed = () => {
        const response = responses[currentQuestion.id];
        if (!response) return false;
        if (Array.isArray(response) && response.length === 0) return false;
        return true;
    };

    const handleNext = async () => {
        if (isLastStep) {
            await handleSubmit();
        } else {
            transitionToStep(currentStep + 1);
        }
    };

    const handleBack = () => {
        if (!isFirstStep) {
            transitionToStep(currentStep - 1);
        }
    };

    const handleSubmit = async (overrideResponses?: Record<string, string | string[]>) => {
        const finalResponses = overrideResponses ?? responses;
        setIsSubmitting(true);
        setTransitionPhase('exiting');
        try {
            const result = await sendEventAsync(
                OnboardingSubmitRequest.create({
                    responses: finalResponses,
                    version: 1,
                })
            );

            if ((result as any)?.refresh_jwt) {
                // Start JWT refresh in background immediately
                const supabase = createBrowserSupabaseClient(env);
                supabase.auth.refreshSession().then(({ error }) => {
                    if (error) {
                        console.error('[Onboarding] Background JWT refresh failed:', error);
                    }
                });

                // Set flag to trigger post-onboarding flow (auto-create a blank workflow)
                sessionStorage.setItem(POST_ONBOARDING_FLOW_KEY, 'true');

                // Stash the FlowCanvas tab to open based on build_type answer.
                // FlowCanvas consumes this once on mount of the auto-created workflow.
                if (finalResponses.build_type === 'interface') {
                    sessionStorage.setItem('noclick_post_onboarding_tab', 'interface');
                } else if (finalResponses.build_type === 'workflow') {
                    sessionStorage.setItem('noclick_post_onboarding_tab', 'canvas');
                }

                // Let the success animation complete before transitioning
                setTimeout(() => {
                    onComplete?.();
                }, 600);
            }
        } catch (error) {
            console.error('Failed to submit onboarding:', error);
            setIsSubmitting(false);
            setTransitionPhase('idle');
        }
    };

    const isSelected = (value: string) => {
        const response = responses[currentQuestion.id];
        if (currentQuestion.type === 'single') {
            return response === value;
        } else {
            return Array.isArray(response) && response.includes(value);
        }
    };

    // Determine grid columns and card sizing based on number of options
    const optionCount = currentQuestion.options.length;
    const gridCols = optionCount <= 2
        ? 'grid-cols-2 max-w-lg mx-auto'
        : optionCount <= 6
            ? 'grid-cols-2 sm:grid-cols-3'
            : 'grid-cols-2 sm:grid-cols-3 md:grid-cols-4';

    // Smaller cards for questions with many options (fixed height for consistent rows)
    const cardPadding = optionCount > 6
        ? 'py-3 px-3 h-[104px] sm:py-4 sm:px-4 sm:h-[130px]'
        : 'p-5 sm:p-8';
    const iconSize = optionCount > 6 ? 'h-6 w-6 sm:h-7 sm:w-7' : 'h-8 w-8 sm:h-10 sm:w-10';
    const textSize = optionCount > 6 ? 'text-sm sm:text-lg' : 'text-base sm:text-xl';

    return (
        <div
            className="fixed inset-0 z-[9999] bg-background flex flex-col p-4 sm:p-6"
            style={{
                paddingTop: 'max(1rem, env(safe-area-inset-top))',
                paddingBottom: 'max(1rem, env(safe-area-inset-bottom))',
            }}
        >
            {/* Progress indicator at top - hidden during success animation */}
            <div className={`flex gap-1.5 sm:gap-2 max-w-md mx-auto w-full pt-2 sm:pt-4 transition-opacity duration-300 ${
                isSubmitting ? 'opacity-0' : 'opacity-100'
            }`}>
                {QUESTIONS.map((_, idx) => (
                    <div
                        key={idx}
                        className={`h-1 flex-1 rounded-full transition-all duration-300 ease-out ${
                            idx <= displayStep ? 'bg-foreground' : 'bg-secondary'
                        }`}
                    />
                ))}
            </div>

            {/* Main content — scrolls and top-anchors when it overflows the
                viewport (e.g. the 11-option role grid on a short phone),
                otherwise stays vertically centered. */}
            <div className="flex-1 overflow-y-auto">
            <div className="min-h-full flex items-center justify-center py-4 sm:py-6">
            {isSubmitting ? (
                <SuccessAnimation />
            ) : (
            <Card className="w-full max-w-4xl bg-transparent border-0 shadow-none">
                <CardHeader className="text-center pb-2 sm:pb-4">
                    <div className={`transition-all duration-200 ease-out ${getTransitionClasses()}`}>
                        <CardTitle className="text-2xl sm:text-4xl font-light tracking-tight text-foreground">
                            {currentQuestion.title}
                        </CardTitle>
                        {currentQuestion.subtitle && (
                            <CardDescription className="text-sm sm:text-lg text-muted-foreground/70 dark:text-zinc-500 mt-2 sm:mt-3 font-light">
                                {currentQuestion.subtitle}
                            </CardDescription>
                        )}
                    </div>
                </CardHeader>

                <CardContent className={`space-y-6 sm:space-y-8 transition-all duration-200 ease-out ${getTransitionClasses()}`}>
                    <div className={`grid ${gridCols} gap-3 sm:gap-4`}>
                        {currentQuestion.options.map(option => {
                            const Icon = option.icon;
                            const Illustration = option.illustration;
                            const selected = isSelected(option.value);
                            const hasImage = !!option.image;
                            const hasIllustration = !!Illustration;
                            const useTallCard = hasImage || hasIllustration;

                            return (
                                <button
                                    key={option.value}
                                    type="button"
                                    onClick={() => currentQuestion.type === 'single'
                                        ? handleSingleSelect(option.value)
                                        : handleMultiSelect(option.value)
                                    }
                                    className={`relative flex flex-col items-center ${useTallCard ? 'justify-between h-44 pt-4 px-4 pb-5 sm:h-64 sm:pt-6 sm:px-6 sm:pb-8' : `justify-center ${cardPadding}`} gap-2 sm:gap-3 rounded-2xl border-2 transition-all duration-200 ${
                                        selected
                                            ? 'border-foreground'
                                            : 'border-border hover:border-foreground/40'
                                    }`}
                                >
                                    {/* Selection indicator for multi-select */}
                                    {selected && currentQuestion.type === 'multi' && (
                                        <div className="absolute top-2 right-2 w-5 h-5 rounded-full bg-foreground flex items-center justify-center">
                                            <Check className="h-3 w-3 text-background" />
                                        </div>
                                    )}

                                    {hasIllustration && Illustration ? (
                                        <div className="flex-1 flex items-center justify-center w-full">
                                            <Illustration
                                                className={`w-full max-w-[200px] h-24 sm:max-w-[280px] sm:h-32 transition-colors ${
                                                    selected ? 'text-foreground' : 'text-muted-foreground/70 dark:text-zinc-500'
                                                }`}
                                            />
                                        </div>
                                    ) : hasImage ? (
                                        <div className="flex-1 flex items-center">
                                            <img
                                                src={option.image}
                                                alt={option.label}
                                                className={`w-28 sm:w-40 max-w-none max-h-20 sm:max-h-28 object-contain transition-opacity ${
                                                    selected ? 'opacity-100' : 'opacity-50'
                                                }`}
                                            />
                                        </div>
                                    ) : Icon ? (
                                        <Icon className={`${iconSize} transition-colors ${
                                            selected ? 'text-foreground' : 'text-muted-foreground/70 dark:text-zinc-500'
                                        }`} />
                                    ) : null}

                                    <span className={`${textSize} font-medium transition-colors text-center ${
                                        selected ? 'text-foreground' : 'text-muted-foreground/70 dark:text-zinc-500'
                                    }`}>
                                        {option.label}
                                    </span>
                                </button>
                            );
                        })}
                    </div>

                    {/* Navigation buttons */}
                    <div className="flex justify-between pt-4 sm:pt-6">
                        <Button
                            variant="ghost"
                            onClick={handleBack}
                            disabled={isFirstStep}
                            className="text-muted-foreground hover:text-foreground hover:bg-transparent text-base sm:text-lg px-4 py-4 sm:px-6 sm:py-6"
                        >
                            <ChevronLeft className="h-5 w-5 mr-1 sm:mr-2" />
                            Back
                        </Button>

                        {canProceed() && (
                            <Button
                                onClick={handleNext}
                                disabled={isSubmitting}
                                className="bg-primary hover:bg-primary/90 text-primary-foreground disabled:opacity-50 text-base sm:text-lg px-4 py-4 sm:px-6 sm:py-6"
                            >
                                {isSubmitting ? 'Saving...' : isLastStep ? 'Get Started' : 'Continue'}
                                {!isLastStep && <ChevronRight className="h-5 w-5 ml-1 sm:ml-2" />}
                            </Button>
                        )}
                    </div>
                </CardContent>
            </Card>
            )}
            </div>
            </div>
        </div>
    );
}
