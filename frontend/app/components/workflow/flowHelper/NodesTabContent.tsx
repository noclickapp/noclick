import { useEffect, useMemo, useState } from 'react';
import { useDraggable } from '@dnd-kit/core';
import { X } from 'lucide-react';
import { OpenAI } from '@lobehub/icons';
import { isTextEntryTarget } from '~/lib/keyboard';
import { KeyHint } from '~/components/shared/KeyHint';
import { DragHintBadge } from '../DragHintBadge';
import { MiniStickyNotePreview } from '../nodes/MiniStickyNotePreview';
import {
    getSearchableNodes,
    type NodeDefinition,
    type NodeDimensions,
} from '../nodes/nodeRegistry';
import { IMG_META } from '../nodes/base/AgentModelIcon';
import { resolveAgentModelKind } from '~/lib/harnessBrand';
import { BrandIcon } from '~/components/shared/BrandIcon';
import {
    buildAgentInitialConfig,
    describeAgentSeed,
    doesAgentQueryMatch,
} from '~/lib/agentModelMatch';
import { useModels } from '~/hooks/useModels';
import { scaled } from '~/lib/constants';
import type { Model } from '~/types/model';
import {
    buildNodeSearchIndexEntry,
    getNodeSearchScore,
    getOperationSearchMatch,
    type NodeSearchIndexEntry,
} from '~/utils/nodeSearchMatch';

// Sized to scale with the active root-font-size tier.
// BASE_PREVIEW_SIZE is exported so FlowCanvas's drag overlay can match it
// — the overlay must be the same visual size as the source tile or the
// drag feels detached from the cursor.
export const BASE_PREVIEW_SIZE = 90;
const BASE_TILE_HEIGHT = 118;
const BASE_ROW_GAP = 12;

interface NodeSearchMatch {
    node: NodeDefinition;
    initialConfig?: Record<string, unknown> | null;
    initialOperation?: string | null;
    seedLabel?: string | null;
    score: number;
}

// Interface blocks are deliberately large & rectangular on the canvas (media,
// forms and tables need the room), but in the palette they must read as square
// tiles with a standard-sized icon like every other node tag — their true
// aspect/size would make lopsided, oversized tiles with a shrunken icon. Fall
// them back to the standard 90×90 node footprint for palette rendering only.
const INTERFACE_TILE_DIMS: NodeDimensions = {
    width: 90,
    height: 90,
    iconSize: 48,
};
// The Multimedia glyph is a wide/short traced mark, so at the standard iconSize it
// reads smaller than the square interface icons — give it a larger size so it looks
// comparable in the palette.
const MULTIMEDIA_TILE_DIMS: NodeDimensions = {
    width: 90,
    height: 90,
    iconSize: 60,
};
function paletteDimsForNode(node: NodeDefinition): NodeDimensions {
    if (node.type === 'interface-file') return MULTIMEDIA_TILE_DIMS;
    return node.type.startsWith('interface-')
        ? INTERFACE_TILE_DIMS
        : node.dimensions;
}

// Preview width follows the node's aspect ratio so wider nodes (e.g. Agent,
// 1.43:1) render true to shape; height matches the scaled preview size.
function previewSizeForNode(node: NodeDefinition): {
    width: number;
    height: number;
} {
    const previewSize = scaled(BASE_PREVIEW_SIZE);
    const dims = paletteDimsForNode(node);
    const aspectRatio = dims.width / dims.height;
    return { width: previewSize * aspectRatio, height: previewSize };
}

interface NodesTabContentProps {
    searchQuery: string;
    /** Resets the parent's search state. Surfaced as a "Clear search" button
     *  in the no-results empty state so users don't have to mouse back up to
     *  the search bar to recover. */
    onClearSearch?: () => void;
}

// The palette node list and its schema-backed search index are pure functions of
// the static registry + node schemas, so both are built ONCE per session at
// module scope — not per mount. The index build touches every operation's schema
// (~9.5k ops), so rebuilding it on every "N" press was the dominant open cost.
let _paletteNodes: NodeDefinition[] | null = null;
function getPaletteNodes(): NodeDefinition[] {
    if (_paletteNodes) return _paletteNodes;
    // Sticky notes pinned first (common quick-access); Agent pinned right after so
    // it lands in a full first row alongside other 1×1 tiles (if it were last it
    // would often be alone on its own flex row and `flex-grow: 1` would stretch it).
    const nodes = getSearchableNodes();
    _paletteNodes = [...nodes].sort((a, b) => {
        if (a.type === 'stickyNote') return -1;
        if (b.type === 'stickyNote') return 1;
        if (a.type === 'agent') return -1;
        if (b.type === 'agent') return 1;
        return 0;
    });
    return _paletteNodes;
}

let _searchIndex: Map<string, NodeSearchIndexEntry> | null = null;
function getNodeSearchIndex(): Map<string, NodeSearchIndexEntry> {
    if (_searchIndex) return _searchIndex;
    _searchIndex = new Map(
        getPaletteNodes().map((node) => [
            node.type,
            buildNodeSearchIndexEntry(node),
        ])
    );
    return _searchIndex;
}

export function NodesTabContent({
    searchQuery,
    onClearSearch,
}: NodesTabContentProps) {
    // Live catalog drives free-form model matching ("deepseek r1" → the newest
    // matching OpenRouter id). Hook returns [] while fetching, so the matcher
    // gracefully degrades to CLI-only matching during cold load.
    const { models } = useModels();

    // Stable module singletons — no per-mount rebuild.
    const availableNodes = getPaletteNodes();

    // Warm the search index in the background on first open so the first
    // keystroke is instant, without ever blocking the browse-open path — the
    // index is only consumed once the user actually types a query.
    useEffect(() => {
        if (_searchIndex) return;
        const w = window as Window & {
            requestIdleCallback?: (cb: () => void) => number;
            cancelIdleCallback?: (id: number) => void;
        };
        const id = w.requestIdleCallback
            ? w.requestIdleCallback(() => getNodeSearchIndex())
            : window.setTimeout(() => getNodeSearchIndex(), 0);
        return () => {
            if (w.cancelIdleCallback) w.cancelIdleCallback(id);
            else clearTimeout(id);
        };
    }, []);

    const trimmedQuery = searchQuery.trim();
    const filteredMatches = useMemo<NodeSearchMatch[]>(() => {
        if (!trimmedQuery) return [];
        const q = trimmedQuery.toLowerCase();
        // Built lazily + cached at module scope; the browse path never reaches here.
        const searchIndex = getNodeSearchIndex();
        // Free-form CLI/model queries (e.g. "claude code", "codex", "opus",
        // "gpt-5.2", "deepseek r1") surface the Agent tile even though those
        // words don't appear in its label/description/type. The drop path
        // separately seeds the new agent node's model from the same query.
        const agentExtraMatch = doesAgentQueryMatch(q, models);
        return availableNodes.flatMap((node) => {
            if (node.type === 'agent' && agentExtraMatch) {
                const initialConfig = buildAgentInitialConfig(
                    trimmedQuery,
                    models
                );
                return [
                    {
                        node,
                        initialConfig,
                        seedLabel: describeAgentSeed(initialConfig, models),
                        score: Number.MAX_SAFE_INTEGER,
                    },
                ];
            }
            const entry = searchIndex.get(node.type);
            if (!entry) return [];
            // Both are scored in shared bands, so prefer whichever is stronger:
            // a node surfaced by its own name beats a sibling matched only via
            // operation field metadata, while a query that names an operation
            // still seeds it. (No flat boost — that buried node-name matches.)
            const operationMatch = getOperationSearchMatch(entry, q);
            const nodeScore = getNodeSearchScore(entry, q);
            if (
                operationMatch &&
                (nodeScore === null || operationMatch.score > nodeScore)
            ) {
                return [{ node, ...operationMatch }];
            }
            if (nodeScore !== null) return [{ node, score: nodeScore }];
            return [];
        });
    }, [trimmedQuery, availableNodes, models]).sort(
        (a, b) => b.score - a.score || a.node.label.localeCompare(b.node.label)
    );

    const displayMatches = useMemo<NodeSearchMatch[]>(() => {
        return trimmedQuery
            ? filteredMatches
            : availableNodes.map((node) => ({ node, score: 0 }));
    }, [trimmedQuery, filteredMatches, availableNodes]);

    // Keyboard add: while the node-search input is focused, ↑/↓/←/→ move a
    // highlight through the results and Enter adds the highlighted node — so a
    // node can be added entirely from the keyboard ("N" then type then Enter).
    // Gated to text-entry focus so it complements (never fights) the canvas
    // arrow-traversal, which only runs when no input is focused.
    const [highlight, setHighlight] = useState(0);
    useEffect(() => {
        setHighlight(0);
    }, [trimmedQuery]);
    useEffect(() => {
        const onKey = (e: KeyboardEvent) => {
            if (!isTextEntryTarget(e.target)) return;
            const n = displayMatches.length;
            if (n === 0) return;
            if (e.key === 'ArrowDown' || e.key === 'ArrowRight') {
                e.preventDefault();
                setHighlight((h) => (h + 1) % n);
            } else if (e.key === 'ArrowUp' || e.key === 'ArrowLeft') {
                e.preventDefault();
                setHighlight((h) => (h - 1 + n) % n);
            } else if (e.key === 'Enter') {
                const match = displayMatches[Math.min(highlight, n - 1)];
                if (!match) return;
                e.preventDefault();
                document.dispatchEvent(
                    new CustomEvent('noclick:add-connected-node', {
                        // keepSearch: stay in the node search (focused) so nodes can
                        // be added in sequence; clear the query for the next one.
                        detail: {
                            nodeType: match.node.type,
                            initialConfig: match.initialConfig,
                            initialOperation: match.initialOperation,
                            keepSearch: true,
                        },
                    })
                );
                onClearSearch?.();
            }
        };
        document.addEventListener('keydown', onKey);
        return () => document.removeEventListener('keydown', onKey);
    }, [displayMatches, highlight, onClearSearch]);

    // No-results inline message when user's search matches nothing
    if (trimmedQuery && filteredMatches.length === 0) {
        return (
            <div className="flex items-center justify-center h-full">
                <div className="flex flex-col items-center gap-3 text-center">
                    <div className="text-muted-foreground dark:text-zinc-500 text-sm">
                        No nodes found for &quot;{searchQuery}&quot;
                    </div>
                    {onClearSearch && (
                        <button
                            type="button"
                            onClick={onClearSearch}
                            className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-full text-xs font-medium bg-foreground/[0.04] hover:bg-foreground/[0.08] text-foreground/80 hover:text-foreground border border-border dark:border-white/[0.06] hover:border-muted-foreground/40 dark:hover:border-white/[0.15] transition-colors"
                        >
                            <X className="h-3.5 w-3.5" />
                            Clear search
                        </button>
                    )}
                </div>
            </div>
        );
    }

    const title = trimmedQuery
        ? `Found ${filteredMatches.length} node${filteredMatches.length !== 1 ? 's' : ''}`
        : 'Available Nodes';

    return (
        <div>
            <div className="flex items-center gap-2 mb-4">
                <div className="text-xs text-muted-foreground dark:text-zinc-500">
                    {title}
                </div>
                <DragHintBadge label="Drag or click" />
                {/* Keyboard-add hint — navigate with arrows, add with Enter. */}
                <span className="flex items-center gap-1 text-[11px] text-muted-foreground/70 dark:text-zinc-600">
                    <KeyHint keys={['up', 'down']} />
                    <KeyHint keys={['enter']} />
                    to add
                </span>
            </div>
            <div
                className="flex flex-wrap"
                style={{ rowGap: `${scaled(BASE_ROW_GAP)}px` }}
            >
                {displayMatches.map((match, i) => (
                    <DraggableNodePreview
                        key={match.node.type}
                        match={match}
                        models={models}
                        isHighlighted={i === highlight}
                    />
                ))}
                {/* Phantom spacer — absorbs extra space on the trailing
                    partial row so its tiles don't stretch wildly. Full
                    rows before it still stretch to fill because the
                    phantom only lives on the final row. */}
                <div
                    aria-hidden
                    style={{
                        flex: '99999 0 auto',
                        height: 0,
                        pointerEvents: 'none',
                    }}
                />
            </div>
        </div>
    );
}

// Draggable wrapper for a node preview. Clicking dispatches the add-node event:
// FlowCanvas appends the node connected to a primed source if one exists, or
// standalone in the centre of the visible canvas otherwise. Dragging the tile
// onto the canvas remains supported and drops the node at the cursor.
function DraggableNodePreview({
    match,
    models,
    isHighlighted,
}: {
    match: NodeSearchMatch;
    models: Model[];
    isHighlighted?: boolean;
}) {
    const { node } = match;
    // Search hits can attach a seed: Agent model hits prefill config fields;
    // operation hits preselect the operation through initialOperation.
    const initialConfig = useMemo(
        () => match.initialConfig ?? null,
        [match.initialConfig]
    );
    const seedLabel = useMemo(
        () => match.seedLabel ?? describeAgentSeed(initialConfig, models),
        [match.seedLabel, initialConfig, models]
    );

    const { attributes, listeners, setNodeRef, isDragging } = useDraggable({
        id: `workflow-node-${node.type}`,
        data: {
            type: 'workflow-node',
            nodeType: node.type,
            nodeDefinition: node,
            initialConfig,
            initialOperation: match.initialOperation,
        },
    });

    const isStickyNote = node.type === 'stickyNote';
    const preview = previewSizeForNode(node);
    // Tile's flex basis = preview width + p-1 padding on each side (8px).
    // `flex-grow: 1` shares leftover row space across tiles so the row fills
    // the panel without trailing gap; wider nodes (Agent) ask for a larger
    // basis so their visual weight stays proportional.
    const basis = preview.width + 8;
    // Bump the tile height when we're showing a seed line so the label area
    // doesn't squeeze the preview. Catalog matches can have longer names
    // (e.g. "DeepSeek V3 Chat") — allow two wrapped lines so the tile shows
    // the full name instead of clamping to an ellipsis.
    const tileHeight = scaled(
        seedLabel ? BASE_TILE_HEIGHT + 26 : BASE_TILE_HEIGHT
    );
    const addNode = () => {
        document.dispatchEvent(
            new CustomEvent('noclick:add-connected-node', {
                detail: {
                    nodeType: node.type,
                    initialConfig,
                    initialOperation: match.initialOperation,
                },
            })
        );
    };

    return (
        <div
            // content-visibility lets the browser skip layout + paint for the
            // ~120 tiles scrolled out of view, so opening the palette only pays
            // for the visible rows (the tiles are gradient/blur-heavy). The
            // intrinsic-size hint keeps the scroll height correct before an
            // off-screen tile is rendered.
            style={{
                flex: `1 0 ${basis}px`,
                height: tileHeight,
                contentVisibility: 'auto',
                containIntrinsicSize: `${Math.round(basis)}px ${tileHeight}px`,
            }}
            role="button"
            tabIndex={0}
            onClick={addNode}
            onKeyDown={(event) => {
                if (event.key !== 'Enter' && event.key !== ' ') return;
                event.preventDefault();
                addNode();
            }}
            title={
                seedLabel
                    ? `${node.description} · will initialize with ${seedLabel}`
                    : node.description
            }
            className={`flex flex-col items-center justify-center gap-1 p-1 rounded-lg transition-colors ${isHighlighted ? 'bg-foreground/[0.08] ring-1 ring-foreground/20' : ''}`}
            data-tour-target={isStickyNote ? 'sticky-note-node' : undefined}
        >
            {/* The draggable ref/listeners live on this inner wrapper (same
                size as the preview) so dnd-kit measures the preview rect
                directly — keeps the drag overlay exactly under the grab
                point without any offset math. */}
            <div
                ref={setNodeRef}
                {...attributes}
                {...listeners}
                // items-start (not items-center): when the tile grows to fit a
                // seed line, the flex-1 wrapper gets taller but the preview is
                // a fixed 90px — items-center would re-center the icon and
                // push the Agent tile's icon down relative to shorter tiles
                // sharing the row. items-start anchors every tile's icon to
                // the same y so the row stays visually aligned.
                className="flex-1 min-h-0 flex items-start justify-center"
                style={{
                    opacity: isDragging ? 0.5 : 1,
                    cursor: isDragging ? 'grabbing' : 'grab',
                    pointerEvents: isDragging ? 'none' : 'auto',
                }}
            >
                {isStickyNote ? (
                    <MiniStickyNotePreview size={scaled(BASE_PREVIEW_SIZE)} />
                ) : (
                    <MiniNodePreview
                        node={node}
                        seedModel={
                            typeof initialConfig?.model === 'string'
                                ? initialConfig.model
                                : null
                        }
                    />
                )}
            </div>
            <div className="text-center w-full leading-tight">
                <div className="text-xs text-foreground font-medium line-clamp-1 w-full">
                    {node.label}
                </div>
                {seedLabel && (
                    <div className="text-[10px] text-emerald-600/80 dark:text-emerald-400/80 line-clamp-2 w-full font-mono break-words">
                        → {seedLabel}
                    </div>
                )}
            </div>
        </div>
    );
}

// Icon for a node preview tile. An Agent tile surfaced by a harness search
// (e.g. "hermes", "claude code") carries a seeded model — render that harness's
// brand mark (the same assets the dropped node will show), oversized relative
// to the live canvas so it stays legible at tile scale (same treatment as
// WorkflowGraphPreview's agent tiles). Everything else renders the registry
// icon. Shared with FlowCanvas's drag overlay so tile and drag ghost can't drift.
export function NodePreviewIcon({
    node,
    seedModel,
    iconSize,
    className,
}: {
    node: NodeDefinition;
    /** Model the tile will seed into data.config.model (agent search hits). */
    seedModel?: string | null;
    iconSize: number;
    className?: string;
}) {
    // Light mode zeroes icon shadows via --icon-shadow-scale, same as the tile.
    const shadow =
        'drop-shadow(0 4px 12px rgba(0, 0, 0, calc(0.4 * var(--icon-shadow-scale, 1))))';
    const kind =
        node.type === 'agent' && seedModel
            ? resolveAgentModelKind(seedModel)
            : 'bot';
    if (kind === 'codex') {
        // currentColor mark: black on light, white on dark (same as AgentModelIcon).
        return (
            <OpenAI
                className={`text-zinc-900 dark:text-white ${className ?? ''}`.trim()}
                style={{ filter: shadow, width: iconSize, height: iconSize }}
            />
        );
    }
    if (kind !== 'bot') {
        const { src, alt } = IMG_META[kind];
        // Light-mode recolor rides the global img[src*=…] rules in tailwind.css.
        return (
            <img
                src={src}
                alt={alt}
                className={className}
                style={{
                    filter: shadow,
                    maxWidth: '78%',
                    maxHeight: '52%',
                    width: 'auto',
                    height: 'auto',
                }}
            />
        );
    }
    return (
        <BrandIcon
            Icon={node.Icon}
            iconColor={node.iconColor}
            className={className}
            style={{
                width: iconSize,
                height: iconSize,
                // invert(var(--brand-invert,0)) composes with the shadow so
                // monochrome marks (.brand-mono sets the var) still flip.
                filter: `invert(var(--brand-invert, 0)) ${shadow}`,
            }}
        />
    );
}

// Scaled-down node preview: shimmer background, glass overlay, icon.
// Pure presentation — the enclosing DraggableNodePreview wraps this in the
// draggable element, so this component knows nothing about drag.
function MiniNodePreview({
    node,
    seedModel,
}: {
    node: NodeDefinition;
    seedModel?: string | null;
}) {
    const { bgGradient } = node;
    const dims = paletteDimsForNode(node);
    const { width, height } = previewSizeForNode(node);
    const scaleFactor = height / dims.height;
    const iconSize = dims.iconSize * scaleFactor;

    return (
        <div
            // Default (non-branded) tile: light card→secondary gradient in light
            // mode so the theme-reactive `text-foreground` glyphs read as dark on
            // a light surface; dark mode pins the original metallic gradient
            // pixel-identically. Branded bgGradient tiles keep their inline value.
            className={`group relative rounded-2xl overflow-hidden border border-border/40 dark:border-zinc-700/40 hover:border-foreground/30 transition-all duration-500 shadow-lg hover:shadow-2xl hover:shadow-foreground/10 flex items-center justify-center ${
                bgGradient
                    ? ''
                    : 'bg-[radial-gradient(circle_at_30%_30%,hsl(var(--card)),hsl(var(--secondary)))] dark:bg-[radial-gradient(circle_at_30%_30%,rgba(63,63,70,0.4),rgba(9,9,11,0.95))]'
            }`}
            style={{
                width,
                height,
                ...(bgGradient ? { background: bgGradient } : {}),
            }}
        >
            <div className="relative flex items-center justify-center w-full h-full">
                {/* Animated background gradient mesh */}
                <div
                    className="absolute inset-0 opacity-40 group-hover:opacity-50 transition-opacity duration-500"
                    style={{
                        background:
                            'radial-gradient(circle at 70% 70%, rgba(120, 113, 108, 0.15), transparent 50%)',
                    }}
                />

                {/* Glass overlay — backdrop-blur is gated to hover so we don't
                    composite a blur layer for every tile on the grid (146 of
                    them); at 2px over the tile's own opaque gradient the blur is
                    imperceptible until hover anyway. */}
                <div className="absolute inset-0 rounded-2xl bg-gradient-to-br from-white/[0.08] via-transparent to-transparent group-hover:backdrop-blur-[2px] pointer-events-none" />

                {/* Inner soft glow */}
                <div className="absolute inset-[1px] rounded-2xl bg-gradient-radial from-white/[0.03] to-transparent opacity-0 group-hover:opacity-70 transition-opacity duration-500" />

                {/* Multi-layer shimmer effect */}
                <div className="absolute inset-0 rounded-2xl overflow-hidden pointer-events-none">
                    <div
                        className="absolute inset-0 opacity-0 group-hover:opacity-70 transition-opacity duration-500"
                        style={{
                            background:
                                'linear-gradient(110deg, transparent 0%, transparent 35%, rgba(255, 255, 255, 0.06) 45%, rgba(255, 255, 255, 0.09) 50%, rgba(255, 255, 255, 0.06) 55%, transparent 65%, transparent 100%)',
                            transform: 'translateX(-100%)',
                            animation: 'shimmer 2.5s ease-in-out infinite',
                            filter: 'blur(10px)',
                        }}
                    />
                    <div
                        className="absolute inset-0 opacity-0 group-hover:opacity-40 transition-opacity duration-500"
                        style={{
                            background:
                                'radial-gradient(circle at 50% 50%, rgba(255, 255, 255, 0.04) 0%, transparent 70%)',
                        }}
                    />
                </div>

                {/* Icon — centred with enhanced shadow */}
                <NodePreviewIcon
                    node={node}
                    seedModel={seedModel}
                    iconSize={iconSize}
                    className="relative z-10 transition-all duration-500 group-hover:scale-110 group-hover:brightness-105"
                />
            </div>
        </div>
    );
}
