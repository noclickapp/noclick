/**
 * Real-time presence service using the configured workflow relay.
 * Connects to <relay>/workflow/:workflowId for collaborative editing.
 * Implements the same interface as MockPresenceService for easy swapping.
 */

import { relayBaseUrl } from '~/lib/hostedDefaults';
import {
  Collaborator,
  CollaboratorCursor,
  PresenceEvent,
  PresenceServiceConfig,
  NodeDragEvent,
  AiEditInfo,
  AiEditingEvent,
} from './types';
import { socketReceiver } from '~/lib/socket-receiver';
import type { ServerToClientEvents } from '~/types/socket-events.generated';
import type { AgentPresenceWire } from '~/lib/agentPresenceStore';

type PresenceEventHandler = (event: PresenceEvent) => void;
type NodeDragHandler = (event: NodeDragEvent) => void;
type AiEditingHandler = (event: AiEditingEvent) => void;

// Server message types (must match workflow-room.ts)
type ServerMessage =
  | { type: "auth:required" }
  | { type: "auth:success"; collaborators: ServerCollaborator[] }
  | { type: "auth:error"; message: string }
  | { type: "collaborator:join"; collaborator: ServerCollaborator }
  | { type: "collaborator:leave"; userId: string }
  | { type: "presence:cursor"; userId: string; x: number; y: number }
  | { type: "presence:cursor:clear"; userId: string }
  | { type: "presence:selection"; userId: string; nodeIds: string[] }
  | { type: "node:drag"; userId: string; nodeId: string; position: { x: number; y: number } }
  | { type: "node:add"; userId: string; node: unknown }
  | { type: "node:remove"; userId: string; nodeId: string }
  | { type: "node:update"; userId: string; nodeId: string; data: unknown }
  | { type: "edge:add"; userId: string; edge: unknown }
  | { type: "edge:remove"; userId: string; edgeId: string }
  | { type: "ai:editing:start"; userId: string; nodeIds: string[] }
  | { type: "ai:editing:update"; userId: string; nodeId: string; info: AiEditInfo }
  | { type: "ai:editing:end"; userId: string }
  | { type: "execution_state"; executions: ExecutionStateEntry[]; agents?: AgentPresenceWire[] }
  | { type: "agent:presence"; agents: AgentPresenceWire[] }
  | { type: "pong"; timestamp: number }
  | { type: "error"; message: string };

// Workflow change event types
export interface WorkflowChangeEvent {
  type: "node:add" | "node:remove" | "node:update" | "edge:add" | "edge:remove";
  collaboratorId: string;
  nodeId?: string;
  data: unknown;
}

type WorkflowChangeHandler = (event: WorkflowChangeEvent) => void;

interface ServerCollaborator {
  id: string;
  name: string;
  avatarUrl?: string;
  color: string;
  connectedAt: number;
}

// Relay URL — resolved per edition; a self-hosted install serves this
// protocol from its own backend, never ours.
const RELAY_URL = typeof window !== 'undefined'
  ? (window as any).__RELAY_URL__ || relayBaseUrl().replace(/^http/, 'ws')
  : relayBaseUrl().replace(/^http/, 'ws');

// Single execution entry in the recovery response
export interface ExecutionStateEntry {
  executionId: string;
  nodeStates: Record<string, string>;
  nodeOutputs: Record<string, unknown>;
}

// Execution state response from workflow relay (supports multiple concurrent executions)
export interface ExecutionStateResponse {
  type: 'execution_state';
  executions: ExecutionStateEntry[];
  // Real-time agent-process presence rides the snapshot too, so a mounting viewer
  // gets it with zero extra request (the canvas badge's busy/running signal).
  agents?: AgentPresenceWire[];
}

type ExecutionEventHandler = (event: ExecutionStateResponse) => void;
type AgentPresenceHandler = (agents: AgentPresenceWire[]) => void;

// Execution event types that should be injected into socketReceiver
const EXECUTION_EVENT_TYPES = new Set([
  'workflow:started',
  'workflow:node:state',
  'workflow:node:output',
  'workflow:complete',
]);

export class WorkflowPresenceService {
  private ws: WebSocket | null = null;
  private collaborators: Map<string, Collaborator> = new Map();
  private eventHandlers: Set<PresenceEventHandler> = new Set();
  private nodeDragHandlers: Set<NodeDragHandler> = new Set();
  private workflowChangeHandlers: Set<WorkflowChangeHandler> = new Set();
  private aiEditingHandlers: Set<AiEditingHandler> = new Set();
  private executionEventHandlers: Set<ExecutionEventHandler> = new Set();
  private lastExecutionState: ExecutionStateResponse | null = null;
  private agentPresenceHandlers: Set<AgentPresenceHandler> = new Set();
  private lastAgentPresence: AgentPresenceWire[] = [];
  private config: PresenceServiceConfig | null = null;
  private reconnectTimer: number | null = null;
  private reconnectAttempts = 0;
  private maxReconnectAttempts = 5;

  /**
   * Connect to the workflow relay for collaborative presence.
   * Requires a JWT token for authentication (obtain from backend).
   */
  connect(config: PresenceServiceConfig & { token: string }): void {
    this.disconnect();
    this.config = config;

    const url = `${RELAY_URL}/workflow/${config.workflowId}`;
    this.ws = new WebSocket(url);

    this.ws.onopen = () => {
      // Send auth token
      this.send({ type: "auth", token: config.token });
    };

    this.ws.onmessage = (event) => {
      try {
        const msg = JSON.parse(event.data) as ServerMessage;
        this.handleMessage(msg);
      } catch (e) {
        console.error('[WorkflowPresence] Invalid message:', e);
      }
    };

    this.ws.onclose = (event) => {
      if (event.code !== 1000) {
        // Fail closed while the relay is unavailable. A reconnect snapshot
        // restores any local process that is still running.
        this.emitAgentPresence([]);
        if (this.config) this.scheduleReconnect();
      }
    };

    this.ws.onerror = (error) => {
      console.error('[WorkflowPresence] WebSocket error:', error);
    };
  }

  disconnect(): void {
    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }
    if (this.ws) {
      this.ws.close(1000, "Disconnecting");
      this.ws = null;
    }
    this.collaborators.clear();
    this.lastExecutionState = null;
    // Never leave a busy badge behind after an intentional teardown.
    this.emitAgentPresence([]);
    this.config = null;
    this.reconnectAttempts = 0;
  }

  broadcastCursor(cursor: CollaboratorCursor | null): void {
    if (cursor) {
      this.send({ type: "presence:cursor", x: cursor.x, y: cursor.y });
    } else {
      this.send({ type: "presence:cursor:clear" });
    }
  }

  broadcastSelection(nodeIds: string[]): void {
    this.send({ type: "presence:selection", nodeIds });
  }

  broadcastNodeDrag(nodeId: string, position: { x: number; y: number }): void {
    this.send({ type: "node:drag", nodeId, position });
  }

  broadcastNodeAdd(node: unknown): void {
    this.send({ type: "node:add", node });
  }

  broadcastNodeRemove(nodeId: string): void {
    this.send({ type: "node:remove", nodeId });
  }

  broadcastNodeUpdate(nodeId: string, data: unknown): void {
    this.send({ type: "node:update", nodeId, data });
  }

  broadcastEdgeAdd(edge: unknown): void {
    this.send({ type: "edge:add", edge });
  }

  broadcastEdgeRemove(edgeId: string): void {
    this.send({ type: "edge:remove", edgeId });
  }

  broadcastAiEditingStart(nodeIds: string[]): void {
    this.send({ type: "ai:editing:start", nodeIds });
  }

  broadcastAiEditingUpdate(nodeId: string, info: AiEditInfo): void {
    this.send({ type: "ai:editing:update", nodeId, info });
  }

  broadcastAiEditingEnd(): void {
    this.send({ type: "ai:editing:end" });
  }

  subscribe(handler: PresenceEventHandler): () => void {
    this.eventHandlers.add(handler);
    return () => this.eventHandlers.delete(handler);
  }

  subscribeToNodeDrags(handler: NodeDragHandler): () => void {
    this.nodeDragHandlers.add(handler);
    return () => this.nodeDragHandlers.delete(handler);
  }

  subscribeToWorkflowChanges(handler: WorkflowChangeHandler): () => void {
    this.workflowChangeHandlers.add(handler);
    return () => this.workflowChangeHandlers.delete(handler);
  }

  subscribeToAiEditing(handler: AiEditingHandler): () => void {
    this.aiEditingHandlers.add(handler);
    return () => this.aiEditingHandlers.delete(handler);
  }

  subscribeToExecutionEvents(handler: ExecutionEventHandler): () => void {
    this.executionEventHandlers.add(handler);
    // Replay buffered state to late subscribers
    if (this.lastExecutionState) {
      handler(this.lastExecutionState);
    }
    return () => this.executionEventHandlers.delete(handler);
  }

  /** Live agent presence for canvas and conversation busy UI. Each callback
   *  receives the complete current set; late subscribers get a replay. */
  subscribeToAgentPresence(handler: AgentPresenceHandler): () => void {
    this.agentPresenceHandlers.add(handler);
    handler(this.lastAgentPresence);
    return () => this.agentPresenceHandlers.delete(handler);
  }

  private emitAgentPresence(agents: AgentPresenceWire[]): void {
    this.lastAgentPresence = agents;
    this.agentPresenceHandlers.forEach(h => h(agents));
  }

  requestExecutionState(): void {
    this.send({ type: "get:execution_state" });
  }

  /** Send stop signal through the workflow relay to the executor. */
  sendStopExecution(executionId: string): void {
    this.send({ type: "execution:stop", executionId });
  }

  getCollaborators(): Collaborator[] {
    return Array.from(this.collaborators.values());
  }

  private send(data: object): void {
    if (this.ws?.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify(data));
    }
  }

  private handleMessage(incoming: ServerMessage | { type: string; [key: string]: unknown }): void {
    // Execution events from backend broadcast — inject into socketReceiver
    if (EXECUTION_EVENT_TYPES.has(incoming.type)) {
      const eventType = incoming.type as keyof ServerToClientEvents;
      // `injectEvent` preserves the event-name/payload correlation through its
      // generic API. This relay receives that pair over JSON, so validate the
      // name above and bridge the wire payload at this one boundary.
      socketReceiver.injectWireEvent(eventType, incoming);
      return;
    }

    // The remaining protocol is the discriminated workflow relay union. Keeping
    // the catch-all wire shape out of the switch lets TypeScript narrow each
    // case to its exact payload instead of degrading every field to `unknown`.
    const msg = incoming as ServerMessage;

    switch (msg.type) {
      case "auth:success":
        this.reconnectAttempts = 0;
        // Initialize collaborators from server and emit join events for each
        msg.collaborators.forEach(c => {
          const collaborator = this.toCollaborator(c);
          this.collaborators.set(c.id, collaborator);
          // Emit join event so React state gets updated
          this.emit({ type: "collaborator:join", collaboratorId: collaborator.id, data: collaborator });
        });
        // Auto-request execution state to recover any in-progress workflow
        this.requestExecutionState();
        break;

      case "auth:error":
        console.error('[WorkflowPresence] Auth failed:', msg.message);
        this.disconnect();
        break;

      case "collaborator:join": {
        const collaborator = this.toCollaborator(msg.collaborator);
        this.collaborators.set(collaborator.id, collaborator);
        this.emit({ type: "collaborator:join", collaboratorId: collaborator.id, data: collaborator });
        break;
      }

      case "collaborator:leave":
        this.collaborators.delete(msg.userId);
        this.emit({ type: "collaborator:leave", collaboratorId: msg.userId });
        break;

      case "presence:cursor": {
        const collab = this.collaborators.get(msg.userId);
        if (collab) {
          collab.cursor = { x: msg.x, y: msg.y };
          collab.lastActiveAt = Date.now();
          this.emit({ type: "collaborator:cursor:move", collaboratorId: msg.userId, data: { cursor: collab.cursor } });
        }
        break;
      }

      case "presence:cursor:clear": {
        const collab = this.collaborators.get(msg.userId);
        if (collab) {
          collab.cursor = null;
          this.emit({ type: "collaborator:cursor:move", collaboratorId: msg.userId, data: { cursor: null } });
        }
        break;
      }

      case "presence:selection": {
        const collab = this.collaborators.get(msg.userId);
        if (collab) {
          collab.selectedNodeIds = msg.nodeIds;
          collab.lastActiveAt = Date.now();
          this.emit({ type: "collaborator:selection:change", collaboratorId: msg.userId, data: { selectedNodeIds: msg.nodeIds } });
        }
        break;
      }

      case "node:drag":
        this.nodeDragHandlers.forEach(h => h({
          type: "collaborator:node:drag",
          collaboratorId: msg.userId,
          nodeId: msg.nodeId,
          position: msg.position,
        }));
        break;

      case "node:add":
        this.workflowChangeHandlers.forEach(h => h({
          type: "node:add",
          collaboratorId: msg.userId,
          data: msg.node,
        }));
        break;

      case "node:remove":
        this.workflowChangeHandlers.forEach(h => h({
          type: "node:remove",
          collaboratorId: msg.userId,
          data: msg.nodeId,
        }));
        break;

      case "node:update":
        this.workflowChangeHandlers.forEach(h => h({
          type: "node:update",
          collaboratorId: msg.userId,
          nodeId: msg.nodeId,
          data: msg.data,
        }));
        break;

      case "edge:add":
        this.workflowChangeHandlers.forEach(h => h({
          type: "edge:add",
          collaboratorId: msg.userId,
          data: msg.edge,
        }));
        break;

      case "edge:remove":
        this.workflowChangeHandlers.forEach(h => h({
          type: "edge:remove",
          collaboratorId: msg.userId,
          data: msg.edgeId,
        }));
        break;

      case "ai:editing:start":
        this.aiEditingHandlers.forEach(h => h({
          type: "ai:editing:start",
          collaboratorId: msg.userId,
          nodeIds: msg.nodeIds,
        }));
        break;

      case "ai:editing:update":
        this.aiEditingHandlers.forEach(h => h({
          type: "ai:editing:update",
          collaboratorId: msg.userId,
          nodeId: msg.nodeId,
          info: msg.info,
        }));
        break;

      case "ai:editing:end":
        this.aiEditingHandlers.forEach(h => h({
          type: "ai:editing:end",
          collaboratorId: msg.userId,
        }));
        break;

      case "execution_state": {
        const state = msg as ExecutionStateResponse;
        this.lastExecutionState = state;
        this.executionEventHandlers.forEach(h => h(state));
        // A reconnect snapshot restores a local process that remained live
        // while the browser's relay connection was unavailable.
        if (Array.isArray(state.agents)) this.emitAgentPresence(state.agents);
        break;
      }

      case "agent:presence": {
        this.emitAgentPresence((msg as { agents?: AgentPresenceWire[] }).agents || []);
        break;
      }
    }
  }

  private toCollaborator(server: ServerCollaborator): Collaborator {
    return {
      id: server.id,
      name: server.name,
      avatarUrl: server.avatarUrl,
      color: server.color,
      cursor: null,
      selectedNodeIds: [],
      isActive: true,
      lastActiveAt: Date.now(),
    };
  }

  private emit(event: PresenceEvent): void {
    this.eventHandlers.forEach(h => h(event));
  }

  private scheduleReconnect(): void {
    if (this.reconnectAttempts >= this.maxReconnectAttempts) {
      console.error('[WorkflowPresence] Max reconnect attempts reached');
      return;
    }

    const delay = Math.min(1000 * Math.pow(2, this.reconnectAttempts), 30000);
    this.reconnectAttempts++;

    this.reconnectTimer = window.setTimeout(() => {
      if (this.config) {
        console.log('[WorkflowPresence] Reconnecting...');
        this.connect(this.config as PresenceServiceConfig & { token: string });
      }
    }, delay);
  }
}

// Per-workflow instances. Each instance owns one WebSocket connection
// to <relay>/workflow/:workflowId. Holding instances per
// workflow id (instead of a single switch-on-connect singleton) lets
// the originating FE keep a presence connection alive on a workflow
// while its canvas is unmounted — required for agentic mutations to
// reach the workflow relay and for remote edits to flow back into
// the background graph store.
const presenceInstances: Map<string, WorkflowPresenceService> = new Map();

export function getWorkflowPresenceService(workflowId: string): WorkflowPresenceService {
  let instance = presenceInstances.get(workflowId);
  if (!instance) {
    instance = new WorkflowPresenceService();
    presenceInstances.set(workflowId, instance);
  }
  return instance;
}

/** Tear down a per-workflow instance. Called by the connection manager
 *  when neither the canvas nor any active gen needs this workflow's
 *  presence connection any more. */
export function disposeWorkflowPresenceService(workflowId: string): void {
  const instance = presenceInstances.get(workflowId);
  if (!instance) return;
  instance.disconnect();
  presenceInstances.delete(workflowId);
}

/** Read-only view of currently-instantiated services (for the manager). */
export function getActivePresenceWorkflowIds(): string[] {
  return Array.from(presenceInstances.keys());
}
