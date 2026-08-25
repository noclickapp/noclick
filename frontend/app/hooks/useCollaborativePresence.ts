/**
 * Hook for managing collaborative presence in workflow canvas.
 * Provides reactive state for collaborator cursors, selections, and avatars.
 *
 * Supports two modes:
 * - Mock mode (default): Simulated collaborators for development/testing
 * - Real mode: Live collaboration via the configured workflow relay
 */

import { useState, useEffect, useCallback, useRef, useMemo } from 'react';
import type { Node, Edge } from '@xyflow/react';
import {
  Collaborator,
  CollaboratorCursor,
  getPresenceService,
  getWorkflowPresenceService,
  PresenceEvent,
  NodeDragEvent,
  ENABLE_REAL_COLLABORATION,
  AiEditInfo,
  AiEditingEvent,
} from '~/lib/collaboration';
import type { WorkflowChangeEvent } from '~/lib/collaboration/workflowPresenceService';
import { getDocumentStateManager } from '~/lib/collaboration/documentStateManager';
import { acquireForCanvas, releaseFromCanvas } from '~/lib/presenceManager';

interface UseCollaborativePresenceOptions {
  workflowId: string;
  /** Current user info - in production, get from auth context */
  localUser?: {
    id: string;
    name: string;
    email?: string;
    avatarUrl?: string;
  };
  /** Nodes with positions and dimensions for mock drag simulation */
  nodes?: Array<{ id: string; position: { x: number; y: number }; width?: number; height?: number }>;
  /** Enable/disable the feature */
  enabled?: boolean;
  /** Callback when a collaborator drags a node */
  onNodeDrag?: (nodeId: string, position: { x: number; y: number }) => void;
  /** Callback when a collaborator adds a node */
  onNodeAdd?: (node: Node) => void;
  /** Callback when a collaborator removes a node */
  onNodeRemove?: (nodeId: string) => void;
  /** Callback when a collaborator updates a node's data */
  onNodeUpdate?: (nodeId: string, data: Record<string, unknown>) => void;
  /** Callback when a collaborator adds an edge */
  onEdgeAdd?: (edge: Edge) => void;
  /** Callback when a collaborator removes an edge */
  onEdgeRemove?: (edgeId: string) => void;
  /** Force use of mock service even when real is available */
  useMock?: boolean;
  /**
   * Callback when reconnecting after being offline.
   * CRITICAL: Must refetch workflow from backend to avoid overwriting others' changes.
   */
  onReconnect?: () => void;
  /** Callback when a remote collaborator starts AI editing */
  onRemoteAiEditingStart?: (userId: string, nodeIds: string[]) => void;
  /** Callback when a remote collaborator updates AI editing info */
  onRemoteAiEditingUpdate?: (userId: string, nodeId: string, info: AiEditInfo) => void;
  /** Callback when a remote collaborator ends AI editing */
  onRemoteAiEditingEnd?: (userId: string) => void;
}

interface CollaborativePresenceState {
  /** All remote collaborators (excludes local user) */
  collaborators: Collaborator[];
  /** Map of nodeId -> collaborators who have it selected (for border highlighting) */
  nodeSelections: Map<string, Collaborator[]>;
  /** Whether presence is connected */
  isConnected: boolean;
  /** Connection mode */
  mode: 'mock' | 'real';
}

interface UseCollaborativePresenceReturn extends CollaborativePresenceState {
  /** Call when local cursor moves on canvas */
  updateLocalCursor: (cursor: CollaboratorCursor | null) => void;
  /** Call when local selection changes */
  updateLocalSelection: (nodeIds: string[]) => void;
  /** Call when local user drags a node */
  broadcastNodeDrag: (nodeId: string, position: { x: number; y: number }) => void;
  /** Call when local user adds a node */
  broadcastNodeAdd: (node: Node) => void;
  /** Call when local user removes a node */
  broadcastNodeRemove: (nodeId: string) => void;
  /** Call when local user updates a node's data */
  broadcastNodeUpdate: (nodeId: string, data: Record<string, unknown>) => void;
  /** Call when local user adds an edge */
  broadcastEdgeAdd: (edge: Edge) => void;
  /** Call when local user removes an edge */
  broadcastEdgeRemove: (edgeId: string) => void;
  /** Call when local AI editing starts */
  broadcastAiEditingStart: (nodeIds: string[]) => void;
  /** Call when local AI editing info updates */
  broadcastAiEditingUpdate: (nodeId: string, info: AiEditInfo) => void;
  /** Call when local AI editing ends */
  broadcastAiEditingEnd: () => void;
}

// Default mock local user - replace with real auth in production
const DEFAULT_LOCAL_USER = {
  id: 'local-user',
  name: 'You',
  email: 'you@example.com',
};

export function useCollaborativePresence({
  workflowId,
  localUser = DEFAULT_LOCAL_USER,
  nodes = [],
  enabled = true,
  onNodeDrag,
  onNodeAdd,
  onNodeRemove,
  onNodeUpdate,
  onEdgeAdd,
  onEdgeRemove,
  useMock = false,
  onReconnect,
  onRemoteAiEditingStart,
  onRemoteAiEditingUpdate,
  onRemoteAiEditingEnd,
}: UseCollaborativePresenceOptions): UseCollaborativePresenceReturn {
  const [collaborators, setCollaborators] = useState<Collaborator[]>([]);
  const [isConnected, setIsConnected] = useState(false);
  const [mode, setMode] = useState<'mock' | 'real'>('mock');
  const onNodeDragRef = useRef(onNodeDrag);
  const onNodeAddRef = useRef(onNodeAdd);
  const onNodeRemoveRef = useRef(onNodeRemove);
  const onNodeUpdateRef = useRef(onNodeUpdate);
  const onEdgeAddRef = useRef(onEdgeAdd);
  const onEdgeRemoveRef = useRef(onEdgeRemove);
  const onReconnectRef = useRef(onReconnect);
  const onRemoteAiEditingStartRef = useRef(onRemoteAiEditingStart);
  const onRemoteAiEditingUpdateRef = useRef(onRemoteAiEditingUpdate);
  const onRemoteAiEditingEndRef = useRef(onRemoteAiEditingEnd);
  // Track if we've connected before (to detect reconnection vs initial connection)
  const hasConnectedBeforeRef = useRef(false);

  // Determine which service to use
  const useRealService = ENABLE_REAL_COLLABORATION && !useMock;

  // Keep callback refs updated
  useEffect(() => {
    onNodeDragRef.current = onNodeDrag;
    onNodeAddRef.current = onNodeAdd;
    onNodeRemoveRef.current = onNodeRemove;
    onNodeUpdateRef.current = onNodeUpdate;
    onEdgeAddRef.current = onEdgeAdd;
    onEdgeRemoveRef.current = onEdgeRemove;
    onReconnectRef.current = onReconnect;
    onRemoteAiEditingStartRef.current = onRemoteAiEditingStart;
    onRemoteAiEditingUpdateRef.current = onRemoteAiEditingUpdate;
    onRemoteAiEditingEndRef.current = onRemoteAiEditingEnd;
  }, [onNodeDrag, onNodeAdd, onNodeRemove, onNodeUpdate, onEdgeAdd, onEdgeRemove, onReconnect, onRemoteAiEditingStart, onRemoteAiEditingUpdate, onRemoteAiEditingEnd]);

  // Compute node selections map from collaborators
  // Memoized to avoid recreating Map on every render (which would cause context re-renders)
  const nodeSelections = useMemo(() => {
    const map = new Map<string, Collaborator[]>();
    collaborators.forEach(collaborator => {
      collaborator.selectedNodeIds.forEach(nodeId => {
        const existing = map.get(nodeId) || [];
        map.set(nodeId, [...existing, collaborator]);
      });
    });
    return map;
  }, [collaborators]);

  // Connect/disconnect based on enabled state and workflowId
  useEffect(() => {
    if (!enabled || !workflowId) return;

    let cleanup: (() => void) | undefined;
    let mounted = true;

    const connect = async () => {
      if (useRealService) {
        // Real collaboration mode. Connection lifecycle is owned by
        // presenceManager — it keeps the WS alive while either the
        // canvas (this hook's mount) OR an active gen wants it. So we
        // acquire here instead of calling service.connect directly,
        // and release on cleanup. The manager dedupes if the gen
        // already opened the connection.
        acquireForCanvas(workflowId, localUser);
        if (!mounted) {
          releaseFromCanvas(workflowId);
          return;
        }

        const service = getWorkflowPresenceService(workflowId);
        const documentState = getDocumentStateManager();

        // Initialize document state with current node positions for conflict resolution
        if (nodes.length > 0) {
          documentState.initializeFromNodes(nodes as Node[]);
        }

        // Clear any stale collaborators before subscribing (handles reconnection)
        setCollaborators([]);

        // Subscribe to presence events
        const unsubscribePresence = service.subscribe((event: PresenceEvent) => {
          if (!mounted) return;

          switch (event.type) {
            case 'collaborator:join':
              if (event.data) {
                // Dedupe: only add if not already present
                setCollaborators(prev => {
                  const exists = prev.some(c => c.id === (event.data as Collaborator).id);
                  return exists ? prev : [...prev, event.data as Collaborator];
                });
              }
              break;

            case 'collaborator:leave':
              setCollaborators(prev => prev.filter(c => c.id !== event.collaboratorId));
              break;

            case 'collaborator:cursor:move':
            case 'collaborator:selection:change':
            case 'collaborator:activity:change':
              setCollaborators(prev =>
                prev.map(c =>
                  c.id === event.collaboratorId ? { ...c, ...event.data } : c
                )
              );
              break;
          }
        });

        // Subscribe to node drag events with conflict resolution
        const unsubscribeDrags = service.subscribeToNodeDrags((event: NodeDragEvent) => {
          if (!mounted) return;

          // Use document state manager for conflict resolution
          const { shouldApply, position } = documentState.handleRemoteChange(
            event.nodeId,
            event.position
          );

          if (shouldApply) {
            onNodeDragRef.current?.(event.nodeId, position);
          }
        });

        // Subscribe to workflow change events (node/edge add/remove)
        const unsubscribeWorkflowChanges = service.subscribeToWorkflowChanges((event: WorkflowChangeEvent) => {
          if (!mounted) return;

          switch (event.type) {
            case 'node:add':
              onNodeAddRef.current?.(event.data as Node);
              break;
            case 'node:remove':
              onNodeRemoveRef.current?.(event.data as string);
              break;
            case 'node:update':
              if (event.nodeId) {
                onNodeUpdateRef.current?.(event.nodeId, event.data as Record<string, unknown>);
              }
              break;
            case 'edge:add':
              onEdgeAddRef.current?.(event.data as Edge);
              break;
            case 'edge:remove':
              onEdgeRemoveRef.current?.(event.data as string);
              break;
          }
        });

        // Subscribe to AI editing events (for remote collaborator AI editing animations)
        const unsubscribeAiEditing = service.subscribeToAiEditing((event: AiEditingEvent) => {
          if (!mounted) return;

          switch (event.type) {
            case 'ai:editing:start':
              if (event.nodeIds) {
                onRemoteAiEditingStartRef.current?.(event.collaboratorId, event.nodeIds);
              }
              break;
            case 'ai:editing:update':
              if (event.nodeId && event.info) {
                onRemoteAiEditingUpdateRef.current?.(event.collaboratorId, event.nodeId, event.info);
              }
              break;
            case 'ai:editing:end':
              onRemoteAiEditingEndRef.current?.(event.collaboratorId);
              break;
          }
        });

        // No service.connect() here — presenceManager called it (or
        // already had it open from the gen path). The hook is
        // strictly a subscriber + state surface now.
        documentState.setConnected();
        setIsConnected(true);
        setMode('real');

        // Detect reconnection and trigger workflow refresh to avoid stale state
        if (hasConnectedBeforeRef.current) {
          // This is a reconnection - MUST refresh workflow from backend
          // to avoid overwriting other users' changes with stale local state
          console.log('[Presence] Reconnection detected - triggering workflow refresh');
          onReconnectRef.current?.();
        }
        hasConnectedBeforeRef.current = true;

        cleanup = () => {
          unsubscribePresence();
          unsubscribeDrags();
          unsubscribeWorkflowChanges();
          unsubscribeAiEditing();
          // Release our canvas hold; manager will dispose the
          // connection only if no gen is also holding it.
          releaseFromCanvas(workflowId);
          documentState.setDisconnected();
          documentState.clear();
        };
      } else {
        // Mock mode
        const service = getPresenceService();

        const unsubscribePresence = service.subscribe((event: PresenceEvent) => {
          if (!mounted) return;

          switch (event.type) {
            case 'collaborator:join':
              if (event.data) {
                setCollaborators(prev => [...prev, event.data as Collaborator]);
              }
              break;

            case 'collaborator:leave':
              setCollaborators(prev => prev.filter(c => c.id !== event.collaboratorId));
              break;

            case 'collaborator:cursor:move':
            case 'collaborator:selection:change':
            case 'collaborator:activity:change':
              setCollaborators(prev =>
                prev.map(c =>
                  c.id === event.collaboratorId ? { ...c, ...event.data } : c
                )
              );
              break;
          }
        });

        const unsubscribeDrags = service.subscribeToNodeDrags((event: NodeDragEvent) => {
          if (!mounted) return;
          onNodeDragRef.current?.(event.nodeId, event.position);
        });

        service.connect({ workflowId, localUser });
        setIsConnected(true);
        setMode('mock');

        cleanup = () => {
          unsubscribePresence();
          unsubscribeDrags();
          service.disconnect();
        };
      }
    };

    connect();

    return () => {
      mounted = false;
      cleanup?.();
      setIsConnected(false);
      setCollaborators([]);
    };
  }, [workflowId, enabled, localUser, useRealService]);

  // Update available nodes for mock simulation
  useEffect(() => {
    if (enabled && nodes.length > 0 && !useRealService) {
      getPresenceService().setAvailableNodes(nodes);
    }
  }, [nodes, enabled, useRealService]);

  const updateLocalCursor = useCallback((cursor: CollaboratorCursor | null) => {
    if (useRealService) {
      getWorkflowPresenceService(workflowId).broadcastCursor(cursor);
    } else {
      getPresenceService().broadcastCursor(cursor);
    }
  }, [useRealService]);

  const updateLocalSelection = useCallback((nodeIds: string[]) => {
    if (useRealService) {
      getWorkflowPresenceService(workflowId).broadcastSelection(nodeIds);
    } else {
      getPresenceService().broadcastSelection(nodeIds);
    }
  }, [useRealService]);

  const broadcastNodeDrag = useCallback((nodeId: string, position: { x: number; y: number }) => {
    if (useRealService) {
      // Record local change for conflict resolution
      const documentState = getDocumentStateManager();
      const resolvedPosition = documentState.recordLocalChange(nodeId, position);

      // Broadcast to other collaborators
      getWorkflowPresenceService(workflowId).broadcastNodeDrag(nodeId, resolvedPosition);
    }
  }, [useRealService]);

  const broadcastNodeAdd = useCallback((node: Node) => {
    if (useRealService) {
      getWorkflowPresenceService(workflowId).broadcastNodeAdd(node);
    }
  }, [useRealService]);

  const broadcastNodeRemove = useCallback((nodeId: string) => {
    if (useRealService) {
      getWorkflowPresenceService(workflowId).broadcastNodeRemove(nodeId);
    }
  }, [useRealService]);

  const broadcastNodeUpdate = useCallback((nodeId: string, data: Record<string, unknown>) => {
    if (useRealService) {
      getWorkflowPresenceService(workflowId).broadcastNodeUpdate(nodeId, data);
    }
  }, [useRealService]);

  const broadcastEdgeAdd = useCallback((edge: Edge) => {
    if (useRealService) {
      getWorkflowPresenceService(workflowId).broadcastEdgeAdd(edge);
    }
  }, [useRealService]);

  const broadcastEdgeRemove = useCallback((edgeId: string) => {
    if (useRealService) {
      getWorkflowPresenceService(workflowId).broadcastEdgeRemove(edgeId);
    }
  }, [useRealService]);

  const broadcastAiEditingStart = useCallback((nodeIds: string[]) => {
    if (useRealService) {
      getWorkflowPresenceService(workflowId).broadcastAiEditingStart(nodeIds);
    }
  }, [useRealService]);

  const broadcastAiEditingUpdate = useCallback((nodeId: string, info: AiEditInfo) => {
    if (useRealService) {
      getWorkflowPresenceService(workflowId).broadcastAiEditingUpdate(nodeId, info);
    }
  }, [useRealService]);

  const broadcastAiEditingEnd = useCallback(() => {
    if (useRealService) {
      getWorkflowPresenceService(workflowId).broadcastAiEditingEnd();
    }
  }, [useRealService]);

  return {
    collaborators,
    nodeSelections,
    isConnected,
    mode,
    updateLocalCursor,
    updateLocalSelection,
    broadcastNodeDrag,
    broadcastNodeAdd,
    broadcastNodeRemove,
    broadcastNodeUpdate,
    broadcastEdgeAdd,
    broadcastEdgeRemove,
    broadcastAiEditingStart,
    broadcastAiEditingUpdate,
    broadcastAiEditingEnd,
  };
}
