/**
 * Types for collaborative presence features.
 * These types define the shape of user presence data including cursors, selections, and identity.
 * Designed to be backend-agnostic so we can swap mock data with real WebSocket/YJS presence later.
 */

/** Represents a collaborator's cursor position in flow canvas coordinates */
export interface CollaboratorCursor {
  x: number;
  y: number;
}

/** Core collaborator identity and state */
export interface Collaborator {
  id: string;
  name: string;
  email?: string;
  avatarUrl?: string;
  color: string; // Hex color assigned for cursor/selection highlighting
  cursor: CollaboratorCursor | null; // null when cursor is outside canvas
  selectedNodeIds: string[]; // IDs of nodes this user has selected
  isActive: boolean; // false when user is idle/away
  lastActiveAt: number; // timestamp for activity tracking
}

/** Presence state for the entire workflow session */
export interface CollaborativePresenceState {
  collaborators: Map<string, Collaborator>;
  localUserId: string | null;
}

/** Events that the presence service can emit */
export type PresenceEventType =
  | 'collaborator:join'
  | 'collaborator:leave'
  | 'collaborator:cursor:move'
  | 'collaborator:selection:change'
  | 'collaborator:activity:change'
  | 'collaborator:node:drag';

export interface PresenceEvent {
  type: PresenceEventType;
  collaboratorId: string;
  data?: Partial<Collaborator>;
}

/** Event data for node drag operations */
export interface NodeDragEvent {
  type: 'collaborator:node:drag';
  collaboratorId: string;
  nodeId: string;
  position: { x: number; y: number };
}

/** Configuration for the presence service */
export interface PresenceServiceConfig {
  workflowId: string;
  localUser: {
    id: string;
    name: string;
    email?: string;
    avatarUrl?: string;
  };
}

/**
 * Predefined color palette for collaborator assignment.
 * These colors are chosen to be visually distinct and work well on dark backgrounds.
 */
export const COLLABORATOR_COLORS = [
  '#F87171', // red-400
  '#FB923C', // orange-400
  '#FBBF24', // amber-400
  '#A3E635', // lime-400
  '#34D399', // emerald-400
  '#22D3EE', // cyan-400
  '#60A5FA', // blue-400
  '#A78BFA', // violet-400
  '#F472B6', // pink-400
  '#E879F9', // fuchsia-400
] as const;

/** Helper to get a deterministic color from user ID */
export function getCollaboratorColor(userId: string): string {
  // Simple hash to get consistent color per user
  let hash = 0;
  for (let i = 0; i < userId.length; i++) {
    hash = ((hash << 5) - hash) + userId.charCodeAt(i);
    hash = hash & hash;
  }
  return COLLABORATOR_COLORS[Math.abs(hash) % COLLABORATOR_COLORS.length];
}
