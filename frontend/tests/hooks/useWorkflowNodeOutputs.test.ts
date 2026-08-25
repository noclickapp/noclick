// @vitest-environment jsdom
// Tests for useWorkflowNodeOutputs hook
// Verifies in-memory caching of large outputs during execution.
// Outputs are now server-backed; this hook only accumulates during real-time streaming.

import { describe, it, expect } from 'vitest';
import { renderHook, act } from '@testing-library/react';

import { useWorkflowNodeOutputs } from '~/hooks/useWorkflowNodeOutputs';

// Create a large output (>=50KB)
const createLargeOutput = (sizeKB: number = 60) => {
    const padding = 'x'.repeat(sizeKB * 1024);
    return { data: padding, type: 'large_test' };
};

// Create a small output (<50KB)
const createSmallOutput = () => {
    return { data: 'small', type: 'test' };
};

describe('useWorkflowNodeOutputs', () => {
    describe('Basic functionality', () => {
        it('should correctly identify large outputs', () => {
            const { result } = renderHook(() => useWorkflowNodeOutputs({ workflowId: 'test-workflow' }));

            expect(result.current.isLargeOutput(createSmallOutput())).toBe(false);
            expect(result.current.isLargeOutput(createLargeOutput(60))).toBe(true);
        });

        it('should only cache large outputs via saveNodeOutput', () => {
            const { result } = renderHook(() => useWorkflowNodeOutputs({ workflowId: 'test-workflow-save' }));

            // Small output should NOT be cached
            act(() => {
                result.current.saveNodeOutput('node-1', createSmallOutput(), 12345);
            });
            expect(result.current.localOutputsRef.current['node-1']).toBeUndefined();

            // Large output SHOULD be cached
            act(() => {
                result.current.saveNodeOutput('node-2', createLargeOutput(), 12346);
            });
            expect(result.current.localOutputsRef.current['node-2']).toBeDefined();
            expect(result.current.localOutputsRef.current['node-2'].outputTimestamp).toBe(12346);
        });

        it('should save explicitly set large outputs', () => {
            const { result } = renderHook(() => useWorkflowNodeOutputs({ workflowId: 'test-workflow-explicit' }));

            const largeOutput = createLargeOutput();

            act(() => {
                result.current.setLargeOutput('node-1', largeOutput, 12345);
            });

            expect(result.current.localOutputsRef.current['node-1']).toBeDefined();
            expect(result.current.localOutputsRef.current['node-1'].output).toEqual(largeOutput);
            expect(result.current.localOutputsRef.current['node-1'].outputTimestamp).toBe(12345);
        });
    });

    describe('Ref access', () => {
        it('should provide immediate access via ref', () => {
            const { result } = renderHook(() => useWorkflowNodeOutputs({ workflowId: 'ref-test' }));

            const largeOutput = createLargeOutput();

            act(() => {
                result.current.setLargeOutput('node-1', largeOutput, 100);
            });

            expect(result.current.localOutputsRef.current['node-1'].output).toEqual(largeOutput);
        });
    });

    describe('Replace-only semantics', () => {
        // Streaming chunks no longer flow through setLargeOutput — they
        // accumulate on node.data.progress via WorkflowNodeProgressEvent.
        // WorkflowNodeOutputEvent is now emitted exactly once per execution,
        // so the cache always replaces and never merges. Test the new
        // contract: successive setLargeOutput calls overwrite each other.
        it('should replace (not merge) on successive setLargeOutput calls', () => {
            const { result } = renderHook(() => useWorkflowNodeOutputs({ workflowId: 'replace-test' }));

            const firstLarge = createLargeOutput(60);

            act(() => {
                result.current.setLargeOutput('chat-node', firstLarge, 100);
            });
            expect(result.current.localOutputsRef.current['chat-node'].output).toEqual(firstLarge);
            expect(result.current.localOutputsRef.current['chat-node'].outputTimestamp).toBe(100);

            const secondLarge = { data: 'y'.repeat(60 * 1024), type: 'replacement' };

            act(() => {
                result.current.setLargeOutput('chat-node', secondLarge, 101);
            });
            // No merge — the second call wholesale replaces the first.
            expect(result.current.localOutputsRef.current['chat-node'].output).toEqual(secondLarge);
            expect(result.current.localOutputsRef.current['chat-node'].outputTimestamp).toBe(101);
        });
    });
});
