// ForkCanvas — xyflow-free workflow canvas with the same API surface as ReactFlow.
// Built because xyflow's first-paint flow forces every node to mount-for-measurement
// before culling kicks in, which OOMs WebContent on iPhone for wide-spread workflows
// (see docs/mobile/canvas-tile-cache.md). Now general-purpose: works as a drop-in for the
// editor canvas too, supports live AI builder updates, drag-to-edit, imperative
// viewport control.
//
// Scope: pan + pinch-zoom + node drag + node rendering + SVG edges + plus-grid
// background. Renders sticky notes with full markdown, generic nodes via the registry's
// Icon, interface nodes via BlockRenderer (forms, iframes, markdown). Supports LOD
// swap so heavy nodes (markdown stickies, iframes) become cheap placeholders at zoom
// out — keeps memory bounded regardless of workflow extent on mobile.
//
// API mirrors ReactFlow: nodes/edges as props, onNodesChange/onEdgesChange callbacks
// fire xyflow-compatible NodeChange / EdgeChange events, imperative fitView/setViewport
// via ref. Reuses xyflow's applyNodeChanges so parent state-reducers work unchanged.

import {
    useEffect,
    useMemo,
    useRef,
    useState,
    useLayoutEffect,
    useImperativeHandle,
    forwardRef,
    memo,
    type ReactNode,
    type CSSProperties,
    type Ref,
} from 'react';
import type { Node, Edge, NodeChange, EdgeChange } from '@xyflow/react';
import {
    applyNodeChanges as xyApplyNodeChanges,
    applyEdgeChanges as xyApplyEdgeChanges,
} from '@xyflow/react';
import { MarkdownRenderer } from '~/components/chat/MarkdownRenderer';
import { BlockRenderer } from '~/components/interface/BlockRenderer';
import type { NodeDefinition } from '~/components/workflow/nodes/types';
import {
    CANVAS_GRID_CSS_BG,
    CANVAS_GRID_CSS_BG_LIGHT,
    CANVAS_GRID_GAP,
} from '~/components/workflow/canvasBackground';
import {
    useNodeEditingState,
    NodeEditOverlay,
    EDIT_EXPANDED_WIDTH,
    EDIT_EXPANDED_HEIGHT,
    EDIT_TRANSITION,
} from '~/components/workflow/nodes/base/nodeEditing';
import type { NodeEditInfo } from '~/components/workflow/WorkflowContext';
import { Zap, ChevronDown } from 'lucide-react';
// From the schema-free leaf: the fork canvas serves mobile + marketing
// previews, whose chunks must not pull the full ~9MB schema registry.
import { isTriggerSource } from '~/utils/nodeMeta';
import { AgentModelIcon } from '~/components/workflow/nodes/base/AgentModelIcon';
import { modelShortName } from '~/lib/modelFiltering';
import {
    getNodeHandleLayout,
    type NodeHandleLayout,
} from '~/components/workflow/nodes/base/nodeHandles';
import { DEFAULT_AGENT_MODEL } from '~/lib/agentChat';
import { stickyScheme } from '~/lib/stickyColors';
import { useIsDark } from '~/hooks/useIsDark';
import {
    NodeStatusBadge,
    type NodeStatusVariant,
} from '~/components/workflow/nodes/base/NodeStatusBadge';
import { RUN_RING } from '~/components/workflow/nodes/base/nodeRunStatus';
import {
    NodeStatusChip,
    shouldShowStatusChip,
} from '~/components/workflow/nodes/base/NodeStatusChip';
import {
    getBackwardEdgePath,
    BACKWARD_EDGE_X_THRESHOLD,
} from '~/utils/edgePaths';
import { InterfaceBlockHeader } from '~/components/workflow/nodes/interface/InterfaceBlockHeader';
import { InterfaceFormLinkButton } from '~/components/workflow/nodes/interface/InterfaceFormLinkButton';
import { getBlockDefinition } from '~/components/interface/blockRegistry';
import type { BlockConfig } from '~/components/interface/types';

// Re-export xyflow's reducers so callers don't need to import @xyflow/react themselves.
export const applyNodeChanges = xyApplyNodeChanges;
export const applyEdgeChanges = xyApplyEdgeChanges;
export type { Node, Edge, NodeChange, EdgeChange };

export interface ForkCanvasProps {
    /** Nodes to render. xyflow-shape; if your workflow data has config at the raw-API
     *  top level (node.config), pass it through createWorkflowNode() first. */
    nodes: Node[];
    edges: Edge[];
    /** Per-type NodeDefinition map — provides the desktop Icon + iconColor + dimensions
     *  so generic cards render with the exact branded Icon component. Missing entries
     *  fall back to a 2-letter glyph. */
    nodeDefs?: Record<string, NodeDefinition | null>;
    /** Fired during node drag with xyflow-compatible position changes. Wire up to your
     *  state with `setNodes(curr => applyNodeChanges(changes, curr))`. */
    onNodesChange?: (changes: NodeChange[]) => void;
    /** Fired when edges are selected/removed. */
    onEdgesChange?: (changes: EdgeChange[]) => void;
    /** Fired on tap/click of a node (without significant drag movement). */
    onNodeClick?: (event: MouseEvent | TouchEvent, node: Node) => void;
    /** If true, runs fitView once on the first non-empty nodes prop. Defaults true. */
    fitView?: boolean;
    /** Changing this value triggers another fitView. Useful when AI adds nodes and
     *  you want the camera to re-center on the new bounds. */
    fitViewSignal?: number | string;
    /** Initial viewport. Used only on the very first render; subsequent changes are
     *  ignored unless you call setViewport via ref. */
    defaultViewport?: { x: number; y: number; zoom: number };
    minZoom?: number;
    maxZoom?: number;
    /** When false, drag does nothing (canvas pans instead). Defaults true. */
    nodesDraggable?: boolean;
    /** When the AI builder is actively editing the workflow. Triggers a subtle
     *  background animation hint + lets cards show their per-node updating state. */
    isEditing?: boolean;
    /** Set of node ids the AI builder is currently editing. Each gets a pulsing
     *  ring + "Updating…" badge so the user can see the focus of attention. */
    editingNodeIds?: Set<string>;
    style?: CSSProperties;
    workflowId?: string;
    /** Extra absolute-positioned UI inside the canvas container (e.g. controls). */
    children?: ReactNode;
    /** Watch-only canvas: no pan/zoom gestures, and touches scroll the page.
     *  Marketing scenes script their own camera, and a canvas that swallows the
     *  gesture makes the section impossible to scroll past on a phone. */
    passiveViewport?: boolean;
}

/** Imperative API exposed via ref. */
export interface ForkCanvasRef {
    fitView: (options?: {
        padding?: number;
        minZoom?: number;
        maxZoom?: number;
        nodes?: { id: string }[];
        duration?: number;
    }) => void;
    setViewport: (v: { x: number; y: number; zoom: number }) => void;
    getViewport: () => { x: number; y: number; zoom: number };
}

/** Returns a flat config object combining everything a sub-component needs.
 *  Handles both supported node shapes:
 *    1. Canonical xyflow shape after createWorkflowNode: config fields sit at
 *       node.data.config, while metadata (content, color, operation, label, goal,
 *       etc.) is hoisted to node.data top-level. We merge them so sub-components
 *       see a single flat object — sticky reads content/color, interface reads
 *       operation alongside the rest of config (same as desktop InterfaceNode's
 *       blockConfig assembly).
 *    2. Raw API shape: node.config at the top level (no data wrapper). */
function getNodeConfig(n: Node): Record<string, unknown> {
    const data = (n.data || {}) as Record<string, unknown>;
    const nested = data.config;
    if (typeof nested === 'object' && nested !== null) {
        const { config: _omit, ...metadata } = data;
        return { ...(nested as Record<string, unknown>), ...metadata };
    }
    const raw = (n as unknown as { config?: Record<string, unknown> }).config;
    return raw && typeof raw === 'object' ? raw : {};
}

interface Transform {
    x: number;
    y: number;
    k: number;
}

function labelFromType(type: string): string {
    return type
        .replace(/^(automation-|interface-|trigger-)/, '')
        .replace(/-/g, ' ');
}

function glyphFromType(type: string): string {
    const stripped = type.replace(/^(automation-|interface-|trigger-)/, '');
    const parts = stripped.split('-').filter(Boolean);
    if (parts.length === 0) return '?';
    if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase();
    return (parts[0][0] + parts[1][0]).toUpperCase();
}

function getInterfaceBlockType(nodeType: string): string {
    return nodeType.replace(/^interface-/, '');
}

// Canvas background plus-grid — derived from the shared CanvasBackground source of
// truth (canvasBackground.tsx) so this custom canvas can't drift from the xyflow
// editor/showcase grid. Used as a tiled background-image that scales with zoom
// (backgroundSize is updated to PLUS_GRID_SIZE × transform.k in applyTransform).
const PLUS_GRID_BG = CANVAS_GRID_CSS_BG;
const PLUS_GRID_BG_LIGHT = CANVAS_GRID_CSS_BG_LIGHT;
const PLUS_GRID_SIZE = CANVAS_GRID_GAP;

// ── Gesture tuning constants ──────────────────────────────────────────────
// PINCH_POWER: power exponent applied to per-frame finger-distance ratios so the
// gesture compounds aggressively across its duration. 1 = linear (no amp), 4 felt
// overshoot-prone in testing, 2.5 is the comfortable middle.
const PINCH_POWER = 2.5;
// WHEEL_ZOOM_SENSITIVITY: deltaY multiplier inside exp(). 0.01 = 10× the typical
// default; one scroll tick produces a meaningful zoom change.
const WHEEL_ZOOM_SENSITIVITY = 0.01;
// DRAG_THRESHOLD_PX: pixels of cumulative movement (in canvas coords) before a
// touch / mouse interaction is treated as a drag rather than a tap.
const DRAG_THRESHOLD_PX = 2;
// MOBILE_MAX_DIM: caps a node's rendered width/height. Layer backing-store memory
// is width × height × DPR² × scale² × 4 bytes; without a cap, an outlier-authored
// 8000×3000 sticky would consume hundreds of MB on iPhone. Most authored sizes
// pass through unchanged; only the pathological outliers clamp.
const MOBILE_MAX_DIM = 5000;

// Extract a YouTube video ID from a URL (or any text containing one). Matches all
// the common URL shapes: youtube.com/watch?v=ID, youtu.be/ID, youtube.com/embed/ID.
function extractYouTubeId(text: string): string | null {
    const m = text.match(
        /(?:youtube\.com\/watch\?v=|youtu\.be\/|youtube\.com\/embed\/|youtube\.com\/v\/)([a-zA-Z0-9_-]{11})/
    );
    return m ? m[1] : null;
}

// Find the first image-ish thing in markdown content: an inline image (![alt](url)),
// or an HTML <img src="...">, or a YouTube link (which we render via its CDN
// thumbnail). Used by the sticky-note low-LOD placeholder so embeds don't disappear
// at fitView — keeps the visual identity of the sticky.
function extractStickyMedia(
    content: string
):
    | { kind: 'image'; src: string }
    | { kind: 'youtube'; videoId: string }
    | null {
    const imgMd = content.match(/!\[[^\]]*\]\(([^)\s]+)/);
    if (imgMd) return { kind: 'image', src: imgMd[1] };
    const imgHtml = content.match(/<img[^>]+src=["']([^"']+)["']/i);
    if (imgHtml) return { kind: 'image', src: imgHtml[1] };
    const yt = extractYouTubeId(content);
    if (yt) return { kind: 'youtube', videoId: yt };
    return null;
}

// Generic schematic preview for non-form interface blocks (html-react, image, video,
// audio, file, dataframe, chatbot, etc.). Header + a stylized "page content" area
// with horizontal lines suggesting content. Cheap, vector-only, scales perfectly.
function InterfaceGenericPreview({
    w,
    h,
    label,
    blockType,
}: {
    w: number;
    h: number;
    label: string;
    blockType: string;
}) {
    return (
        <div
            style={{
                width: w,
                height: h,
                borderRadius: 12,
                background: 'hsl(var(--card))',
                border: '1px solid hsl(var(--border))',
                color: 'hsl(var(--card-foreground))',
                display: 'flex',
                flexDirection: 'column',
                overflow: 'hidden',
                boxSizing: 'border-box',
                pointerEvents: 'none',
                fontFamily: 'system-ui, -apple-system, sans-serif',
            }}
        >
            <div
                style={{
                    padding: '12px 18px',
                    borderBottom: '1px solid hsl(var(--border))',
                    fontSize: 13,
                    fontWeight: 500,
                    color: 'hsl(var(--muted-foreground))',
                    textTransform: 'capitalize',
                    display: 'flex',
                    justifyContent: 'space-between',
                    alignItems: 'center',
                    flexShrink: 0,
                }}
            >
                <span>{label}</span>
                <span
                    style={{
                        fontSize: 11,
                        color: 'hsl(var(--muted-foreground) / 0.7)',
                    }}
                >
                    {blockType}
                </span>
            </div>
            <div
                style={{
                    padding: '16px 18px',
                    flex: 1,
                    minHeight: 0,
                    display: 'flex',
                    flexDirection: 'column',
                    gap: 8,
                    overflow: 'hidden',
                }}
            >
                {[1, 0.85, 0.95, 0.7, 0.9].map((widthPct, i) => (
                    <div
                        key={i}
                        style={{
                            height: 12,
                            width: `${widthPct * 100}%`,
                            borderRadius: 4,
                            background: 'hsl(var(--secondary))',
                        }}
                    />
                ))}
            </div>
        </div>
    );
}

// Visual-only handle dots, positioned per the node's handle layout — the same
// topology the desktop <Handle>s use (via the shared getNodeHandleLayout), so the
// agent's bottom (tool-provider) handle and a provider's top handle render here
// too. Match the desktop xyflow Handle look (gray circle, ~16px). Pure decoration —
// no event listeners, no store subscriptions; edges are computed from the node
// bounding box + the edge's handle ids independently. zIndex 100 keeps the dots
// above the card's icon/background no matter what stacking context the card creates.
function CardHandles({ layout }: { layout?: NodeHandleLayout }) {
    if (!layout) return null;
    const dot: React.CSSProperties = {
        position: 'absolute',
        width: 16,
        height: 16,
        borderRadius: '50%',
        background: 'rgb(161, 161, 170)', // zinc-400
        border: '2px solid rgb(113, 113, 122)', // zinc-500
        pointerEvents: 'none',
        zIndex: 100,
    };
    const vMid = { top: '50%', marginTop: -8 };
    const hMid = { left: '50%', marginLeft: -8 };
    return (
        <>
            {layout.input && <span style={{ ...dot, ...vMid, left: -8 }} />}
            {layout.output && <span style={{ ...dot, ...vMid, right: -8 }} />}
            {layout.provider && <span style={{ ...dot, ...hMid, top: -8 }} />}
            {layout.agentTarget && (
                <span style={{ ...dot, ...hMid, bottom: -8 }} />
            )}
        </>
    );
}

// Mirror of the desktop TriggerBoltBadge (base/TriggerBoltBadge.tsx): a bare
// amber bolt floating just left of the card where the input handle would be —
// triggers have no input. Inline-styled like the rest of ForkCanvas chrome.
function TriggerBolt() {
    return (
        <span
            style={{
                position: 'absolute',
                left: -22,
                top: '50%',
                marginTop: -8,
                pointerEvents: 'none',
                zIndex: 100,
                filter: 'drop-shadow(0 1px 3px rgba(0, 0, 0, 0.8))',
            }}
        >
            <Zap size={16} color="rgb(251, 191, 36)" fill="rgb(251, 191, 36)" />
        </span>
    );
}

// Sticky cards keep their authored width/height. The whole point of the rewrite is that
// the device is fully capable of rendering these — we don't need to cap the size to
// stay under WebKit's compositor budget (the budget belongs to xyflow's first-paint
// mass-mount, which we've removed by building our own renderer).
function StickyCard({
    node,
    w,
    h,
    lod,
}: {
    node: Node;
    w: number;
    h: number;
    lod: 'low' | 'high';
}) {
    const config = getNodeConfig(node);
    const colorIdx = (config.color as number | undefined) ?? 0;
    // Resolve from the shared stickyColors source of truth (same as the desktop
    // canvas + WorkflowGraphPreview) so the tint flips with the theme — a soft
    // pastel on light, a deep near-black tint on dark — instead of the old fixed
    // light-only palette that read wrong in both modes.
    const isDark = useIsDark();
    const colors = stickyScheme(colorIdx, isDark);
    const content = (config.content as string | undefined) || '';
    // Low-LOD placeholder: when zoomed out below the legibility threshold, the user
    // can't read the markdown anyway (text would be sub-pixel). Skip the MarkdownRenderer
    // entirely and just draw the colored card with a short text preview + the first
    // visual (YouTube thumbnail or inline image) preserved as an <img>, so the visual
    // identity of media-rich stickies isn't lost between zoom levels. Layer cost is
    // bounded — <img> uses one bitmap of the image's natural size, not a full
    // markdown DOM tree.
    if (lod === 'low') {
        const preview = content
            .replace(/[#*`>_\[\]\n]/g, ' ')
            .replace(/\s+/g, ' ')
            .trim()
            .slice(0, 80);
        const media = extractStickyMedia(content);
        const mediaSrc =
            media?.kind === 'youtube'
                ? `https://img.youtube.com/vi/${media.videoId}/hqdefault.jpg`
                : media?.kind === 'image'
                  ? media.src
                  : null;
        return (
            <div
                style={{
                    width: w,
                    height: h,
                    background: colors.bg,
                    border: `1px solid ${colors.border}`,
                    color: colors.text,
                    borderRadius: 6,
                    padding: 12,
                    overflow: 'hidden',
                    fontSize: 14,
                    lineHeight: 1.5,
                    fontFamily: 'system-ui, -apple-system, sans-serif',
                    boxSizing: 'border-box',
                    pointerEvents: 'none',
                    display: 'flex',
                    flexDirection: 'column',
                    gap: 8,
                }}
            >
                {mediaSrc && (
                    <img
                        src={mediaSrc}
                        alt=""
                        loading="lazy"
                        decoding="async"
                        style={{
                            width: '100%',
                            flex: 1,
                            minHeight: 0,
                            objectFit: 'cover',
                            borderRadius: 4,
                            background: 'rgba(0,0,0,0.1)',
                        }}
                    />
                )}
                <div
                    style={{
                        flex: mediaSrc ? '0 0 auto' : '1 1 auto',
                        overflow: 'hidden',
                    }}
                >
                    {preview}
                    {content.length > preview.length ? '…' : ''}
                </div>
            </div>
        );
    }
    // pointer-events: none keeps the touch target on the node wrapper (data-node-id),
    // so iOS doesn't kick into image-preview / native drag when long-pressing
    // markdown-embedded images or YouTube thumbnails inside the sticky.
    return (
        <div
            style={
                {
                    width: w,
                    height: h,
                    background: colors.bg,
                    border: `1px solid ${colors.border}`,
                    color: colors.text,
                    borderRadius: 6,
                    padding: 16,
                    overflow: 'auto',
                    fontSize: 14,
                    lineHeight: 1.5,
                    fontFamily: 'system-ui, -apple-system, sans-serif',
                    boxSizing: 'border-box',
                    pointerEvents: 'none',
                    WebkitTouchCallout: 'none',
                    WebkitUserDrag: 'none',
                } as React.CSSProperties
            }
        >
            <MarkdownRenderer content={content} />
        </div>
    );
}

// Generic node card — same look as the desktop FlatReadOnlyCard (rounded-2xl, zinc
// border, radial-gradient bg) using the actual NodeDefinition.Icon component from the
// registry. When the AI builder is editing this node, expands to the same layout +
// status UI as the desktop AutomationNode — via the shared useNodeEditingState hook
// and NodeEditOverlay component in nodes/base/nodeEditing.tsx.
const GenericCard = memo(function GenericCard({
    node,
    def,
    w,
    h,
}: {
    node: Node;
    def?: NodeDefinition | null;
    w: number;
    h: number;
}) {
    const t = node.type || 'node';
    // Fallback chain: node.data.label > NodeDefinition.label > labelFromType. Same for
    // icon: NodeDefinition.Icon (React component, used by production registered nodes)
    // > node.data.icon (URL string, used by lightweight demo/showcase nodes without a
    // NodeDefinition entry) > 2-letter glyph.
    const data = (node.data ?? {}) as { icon?: unknown; label?: unknown };
    const dataIconUrl =
        typeof data.icon === 'string' && data.icon.length > 0
            ? data.icon
            : null;
    const dataLabel =
        typeof data.label === 'string' && data.label.length > 0
            ? data.label
            : null;
    const label = dataLabel ?? def?.label ?? labelFromType(t);
    const dim = def?.dimensions || { width: 90, height: 90, iconSize: 48 };
    const Icon = def?.Icon;

    // Execution-status corner mark — the SAME NodeStatusBadge the desktop canvas draws,
    // so failed (red ✕) / completed (white ✓) / incomplete (amber !) nodes read identically
    // on mobile. Only the cheap badge is rendered here (no animated rings / glow / blur) to
    // stay within the ForkCanvas perf budget that prevents mobile WebKit crashes.
    const exec = (node.data as { executionState?: string } | undefined)
        ?.executionState;
    const lastRun = (node.data as { _lastRunStatus?: string } | undefined)
        ?._lastRunStatus;
    const lastRunAt = (node.data as { _lastRunAt?: number } | undefined)
        ?._lastRunAt;
    const configInvalid =
        (node.data as { configValid?: boolean } | undefined)?.configValid ===
        false;
    const statusVariant: NodeStatusVariant | null =
        exec === 'error' || lastRun === 'error'
            ? 'error'
            : configInvalid
              ? 'incomplete'
              : exec === 'completed' || lastRun === 'completed'
                ? 'completed'
                : null;
    // Status border ring (completed/failed/incomplete) + the "✓/✗ N ago" pill, mirroring
    // desktop NodeAuroraLayers + AutomationNode border + NodeLabel. Static only — no
    // animated sweep/glow layers — to stay within the ForkCanvas perf budget.
    const ringVariant = statusVariant;
    const showChip = shouldShowStatusChip(
        lastRun,
        lastRunAt,
        exec === 'running'
    );

    const { isBeingEdited, editInfo, remoteEditorName } = useNodeEditingState(
        node.id,
        {
            previewEditInfo: (
                node.data as
                    | {
                          _previewEditInfo?: NodeEditInfo | null;
                      }
                    | undefined
            )?._previewEditInfo,
        }
    );
    const currentWidth = isBeingEdited ? EDIT_EXPANDED_WIDTH : w;
    const currentHeight = isBeingEdited ? EDIT_EXPANDED_HEIGHT : h;

    // Trigger entry-point treatment, mirroring desktop AutomationNode: no left
    // handle dot, amber bolt where events come in. (Shape treatment pending the
    // /triggerstyles pick.)
    const operation = (node.data as { operation?: string } | undefined)
        ?.operation;
    // Landing-demo showcase nodes carry no type/operation the registry knows, so
    // they declare trigger-ness and handle topology in data instead.
    const demo = node.data as
        | { isTrigger?: boolean; handles?: NodeHandleLayout }
        | undefined;
    const isTrigger = demo?.isTrigger ?? isTriggerSource(t, operation);
    // Handle topology from the shared helper — drives the connection dots and
    // matches the desktop node, so the agent's bottom handle + provider top handles
    // render here too (they previously didn't, drifting from FlowCanvas).
    const handleLayout = demo?.handles ?? getNodeHandleLayout(t, operation);
    // Agent nodes render the model-specific brand logo (Codex/Claude Code/OpenCode/
    // OpenClaw/Hermes/Bot) via the shared AgentModelIcon, instead of the static Bot
    // from the NodeDefinition — same as the desktop AIAgentNode.
    // Real agent nodes (type 'agent') OR lightweight showcase agent nodes
    // (data.isAgent, used by the landing-page demo) render the harness logo.
    const isAgent =
        t === 'agent' ||
        (node.data as { isAgent?: boolean } | undefined)?.isAgent === true;
    const isDisabled =
        (node.data as { disabled?: boolean } | undefined)?.disabled === true;
    const agentModel = isAgent
        ? (getNodeConfig(node).model as string) ||
          (node.data as { model?: string } | undefined)?.model ||
          DEFAULT_AGENT_MODEL
        : '';
    const cardRadius = 16;

    return (
        <div
            style={
                {
                    width: currentWidth,
                    height: currentHeight,
                    position: 'relative',
                    WebkitTouchCallout: 'none',
                    WebkitUserDrag: 'none',
                    transition: EDIT_TRANSITION,
                } as React.CSSProperties
            }
        >
            <CardHandles layout={handleLayout} />
            {isTrigger && !isBeingEdited && <TriggerBolt />}
            {!isBeingEdited && statusVariant && (
                <NodeStatusBadge variant={statusVariant} />
            )}
            <div
                className="overflow-hidden"
                style={{
                    width: '100%',
                    height: '100%',
                    borderRadius: cardRadius,
                    border: '1px solid hsl(var(--border))',
                    // Opaque base under the gradient so the canvas grid doesn't bleed through
                    // its translucent stops — matches the solid look of the desktop FlowCanvas
                    // node, which relies on a backdrop-blur glass we can't use on mobile.
                    backgroundColor: 'hsl(var(--card))',
                    backgroundImage:
                        'radial-gradient(circle at 30% 30%, hsl(var(--secondary)), hsl(var(--card)))',
                    color: 'hsl(var(--card-foreground))',
                    pointerEvents: 'none',
                    display: 'flex',
                    alignItems: isBeingEdited ? 'stretch' : 'center',
                    justifyContent: isBeingEdited ? 'stretch' : 'center',
                }}
            >
                {isBeingEdited ? (
                    Icon ? (
                        <NodeEditOverlay
                            Icon={Icon}
                            iconColor={def?.iconColor}
                            editInfo={editInfo}
                            remoteEditorName={remoteEditorName}
                        />
                    ) : (
                        <span
                            style={{
                                fontSize: 16,
                                fontWeight: 700,
                                color: 'hsl(var(--muted-foreground))',
                                margin: 'auto',
                            }}
                        >
                            {glyphFromType(t)}
                        </span>
                    )
                ) : isAgent ? (
                    <div
                        style={{
                            display: 'flex',
                            flexDirection: 'column',
                            alignItems: 'center',
                            gap: 8,
                        }}
                    >
                        <AgentModelIcon
                            model={agentModel}
                            variant="normal"
                            disabled={isDisabled}
                        />
                        <div
                            style={{
                                fontSize: 12,
                                fontWeight: 500,
                                color: 'hsl(var(--muted-foreground))',
                                opacity: isDisabled ? 0.2 : 1,
                            }}
                        >
                            Agent Model
                        </div>
                        <div
                            style={{
                                display: 'flex',
                                alignItems: 'center',
                                gap: 4,
                                fontSize: 12,
                                color: 'hsl(var(--muted-foreground))',
                                opacity: isDisabled ? 0.2 : 1,
                            }}
                        >
                            <span>{modelShortName(agentModel)}</span>
                            <ChevronDown style={{ width: 12, height: 12 }} />
                        </div>
                    </div>
                ) : Icon ? (
                    <Icon
                        className={def?.iconColor || ''}
                        style={{
                            width: dim.iconSize,
                            height: dim.iconSize,
                            pointerEvents: 'none',
                        }}
                    />
                ) : dataIconUrl ? (
                    <img
                        src={dataIconUrl}
                        alt=""
                        loading="lazy"
                        decoding="async"
                        style={{
                            width: dim.iconSize,
                            height: dim.iconSize,
                            pointerEvents: 'none',
                        }}
                    />
                ) : (
                    <span
                        style={{
                            fontSize: 18,
                            fontWeight: 700,
                            color: 'hsl(var(--muted-foreground))',
                        }}
                    >
                        {glyphFromType(t)}
                    </span>
                )}
            </div>
            {!isBeingEdited && ringVariant && (
                <div
                    style={{
                        position: 'absolute',
                        inset: 0,
                        borderRadius: cardRadius,
                        pointerEvents: 'none',
                        border: `1.5px solid ${RUN_RING[ringVariant].border}`,
                        boxShadow: RUN_RING[ringVariant].glow,
                    }}
                />
            )}
            {!isBeingEdited && (
                <div
                    style={{
                        position: 'absolute',
                        left: '50%',
                        top: 'calc(100% + 4px)',
                        transform: 'translateX(-50%)',
                        display: 'flex',
                        flexDirection: 'column',
                        alignItems: 'center',
                        gap: 4,
                        pointerEvents: 'none',
                    }}
                >
                    <div
                        className="text-zinc-600 dark:text-zinc-300"
                        style={{
                            fontSize: 11,
                            whiteSpace: 'nowrap',
                        }}
                    >
                        {label}
                    </div>
                    {showChip && (
                        <NodeStatusChip
                            status={lastRun as string}
                            at={lastRunAt as number}
                        />
                    )}
                </div>
            )}
        </div>
    );
});

// Interface node card — renders the actual block UI (form fields, html-react iframe,
// markdown, image, etc.) via BlockRenderer in read-only mode. Same look as the desktop
// InterfaceNode header + content (radial gradient + bordered card) without the xyflow
// wrapper, NodeResizer, or Handle components.
const InterfaceCard = memo(function InterfaceCard({
    node,
    def,
    w,
    h,
    lod,
    workflowId,
}: {
    node: Node;
    def?: NodeDefinition | null;
    w: number;
    h: number;
    lod: 'low' | 'high';
    workflowId?: string;
}) {
    const blockType = getInterfaceBlockType(node.type || '');
    const config = getNodeConfig(node);
    const blockDef = getBlockDefinition(blockType);
    // Interface blocks are normal dataflow nodes (left input, right output).
    const handleLayout = getNodeHandleLayout(node.type, undefined);
    const dataLabel = (node.data as { label?: unknown } | undefined)?.label;
    const label =
        (typeof dataLabel === 'string' && dataLabel) ||
        blockDef?.label ||
        labelFromType(node.type || blockType);
    const isReadOnly = !!(node.data as { isReadOnly?: boolean } | undefined)
        ?.isReadOnly;
    // Always-high-LOD interface blocks: forms (kept functional at every zoom level —
    // their backing store is ~8MB per form at DPR 3, fits a workflow's worth) and
    // html-react (user wants pixel fidelity at all zoom levels — the iframe content
    // is the visual identity of these nodes, not just decoration). Trade-off: the
    // html-react iframe is expensive (~85MB layer at 1884×1253), so workflows with
    // many html-react nodes may push the budget. Hasn't been an issue for typical
    // workflows so far. The LOD swap below still applies to other heavy interface
    // blocks (chatbot, dataframe, image/video/audio with large media) where the
    // schematic preview is acceptable at fitView.
    const isAlwaysFunctional =
        blockType === 'form' || blockType === 'html-react';
    if (lod === 'low' && !isAlwaysFunctional) {
        return (
            <div style={{ width: w, height: h, position: 'relative' }}>
                <CardHandles layout={handleLayout} />
                <InterfaceGenericPreview
                    w={w}
                    h={h}
                    label={label}
                    blockType={blockType}
                />
            </div>
        );
    }
    return (
        <div style={{ width: w, height: h, position: 'relative' }}>
            <CardHandles layout={handleLayout} />
            {/* Card chrome + browser-style header mirror the desktop InterfaceNode (shared
                InterfaceBlockHeader) so the refreshed look — icon and label —
                stays in sync across desktop and mobile. */}
            <div
                className="rounded-xl overflow-hidden flex flex-col"
                style={{
                    width: '100%',
                    height: '100%',
                    background: 'hsl(var(--card))',
                    border: '1px solid hsl(var(--border))',
                    color: 'hsl(var(--card-foreground))',
                    boxSizing: 'border-box',
                }}
            >
                <InterfaceBlockHeader
                    Icon={blockDef?.icon}
                    iconColor={def?.iconColor}
                    label={label}
                    trailing={
                        <>
                            <InterfaceFormLinkButton
                                nodeId={node.id}
                                nodeType={node.type}
                                config={config as BlockConfig}
                                workflowId={workflowId}
                                isReadOnly={isReadOnly}
                            />
                        </>
                    }
                />
                <div style={{ flex: 1, minHeight: 0, overflow: 'auto' }}>
                    <BlockRenderer
                        blockType={blockType}
                        id={node.id}
                        config={config}
                        output={null}
                        isSelected={false}
                        onConfigChange={() => {
                            /* read-only */
                        }}
                        isReadOnly={true}
                    />
                </div>
            </div>
        </div>
    );
});

function NodeBody({
    node,
    def,
    w,
    h,
    lodTiers,
    workflowId,
}: {
    node: Node;
    def?: NodeDefinition | null;
    w: number;
    h: number;
    lodTiers: LodTiers;
    workflowId?: string;
}) {
    if (node.type === 'stickyNote')
        return <StickyCard node={node} w={w} h={h} lod={lodTiers.sticky} />;
    if (node.type?.startsWith('interface-'))
        return (
            <InterfaceCard
                node={node}
                def={def}
                w={w}
                h={h}
                lod={lodTiers.interface}
                workflowId={workflowId}
            />
        );
    return <GenericCard node={node} def={def} w={w} h={h} />;
}

function bezierPath(sx: number, sy: number, tx: number, ty: number): string {
    const cx = (sx + tx) / 2;
    return `M ${sx} ${sy} C ${cx} ${sy}, ${cx} ${ty}, ${tx} ${ty}`;
}

// Pick a path: backward routing (shared ~/utils/edgePaths, same as the desktop
// AnimatedWorkflowEdge) if target is left of source beyond the threshold,
// bezier otherwise.
function edgePath(sx: number, sy: number, tx: number, ty: number): string {
    const isBackward = tx < sx - BACKWARD_EDGE_X_THRESHOLD;
    return isBackward
        ? getBackwardEdgePath(sx, sy, tx, ty)
        : bezierPath(sx, sy, tx, ty);
}

// Vertical S-curve for tool-provider / MCP-hosting edges (a provider's top handle →
// an agent's or MCP server's bottom handle). Control points are offset in Y so the
// curve leaves the source and arrives at the target vertically, regardless of which
// sits higher — autolayout places the provider below its agent, so it runs upward.
function verticalEdgePath(
    sx: number,
    sy: number,
    tx: number,
    ty: number
): string {
    const cy = (sy + ty) / 2;
    return `M ${sx} ${sy} C ${sx} ${cy}, ${tx} ${cy}, ${tx} ${ty}`;
}

// Memoized edge path. Only re-renders when its `d` actually changes — so during node
// drag, only edges connected to the dragged node have their <path> reconciled. Other
// edges' DOM stays untouched, no flicker, no compositing-layer invalidation cascade.
const EdgePath = memo(function EdgePath({ d }: { d: string }) {
    return (
        <path
            d={d}
            stroke="hsl(var(--canvas-edge))"
            strokeWidth={3}
            strokeDasharray="5 5"
            opacity={0.8}
            fill="none"
        />
    );
});

function clamp(v: number, lo: number, hi: number): number {
    return Math.max(lo, Math.min(hi, v));
}

// Coerce a node-dimension value (number, "200", or "200px") to a finite number.
function numOrUndef(v: unknown): number | undefined {
    if (typeof v === 'number') return Number.isFinite(v) ? v : undefined;
    if (typeof v === 'string') {
        const n = parseFloat(v);
        return Number.isFinite(n) ? n : undefined;
    }
    return undefined;
}

// Elements explicitly marked `.nodrag` (e.g. the interface Publish button) must receive
// their own clicks. ForkCanvas's container-level gesture handlers would otherwise treat
// the touch as a node tap and preventDefault() would swallow the synthesized click — so
// the start handlers bail out early when the event originates inside a `.nodrag` element.
function isNoDragTarget(target: EventTarget | null): boolean {
    return target instanceof Element && !!target.closest('.nodrag');
}

// Per-type LOD thresholds. Below these zoom levels, heavy content is replaced with
// a cheap placeholder. Stickies get a lower threshold so embedded media (YouTube
// thumbnails → playable iframe) materializes earlier — users want to see the actual
// player without zooming in significantly. Interface blocks stay at 0.5 since their
// iframes (html-react) are heavier and cheaper to render in placeholder form.
const STICKY_LOD_THRESHOLD = 0.25;
const INTERFACE_LOD_THRESHOLD = 0.5;

interface LodTiers {
    sticky: 'low' | 'high';
    interface: 'low' | 'high';
}
function computeLodTiers(k: number): LodTiers {
    return {
        sticky: k < STICKY_LOD_THRESHOLD ? 'low' : 'high',
        interface: k < INTERFACE_LOD_THRESHOLD ? 'low' : 'high',
    };
}

function ForkCanvasInner(
    {
        nodes: nodesProp,
        edges,
        nodeDefs,
        onNodesChange,
        onEdgesChange: _onEdgesChange, // reserved; not yet wired to internal events
        onNodeClick,
        fitView: fitViewEnabled = true,
        fitViewSignal,
        defaultViewport,
        minZoom: minZoomProp = 0.02,
        maxZoom: maxZoomProp = 1.5,
        nodesDraggable = true,
        isEditing = false,
        editingNodeIds,
        style,
            workflowId,
        children,
        passiveViewport = false,
    }: ForkCanvasProps,
    ref: Ref<ForkCanvasRef>
) {
    const containerRef = useRef<HTMLDivElement>(null);
    const transformElRef = useRef<HTMLDivElement>(null);
    const [didInitFit, setDidInitFit] = useState(false);
    // Fully controlled: nodes come from props. Drag fires onNodesChange so the parent
    // updates its source-of-truth state and passes new nodes back as props on the
    // next render — same pattern as ReactFlow's controlled mode.
    const nodes = nodesProp;
    // Per-type LOD tiers. State update only triggers when any tier changes (so pinch
    // gestures don't re-render the whole tree on every frame). See computeLodTiers
    // for the per-type thresholds.
    const [lodTiers, setLodTiers] = useState<LodTiers>({
        sticky: 'high',
        interface: 'high',
    });
    const lodTiersRef = useRef<LodTiers>(lodTiers);

    // Transform is owned by a ref + applied directly to the DOM element rather than
    // going through React state. Pinch/pan fires at 60Hz; if we re-rendered React for
    // each tick, all 37 nodes' style props would reconcile every frame and pinch would
    // feel sluggish. With the ref-based applyTransform, only the inner div's style
    // changes per frame, no React render.
    //
    // The bg pattern and edge SVG live in the OUTER container (viewport-sized), not
    // inside the transformed parent. Putting them inside makes them part of a single
    // composited layer whose bitmap covers the union of their bounding boxes — for a
    // workflow with sticky notes at x=4086+w=4391, that's an 11000×5000 layer ≈ 220MB
    // per buffer, which OOMs the iPhone WebContent process during pan. Keeping them
    // outside the transform and updating background-position / viewBox per tick keeps
    // each layer at viewport size (~400×800 ≈ 1.3MB).
    const transformRef = useRef<Transform>({ x: 0, y: 0, k: 1 });
    const bgElRef = useRef<HTMLDivElement>(null);
    const svgElRef = useRef<SVGSVGElement>(null);
    // rAF-throttled DOM writes. Touch events on iOS can fire faster than the compositor
    // paints (60-120Hz vs 60Hz paint). Without throttling, each event triggers a DOM
    // write that the browser queues, so aggressive gestures grow the queue and
    // accumulate work. Coalescing to one DOM write per frame (rAF) bounds the work.
    const rafScheduledRef = useRef(false);
    function flushTransform() {
        rafScheduledRef.current = false;
        const t = transformRef.current;
        if (transformElRef.current) {
            transformElRef.current.style.transform = `translate(${t.x}px, ${t.y}px) scale(${t.k})`;
        }
        if (bgElRef.current) {
            // Plus-grid pattern: scales with zoom so the marks shrink as the canvas
            // zooms out (matching the visual scale of nodes/content). backgroundSize
            // is the cell size in screen pixels = canvas grid spacing × zoom.
            const size = PLUS_GRID_SIZE * t.k;
            bgElRef.current.style.backgroundSize = `${size}px ${size}px`;
            bgElRef.current.style.backgroundPosition = `${t.x}px ${t.y}px`;
        }
        if (svgElRef.current && containerRef.current) {
            const cw = containerRef.current.clientWidth;
            const ch = containerRef.current.clientHeight;
            svgElRef.current.setAttribute(
                'viewBox',
                `${-t.x / t.k} ${-t.y / t.k} ${cw / t.k} ${ch / t.k}`
            );
        }
    }
    function applyTransform(t: Transform) {
        transformRef.current = t;
        // Flip LOD tiers when zoom crosses each threshold. setLodTiers only fires when
        // ANY tier changes, so we don't re-render on every gesture tick.
        const newTiers = computeLodTiers(t.k);
        const cur = lodTiersRef.current;
        if (
            newTiers.sticky !== cur.sticky ||
            newTiers.interface !== cur.interface
        ) {
            lodTiersRef.current = newTiers;
            setLodTiers(newTiers);
        }
        if (rafScheduledRef.current) return;
        rafScheduledRef.current = true;
        requestAnimationFrame(flushTransform);
    }
    const nodesRef = useRef(nodes);
    nodesRef.current = nodes;
    // Refs to the latest callback props, so the native event listeners (attached once
    // via useEffect) always call the freshest handlers without re-binding on every
    // prop change.
    const onNodesChangeRef = useRef(onNodesChange);
    onNodesChangeRef.current = onNodesChange;
    const onNodeClickRef = useRef(onNodeClick);
    onNodeClickRef.current = onNodeClick;
    const nodesDraggableRef = useRef(nodesDraggable);
    nodesDraggableRef.current = nodesDraggable;

    // Default node dimensions when the workflow data doesn't specify width/height.
    // First try the registry's NodeDefinition.dimensions (matches desktop FlatReadOnlyCard
    // sizing exactly), then fall back per-type. Sticky 360×320, interface 320×240,
    // generic 90×90. Caps width/height to MOBILE_MAX_DIM to bound peak layer memory.
    function nodeDims(n: Node): { w: number; h: number } {
        const cap = (w: number, h: number) => ({
            w: Math.min(w, MOBILE_MAX_DIM),
            h: Math.min(h, MOBILE_MAX_DIM),
        });
        // Resizable nodes (sticky notes, interface blocks) persist their size in
        // node.style.{width,height}; only a live NodeResizer drag writes the top-level
        // node.{width,height}. Resolve both — the same rule buildSaveConfig uses — so a
        // saved/AI-built sticky or html-react renders at its TRUE size instead of the
        // type default (the old check read node.width/height only and ignored style,
        // so every non-live-resized sticky/interface fell through to the default).
        const style = n.style as
            | { width?: number | string; height?: number | string }
            | undefined;
        const ew = numOrUndef(n.width ?? style?.width);
        const eh = numOrUndef(n.height ?? style?.height);
        if (ew != null && eh != null) return cap(ew, eh);
        // Agent nodes render at 200x140 (matching the desktop AIAgentNode). Covers both
        // real agent nodes (type 'agent') — sized here even before nodeDefs loads so they
        // don't pop from a 90x90 square — and lightweight showcase agent nodes (data.isAgent,
        // landing demo) which carry no NodeDefinition.
        if (
            n.type === 'agent' ||
            (n.data as { isAgent?: boolean } | undefined)?.isAgent
        )
            return cap(200, 140);
        const def = nodeDefs?.[n.type ?? ''];
        if (def?.dimensions)
            return cap(def.dimensions.width, def.dimensions.height);
        if (n.type === 'stickyNote') return cap(ew ?? 360, eh ?? 320);
        if (n.type?.startsWith('interface-')) return cap(ew ?? 320, eh ?? 240);
        return cap(ew ?? 90, eh ?? 90);
    }

    // Live measured dimensions per node, populated by a ResizeObserver attached to
    // each card's outer element. When a card resizes (e.g. CSS-transitioning 90→220
    // during AI edit expand), the observer fires per frame and we re-compute edge
    // endpoints — so edges follow the expand smoothly instead of snapping/floating.
    // Falls back to nodeDims() when no measurement is available (e.g. first paint).
    const measuredDimsRef = useRef<Map<string, { w: number; h: number }>>(
        new Map()
    );
    const [edgeTick, setEdgeTick] = useState(0);
    useEffect(() => {
        if (typeof ResizeObserver === 'undefined') return;
        const ro = new ResizeObserver((entries) => {
            let changed = false;
            for (const entry of entries) {
                const target = entry.target as HTMLElement;
                const wrapper = target.parentElement;
                const id = wrapper?.getAttribute('data-node-id');
                if (!id) continue;
                const w = entry.contentRect.width;
                const h = entry.contentRect.height;
                const cur = measuredDimsRef.current.get(id);
                if (
                    !cur ||
                    Math.abs(cur.w - w) > 0.5 ||
                    Math.abs(cur.h - h) > 0.5
                ) {
                    measuredDimsRef.current.set(id, { w, h });
                    changed = true;
                }
            }
            if (changed) setEdgeTick((t) => (t + 1) % 1_000_000);
        });
        // Observe every wrapper's first child (the card itself).
        const wrappers =
            containerRef.current?.querySelectorAll('[data-node-id]') ?? [];
        wrappers.forEach((w) => {
            const card = w.firstElementChild;
            if (card instanceof HTMLElement) ro.observe(card);
        });
        return () => ro.disconnect();
        // Re-attach when the set of nodes changes (AI adds/removes a node).
    }, [nodes]);

    // Edge endpoints prefer the live measured dimensions; fall back to nodeDims.
    function nodeDimsForEdge(n: Node): { w: number; h: number } {
        const measured = measuredDimsRef.current.get(n.id);
        if (measured) return measured;
        return nodeDims(n);
    }

    // Compute edge geometry. Re-runs when nodes drag, when AI edits expand a node
    // (via edgeTick bumped by the ResizeObserver), and when nodeDefs load. Edge
    // endpoints use the live measured dimensions when available so the path follows
    // the card's CSS-transitioning width every frame.
    const { edgePaths, contentBounds } = useMemo(() => {
        const nodeMap = new Map(nodes.map((n) => [n.id, n]));
        const paths: { id: string; d: string }[] = [];
        let minX = Infinity,
            minY = Infinity,
            maxX = -Infinity,
            maxY = -Infinity;
        for (const n of nodes) {
            // contentBounds uses the static nodeDims (not measured) so the fitView
            // bbox doesn't shrink/grow while a card is mid-transition.
            const { w, h } = nodeDims(n);
            minX = Math.min(minX, n.position.x);
            minY = Math.min(minY, n.position.y);
            maxX = Math.max(maxX, n.position.x + w);
            maxY = Math.max(maxY, n.position.y + h);
        }
        for (const e of edges) {
            const s = nodeMap.get(e.source);
            const t = nodeMap.get(e.target);
            if (!s || !t) continue;
            const { w: sw, h: sh } = nodeDimsForEdge(s);
            const { w: tw, h: th } = nodeDimsForEdge(t);
            // Tool-provider / MCP-hosting wiring leaves the source's top handle and
            // enters the target's bottom handle; every other edge is right → left.
            const fromTop = e.sourceHandle === 'top';
            const toBottom = e.targetHandle === 'bottom';
            const sx = fromTop ? s.position.x + sw / 2 : s.position.x + sw;
            const sy = fromTop ? s.position.y : s.position.y + sh / 2;
            const tx = toBottom ? t.position.x + tw / 2 : t.position.x;
            const ty = toBottom ? t.position.y + th : t.position.y + th / 2;
            const d =
                fromTop || toBottom
                    ? verticalEdgePath(sx, sy, tx, ty)
                    : edgePath(sx, sy, tx, ty);
            paths.push({ id: e.id, d });
        }
        return {
            edgePaths: paths,
            contentBounds: isFinite(minX)
                ? { x: minX, y: minY, width: maxX - minX, height: maxY - minY }
                : { x: 0, y: 0, width: 0, height: 0 },
        };
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [nodes, edges, nodeDefs, edgeTick]);

    // Core fit logic — used by initial fitView, fitViewSignal, and the imperative
    // ref. Computes a transform that fits the targeted nodes in the container with
    // padding, clamped to [minZoom, maxZoom]. Skips sticky notes by default (they sit
    // outside the main flow); pass `nodes` option to override the target set.
    function runFitView(
        options: {
            padding?: number;
            minZoom?: number;
            maxZoom?: number;
            nodes?: { id: string }[];
        } = {}
    ) {
        const el = containerRef.current;
        if (!el) return;
        const cw = el.clientWidth;
        const ch = el.clientHeight;
        if (cw === 0 || ch === 0) return;
        if (contentBounds.width === 0 || contentBounds.height === 0) return;
        const targetIds = options.nodes
            ? new Set(options.nodes.map((n) => n.id))
            : null;
        const targetNodes = targetIds
            ? nodes.filter((n) => targetIds.has(n.id))
            : nodes.filter((n) => n.type !== 'stickyNote');
        let tMinX = Infinity,
            tMinY = Infinity,
            tMaxX = -Infinity,
            tMaxY = -Infinity;
        for (const n of targetNodes) {
            const { w, h } = nodeDims(n);
            tMinX = Math.min(tMinX, n.position.x);
            tMinY = Math.min(tMinY, n.position.y);
            tMaxX = Math.max(tMaxX, n.position.x + w);
            tMaxY = Math.max(tMaxY, n.position.y + h);
        }
        const useTarget = isFinite(tMinX);
        const fitX = useTarget ? tMinX : contentBounds.x;
        const fitY = useTarget ? tMinY : contentBounds.y;
        const fitW = useTarget ? tMaxX - tMinX : contentBounds.width;
        const fitH = useTarget ? tMaxY - tMinY : contentBounds.height;
        const padding = options.padding ?? 0.1;
        const k = clamp(
            Math.min(
                cw / (fitW * (1 + padding * 2)),
                ch / (fitH * (1 + padding * 2))
            ),
            options.minZoom ?? minZoomProp,
            options.maxZoom ?? maxZoomProp
        );
        const cx = fitX + fitW / 2;
        const cy = fitY + fitH / 2;
        applyTransform({ x: cw / 2 - cx * k, y: ch / 2 - cy * k, k });
    }

    // On first non-empty layout, run an initial fitView (if enabled).
    useLayoutEffect(() => {
        if (didInitFit) return;
        if (!fitViewEnabled) {
            // If a defaultViewport was supplied, apply it; else leave at (0, 0, 1).
            if (defaultViewport) {
                applyTransform({
                    x: defaultViewport.x,
                    y: defaultViewport.y,
                    k: defaultViewport.zoom,
                });
            }
            setDidInitFit(true);
            return;
        }
        const el = containerRef.current;
        if (!el) return;
        if (el.clientWidth === 0 || el.clientHeight === 0) return;
        // Nodes haven't populated yet (workflow:get is async — the common mobile
        // "open a workflow" path). Do NOT mark the fit as done, or the later re-run
        // once contentBounds fills in would be short-circuited by the didInitFit
        // guard and the graph would open unfitted. Just wait; this effect re-runs
        // when contentBounds changes.
        if (contentBounds.width === 0 || contentBounds.height === 0) return;
        runFitView();
        setDidInitFit(true);
        // runFitView reads from refs/props; we only re-run when bounds populate.
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [contentBounds, didInitFit]);

    // Re-run fitView whenever the parent bumps fitViewSignal (e.g. after an AI batch).
    useEffect(() => {
        if (fitViewSignal === undefined) return;
        if (!didInitFit) return;
        runFitView();
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [fitViewSignal]);

    // Imperative API for parents that need to drive the viewport (Controls component,
    // fit-on-AI-batch, programmatic zoom-to-node, etc.). runFitView is closed over
    // the latest nodes/contentBounds on each render; we route through a ref so the
    // imperative method always invokes the current closure rather than the one bound
    // at mount.
    const runFitViewRef = useRef(runFitView);
    runFitViewRef.current = runFitView;
    useImperativeHandle(
        ref,
        () => ({
            fitView: (options) => runFitViewRef.current(options ?? {}),
            setViewport: (v) => applyTransform({ x: v.x, y: v.y, k: v.zoom }),
            getViewport: () => ({
                x: transformRef.current.x,
                y: transformRef.current.y,
                zoom: transformRef.current.k,
            }),
            // eslint-disable-next-line react-hooks/exhaustive-deps
        }),
        []
    );

    // Keep SVG viewBox + bg pattern in sync on window resize. Re-applies the current
    // transform to recompute viewBox dimensions against the new container size.
    useEffect(() => {
        const onResize = () => applyTransform(transformRef.current);
        window.addEventListener('resize', onResize);
        return () => window.removeEventListener('resize', onResize);
    }, []);

    // Node drag state. When set, single-finger touchmove repositions the node instead
    // of panning the canvas.
    const nodeDragRef = useRef<{
        id: string;
        startX: number;
        startY: number;
        startNodeX: number;
        startNodeY: number;
        moved: boolean;
    } | null>(null);

    // Find the data-node-id ancestor for a hit-test. Tries the event's own target
    // first; if that's pointer-events:none (e.g. the edge SVG at zIndex 1) closest()
    // won't find a [data-node-id] ancestor, so we fall back to elementFromPoint,
    // which respects pointer-events and returns the topmost interactable element.
    function findNodeIdAtPoint(
        clientX: number,
        clientY: number,
        eventTarget: EventTarget | null
    ): string | null {
        const fromTarget =
            eventTarget instanceof Element
                ? (eventTarget
                      .closest('[data-node-id]')
                      ?.getAttribute('data-node-id') ?? null)
                : null;
        if (fromTarget) return fromTarget;
        if (typeof document === 'undefined') return null;
        const el = document.elementFromPoint(clientX, clientY);
        return el instanceof Element
            ? (el.closest('[data-node-id]')?.getAttribute('data-node-id') ??
                  null)
            : null;
    }

    // ── Node-drag helpers ─────────────────────────────────────────────────
    // Pure functions of refs/state — shared between touch and mouse event handlers.
    // tryStartNodeDrag mutates nodeDragRef when a hit-test lands on a node.

    function tryStartNodeDrag(
        clientX: number,
        clientY: number,
        eventTarget: EventTarget | null
    ): boolean {
        if (!nodesDraggableRef.current) return false;
        const nodeId = findNodeIdAtPoint(clientX, clientY, eventTarget);
        if (!nodeId) return false;
        const n = nodesRef.current.find((n) => n.id === nodeId);
        if (!n) return false;
        nodeDragRef.current = {
            id: nodeId,
            startX: clientX,
            startY: clientY,
            startNodeX: n.position.x,
            startNodeY: n.position.y,
            moved: false,
        };
        return true;
    }

    function advanceNodeDrag(clientX: number, clientY: number): boolean {
        const drag = nodeDragRef.current;
        if (!drag) return false;
        const k = transformRef.current.k;
        const dx = (clientX - drag.startX) / k;
        const dy = (clientY - drag.startY) / k;
        if (Math.abs(dx) + Math.abs(dy) > DRAG_THRESHOLD_PX) drag.moved = true;
        onNodesChangeRef.current?.([
            {
                type: 'position',
                id: drag.id,
                position: { x: drag.startNodeX + dx, y: drag.startNodeY + dy },
                dragging: true,
            },
        ]);
        return true;
    }

    function finishNodeDrag(event: MouseEvent | TouchEvent): boolean {
        const drag = nodeDragRef.current;
        if (!drag) return false;
        const n = nodesRef.current.find((n) => n.id === drag.id);
        if (!drag.moved && onNodeClickRef.current && n) {
            onNodeClickRef.current(event, n);
        } else if (drag.moved && n) {
            // Final 'dragging: false' so parents can distinguish ongoing-drag
            // updates from drag-commit.
            onNodesChangeRef.current?.([
                {
                    type: 'position',
                    id: n.id,
                    position: n.position,
                    dragging: false,
                },
            ]);
        }
        nodeDragRef.current = null;
        return true;
    }

    // Native touch handlers: passive: false so we can preventDefault and stop iOS from
    // hijacking the gesture into page-scroll / page-zoom.
    useEffect(() => {
        const el = containerRef.current;
        if (!el) return;
        const touches = new Map<number, { x: number; y: number }>();

        const onStart = (e: TouchEvent) => {
            // Let interactive node chrome (Publish button, etc.) handle its own tap.
            if (isNoDragTarget(e.target)) return;
            // Single-finger touch on a node → node drag. Pinch always goes to canvas.
            if (e.touches.length === 1 && nodeDragRef.current === null) {
                const t0 = e.touches[0];
                if (tryStartNodeDrag(t0.clientX, t0.clientY, e.target)) {
                    e.preventDefault();
                    return;
                }
            }
            e.preventDefault();
            for (const t of Array.from(e.changedTouches)) {
                touches.set(t.identifier, { x: t.clientX, y: t.clientY });
            }
        };

        const onMove = (e: TouchEvent) => {
            e.preventDefault();
            if (nodeDragRef.current && e.touches.length === 1) {
                const t = e.touches[0];
                advanceNodeDrag(t.clientX, t.clientY);
                return;
            }
            if (e.touches.length === 1) {
                const t = e.touches[0];
                const prev = touches.get(t.identifier);
                if (!prev) return;
                const dx = t.clientX - prev.x;
                const dy = t.clientY - prev.y;
                const curr = transformRef.current;
                applyTransform({ x: curr.x + dx, y: curr.y + dy, k: curr.k });
                touches.set(t.identifier, { x: t.clientX, y: t.clientY });
            } else if (e.touches.length >= 2) {
                const a = e.touches[0];
                const b = e.touches[1];
                const prevA = touches.get(a.identifier);
                const prevB = touches.get(b.identifier);
                if (!prevA || !prevB) return;
                const prevCx = (prevA.x + prevB.x) / 2;
                const prevCy = (prevA.y + prevB.y) / 2;
                const cx = (a.clientX + b.clientX) / 2;
                const cy = (a.clientY + b.clientY) / 2;
                const prevDist =
                    Math.hypot(prevA.x - prevB.x, prevA.y - prevB.y) || 1;
                const curDist =
                    Math.hypot(a.clientX - b.clientX, a.clientY - b.clientY) ||
                    1;
                const dscale = Math.pow(curDist / prevDist, PINCH_POWER);
                const curr = transformRef.current;
                const newK = clamp(curr.k * dscale, minZoomProp, maxZoomProp);
                const realScale = newK / curr.k;
                const dx = cx - prevCx;
                const dy = cy - prevCy;
                applyTransform({
                    x: cx + dx - (cx - curr.x) * realScale,
                    y: cy + dy - (cy - curr.y) * realScale,
                    k: newK,
                });
                touches.set(a.identifier, { x: a.clientX, y: a.clientY });
                touches.set(b.identifier, { x: b.clientX, y: b.clientY });
            }
        };

        const onEnd = (e: TouchEvent) => {
            if (e.touches.length === 0) finishNodeDrag(e);
            for (const t of Array.from(e.changedTouches)) {
                touches.delete(t.identifier);
            }
        };

        if (passiveViewport) return;
        el.addEventListener('touchstart', onStart, { passive: false });
        el.addEventListener('touchmove', onMove, { passive: false });
        el.addEventListener('touchend', onEnd);
        el.addEventListener('touchcancel', onEnd);

        return () => {
            el.removeEventListener('touchstart', onStart);
            el.removeEventListener('touchmove', onMove);
            el.removeEventListener('touchend', onEnd);
            el.removeEventListener('touchcancel', onEnd);
        };
    }, [passiveViewport]);

    // Mouse support for desktop debugging — same node-drag logic.
    const mouseDragRef = useRef<{ x: number; y: number } | null>(null);
    useEffect(() => {
        const el = containerRef.current;
        if (!el) return;
        const onMouseDown = (e: MouseEvent) => {
            if (isNoDragTarget(e.target)) return;
            if (tryStartNodeDrag(e.clientX, e.clientY, e.target)) return;
            mouseDragRef.current = { x: e.clientX, y: e.clientY };
        };
        const onMouseMove = (e: MouseEvent) => {
            if (advanceNodeDrag(e.clientX, e.clientY)) return;
            const prev = mouseDragRef.current;
            if (!prev) return;
            const dx = e.clientX - prev.x;
            const dy = e.clientY - prev.y;
            const curr = transformRef.current;
            applyTransform({ x: curr.x + dx, y: curr.y + dy, k: curr.k });
            mouseDragRef.current = { x: e.clientX, y: e.clientY };
        };
        const onMouseUp = (e: MouseEvent) => {
            finishNodeDrag(e);
            mouseDragRef.current = null;
        };
        const onWheel = (e: WheelEvent) => {
            e.preventDefault();
            const rect = el.getBoundingClientRect();
            const cx = e.clientX - rect.left;
            const cy = e.clientY - rect.top;
            const factor = Math.exp(-e.deltaY * WHEEL_ZOOM_SENSITIVITY);
            const curr = transformRef.current;
            const newK = clamp(curr.k * factor, minZoomProp, maxZoomProp);
            const realScale = newK / curr.k;
            applyTransform({
                x: cx - (cx - curr.x) * realScale,
                y: cy - (cy - curr.y) * realScale,
                k: newK,
            });
        };
        if (passiveViewport) return;
        el.addEventListener('mousedown', onMouseDown);
        window.addEventListener('mousemove', onMouseMove);
        window.addEventListener('mouseup', onMouseUp);
        el.addEventListener('wheel', onWheel, { passive: false });
        return () => {
            el.removeEventListener('mousedown', onMouseDown);
            window.removeEventListener('mousemove', onMouseMove);
            window.removeEventListener('mouseup', onMouseUp);
            el.removeEventListener('wheel', onWheel);
        };
    }, [passiveViewport]);

    // Initial background-position / SVG viewBox match the initial transform. After
    // mount, applyTransform updates them imperatively on every gesture tick.
    const initT = transformRef.current;

    return (
        <div
            ref={containerRef}
            className={`absolute inset-0 overflow-hidden${isEditing ? ' fork-canvas-editing' : ''}`}
            style={{
                touchAction: passiveViewport ? 'pan-y' : 'none',
                userSelect: 'none',
                WebkitUserSelect: 'none',
                WebkitTouchCallout: 'none',
                backgroundColor: 'hsl(var(--canvas-bg))',
                ...style,
            }}
        >
            {/* Plus-grid background pattern, container-sized (NOT inside the transform
                parent). backgroundPosition + backgroundSize update via applyTransform()
                so the pattern visually pans/zooms with the canvas while the layer
                stays at viewport size — bounded GPU memory regardless of canvas span. */}
            <div
                ref={bgElRef}
                style={{
                    position: 'absolute',
                    inset: 0,
                    pointerEvents: 'none',
                    backgroundImage:
                        document.documentElement.classList.contains('dark')
                            ? PLUS_GRID_BG
                            : PLUS_GRID_BG_LIGHT,
                    backgroundSize: `${PLUS_GRID_SIZE * initT.k}px ${PLUS_GRID_SIZE * initT.k}px`,
                    backgroundPosition: `${initT.x}px ${initT.y}px`,
                }}
            />
            {/* Sticky notes — inside the transform parent so they pan/scale with the
                canvas. Rendered BEFORE the edge SVG so edges appear over them. */}
            <div
                ref={transformElRef}
                style={{
                    position: 'absolute',
                    top: 0,
                    left: 0,
                    transform: `translate(${initT.x}px, ${initT.y}px) scale(${initT.k})`,
                    transformOrigin: '0 0',
                    width: 0,
                    height: 0,
                    /* Explicit zIndex 0 so the stacking with the SVG (zIndex 1) and bg
                       pattern is unambiguous — no implicit auto-vs-positive race during
                       gesture-triggered repaints. */
                    zIndex: 0,
                }}
            >
                {nodes
                    .filter((n) => n.type === 'stickyNote')
                    .map((n) => {
                        const { w, h } = nodeDims(n);
                        return (
                            <div
                                key={n.id}
                                data-node-id={n.id}
                                style={{
                                    position: 'absolute',
                                    top: 0,
                                    left: 0,
                                    transform: `translate(${n.position.x}px, ${n.position.y}px)`,
                                    /* No `content-visibility: auto` here — it implicitly
                                       applies `contain: paint` even when the element is
                                       on-screen, which clips handle dots that protrude
                                       past the card edge. With LOD-swap doing the heavy
                                       lifting (placeholders are KB-scale at fitView),
                                       always-rendering all nodes is acceptable. */
                                }}
                            >
                                <NodeBody
                                    node={n}
                                    def={nodeDefs?.[n.type ?? '']}
                                    w={w}
                                    h={h}
                                    lodTiers={lodTiers}
                                    workflowId={workflowId}
                                />
                            </div>
                        );
                    })}
                {/* Regular (non-sticky) nodes — rendered after the edge layer so they
                    paint above edges. (Edge SVG is at container level, not here, so
                    z-order in the DOM here doesn't enforce it — we use zIndex on the
                    SVG instead, see below.) */}
                {nodes
                    .filter((n) => n.type !== 'stickyNote')
                    .map((n) => {
                        const { w, h } = nodeDims(n);
                        const isUpdating = editingNodeIds?.has(n.id) ?? false;
                        // Preview stories reserve the next node's place before
                        // revealing it: it must hold its box (so the camera
                        // frames the space) and paint nothing — including its
                        // caption, which would otherwise appear beside a node
                        // that has no edge yet.
                        const reserved =
                            (n.data as { _previewHidden?: boolean } | undefined)
                                ?._previewHidden === true;
                        if (reserved) {
                            return (
                                <div
                                    key={n.id}
                                    data-node-id={n.id}
                                    aria-hidden="true"
                                    style={{
                                        position: 'absolute',
                                        top: 0,
                                        left: 0,
                                        width: w,
                                        height: h,
                                        transform: `translate(${n.position.x}px, ${n.position.y}px)`,
                                        visibility: 'hidden',
                                    }}
                                />
                            );
                        }
                        return (
                            <div
                                key={n.id}
                                data-node-id={n.id}
                                style={{
                                    position: 'absolute',
                                    top: 0,
                                    left: 0,
                                    transform: `translate(${n.position.x}px, ${n.position.y}px)`,
                                    zIndex: isUpdating ? 3 : 2,
                                }}
                            >
                                <NodeBody
                                    node={n}
                                    def={nodeDefs?.[n.type ?? '']}
                                    w={w}
                                    h={h}
                                    lodTiers={lodTiers}
                                    workflowId={workflowId}
                                />
                            </div>
                        );
                    })}
            </div>
            {/* Edge SVG — container-sized (not in transform parent), viewBox shows
                the current canvas region. zIndex 1 = above stickies, below regular
                nodes. The viewBox is computed in JSX from transformRef + container
                size so React's reconciliation during a node-drag re-render doesn't
                reset it to a stale placeholder; applyTransform() uses the same
                formula for imperative updates during gestures. */}
            {(() => {
                const cw = containerRef.current?.clientWidth ?? 0;
                const ch = containerRef.current?.clientHeight ?? 0;
                const t = transformRef.current;
                const vbW = cw > 0 ? cw / t.k : 1000;
                const vbH = ch > 0 ? ch / t.k : 1000;
                const viewBox = `${-t.x / t.k} ${-t.y / t.k} ${vbW} ${vbH}`;
                return (
                    <svg
                        ref={svgElRef}
                        style={{
                            position: 'absolute',
                            inset: 0,
                            pointerEvents: 'none',
                            zIndex: 1,
                            /* translateZ(0) forces this SVG into its own composited layer,
                       independent of the transform parent's repaint cycle. Without
                       it, iOS Safari sometimes paints the SVG behind the transform
                       parent's contents (esp. stickies) during gesture animations
                       because both compete in the outer container's stacking ctx. */
                            transform: 'translateZ(0)',
                            willChange: 'transform',
                        }}
                        viewBox={viewBox}
                    >
                        {/* Match the desktop edge style from utils/workflowLayout.ts:
                    white dashed stroke, width 3, opacity 0.8. Each path is memoized
                    so only edges whose `d` actually changes (i.e. those connected to
                    a dragged node) get reconciled — others' DOM stays untouched, no
                    flicker. */}
                        {edgePaths.map((p) => (
                            <EdgePath key={p.id} d={p.d} />
                        ))}
                    </svg>
                );
            })()}
            {children}
        </div>
    );
}

export const ForkCanvas = forwardRef<ForkCanvasRef, ForkCanvasProps>(
    ForkCanvasInner
);
ForkCanvas.displayName = 'ForkCanvas';

// Backward-compat alias for the original mobile-only name. Existing callers that
// import { MobileFlowCanvas } from '...' keep working unchanged.
export const MobileFlowCanvas = ForkCanvas;
