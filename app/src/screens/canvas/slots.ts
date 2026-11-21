// The canvas's slots (src/slots.ts): the places on a workflow's canvas a host may fill, each with what stands there
// when none does (slotStandards.tsx). Connecting the account a step or an agent needs is the shared `connect.app` and
// `connect.model` (src/ui/slots.ts); these are the canvas's parts only a host has: the builder chat beside it, other
// people editing it live, the Interface tab, an agent's chat there, and sharing the workflow with people.
import type { ComponentType, ReactNode, RefAttributes } from 'react';
import { slot } from '@/slots';
import type { ChatAttachment } from '@/ui/chat/useChatFiles';
import type { AgentWiring } from './agentWiring';
import type { Collaborator, Presence, PresenceOptions } from './presence';
import { AgentChatOnNoClick, BuildWithNoClick, InterfaceOnNoClick, NOBODY_ELSE, ShareOnNoClick } from './slotStandards';

// ── the builder chat ────────────────────────────────────────────────────────

export interface CanvasBuilderProps {
    /** The workflow open on the canvas, which it builds; null while none is. */
    workflowId: string | null;
    /** Whether it's open: on a laptop, beside the canvas; on a phone the frame shows it over the canvas while it is. */
    open: boolean;
    onOpenChange: (open: boolean) => void;
    /** Drawn as on a phone: it fills the sheet the frame holds it in. */
    phone: boolean;
    /** Laptop: its left edge, right of the app's sidebar. */
    offsetLeft?: number;
    /** Laptop: its width as it changes, which the frame lays the page beside. */
    onWidthChange?: (width: number) => void;
    /** Laptop: true while its edge is dragged, when the frame stops easing. */
    onDragChange?: (dragging: boolean) => void;
    /** Opened or closed by keyboard: no easing. */
    noAnimation?: boolean;
}

/** Beside the canvas (over it on a phone): building the workflow by asking for it. The standard starts a build with
 *  NoClick's builder (`Workflow.build`) and shows how it goes, a question it asks answered on its page on NoClick. */
export const BUILDER = slot<ComponentType<CanvasBuilderProps>>('canvas.builder', BuildWithNoClick);

// ── other people on the canvas ──────────────────────────────────────────────

export interface CanvasPresence {
    /** Who else has the workflow open, and how this person's moves reach them: called once by the canvas. */
    usePresence: (options: PresenceOptions) => Presence;
    /** Around the canvas's steps, so each can show who else has it selected. */
    Layer: ComponentType<{ collaborators: Collaborator[]; nodeSelections: Map<string, Collaborator[]>; children: ReactNode }>;
    /** Over the steps, inside the canvas's viewport: the others' pointers. */
    Cursors: ComponentType<{ collaborators: Collaborator[] }>;
    /** In the canvas's top bar on a laptop: who else has it open. */
    Avatars: ComponentType<{ collaborators: Collaborator[] }>;
}

/** Other people editing the workflow as it's edited: their pointers, selections and unsaved moves. The standard draws
 *  nobody else (another person's changes reach the canvas once they're saved). */
export const PRESENCE = slot<CanvasPresence>('canvas.presence', NOBODY_ELSE);

// ── the Interface tab ───────────────────────────────────────────────────────

/** A block's settings: its step's config. */
export interface BlockConfig {
    label?: string;
    placeholder?: string;
    [key: string]: unknown;
}

/** One block's place on the Interface tab's grid, in grid units. */
export interface InterfaceGridItem {
    /** The block's id: its step's. */
    i: string;
    x: number;
    y: number;
    w: number;
    h: number;
    minW?: number;
    minH?: number;
    maxW?: number;
    maxH?: number;
    static?: boolean;
    isDraggable?: boolean;
    isResizable?: boolean;
    isBounded?: boolean;
    moved?: boolean;
}

/** The Interface tab's grid as the canvas keeps it while the tab isn't drawn. */
export interface InterfaceGridState {
    layout: readonly InterfaceGridItem[];
    /** The sub-tabs in order: 'grid' for the grid, a block's id for one drawn whole. */
    tabOrder?: string[];
}

/** What the canvas asks of the Interface tab while it's drawn. */
export interface InterfaceHandle {
    /** Places a block that was just added on the canvas. */
    addBlock: (blockId: string, blockType: string) => void;
    removeBlock: (blockId: string) => void;
    /** Takes a whole grid (one the builder laid out). */
    setFullState: (state: InterfaceGridState) => void;
    /** Opens a sub-tab: 'grid', or a block's id (an agent step's Chat opens its chat). */
    setActiveSubTab: (subTabId: string) => void;
}

/** A message sent from an agent's chat: the agent step, the words, the model, the conversation it goes into (passed
 *  because the send may be starting it, so reading it back from the step would race the write), and the files with
 *  it, already uploaded. */
export type AgentChatSend = (nodeId: string, message: string, model: string, conversationKey?: string, attachments?: ChatAttachment[]) => void;

/** A step wired to an agent, as the agent's chat reads it while setting it up: its data, settings and accounts. */
export interface WiredNodeData {
    nodeData: Record<string, unknown>;
    config: Record<string, unknown>;
    credentialIds: Record<string, string>;
}

/** Changing the steps wired to an agent (its triggers and tools), not the agent's own step. */
interface WiredNodeEdits {
    /** Patches a wired step's settings (a tool's allowlist). */
    onWiredNodeConfigPatch?: (nodeId: string, config: Record<string, unknown>) => void;
    onWiredNodeCredentialsChange?: (nodeId: string, credentialIds: Record<string, string>) => void;
    /** A wired step as it is now: read again each time it's drawn. */
    getWiredNodeData?: (nodeId: string) => WiredNodeData | null;
}

export interface CanvasInterfaceProps extends WiredNodeEdits {
    /** A block placed on the grid, for the canvas to add its step. */
    onBlockAdded?: (blockId: string, nodeType: string) => void;
    onBlockRemoved?: (blockId: string) => void;
    /** The blocks to draw first: the canvas's interface steps. */
    initialBlocks?: { id: string; blockType: string; nodeData?: Record<string, unknown> }[];
    /** The grid as it was last drawn, kept by the canvas across tab switches. */
    savedState?: InterfaceGridState | null;
    onStateChange?: (state: InterfaceGridState) => void;
    /** A block's settings changed, for the canvas to write them on its step. */
    onBlockConfigChanged?: (blockId: string, config: BlockConfig) => void;
    /** A form block submitted: the canvas runs the workflow with the values. */
    onFormSubmit?: (blockId: string, values: Record<string, unknown>) => void;
    /** Blocks waiting on a run that's under way. */
    loadingBlockIds?: Set<string>;
    /** The sub-tab open now: 'grid' or a block's id. */
    onActiveSubTabChange?: (subTabId: string) => void;
    /** Nothing moves, is removed or is renamed; a block's own actions call `onReadOnlyInteraction`. */
    isReadOnly?: boolean;
    onReadOnlyInteraction?: () => void;
    workflowId?: string;
    onAgentChatSend?: AgentChatSend;
    /** An agent's chat changed the accounts its step holds (its model's key or sign-in). */
    onAgentCredentialIdsChange?: (nodeId: string, credentialIds: Record<string, string>) => void;
    /** Each shown agent's triggers and tools, worked out by the canvas from its steps. */
    agentWiring?: Record<string, AgentWiring>;
    /** Wires a new trigger or tool step to an agent; answers the new step's id. */
    onAgentWiringAdd?: (agentNodeId: string, nodeType: string, role: 'trigger' | 'tool', operation?: string) => string | void;
    /** Unwires a trigger or tool (its connection, and the step too when nothing else holds it). */
    onAgentWiringRemove?: (edgeId: string, nodeId: string) => void;
}

/** The canvas's Interface tab: the workflow's forms, tables and chats laid out as a page, and publishing it. The
 *  standard says it's laid out and published on NoClick, and opens the workflow there. */
export const INTERFACE = slot<ComponentType<CanvasInterfaceProps & RefAttributes<InterfaceHandle>>>('canvas.interface', InterfaceOnNoClick);

// ── an agent's chat ─────────────────────────────────────────────────────────

/** What a block on the Interface tab is drawn with: its step and settings, its latest output, and the canvas's ways to
 *  change the step and what's wired to it. */
export interface CanvasBlockProps extends WiredNodeEdits {
    /** Its step's id. */
    id: string;
    config: BlockConfig;
    isSelected: boolean;
    onConfigChange: (config: BlockConfig) => void;
    /** Its step's output from the latest run. */
    output?: Record<string, unknown> | null;
    /** Nothing it does changes the workflow or runs it; acting calls `onInteraction` instead. */
    isReadOnly?: boolean;
    onInteraction?: () => void;
    workflowId?: string;
    onAgentChatSend?: AgentChatSend;
    /** The accounts its step holds, credential type to id. */
    credentialIds?: Record<string, string>;
    onCredentialIdsChange?: (credentialIds: Record<string, string>) => void;
    /** Its agent's triggers and tools. */
    agentWiring?: AgentWiring;
    /** Wires a new trigger or tool step to its agent; answers the new step's id. */
    onAgentWiringAdd?: (nodeType: string, role: 'trigger' | 'tool', operation?: string) => string | void;
    onAgentWiringRemove?: (edgeId: string, nodeId: string) => void;
}

/** An agent step's chat, a block of the Interface tab: talking to the agent in the workflow, and setting up its model,
 *  triggers and tools. The standard says the agent is talked to on NoClick, and opens the workflow there. */
export const AGENT_CHAT = slot<ComponentType<CanvasBlockProps>>('canvas.agentChat', AgentChatOnNoClick);

// ── sharing ─────────────────────────────────────────────────────────────────

export interface CanvasShareProps {
    open: boolean;
    onOpenChange: (open: boolean) => void;
    /** The workflow shared; null before it's read. */
    workflow: { id: string; name: string } | null;
}

/** Sharing the workflow with people and the workspace, opened from the canvas's top bar. The standard says who else may
 *  open it is chosen on NoClick, and opens the workflow there. */
export const SHARE = slot<ComponentType<CanvasShareProps>>('canvas.share', ShareOnNoClick);
