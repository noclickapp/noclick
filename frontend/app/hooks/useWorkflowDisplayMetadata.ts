// Hook for managing workflow display metadata with local caching and backend sync.
// Handles viewport, selected node, FlowHelperView state, and active tab persistence.

import { useCallback, useRef, useEffect } from 'react';
import { Viewport } from '@xyflow/react';
import { useCachedValtioState } from './useCachedValtioState';
import { useDebounce } from './useDebounce';
import { sendEventWithCallback } from '~/lib/socket-sender';
import { WorkflowUpdateRequest } from '~/types/socket-events.generated';
import { lowResScale } from '~/lib/constants';

// Display metadata structure for persisting UI state
export interface WorkflowDisplayMetadata {
    viewport: Viewport;
    selectedNodeId: string | null;
    flowHelperView: {
        height: number;
        isFullScreen: boolean;
        isExpanded: boolean;
        activeTab: 'home' | 'config' | 'credentials' | null;
        searchQuery: string;
    };
    activeTab: 'canvas' | 'logs' | 'interface' | 'setup' | 'resources';
}

// Default FlowHelper height tracks 40% of viewport, scaled by the active
// low-res font tier so the panel stays proportional to its (rem-based) contents.
const getDefaultFlowHelperHeight = () => {
    if (typeof window === 'undefined') return 400; // SSR fallback
    return Math.round(window.innerHeight * 0.4 * lowResScale());
};

export const DEFAULT_DISPLAY_METADATA: WorkflowDisplayMetadata = {
    viewport: { x: 0, y: 0, zoom: 1 },
    selectedNodeId: null,
    flowHelperView: {
        height: 350, // Will be overridden by getDefaultFlowHelperHeight() at runtime
        isFullScreen: false,
        isExpanded: false, // Start collapsed - cache will restore returning users' preference
        activeTab: 'home',
        searchQuery: '',
    },
    activeTab: 'canvas',
};

// Get default metadata with dynamically calculated height.
export const getDefaultDisplayMetadata = (): WorkflowDisplayMetadata => {
    return {
        ...DEFAULT_DISPLAY_METADATA,
        flowHelperView: {
            ...DEFAULT_DISPLAY_METADATA.flowHelperView,
            height: getDefaultFlowHelperHeight(),
        },
    };
};

interface UseWorkflowDisplayMetadataProps {
    workflowId: string;
    hasLoadedWorkflow: boolean;
}

interface UseWorkflowDisplayMetadataReturn {
    // Raw state and ref for advanced use cases
    displayMetadata: WorkflowDisplayMetadata;
    displayMetadataRef: React.RefObject<WorkflowDisplayMetadata>;
    setDisplayMetadata: (value: WorkflowDisplayMetadata | ((prev: WorkflowDisplayMetadata) => WorkflowDisplayMetadata)) => void;

    // Derived values
    activeTab: 'canvas' | 'logs' | 'interface' | 'setup' | 'resources';
    viewport: Viewport;
    flowHelperHeight: number;
    isFlowHelperFullScreen: boolean;
    isConfigViewExpanded: boolean;
    flowHelperActiveTab: 'home' | 'config' | 'credentials' | null;
    flowHelperSearchQuery: string;

    // Setters
    setActiveTab: (tab: 'canvas' | 'logs' | 'interface' | 'setup' | 'resources') => void;
    setViewport: (viewport: Viewport) => void;
    setFlowHelperHeight: (height: number) => void;
    setIsFlowHelperFullScreen: (isFullScreen: boolean) => void;
    setIsConfigViewExpanded: (isExpanded: boolean) => void;
    setFlowHelperActiveTab: (tab: 'home' | 'config' | 'credentials' | null) => void;
    setFlowHelperSearchQuery: (query: string) => void;
    setSelectedNodeId: (nodeId: string | null) => void;

    // Restoration helpers
    hasLocalCache: () => boolean;
    restoreFromBackend: (backendDisplayMeta: Record<string, unknown> | null | undefined) => void;
}

export function useWorkflowDisplayMetadata({
    workflowId,
    hasLoadedWorkflow,
}: UseWorkflowDisplayMetadataProps): UseWorkflowDisplayMetadataReturn {
    // Cached display metadata - persisted to IndexedDB only (no Redis sync)
    const displayMetadataPath = workflowId ? `/workflow/${workflowId}` : '/workflow/default';
    const defaultMetadata = getDefaultDisplayMetadata();

    const [displayMetadata, setDisplayMetadata] = useCachedValtioState<WorkflowDisplayMetadata>(
        displayMetadataPath,
        'displayMetadata',
        defaultMetadata,
        true // skipRedisSync - only cache locally in IndexedDB
    );

    // Ref to access latest cached display metadata in callbacks without re-running effects
    const displayMetadataRef = useRef(displayMetadata);
    displayMetadataRef.current = displayMetadata;

    // Debounce for backend save (local cache updates immediately)
    const debouncedDisplayMetadata = useDebounce(displayMetadata, 2000);

    // Individual setters
    const setActiveTab = useCallback((tab: 'canvas' | 'logs' | 'interface' | 'setup' | 'resources') => {
        setDisplayMetadata(prev => ({ ...prev, activeTab: tab }));
    }, [setDisplayMetadata]);

    const setViewport = useCallback((newViewport: Viewport) => {
        setDisplayMetadata(prev => ({ ...prev, viewport: newViewport }));
    }, [setDisplayMetadata]);

    const setFlowHelperHeight = useCallback((height: number) => {
        setDisplayMetadata(prev => ({
            ...prev,
            flowHelperView: { ...prev.flowHelperView, height }
        }));
    }, [setDisplayMetadata]);

    const setIsFlowHelperFullScreen = useCallback((isFullScreen: boolean) => {
        setDisplayMetadata(prev => ({
            ...prev,
            flowHelperView: { ...prev.flowHelperView, isFullScreen }
        }));
    }, [setDisplayMetadata]);

    const setIsConfigViewExpanded = useCallback((isExpanded: boolean) => {
        setDisplayMetadata(prev => ({
            ...prev,
            flowHelperView: { ...prev.flowHelperView, isExpanded }
        }));
    }, [setDisplayMetadata]);

    const setFlowHelperActiveTab = useCallback((tab: 'home' | 'config' | 'credentials' | null) => {
        setDisplayMetadata(prev => ({
            ...prev,
            flowHelperView: { ...prev.flowHelperView, activeTab: tab }
        }));
    }, [setDisplayMetadata]);

    const setFlowHelperSearchQuery = useCallback((query: string) => {
        setDisplayMetadata(prev => ({
            ...prev,
            flowHelperView: { ...prev.flowHelperView, searchQuery: query }
        }));
    }, [setDisplayMetadata]);

    const setSelectedNodeId = useCallback((nodeId: string | null) => {
        setDisplayMetadata(prev => ({ ...prev, selectedNodeId: nodeId }));
    }, [setDisplayMetadata]);

    // Check if local cache has non-default values
    const hasLocalCache = useCallback(() => {
        const localCache = displayMetadataRef.current;
        return (
            localCache.viewport.x !== DEFAULT_DISPLAY_METADATA.viewport.x ||
            localCache.viewport.y !== DEFAULT_DISPLAY_METADATA.viewport.y ||
            localCache.viewport.zoom !== DEFAULT_DISPLAY_METADATA.viewport.zoom ||
            localCache.selectedNodeId !== DEFAULT_DISPLAY_METADATA.selectedNodeId ||
            localCache.flowHelperView.height !== DEFAULT_DISPLAY_METADATA.flowHelperView.height ||
            localCache.flowHelperView.isExpanded !== DEFAULT_DISPLAY_METADATA.flowHelperView.isExpanded ||
            localCache.activeTab !== DEFAULT_DISPLAY_METADATA.activeTab
        );
    }, []);

    // Restore from backend if local cache is empty
    const restoreFromBackend = useCallback((backendDisplayMeta: Record<string, unknown> | null | undefined) => {
        if (hasLocalCache() || !backendDisplayMeta || Object.keys(backendDisplayMeta).length === 0) {
            return;
        }

        const meta = backendDisplayMeta as Record<string, any>;
        setDisplayMetadata({
            viewport: meta.viewport || DEFAULT_DISPLAY_METADATA.viewport,
            selectedNodeId: meta.selectedNodeId ?? DEFAULT_DISPLAY_METADATA.selectedNodeId,
            flowHelperView: {
                height: meta.flowHelperView?.height ?? DEFAULT_DISPLAY_METADATA.flowHelperView.height,
                isFullScreen: meta.flowHelperView?.isFullScreen ?? DEFAULT_DISPLAY_METADATA.flowHelperView.isFullScreen,
                isExpanded: meta.flowHelperView?.isExpanded ?? DEFAULT_DISPLAY_METADATA.flowHelperView.isExpanded,
                activeTab: meta.flowHelperView?.activeTab ?? DEFAULT_DISPLAY_METADATA.flowHelperView.activeTab,
                searchQuery: meta.flowHelperView?.searchQuery ?? DEFAULT_DISPLAY_METADATA.flowHelperView.searchQuery,
            },
            activeTab: meta.activeTab || DEFAULT_DISPLAY_METADATA.activeTab,
        });
    }, [hasLocalCache, setDisplayMetadata]);

    // Auto-save display metadata to backend when it changes
    useEffect(() => {
        if (!workflowId || workflowId.startsWith('workflow_demo') || !hasLoadedWorkflow) {
            return;
        }

        console.log('[useWorkflowDisplayMetadata] Auto-saving display metadata:', workflowId);

        sendEventWithCallback(
            WorkflowUpdateRequest.create({
                workflow_id: workflowId,
                display_metadata: debouncedDisplayMetadata as unknown as { [k: string]: unknown }
            }),
            (response) => {
                if (response.error) {
                    console.error('[useWorkflowDisplayMetadata] Save failed:', response.error);
                } else {
                    console.log('[useWorkflowDisplayMetadata] Saved successfully');
                }
            }
        );
    }, [debouncedDisplayMetadata, workflowId, hasLoadedWorkflow]);

    return {
        // Raw state
        displayMetadata,
        displayMetadataRef,
        setDisplayMetadata,

        // Derived values
        activeTab: displayMetadata.activeTab,
        viewport: displayMetadata.viewport,
        flowHelperHeight: displayMetadata.flowHelperView.height,
        isFlowHelperFullScreen: displayMetadata.flowHelperView.isFullScreen,
        isConfigViewExpanded: displayMetadata.flowHelperView.isExpanded,
        flowHelperActiveTab: displayMetadata.flowHelperView.activeTab,
        flowHelperSearchQuery: displayMetadata.flowHelperView.searchQuery,

        // Setters
        setActiveTab,
        setViewport,
        setFlowHelperHeight,
        setIsFlowHelperFullScreen,
        setIsConfigViewExpanded,
        setFlowHelperActiveTab,
        setFlowHelperSearchQuery,
        setSelectedNodeId,

        // Restoration helpers
        hasLocalCache,
        restoreFromBackend,
    };
}
