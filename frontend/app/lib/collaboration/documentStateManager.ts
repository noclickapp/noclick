/**
 * DocumentStateManager - Tracks document state and handles offline/online conflict resolution.
 *
 * Implements Figma-style property-level last-writer-wins:
 * - Tracks local unacknowledged changes while online
 * - On disconnect, marks pending changes for reapplication
 * - On reconnect, fetches fresh server state and reapplies local changes
 * - Property-level granularity: changes to different properties don't conflict
 */

import type { Node } from '@xyflow/react';

/** Change record for a single property on a node */
interface PropertyChange {
  nodeId: string;
  property: 'position' | 'data' | 'selected';
  value: unknown;
  timestamp: number;
}

/** Node position with timestamp for conflict resolution */
interface NodePosition {
  x: number;
  y: number;
  timestamp: number;
}

/** Listener for state changes */
type StateChangeListener = (nodeId: string, position: NodePosition) => void;

export class DocumentStateManager {
  /** Map of nodeId -> position with timestamp */
  private nodePositions: Map<string, NodePosition> = new Map();

  /** Pending changes that haven't been acknowledged by server */
  private pendingChanges: PropertyChange[] = [];

  /** Whether we're currently connected to the server */
  private isConnected = false;

  /** Listeners for remote position updates */
  private positionListeners: Set<StateChangeListener> = new Set();

  /** Track if we have unsynced offline changes */
  private hasOfflineChanges = false;

  /** Re-entrancy guard for listener notification */
  private isNotifying = false;

  /**
   * Initialize with current node positions from FlowCanvas.
   * Called when workflow is loaded or on reconnection.
   * Clears any stale pending changes since we're starting fresh.
   */
  initializeFromNodes(nodes: Node[]): void {
    // Clear stale state - we're initializing fresh from server/canvas
    this.nodePositions.clear();
    this.pendingChanges = [];
    this.hasOfflineChanges = false;

    const now = Date.now();
    nodes.forEach(node => {
      this.nodePositions.set(node.id, {
        x: node.position.x,
        y: node.position.y,
        timestamp: now,
      });
    });
  }

  /**
   * Record a local position change (user dragging a node).
   * Returns the position to use (may be overridden by more recent remote change).
   */
  recordLocalChange(
    nodeId: string,
    position: { x: number; y: number }
  ): { x: number; y: number } {
    const now = Date.now();
    const currentPosition = this.nodePositions.get(nodeId);

    // If we have a more recent remote position, don't override it
    if (currentPosition && currentPosition.timestamp > now) {
      return { x: currentPosition.x, y: currentPosition.y };
    }

    // Store the new position
    this.nodePositions.set(nodeId, { x: position.x, y: position.y, timestamp: now });

    // Always track as pending change (both online and offline)
    // This ensures offline changes are properly reapplied on reconnect
    this.pendingChanges.push({
      nodeId,
      property: 'position',
      value: position,
      timestamp: now,
    });

    // Also track offline flag for quick hasPendingChanges check
    if (!this.isConnected) {
      this.hasOfflineChanges = true;
    }

    return position;
  }

  /**
   * Handle a remote position update from another collaborator.
   * Implements last-writer-wins based on timestamp.
   */
  handleRemoteChange(
    nodeId: string,
    position: { x: number; y: number },
    timestamp?: number
  ): { shouldApply: boolean; position: { x: number; y: number } } {
    // Use nullish coalescing to properly handle timestamp of 0
    const changeTime = timestamp ?? Date.now();
    const currentPosition = this.nodePositions.get(nodeId);

    // Last-writer-wins: only apply if newer than our local state
    if (!currentPosition || changeTime >= currentPosition.timestamp) {
      const newPosition = { x: position.x, y: position.y, timestamp: changeTime };
      this.nodePositions.set(nodeId, newPosition);

      // Notify listeners (with re-entrancy protection to prevent infinite loops)
      if (!this.isNotifying) {
        this.isNotifying = true;
        try {
          this.positionListeners.forEach(listener => {
            try {
              listener(nodeId, newPosition);
            } catch (error) {
              // Log but don't throw - ensure all listeners get notified
              console.error('Error in position listener:', error);
            }
          });
        } finally {
          this.isNotifying = false;
        }
      }

      return { shouldApply: true, position };
    }

    // Our local change is more recent, don't apply remote
    return { shouldApply: false, position: { x: currentPosition.x, y: currentPosition.y } };
  }

  /**
   * Mark connection as established.
   * Called when successfully connected to workflow relay.
   */
  setConnected(): void {
    this.isConnected = true;
  }

  /**
   * Mark connection as lost.
   * Pending changes will be reapplied on reconnection.
   */
  setDisconnected(): void {
    this.isConnected = false;
  }

  /**
   * Handle reconnection: compare server state with local state
   * and return changes that should be reapplied.
   */
  onReconnect(serverNodes: Node[]): Array<{ nodeId: string; position: { x: number; y: number } }> {
    const changesToReapply: Array<{ nodeId: string; position: { x: number; y: number } }> = [];

    if (!this.hasOfflineChanges && this.pendingChanges.length === 0) {
      // No local changes, just accept server state
      this.initializeFromNodes(serverNodes);
      return [];
    }

    // Build map of server positions
    const serverPositions = new Map<string, { x: number; y: number }>();
    serverNodes.forEach(node => {
      serverPositions.set(node.id, { x: node.position.x, y: node.position.y });
    });

    // Track nodes to remove (deleted on server)
    const nodesToRemove: string[] = [];

    // Check each local position against server
    this.nodePositions.forEach((localPos, nodeId) => {
      const serverPos = serverPositions.get(nodeId);

      if (!serverPos) {
        // Node doesn't exist on server (deleted), mark for removal
        nodesToRemove.push(nodeId);
        return;
      }

      // If local position differs from server and we have pending changes,
      // reapply our local change (user intent preservation)
      const hasPendingChange = this.pendingChanges.some(
        c => c.nodeId === nodeId && c.property === 'position'
      );

      if (hasPendingChange) {
        changesToReapply.push({
          nodeId,
          position: { x: localPos.x, y: localPos.y },
        });
      } else {
        // Accept server state for this node
        this.nodePositions.set(nodeId, {
          x: serverPos.x,
          y: serverPos.y,
          timestamp: Date.now(),
        });
      }
    });

    // Remove deleted nodes from local state and their pending changes
    nodesToRemove.forEach(nodeId => this.nodePositions.delete(nodeId));
    if (nodesToRemove.length > 0) {
      const deletedSet = new Set(nodesToRemove);
      this.pendingChanges = this.pendingChanges.filter(c => !deletedSet.has(c.nodeId));
    }

    // Add server nodes that we don't have locally
    const now = Date.now();
    serverPositions.forEach((serverPos, nodeId) => {
      if (!this.nodePositions.has(nodeId)) {
        this.nodePositions.set(nodeId, {
          x: serverPos.x,
          y: serverPos.y,
          timestamp: now,
        });
      }
    });

    // DON'T clear pendingChanges here - caller must call acknowledgeChange after
    // successful broadcast. This prevents data loss on rapid disconnect-reconnect.
    // Only clear the offline flag since we've processed the reconnection.
    this.hasOfflineChanges = false;

    return changesToReapply;
  }

  /**
   * Acknowledge that a change has been persisted to the server.
   * Called after successful save/sync operation.
   */
  acknowledgeChange(nodeId: string): void {
    this.pendingChanges = this.pendingChanges.filter(
      c => !(c.nodeId === nodeId && c.property === 'position')
    );
  }

  /**
   * Subscribe to remote position updates.
   * Returns unsubscribe function.
   */
  onRemotePositionUpdate(listener: StateChangeListener): () => void {
    this.positionListeners.add(listener);
    return () => this.positionListeners.delete(listener);
  }

  /**
   * Get the current authoritative position for a node.
   * Used when we need to resolve conflicts.
   */
  getNodePosition(nodeId: string): { x: number; y: number } | undefined {
    const pos = this.nodePositions.get(nodeId);
    return pos ? { x: pos.x, y: pos.y } : undefined;
  }

  /**
   * Check if there are unacknowledged changes.
   */
  hasPendingChanges(): boolean {
    return this.pendingChanges.length > 0 || this.hasOfflineChanges;
  }

  /**
   * Clear all state (e.g., when switching workflows).
   */
  clear(): void {
    this.nodePositions.clear();
    this.pendingChanges = [];
    this.hasOfflineChanges = false;
    this.positionListeners.clear();
    this.isNotifying = false;
  }
}

// Singleton instance
let documentStateManagerInstance: DocumentStateManager | null = null;

export function getDocumentStateManager(): DocumentStateManager {
  if (!documentStateManagerInstance) {
    documentStateManagerInstance = new DocumentStateManager();
  }
  return documentStateManagerInstance;
}
