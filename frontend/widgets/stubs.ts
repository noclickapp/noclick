// Minimal stubs for app-specific modules that the node component tree imports.
// These are only used in the standalone widget build — they provide safe defaults
// so components render in read-only mode without the full app runtime.

/* eslint-disable @typescript-eslint/no-explicit-any */

// ~/lib/perf-state
export const perfState = { shouldOptimize: false };

// ~/components/workflow/collaboration/CollaborativeContext
export function useCollaborativeNodeSelection(_nodeId: string): any[] {
    return [];
}
export function useCollaborativeNodeBorderColor(_nodeId: string): string | null {
    return null;
}
export function CollaborativeProvider({ children }: { children: any }) {
    return children;
}

// ~/components/workflow/collaboration barrel
export const CollaboratorAvatars = () => null;
export const CollaborativeCursors = () => null;
export const CollaboratorCursorNode = () => null;
export const CURSOR_NODE_PREFIX = '__cursor__';
export function isCursorNode() {
    return false;
}

// ~/lib/collaboration
export type Collaborator = {
    id: string;
    name: string;
    color: string;
};

// ~/components/workflow/WorkflowContext
export function useWorkflowId(): string | undefined {
    return undefined;
}
export function useWorkflowName(): string | undefined {
    return undefined;
}
export function WorkflowProvider({ children }: { children: any }) {
    return children;
}
export function setCurrentWorkflowId() {}
export function getCurrentWorkflowId() {
    return undefined;
}
export function setCurrentWorkflowName() {}
export function getCurrentWorkflowName() {
    return undefined;
}
export interface NodeEditInfo {
    action?: string;
    status?: string;
    operation?: string;
    config?: Record<string, any>;
}
export function setEditingNodeIds() {}
export function getEditingNodeIds() {
    return new Set<string>();
}
export function setIsAiEditing() {}
export function getIsAiEditing() {
    return false;
}
export function isNodeBeingEdited() {
    return false;
}
export function setNodeEditInfo() {}
export function updateNodeEditInfo() {}
export function getNodeEditInfo() {
    return undefined;
}
export function clearNodeEditInfo() {}
export function clearAllNodeEditInfo() {}
export function setRemoteAiEditing() {}
export function updateRemoteAiEditingInfo() {}
export function clearRemoteAiEditing() {}
export function getRemoteAiEditing() {
    return new Map();
}
export function isNodeBeingEditedByRemote() {
    return null;
}
export function isAnyRemoteAiEditing() {
    return false;
}
export function setPendingNodeSelection() {}
export function getPendingNodeSelection() {
    return null;
}
export function clearPendingNodeSelection() {}
export function consumePendingNodeSelection() {
    return null;
}

// ~/hooks/useModels
export function useModels() {
    return { models: [], isLoading: false };
}

// ~/hooks/useOpenRouterModels, ~/hooks/useLiteLLMModels
export function useOpenRouterModels() {
    return { models: [], isLoading: false };
}
export function useLiteLLMModels() {
    return { models: [], isLoading: false };
}

// ~/hooks/useDrawer
export function useDrawer() {
    return { isOpen: false, open: () => {}, close: () => {}, toggle: () => {} };
}

// ~/hooks/useAPIKeys
export function useAPIKeys() {
    return { keys: [], isLoading: false };
}

// ~/hooks/useCachedValtioState
export function useCachedValtioState(_key: string, defaultValue: any = null) {
    return [defaultValue, () => {}, { isLoaded: true }];
}

// ~/hooks/useValtioState
export function useValtioState(_key: string, defaultValue: any = null) {
    return [defaultValue, () => {}];
}

// ~/hooks/useResourceUpload, ~/hooks/useMediaResource
export function useResourceUpload() {
    return { upload: async () => '', isUploading: false };
}
export function useMediaResource() {
    return { url: null, isLoading: false };
}

// ~/components/chat/ModelDropdown
export function ModelDropdown() {
    return null;
}
export function bumpedIconScale(_provider: string | undefined, base: number): number {
    return base;
}

// ~/components/chat/MarkdownRenderer — lightweight stub that renders basic markdown as HTML
import { createElement } from 'react';
export function MarkdownRenderer({ content, className }: { content: string; className?: string; variant?: string }) {
    // Convert basic markdown (headings, bold, italic, code, lists) to HTML
    const html = content
        .replace(/^### (.+)$/gm, '<h3>$1</h3>')
        .replace(/^## (.+)$/gm, '<h2>$1</h2>')
        .replace(/^# (.+)$/gm, '<h1>$1</h1>')
        .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
        .replace(/\*(.+?)\*/g, '<em>$1</em>')
        .replace(/`(.+?)`/g, '<code style="background:rgba(255,255,255,0.1);padding:1px 4px;border-radius:3px">$1</code>')
        .replace(/^- (.+)$/gm, '<li style="margin-left:16px;list-style:disc">$1</li>')
        .replace(/\n\n/g, '<br/><br/>')
        .replace(/\n/g, '<br/>');
    return createElement('div', {
        className: `prose prose-invert prose-sm max-w-none text-zinc-300 ${className || ''}`,
        dangerouslySetInnerHTML: { __html: html },
    });
}

// ~/components/workflow/IODataDisplay
export function IODataDisplay() {
    return null;
}

// ~/lib/socket-sender
export function sendEvent() { return false; }
export function sendEventWithCallback() { return false; }
export async function sendEventAsync() { return null; }
export const YjsSyncRequest = { create: () => ({}) };

// ~/lib/socket, ~/lib/socketClient
export const socket = null;
export function getSocket() {
    return null;
}
export function connectSocket() {}
export function disconnectSocket() {}
