// Hook for fetching node output history from the backend.
// Shared between OutputPanel (full carousel) and InputNodeDisplay.
// Supports restoring a previously selected carousel position via initialHistoryIndex.

import { useState, useEffect, useRef, type Dispatch, type SetStateAction } from 'react';
import { sendEventAsync } from '~/lib/socket-sender';

export interface OutputHistoryEntry {
    execution_id: string;
    created_at: string;
    output: unknown;
}

interface UseNodeOutputHistoryOptions {
    workflowId: string | undefined;
    nodeId: string | undefined;
    /** Max entries to fetch (default 20). */
    limit?: number;
    /** Change this value to trigger a refetch (e.g. pass node.data.output). */
    refetchTrigger?: unknown;
    /** Restore carousel to this index on mount (from persisted selection). */
    initialHistoryIndex?: number;
    /** Called when index or entries change — used to persist selection for execution. */
    onIndexChange?: (nodeId: string, index: number, output: unknown | undefined) => void;
}

interface UseNodeOutputHistoryReturn {
    historyEntries: OutputHistoryEntry[];
    historyIndex: number;
    setHistoryIndex: Dispatch<SetStateAction<number>>;
    /** Shortcut for historyEntries[0]?.output — the latest stored output. */
    latestHistoryOutput: unknown | undefined;
}

export function useNodeOutputHistory({
    workflowId,
    nodeId,
    limit = 20,
    refetchTrigger,
    initialHistoryIndex,
    onIndexChange,
}: UseNodeOutputHistoryOptions): UseNodeOutputHistoryReturn {
    const [historyEntries, setHistoryEntries] = useState<OutputHistoryEntry[]>([]);
    const [historyIndex, setHistoryIndex] = useState(initialHistoryIndex ?? 0);
    // Track the nodeId we last fetched for so we only apply initialHistoryIndex
    // on the first fetch for this node, not on refetch triggers.
    const lastFetchedNodeIdRef = useRef<string | undefined>(undefined);

    useEffect(() => {
        if (!nodeId || !workflowId) {
            setHistoryEntries([]);
            setHistoryIndex(0);
            return;
        }

        const isNewNode = lastFetchedNodeIdRef.current !== nodeId;
        lastFetchedNodeIdRef.current = nodeId;

        // On node change, restore to initial index if provided; otherwise reset to 0.
        // On refetch (same node, new execution), always reset to 0.
        if (isNewNode) {
            setHistoryIndex(initialHistoryIndex ?? 0);
        } else {
            setHistoryIndex(0);
        }

        (sendEventAsync as any)({
            event_name: 'workflow:get_node_output_history',
            workflow_id: workflowId,
            node_id: nodeId,
            limit,
        })
            .then((resp: any) => {
                const entries: OutputHistoryEntry[] = resp?.history?.length ? resp.history : [];
                setHistoryEntries(entries);
                // Clamp restored index to available entries
                if (isNewNode && initialHistoryIndex && initialHistoryIndex > 0) {
                    setHistoryIndex(prev => Math.min(prev, Math.max(entries.length - 1, 0)));
                }
            })
            .catch(() => {
                setHistoryEntries([]);
            });
    }, [nodeId, workflowId, limit, refetchTrigger]); // eslint-disable-line react-hooks/exhaustive-deps
    // initialHistoryIndex intentionally omitted — only used on mount/node-change, not as a refetch trigger

    // Sync selection to parent whenever index or entries change.
    // Fires on: user carousel click, hook reset after new execution, fetch completion.
    // Including historyEntries ensures the ref gets the real output after fetch
    // (not undefined from the brief window between mount and fetch completion).
    const onIndexChangeRef = useRef(onIndexChange);
    onIndexChangeRef.current = onIndexChange;
    useEffect(() => {
        if (nodeId) {
            onIndexChangeRef.current?.(nodeId, historyIndex, historyEntries[historyIndex]?.output);
        }
    }, [nodeId, historyIndex, historyEntries]);

    return {
        historyEntries,
        historyIndex,
        setHistoryIndex,
        latestHistoryOutput: historyEntries[0]?.output,
    };
}

/**
 * Resolve which output to display given mocked, live, and history data.
 * Shared resolution order: mocked → history[index] → live → history[0] → live.
 */
export function resolveDisplayOutput({
    mockedOutput,
    liveOutput,
    historyEntries,
    historyIndex,
}: {
    mockedOutput: unknown | undefined;
    liveOutput: unknown | undefined;
    historyEntries: OutputHistoryEntry[];
    historyIndex: number;
}): { displayOutput: unknown; isMocked: boolean; isViewingHistory: boolean; hasDisplayOutput: boolean } {
    const isMocked = mockedOutput !== undefined;
    const hasLiveOutput = liveOutput !== undefined && liveOutput !== null;
    const hasHistoryData = !isMocked && historyEntries.length > 0;
    const isViewingHistory = !isMocked && historyIndex > 0 && !!historyEntries[historyIndex];

    const displayOutput = isMocked
        ? mockedOutput
        : isViewingHistory
            ? historyEntries[historyIndex].output
            : hasLiveOutput
                ? liveOutput
                : hasHistoryData
                    ? historyEntries[0].output
                    : liveOutput;

    return {
        displayOutput,
        isMocked,
        isViewingHistory,
        hasDisplayOutput: displayOutput !== undefined && displayOutput !== null,
    };
}
