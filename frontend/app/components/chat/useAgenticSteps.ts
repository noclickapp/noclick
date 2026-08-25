/**
 * useAgenticSteps Hook
 *
 * Manages state and business logic for agentic step functionality - step expansion/collapse,
 * auto-collapse timing, and height calculations. Auto-collapse is needed to hide reasoning
 * once it is complete. Height calculations enable smooth CSS transitions.
 *
 * Special handling for "Thinking" steps: always auto-expands when active/pending and allows
 * unlimited height for full content display without scrolling.
 */

import { useState, useCallback, useEffect } from 'react';
import { AgenticStep, Message } from './types';

interface UseAgenticStepsReturn {
    expandedSteps: Record<string, boolean>;
    collapsedReasoning: Record<number, boolean>;
    handleToggleExpand: (stepId: string, messageIndex: number) => void;
    handleToggleReasoning: (messageIndex: number) => void;
    updateStepsWithExpansion: (steps: AgenticStep[], messageIndex: number) => AgenticStep[];
    calculateMaxHeight: (steps: AgenticStep[], messageIndex: number) => string;
}

export const useAgenticSteps = (messages: Message[]): UseAgenticStepsReturn => {
    // Keep track of expanded agentic steps per message
    const [expandedSteps, setExpandedSteps] = useState<Record<string, boolean>>({});
    // Keep track of which reasoning sections are collapsed
    const [collapsedReasoning, setCollapsedReasoning] = useState<Record<number, boolean>>({});
    // Track the last active step to detect changes
    const [lastActiveStep, setLastActiveStep] = useState<{ messageIndex: number; stepId: string } | null>(null);
    
    const handleToggleExpand = useCallback((stepId: string, messageIndex: number) => {
        // Create unique key combining message index and step ID
        const uniqueKey = `${messageIndex}-${stepId}`;
        setExpandedSteps(prev => ({
            ...prev,
            [uniqueKey]: !prev[uniqueKey]
        }));
    }, []);
    
    const updateStepsWithExpansion = useCallback((steps: AgenticStep[], messageIndex: number): AgenticStep[] => {
        return steps.map(step => {
            const uniqueKey = `${messageIndex}-${step.id}`;
            return {
                ...step,
                isExpanded: expandedSteps[uniqueKey] || false,
                subSteps: step.subSteps ? updateStepsWithExpansion(step.subSteps, messageIndex) : undefined
            };
        });
    }, [expandedSteps]);
    
    const handleToggleReasoning = useCallback((messageIndex: number) => {
        setCollapsedReasoning(prev => ({
            ...prev,
            [messageIndex]: !prev[messageIndex]
        }));
    }, []);
    
    // Calculate max height based on expanded content
    const calculateMaxHeight = useCallback((steps: AgenticStep[], messageIndex: number): string => {
        // Check if any of the steps is a "Thinking" step - if so, allow unlimited height
        const hasThinkingStep = steps.some(step => step.text === 'Thinking');
        if (hasThinkingStep) {
            return 'none'; // No max height for thinking steps
        }

        let totalItems = steps.length;
        steps.forEach(step => {
            const uniqueKey = `${messageIndex}-${step.id}`;
            if (step.subSteps && expandedSteps[uniqueKey]) {
                totalItems += step.subSteps.length;
            }
        });
        // Base height + extra for expanded items (roughly 24px per item)
        const baseHeight = 200;
        const itemHeight = 24;
        const calculatedHeight = baseHeight + (totalItems * itemHeight);
        return `${Math.min(calculatedHeight, 800)}px`; // Cap at 800px
    }, [expandedSteps]);
    
    // Auto-expand active steps and collapse previous ones
    useEffect(() => {
        messages.forEach((message, messageIndex) => {
            if (!message.isUser && message.agenticSteps && message.agenticSteps.length > 0) {
                // Find the currently active step (in_progress) or the last step if thinking
                let activeStepFound: { step: AgenticStep; parentId?: string } | null = null;

                const findActiveStep = (steps: AgenticStep[], parentId?: string): void => {
                    for (const step of steps) {
                        if (step.status === 'in_progress') {
                            activeStepFound = { step, parentId };
                            return;
                        }
                        if (step.subSteps) {
                            findActiveStep(step.subSteps, step.id);
                        }
                    }
                };

                findActiveStep(message.agenticSteps);

                // If no in_progress step found but message is not complete, use the last step
                if (!activeStepFound && !message.isComplete && message.agenticSteps.length > 0) {
                    const lastStep = message.agenticSteps[message.agenticSteps.length - 1];
                    activeStepFound = { step: lastStep };
                }

                // Special handling: Always expand "Thinking" steps when they're pending (actively streaming)
                if (!activeStepFound) {
                    const thinkingStep = message.agenticSteps.find(s => s.text === 'Thinking' && s.status === 'pending');
                    if (thinkingStep) {
                        activeStepFound = { step: thinkingStep };
                    }
                }

                if (activeStepFound) {
                    const activeStep = activeStepFound;
                    const currentActiveKey = `${messageIndex}-${activeStep.step.id}`;
                    const lastActiveKey = lastActiveStep ? `${lastActiveStep.messageIndex}-${lastActiveStep.stepId}` : null;

                    // If the active step has changed
                    if (!lastActiveStep || currentActiveKey !== lastActiveKey) {
                        setExpandedSteps(prev => {
                            const newExpanded = { ...prev };

                            // Collapse all steps from the previous message if we're in a different message
                            if (lastActiveStep && lastActiveStep.messageIndex !== messageIndex) {
                                // Find all keys that belong to the previous message and collapse them
                                Object.keys(newExpanded).forEach(key => {
                                    if (key.startsWith(`${lastActiveStep.messageIndex}-`)) {
                                        newExpanded[key] = false;
                                    }
                                });
                            }
                            // Collapse the previous active step (if it exists and is different)
                            else if (lastActiveKey && lastActiveKey !== currentActiveKey) {
                                newExpanded[lastActiveKey] = false;
                            }

                            // Expand the current active step if it has substeps or is a thinking step
                            if (activeStep.step.subSteps && activeStep.step.subSteps.length > 0) {
                                newExpanded[currentActiveKey] = true;
                            }
                            // Always expand "Thinking" steps when they're active
                            if (activeStep.step.text === 'Thinking') {
                                newExpanded[currentActiveKey] = true;
                            }

                            // Also expand parent step if this is a substep
                            if (activeStep.parentId) {
                                const parentKey = `${messageIndex}-${activeStep.parentId}`;
                                newExpanded[parentKey] = true;
                            }

                            return newExpanded;
                        });

                        setLastActiveStep({ messageIndex, stepId: activeStep.step.id });
                    }
                }
            }
        });
    }, [messages, lastActiveStep]);

    // Auto-collapse reasoning when message is complete and has text
    useEffect(() => {
        messages.forEach((message, index) => {
            if (!message.isUser &&
                message.agenticSteps &&
                message.agenticSteps.length > 0 &&
                message.text &&
                message.isComplete &&
                message.agenticSteps.every(step => step.status === 'completed') &&
                collapsedReasoning[index] === undefined) {

                // Add a small delay for the collapse animation
                setTimeout(() => {
                    setCollapsedReasoning(prev => ({
                        ...prev,
                        [index]: true
                    }));
                }, 1000); // Brief moment to see completed steps before collapsing
            }
        });
    }, [messages, collapsedReasoning]);
    
    return {
        expandedSteps,
        collapsedReasoning,
        handleToggleExpand,
        handleToggleReasoning,
        updateStepsWithExpansion,
        calculateMaxHeight,
    };
};
