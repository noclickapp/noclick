// Utility functions for converting and merging agentic steps from backend responses
// This file handles the conversion between backend and frontend agentic step formats

import { AgenticStep } from './types';
import { type AgenticStep as BackendAgenticStep } from '~/types/socket-schema.generated';

/**
 * Converts backend agentic steps format to frontend format
 */
export function convertAgenticSteps(backendSteps: BackendAgenticStep[] | null | undefined): AgenticStep[] | undefined {
    if (!backendSteps) return undefined;
    
    return backendSteps.map(step => ({
        id: step.id,
        text: step.text,
        status: (step.status || 'pending') as 'pending' | 'in_progress' | 'completed',
        subSteps: step.sub_steps?.map(subStep => ({
            id: subStep.id,
            text: subStep.text,
            status: (subStep.status || 'pending') as 'pending' | 'in_progress' | 'completed',
        }))
    }));
}

/**
 * Cleans file paths by removing /tmp/apps/<app_id>/ prefixes
 * @param text The text that might contain file paths
 * @returns The text with cleaned file paths
 */
export function cleanAppFilePath(text: string): string {
    // Pattern matches /tmp/apps/<uuid>/ where UUID is in format 8-4-4-4-12 hex characters
    const pattern = /\/tmp\/apps\/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\//gi;
    return text.replace(pattern, '');
}

/**
 * Merges new agentic steps with existing ones, preserving UI state like isExpanded
 */
export function mergeAgenticSteps(
    existingSteps: AgenticStep[], 
    newSteps: AgenticStep[] | undefined
): AgenticStep[] {
    if (!newSteps) return existingSteps;
    
    // Create a map of existing steps by ID for quick lookup
    const stepsMap = new Map(existingSteps.map(step => [step.id, step]));
    
    // Update or add each new step
    newSteps.forEach(newStep => {
        const existingStep = stepsMap.get(newStep.id);
        if (existingStep) {
            // Merge substeps if they exist
            let mergedSubSteps = existingStep.subSteps;
            if (newStep.subSteps && existingStep.subSteps) {
                // Create a map of existing substeps
                const subStepsMap = new Map(existingStep.subSteps.map(sub => [sub.id, sub]));
                
                // Update or add new substeps
                newStep.subSteps.forEach(newSub => {
                    const existingSub = subStepsMap.get(newSub.id);
                    if (existingSub) {
                        // Update existing substep, preserving text if new one is empty
                        subStepsMap.set(newSub.id, {
                            ...existingSub,
                            status: newSub.status,
                            text: newSub.text || existingSub.text
                        });
                    } else {
                        subStepsMap.set(newSub.id, newSub);
                    }
                });
                
                mergedSubSteps = Array.from(subStepsMap.values());
            } else if (newStep.subSteps) {
                mergedSubSteps = newStep.subSteps;
            }
            
            // Update existing step (preserve isExpanded state and merge substeps)
            stepsMap.set(newStep.id, {
                ...existingStep,
                status: newStep.status,
                text: newStep.text || existingStep.text, // Preserve text if new one is empty
                subSteps: mergedSubSteps,
                isExpanded: existingStep.isExpanded
            });
        } else {
            // Add new step
            stepsMap.set(newStep.id, newStep);
        }
    });
    
    // Convert map back to array maintaining original order
    return Array.from(stepsMap.values());
}
