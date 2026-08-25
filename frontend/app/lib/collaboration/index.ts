/**
 * Collaboration module exports.
 * Provides presence tracking, cursor sharing, and selection highlighting for collaborative editing.
 *
 * Two implementations:
 * - MockPresenceService: For local development/testing with simulated users
 * - WorkflowPresenceService: Real-time via the configured workflow relay
 *
 * Use getPresenceService() for mock (development) or getWorkflowPresenceService() for real (production).
 */

export * from './types';
export * from './mockPresenceService';
export * from './workflowPresenceService';
export * from './documentStateManager';

// Environment flag to enable real collaboration (set via build config or feature flag)
export const ENABLE_REAL_COLLABORATION = true;
