// Hook for caching workflow node outputs in memory during the current session.
// Outputs are now server-backed (workflow_node_outputs table) and fetched on workflow load.
// This hook serves as an in-memory accumulator for real-time streaming outputs during execution.

import { useCallback, useRef } from 'react';

// Structure for a single node's cached output
export interface CachedNodeOutput {
    output: unknown;
    outputTimestamp: number;
}

// Map of nodeId -> cached output data
export type NodeOutputsCache = Record<string, CachedNodeOutput>;

interface UseWorkflowNodeOutputsProps {
    workflowId: string;
}

interface UseWorkflowNodeOutputsReturn {
    // Save a large output to in-memory cache
    setLargeOutput: (nodeId: string, output: unknown, outputTimestamp: number) => void;

    // Check if an output should be stored locally (based on size)
    isLargeOutput: (output: unknown) => boolean;

    // Save output - automatically determines if it should be stored locally
    saveNodeOutput: (nodeId: string, output: unknown, outputTimestamp: number) => void;

    // Ref for accessing latest cache in callbacks without causing re-renders
    localOutputsRef: React.RefObject<NodeOutputsCache>;
}

// Must match backend OUTPUT_SIZE_THRESHOLD_BYTES
const OUTPUT_SIZE_THRESHOLD_BYTES = 50 * 1024; // 50KB

function getOutputSize(output: unknown): number {
    try {
        return JSON.stringify(output).length;
    } catch {
        return 0;
    }
}

export function useWorkflowNodeOutputs({
    workflowId: _workflowId,
}: UseWorkflowNodeOutputsProps): UseWorkflowNodeOutputsReturn {
    // In-memory cache for real-time streaming accumulation only
    const cacheRef = useRef<NodeOutputsCache>({});

    // Check if an output is large (should be stored locally)
    const isLargeOutput = useCallback((output: unknown): boolean => {
        return getOutputSize(output) >= OUTPUT_SIZE_THRESHOLD_BYTES;
    }, []);

    // Set a large output explicitly. Always replaces — there's no merge
    // logic here because WorkflowNodeOutputEvent is now emitted exactly
    // once per node execution. Streaming chunks land on node.data.progress
    // via WorkflowNodeProgressEvent and never touch the output slot.
    const setLargeOutput = useCallback((nodeId: string, output: unknown, outputTimestamp: number) => {
        cacheRef.current = {
            ...cacheRef.current,
            [nodeId]: { output, outputTimestamp },
        };
    }, []);

    // Save output - automatically checks size and saves to in-memory if large
    const saveNodeOutput = useCallback((nodeId: string, output: unknown, outputTimestamp: number) => {
        if (isLargeOutput(output)) {
            console.log(`[useWorkflowNodeOutputs] Large output for ${nodeId} (${getOutputSize(output)} bytes), caching in memory`);
            setLargeOutput(nodeId, output, outputTimestamp);
        }
        // Small outputs are handled by backend persistence
    }, [isLargeOutput, setLargeOutput]);

    return {
        setLargeOutput,
        isLargeOutput,
        saveNodeOutput,
        localOutputsRef: cacheRef,
    };
}

// Re-export types for backwards compatibility
export type { CachedNodeOutput as NodeOutput };
