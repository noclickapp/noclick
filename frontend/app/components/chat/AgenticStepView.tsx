/**
 * AgenticStepView Component
 *
 * Renders agentic steps in the chat interface with special handling for "Thinking" steps.
 * Thinking steps display their content as prose text in a highlighted box (no scrolling),
 * while other steps show as nested hierarchies. Auto-expands when active, auto-collapses when done.
 */

import { ChevronDown, ChevronRight, CheckCircle, Clock, Circle } from 'lucide-react';
import { cn } from '~/lib/utils';
import { AgenticStep } from './types';
import { cleanAppFilePath } from './agenticStepUtils';

interface AgenticStepViewProps {
    step: AgenticStep;
    onToggleExpand: (stepId: string, messageIndex: number) => void;
    messageIndex: number;
    level?: number;
    stepIndex?: number;
    isFirstAppearance?: boolean;
    keepAnimating?: boolean;
}

const getStatusIcon = (status: 'pending' | 'in_progress' | 'completed') => {
    switch (status) {
        case 'completed':
            return <CheckCircle className="w-3 h-3 text-foreground" />;
        case 'in_progress':
            return <Clock className="w-3 h-3 text-blue-600 dark:text-blue-400 animate-pulse" />;
        case 'pending':
            return <Circle className="w-3 h-3 text-muted-foreground" />;
    }
};

export const AgenticStepView = ({ step, onToggleExpand, messageIndex, level = 0, stepIndex = 0, isFirstAppearance = false, keepAnimating = false }: AgenticStepViewProps) => {
    const hasSubSteps = step.subSteps && step.subSteps.length > 0;

    const handleStepClick = () => {
        if (hasSubSteps) {
            onToggleExpand(step.id, messageIndex);
        }
    };

    // Only animate on first appearance (during thinking), not when expanding completed reasoning
    const animationClass = isFirstAppearance
        ? (stepIndex === 0 && level === 0
            ? "animate-in slide-in-from-left-2 duration-300 ease-out"
            : "animate-in slide-in-from-top-1 duration-200 ease-out")
        : "";

    return (
        <div
            className={cn("text-muted-foreground", animationClass)}
            style={{ animationFillMode: 'both' }}
        >
            <div className="flex items-center gap-2 py-1 text-xs">
                {hasSubSteps ? (
                    <button
                        onClick={handleStepClick}
                        className="flex items-center justify-center w-4 h-4 hover:text-foreground/80 transition-colors flex-shrink-0"
                    >
                        {step.isExpanded ? (
                            <ChevronDown className="w-3 h-3" />
                        ) : (
                            <ChevronRight className="w-3 h-3" />
                        )}
                    </button>
                ) : (
                    <div className="w-4 h-4 flex items-center justify-center flex-shrink-0">
                        {getStatusIcon(step.status)}
                    </div>
                )}
                <span
                    className={cn(
                        "flex-1 break-all",
                        (step.status === 'in_progress' || keepAnimating) && "animate-pulse-text",
                        hasSubSteps && "cursor-pointer hover:text-foreground/80 transition-colors"
                    )}
                    onClick={handleStepClick}
                    onKeyDown={(e) => {
                        if ((e.key === 'Enter' || e.key === ' ') && hasSubSteps) {
                            e.preventDefault();
                            handleStepClick();
                        }
                    }}
                    role={hasSubSteps ? "button" : undefined}
                    tabIndex={hasSubSteps ? 0 : undefined}
                >{cleanAppFilePath(step.text)}</span>
                {hasSubSteps && (
                    <span
                        className="text-muted-foreground/80 dark:text-gray-500 text-xs cursor-pointer hover:text-muted-foreground transition-colors"
                        onClick={handleStepClick}
                        onKeyDown={(e) => {
                            if (e.key === 'Enter' || e.key === ' ') {
                                e.preventDefault();
                                handleStepClick();
                            }
                        }}
                        role="button"
                        tabIndex={0}
                    >
                        ({step.subSteps?.filter(s => s.status === 'completed').length || 0}/{step.subSteps?.length || 0})
                    </span>
                )}
            </div>
            {hasSubSteps && (
                <div
                    className={cn(
                        "relative transition-all duration-300 ease-out",
                        step.isExpanded ? "opacity-100" : "max-h-0 opacity-0 overflow-hidden"
                    )}
                    style={{
                        maxHeight: step.isExpanded ? 'none' : '0px'
                    }}
                >
                    {step.text === 'Thinking' ? (
                        // For thinking steps, show content as plain text without icons
                        <div className="ml-1 pr-2 pt-1 text-xs text-muted-foreground whitespace-pre-wrap break-words">
                            {step.subSteps?.map(subStep => subStep.text).join('\n')}
                        </div>
                    ) : (
                        // Regular nested steps with icons and structure
                        <>
                            {/* Vertical line for nesting - aligned with non-indented items */}
                            <div className="absolute left-2 top-0 bottom-0 w-px bg-border dark:bg-gray-600/40"></div>
                            <div className="ml-5 pr-2">
                                {step.subSteps?.map((subStep, subIndex) => (
                                    <AgenticStepView
                                        key={subStep.id}
                                        step={subStep}
                                        onToggleExpand={onToggleExpand}
                                        messageIndex={messageIndex}
                                        level={level + 1}
                                        stepIndex={subIndex}
                                        isFirstAppearance={isFirstAppearance}
                                        keepAnimating={keepAnimating}
                                    />
                                ))}
                            </div>
                        </>
                    )}
                </div>
            )}
        </div>
    );
};
