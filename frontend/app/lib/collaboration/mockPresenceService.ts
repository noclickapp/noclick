/**
 * Mock presence service that simulates collaborative user behavior.
 * This service generates fake collaborators with moving cursors and changing selections
 * for testing the collaborative UX. Replace the mock methods with real socket/YJS calls
 * when backend integration is ready.
 *
 * STUB LOCATIONS for real backend:
 * - connect(): Initialize real WebSocket/YJS presence
 * - disconnect(): Clean up real connections
 * - broadcastCursor(): Send local cursor to other users
 * - broadcastSelection(): Send local selection to other users
 */

import {
  Collaborator,
  CollaboratorCursor,
  PresenceEvent,
  PresenceServiceConfig,
  NodeDragEvent,
  getCollaboratorColor,
} from './types';

type PresenceEventHandler = (event: PresenceEvent) => void;
type NodeDragHandler = (event: NodeDragEvent) => void;

// Mock user profiles for simulation - using lorelei style with background colors for solid avatars
const MOCK_USERS = [
  { id: 'mock-user-1', name: 'Alice Chen', avatarUrl: 'https://api.dicebear.com/7.x/lorelei/svg?seed=alice&backgroundColor=f87171' },
  { id: 'mock-user-2', name: 'Bob Smith', avatarUrl: 'https://api.dicebear.com/7.x/lorelei/svg?seed=bob&backgroundColor=60a5fa' },
  { id: 'mock-user-3', name: 'Carol Wu', avatarUrl: 'https://api.dicebear.com/7.x/lorelei/svg?seed=carol&backgroundColor=34d399' },
];

export class MockPresenceService {
  private collaborators: Map<string, Collaborator> = new Map();
  private eventHandlers: Set<PresenceEventHandler> = new Set();
  private nodeDragHandlers: Set<NodeDragHandler> = new Set();
  private animationIntervals: number[] = [];
  private joinTimeouts: number[] = []; // Track setTimeout handles to prevent duplicates
  private config: PresenceServiceConfig | null = null;
  private nodeIds: string[] = [];
  private nodePositions: Map<string, { x: number; y: number }> = new Map();
  private nodeDimensions: Map<string, { width: number; height: number }> = new Map();

  /**
   * STUB: Connect to presence service
   * Replace with real WebSocket/YJS connection initialization
   */
  connect(config: PresenceServiceConfig): void {
    // Clean up any existing simulation first (handles React strict mode re-renders)
    this.stopMockSimulation();
    this.collaborators.clear();

    this.config = config;
    // --- REAL BACKEND STUB ---
    // await socket.emit('presence:join', { workflowId: config.workflowId, user: config.localUser });
    // yjs.awareness.setLocalState({ user: config.localUser, cursor: null, selectedNodeIds: [] });
    // --- END STUB ---

    // Mock: Simulate users joining after a delay
    this.startMockSimulation();
  }

  /**
   * STUB: Disconnect from presence service
   * Replace with real cleanup
   */
  disconnect(): void {
    // --- REAL BACKEND STUB ---
    // socket.emit('presence:leave', { workflowId: this.config?.workflowId });
    // yjs.awareness.setLocalState(null);
    // --- END STUB ---

    this.stopMockSimulation();
    this.collaborators.clear();
    this.config = null;
  }

  /**
   * STUB: Broadcast local cursor position to other users
   */
  broadcastCursor(cursor: CollaboratorCursor | null): void {
    // --- REAL BACKEND STUB ---
    // socket.emit('presence:cursor', { cursor });
    // yjs.awareness.setLocalStateField('cursor', cursor);
    // --- END STUB ---
  }

  /**
   * STUB: Broadcast local node selection to other users
   */
  broadcastSelection(nodeIds: string[]): void {
    // --- REAL BACKEND STUB ---
    // socket.emit('presence:selection', { nodeIds });
    // yjs.awareness.setLocalStateField('selectedNodeIds', nodeIds);
    // --- END STUB ---
  }

  /** Update the list of available nodes with their positions and dimensions for mock simulation */
  setAvailableNodes(nodes: Array<{ id: string; position: { x: number; y: number }; width?: number; height?: number }>): void {
    this.nodeIds = nodes.map(n => n.id);
    this.nodePositions.clear();
    this.nodeDimensions.clear();
    nodes.forEach(n => {
      this.nodePositions.set(n.id, { ...n.position });
      this.nodeDimensions.set(n.id, { width: n.width || 240, height: n.height || 200 });
    });
  }

  /** Subscribe to presence events */
  subscribe(handler: PresenceEventHandler): () => void {
    this.eventHandlers.add(handler);
    return () => this.eventHandlers.delete(handler);
  }

  /** Subscribe to node drag events (separate from presence for cleaner handling) */
  subscribeToNodeDrags(handler: NodeDragHandler): () => void {
    this.nodeDragHandlers.add(handler);
    return () => this.nodeDragHandlers.delete(handler);
  }

  private emitNodeDrag(event: NodeDragEvent): void {
    this.nodeDragHandlers.forEach(handler => handler(event));
  }

  /** Get current collaborators (excluding local user) */
  getCollaborators(): Collaborator[] {
    return Array.from(this.collaborators.values());
  }

  private emit(event: PresenceEvent): void {
    this.eventHandlers.forEach(handler => handler(event));
  }

  private startMockSimulation(): void {
    // Add mock users with staggered timing
    MOCK_USERS.forEach((user, index) => {
      const joinDelay = 1000 + index * 800; // Stagger joins

      const timeoutId = window.setTimeout(() => {
        // Guard against adding if already disconnected or user exists
        if (!this.config || this.collaborators.has(user.id)) return;

        const collaborator: Collaborator = {
          id: user.id,
          name: user.name,
          avatarUrl: user.avatarUrl,
          color: getCollaboratorColor(user.id),
          cursor: this.getRandomCanvasPosition(),
          selectedNodeIds: [],
          isActive: true,
          lastActiveAt: Date.now(),
        };

        this.collaborators.set(user.id, collaborator);
        this.emit({ type: 'collaborator:join', collaboratorId: user.id, data: collaborator });

        // Start cursor animation for this user
        this.startCursorAnimation(user.id);
        // Start selection changes for this user
        this.startSelectionAnimation(user.id, index);
      }, joinDelay);

      this.joinTimeouts.push(timeoutId);
    });
  }

  private stopMockSimulation(): void {
    // Clear all pending join timeouts
    this.joinTimeouts.forEach(id => clearTimeout(id));
    this.joinTimeouts = [];
    // Clear all animation intervals
    this.animationIntervals.forEach(id => clearInterval(id));
    this.animationIntervals = [];
  }

  private getRandomCanvasPosition(): CollaboratorCursor {
    // Canvas coordinates typically range from -500 to 1500 or so
    return {
      x: Math.random() * 1200 - 200,
      y: Math.random() * 800 - 100,
    };
  }

  /**
   * Combined cursor movement and node interaction animation.
   * Handles: random cursor movement, node selection, and node dragging.
   * All in one loop so cursor and drag are coordinated.
   *
   * Phases:
   * 1. WANDERING: Cursor moves randomly
   * 2. REACHING: Cursor moves to node (node is selected but not moving yet)
   * 3. DRAGGING: Node follows cursor as it moves to new positions
   */
  private startCursorAnimation(userId: string): void {
    const initialCollaborator = this.collaborators.get(userId);
    if (!initialCollaborator?.cursor) return;

    // Cursor state
    let currentPos = { ...initialCollaborator.cursor };
    let targetPos = this.getRandomCanvasPosition();

    // Interaction state
    type Phase = 'wandering' | 'reaching' | 'dragging';
    let phase: Phase = 'wandering';
    let selectedNodeId: string | null = null;
    let dragTargetPos = { x: 0, y: 0 };
    let phaseFrames = 0;
    const maxDragFrames = 50; // ~2.5 seconds of dragging
    let idleFrames = 0;
    const minIdleFrames = 40; // Wait ~2 seconds between interactions

    const intervalId = window.setInterval(() => {
      const collaborator = this.collaborators.get(userId);
      if (!collaborator) return;

      if (phase === 'dragging' && selectedNodeId) {
        // === DRAGGING PHASE: Node follows cursor ===
        phaseFrames++;

        const nodeDims = this.nodeDimensions.get(selectedNodeId);
        if (!nodeDims) {
          phase = 'wandering';
          selectedNodeId = null;
          return;
        }

        // Move cursor toward drag target
        const dx = dragTargetPos.x - currentPos.x;
        const dy = dragTargetPos.y - currentPos.y;
        currentPos.x += dx * 0.1;
        currentPos.y += dy * 0.1;

        // Update cursor
        this.updateCursor(userId, collaborator, currentPos);

        // Move node so cursor stays at its center
        // cursor is at center, so node top-left = cursor - (width/2, height/2)
        const newNodePos = {
          x: currentPos.x - nodeDims.width / 2,
          y: currentPos.y - nodeDims.height / 2,
        };
        this.nodePositions.set(selectedNodeId, newNodePos);
        this.emitNodeDrag({
          type: 'collaborator:node:drag',
          collaboratorId: userId,
          nodeId: selectedNodeId,
          position: newNodePos,
        });

        // Pick new drag target occasionally
        if (phaseFrames % 25 === 0) {
          dragTargetPos = {
            x: currentPos.x + (Math.random() - 0.5) * 250,
            y: currentPos.y + (Math.random() - 0.5) * 150,
          };
        }

        // Stop dragging after max frames
        if (phaseFrames >= maxDragFrames) {
          // Deselect node
          const updated = { ...this.collaborators.get(userId)!, selectedNodeIds: [], lastActiveAt: Date.now() };
          this.collaborators.set(userId, updated);
          this.emit({
            type: 'collaborator:selection:change',
            collaboratorId: userId,
            data: { selectedNodeIds: [] },
          });

          phase = 'wandering';
          selectedNodeId = null;
          phaseFrames = 0;
          idleFrames = 0;
          targetPos = this.getRandomCanvasPosition();
        }

      } else if (phase === 'reaching' && selectedNodeId) {
        // === REACHING PHASE: Cursor moving to node center ===
        phaseFrames++;
        const nodePos = this.nodePositions.get(selectedNodeId);
        const nodeDims = this.nodeDimensions.get(selectedNodeId);
        if (!nodePos || !nodeDims) {
          phase = 'wandering';
          selectedNodeId = null;
          return;
        }

        // Calculate node center (node.position is top-left corner)
        const nodeCenterX = nodePos.x + nodeDims.width / 2;
        const nodeCenterY = nodePos.y + nodeDims.height / 2;

        // Move cursor toward node center
        const dx = nodeCenterX - currentPos.x;
        const dy = nodeCenterY - currentPos.y;
        const distance = Math.sqrt(dx * dx + dy * dy);

        currentPos.x += dx * 0.15;
        currentPos.y += dy * 0.15;

        // Update cursor
        this.updateCursor(userId, collaborator, currentPos);

        // Once cursor is close to node center, start dragging
        if (distance < 30) {
          phase = 'dragging';
          phaseFrames = 0;
          // Set initial drag target to nearby position (offset from center)
          dragTargetPos = {
            x: nodeCenterX + (Math.random() - 0.5) * 200,
            y: nodeCenterY + (Math.random() - 0.5) * 120,
          };
        }

        // Timeout if taking too long to reach
        if (phaseFrames > 60) {
          phase = 'wandering';
          selectedNodeId = null;
          phaseFrames = 0;
        }

      } else {
        // === WANDERING PHASE: Random cursor movement ===
        idleFrames++;

        const dx = targetPos.x - currentPos.x;
        const dy = targetPos.y - currentPos.y;
        const distance = Math.sqrt(dx * dx + dy * dy);

        if (distance < 15) {
          targetPos = this.getRandomCanvasPosition();
        }

        currentPos.x += dx * 0.08;
        currentPos.y += dy * 0.08;

        // Update cursor
        this.updateCursor(userId, collaborator, currentPos);

        // Maybe start reaching for a node
        if (idleFrames > minIdleFrames && this.nodeIds.length > 0 && Math.random() < 0.04) {
          const randomIndex = Math.floor(Math.random() * this.nodeIds.length);
          const nodeId = this.nodeIds[randomIndex];
          const nodePos = this.nodePositions.get(nodeId);

          if (nodePos) {
            phase = 'reaching';
            selectedNodeId = nodeId;
            phaseFrames = 0;

            // Select the node immediately (shows border)
            const updated = { ...collaborator, selectedNodeIds: [nodeId], lastActiveAt: Date.now() };
            this.collaborators.set(userId, updated);
            this.emit({
              type: 'collaborator:selection:change',
              collaboratorId: userId,
              data: { selectedNodeIds: [nodeId] },
            });
          }
        }
      }
    }, 50);

    this.animationIntervals.push(intervalId);
  }

  /** Helper to update cursor position and emit event */
  private updateCursor(userId: string, collaborator: Collaborator, pos: { x: number; y: number }): void {
    const updated = { ...collaborator, cursor: { ...pos }, lastActiveAt: Date.now() };
    this.collaborators.set(userId, updated);
    this.emit({
      type: 'collaborator:cursor:move',
      collaboratorId: userId,
      data: { cursor: updated.cursor },
    });
  }

  // Selection animation is now integrated into cursor animation
  private startSelectionAnimation(_userId: string, _userIndex: number): void {
    // No-op: selection and dragging are now handled in startCursorAnimation
  }
}

// Singleton instance for the app
let presenceServiceInstance: MockPresenceService | null = null;

export function getPresenceService(): MockPresenceService {
  if (!presenceServiceInstance) {
    presenceServiceInstance = new MockPresenceService();
  }
  return presenceServiceInstance;
}
