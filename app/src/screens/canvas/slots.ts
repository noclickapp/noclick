// The canvas's slots (src/slots.ts): the places on a workflow's canvas a host may fill, each with what stands there
// when none does (slotStandards.tsx). Connecting the account a step or an agent needs is the shared `connect.app` and
// `connect.model` (src/ui/slots.ts); these are the canvas's parts only a host has: the builder chat beside it, other
// people editing it live, the Interface tab, an agent's chat there, and sharing the workflow with people; what a step's
// settings form (`form/`) reads from whoever renders it, its accounts' among them (standards in accountStandards.tsx);
// what drawing its steps and connections reads (`nodes/`, `edges/`, standards in drawingStandards.tsx); and how the
// graph is saved and read again beyond /v1 (`graph/`, standard in graph/saves.ts). A host fills them before the canvas
// first draws (some hold hooks the canvas and the form call).
import type { ComponentType, ReactElement, ReactNode, RefAttributes } from 'react';
import type { CredentialRequirement, StepSettings } from '@/lib/accountWays';
import type { AccountCredential } from '@/screens/connections/model';
import { slot } from '@/slots';
import type { ChatAttachment } from '@/ui/chat/useChatFiles';
import type { AgentWiring } from './agentWiring';
import type { NodeDisplayStrategy } from './form/referenceTypes';
import type { StepReads } from './form/reads';
import type { WidgetRenderProps } from './form/schemaWidgetRegistry';
import { V1_GRAPH_SAVES, type GraphSaves } from './graph/saves';
import type { NodeDefinition, NodeDimensions } from './nodes/types';
import type { AiEditInfo, Collaborator, Presence, PresenceOptions } from './presence';
import { useV1AccountWays, useV1Accounts, useV1SaveAccount } from './accountStandards';
import { catalogOutline, NoteAsReadme, plainDrawingOf, useV1StepRoles } from './drawingStandards';
import {
    AgentChatOnNoClick,
    BuildWithNoClick,
    InterfaceOnNoClick,
    NOBODY_ELSE,
    noclickStepLink,
    ShareOnNoClick,
    standardDisplayStrategy,
    useNoTrack,
    useV1ConnectionMissing,
    useV1StepReads,
    useV1StepSchema,
    useV1WorkflowId,
} from './slotStandards';

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

// ── a step's settings form ──────────────────────────────────────────────────

/** A step type's settings schema as read: the JSON Schema the form draws from (null for a type that takes no settings),
 *  still on its way, or why it couldn't be read. */
export type StepSchemaRead = { status: 'loading' } | { status: 'ready'; schema: Record<string, any> | null } | { status: 'failed'; message: string };

export interface StepSchemas {
    /** The type's schema, drawing again when it lands. */
    useStepSchema: (type: string) => StepSchemaRead;
}

/** Where a step type's settings schema comes from. The standard reads `GET /v1/step_types/{type}` once a session (per
 *  client), so the form works against any NoClick; NoClick's app hands the schemas it was built with. */
export const STEP_SCHEMAS = slot<StepSchemas>('canvas.step.schemas', { useStepSchema: useV1StepSchema });

export interface StepReadsHost {
    /** What the form's fields read beside the step's settings, for the step around them (`StepContext`). */
    useStepReads: () => StepReads;
    /** The workflow the step is in, for a field drawn outside a step's form too. */
    useWorkflowId: () => string | undefined;
}

/** A step's reads. The standard answers them on /v1 for the step the form is for: `POST
 *  /v1/workflows/{id}/steps/{step}/options` and `/values`, `/expression` and `/clear_state`; it judges settings only when
 *  they're saved. */
export const STEP_READS = slot<StepReadsHost>('canvas.step.reads', { useStepReads: useV1StepReads, useWorkflowId: useV1WorkflowId });

/** A step type's glyph, as the operation picker heads its list with it. */
export interface StepMark {
    Icon: ComponentType<Record<string, unknown>>;
    iconColor?: string;
}

export interface StepMarks {
    /** How references into a step type's output are offered and checked. */
    displayStrategy: (type: string | undefined) => NodeDisplayStrategy;
    /** The type's glyph; undefined where there's none. */
    mark: (type: string) => StepMark | undefined;
}

/** What integrations' own definitions say of their steps: where references into their output are and their glyph.
 *  The standard offers every field of a step's output as a reference and draws no glyph. */
export const STEP_MARKS = slot<StepMarks>('canvas.step.marks', { displayStrategy: standardDisplayStrategy, mark: () => undefined });

/** Whether a step still needs an account connected before it runs: by its type, the accounts it holds, its operation
 *  and its settings. */
export type ConnectionMissing = (type: string, credentialIds: Record<string, string>, step: { operation?: string; config: Record<string, any> }) => boolean;

/** Whether a step still needs an account. The standard reads the step type's `connection` and its operation's
 *  `needs_account` (from `GET /v1/step_types/{type}`). */
export const STEP_CONNECTION = slot<{ useConnectionMissing: ConnectionMissing }>('canvas.step.connection', { useConnectionMissing: useV1ConnectionMissing });

/** Where the form tells what a person did with it (an AI fill asked for, a field error shown). */
export type Track = (event: string, properties?: Record<string, unknown>) => void;

/** The form's analytics. The standard tells no one. */
export const STEP_TRACK = slot<() => Track>('canvas.step.track', useNoTrack);

/** A link to one of a step's fields, as "Copy link to field" copies it. The standard links to the step on NoClick's
 *  canvas; null offers no link. */
export const STEP_LINK = slot<((workflowId: string, nodeId: string, fieldKey?: string) => string) | null>('canvas.step.link', noclickStepLink);

export type WidgetRenderer = (props: WidgetRenderProps) => ReactElement | null;

/** A host's own widgets by `ui:widget` name, ahead of the form's (where it has some the form hasn't, or draws one its
 *  own way). The standard adds none: a field whose widget isn't known draws by its type. */
export const STEP_WIDGETS = slot<Readonly<Record<string, WidgetRenderer>>>('canvas.step.widgets', {});

/** What a step type's own panel is handed: the step's settings, its operation and accounts, and how to change a setting. */
export interface StepPanelProps {
    config: Record<string, any>;
    operation: string | undefined;
    credentialIds: Record<string, string>;
    onChange: (key: string, value: any) => void;
}

/** A step type's own panel above its fields, in place of the fields it lists. */
export interface StepPanel {
    /** Whether it shows for the step's operation. */
    shows: (operation: string | undefined) => boolean;
    /** The settings it edits, which the form then leaves out. */
    fields: ReadonlySet<string>;
    Panel: ComponentType<StepPanelProps>;
}

/** Step types' own panels, by type. The standard has none: their settings draw as fields. */
export const STEP_PANELS = slot<Readonly<Record<string, StepPanel>>>('canvas.step.panels', {});

// ── a step's accounts ────────────────────────────────────────────────────────

/** The ways a step's accounts are connected, as read: still on their way, why they couldn't be read, or each way in (a
 *  credential type the step takes, a sign-in first), with the app they're of. */
export type AccountWaysRead =
    | { status: 'loading' }
    | { status: 'failed'; message: string }
    | {
          status: 'ready';
          ways: CredentialRequirement[];
          /** The app, as people name it ("Notion"). */
          app: string;
          /** Its name among the integrations the API lists, where its accounts connect there; null where none do. */
          integration: string | null;
          /** The model provider whose AI account the ways are (an agent's), connected through `connect.model`; null
           *  for an app's. */
          model: string | null;
          /** Whether the step runs with no account, on NoClick's own key, billed by use. */
          optional: boolean;
      };

/** An account a step can be given, as a list of them reads it. */
export interface StepAccount extends AccountCredential {
    /** Over the plan's cap on accounts of its kind: listed by the host, never offered. */
    over_cap?: boolean;
    /** Whether it's yours, where a read of a workflow's accounts says so instead of `access_type`. */
    owned_by_me?: boolean;
    /** Whose it is, where it's another person's and runs this workflow as its owner's. */
    owner_name?: string | null;
}

export interface StepAccountList {
    /** Every account the person can give a step, those shared with them too; empty while `loading`. */
    accounts: StepAccount[];
    loading: boolean;
    /** Why they couldn't be read, where they couldn't. */
    error: string | null;
    reload: () => Promise<void>;
    /** Whether every account a step can hold is listed under the id the step keeps for it, so one that isn't listed is
     *  gone or isn't the person's to use. */
    namesEvery: boolean;
}

/** What a step type's own account form is handed (where choosing its account depends on more than its type). */
export interface StepAccountFormProps {
    /** The step's operation and settings (`config` holds them nested). */
    nodeData: { operation?: string; config?: Record<string, unknown> };
    /** Its accounts: credential type → the account's id. */
    credentialIds: Record<string, string>;
    onCredentialIdsChange: (credentialIds: Record<string, string>) => void;
    /** A compact host (a question someone was asked): picking and connecting only. */
    compact?: boolean;
    /** Hears an account just connected here, never one picked from the list. */
    onConnected?: (credentialId: string) => void;
}

export interface StepAccountsHost {
    /** How a step type's accounts are connected, for the step's operation and settings. */
    useWays: (type: string, step: StepSettings) => AccountWaysRead;
    /** The accounts the person can give a step. */
    useAccounts: () => StepAccountList;
    /** Saves a step's account of a kind as it's chosen (null takes it off), for the step the form is for; null where
     *  whoever renders the form saves a step's accounts from what it's told. */
    useSave: () => ((credentialType: string, credentialId: string | null) => Promise<void>) | null;
    /** Deletes one of the person's own accounts, answering why it couldn't (null once it's gone); null offers no
     *  Delete. */
    useRemove: () => ((credentialId: string) => Promise<string | null>) | null;
    /** Choosing who else may use one of the person's own accounts; null offers no Share. */
    Share: ComponentType<{ account: { id: string; name: string } | null; onClose: () => void }> | null;
    /** Step types' own account forms, by type, in place of the pickers. */
    forms: Readonly<Record<string, ComponentType<StepAccountFormProps>>>;
}

/** A step's accounts: the pickers' ways in, the accounts they list, saving a choice and what else can be done with an
 *  account. The standard reads the step type's schema and the account's connections on /v1 and saves a choice as the
 *  step's `set_connection` edit; it shares and deletes nothing (Connections does), and has no form of a type's own.
 *  Connecting one goes through `connect.app` (an app's) and `connect.model` (an AI account), the only ways to. */
export const STEP_ACCOUNTS = slot<StepAccountsHost>('canvas.step.accounts', {
    useWays: useV1AccountWays,
    useAccounts: useV1Accounts,
    useSave: useV1SaveAccount,
    useRemove: () => null,
    Share: null,
    forms: {},
});

// ── drawing the steps and connections ───────────────────────────────────────

/** What a step is in a workflow, by its type, as the drawing reads it. */
export interface StepRoles {
    /** Whether a step of the type, with its operation, starts runs: it takes nothing in, and wears the trigger's bolt. */
    trigger: (type: string | null | undefined, operation: string | null | undefined) => boolean;
    /** Whether an agent can use a step of the type as its tools: it has a handle on top to wire it into one. */
    tool: (type: string | null | undefined) => boolean;
    /** The type an older one became (a step saved before two types merged), or the type itself. */
    canonical: (type: string) => string;
}

/** What steps are by their type, as their nodes, connections and hints are drawn: a trigger's bolt and missing input, a
 *  tool's handle on top, an older type drawn as the one it became. The standard knows a type once `GET
 *  /v1/step_types/{type}` has read it (the step form's read, once a session per client), drawing again as each lands;
 *  NoClick's app knows every type from the catalog it was built with. */
export const STEP_ROLES = slot<{ useRoles: () => StepRoles }>('canvas.step.roles', { useRoles: useV1StepRoles });

/** A build working on a step: what it's doing, and whose it is where it's another person's. */
export interface StepEdit {
    info?: AiEditInfo;
    /** The person whose build it is; undefined for this canvas's own. */
    by?: string;
}

/** Which steps a build is working on right now, asked by each step's card every tenth of a second to open while it
 *  lands. The standard knows of none: a build the canvas follows marks the steps it adds and configures in their data
 *  (`mcpAnimationState`), which opens their cards all the same; NoClick's app also knows its own builder's edits and
 *  those other people's builders are making. */
export const STEP_EDITING = slot<{ editing: (nodeId: string) => StepEdit | null }>('canvas.step.editing', { editing: () => null });

/** What a step type draws as before its node loads: its size and glyph. */
export interface StepOutline {
    dimensions?: NodeDimensions;
    /** The glyph's markup, as a catalog serializes it. */
    iconHtml?: string;
    iconColor?: string;
}

export interface StepDrawing {
    /** The types the canvas draws (React Flow's node types), older ones included; null for any type, each drawn as the
     *  canvas meets it. */
    types: readonly string[] | null;
    /** Loads the nodes of `types`, drawing again as they land; true once all have. */
    useLoaded: (types: Iterable<string | null | undefined>) => boolean;
    /** A type's node once loaded (an older type's, the node of the one it became). */
    definition: (type: string) => NodeDefinition | undefined;
    /** What a type draws as until its node loads. */
    outline: (type: string) => StepOutline | undefined;
}

/** How each step type is drawn on the canvas (nodes/lazyNodeTypes.tsx wraps each in its label, pills and hints). The
 *  standard draws a sticky note as a note and any other step as a plain step (nodes/PlainStep.tsx): its card with the
 *  glyph of the catalog the host loaded, if any, and a handle for each connection it holds. NoClick's app draws each
 *  integration's own node, loaded as its first step is drawn. */
export const STEP_DRAWING = slot<StepDrawing>('canvas.step.drawing', {
    types: null,
    useLoaded: () => true,
    definition: plainDrawingOf,
    outline: catalogOutline,
});

/** A sticky note's text, drawn from its Markdown. The standard draws it as a code repository's README is; NoClick's
 *  app as its chat draws a reply. */
export const NOTE_MARKDOWN = slot<ComponentType<{ content: string; className?: string }>>('canvas.note.markdown', NoteAsReadme);

// ── the graph's saves ───────────────────────────────────────────────────────

/** How the canvas's graph is saved and read again (graph/saves.ts), asked by the graph store outside any component:
 *  which way each workflow's record saves, a host's own whole-graph save, the graph read again and whether saves wait
 *  for another writer. The standard saves every record as the edits that changed it (`POST
 *  /v1/workflows/{id}/edits`), reads `GET /v1/workflows/{id}/graph` and never waits. */
export const GRAPH_SAVES = slot<GraphSaves>('canvas.graph.saves', V1_GRAPH_SAVES);
