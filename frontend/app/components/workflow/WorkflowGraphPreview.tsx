// WorkflowGraphPreview — browser-card thumbnail that renders a workflow's real graph
// as a faithful uniform zoom-out of the live canvas: node tiles with the canvas's
// exact footprint (90×90 automation squares, 200×140 agents, resizable interface
// blocks and sticky notes at their persisted size), radial-gradient tile background,
// centered brand icons / harness logos / app-shell wireframes / tinted stickies, plus
// the canvas's white dashed bezier edges anchored to tile sides. Everything lives in
// one SVG with a fixed viewBox so it scales like an image — no observers, state, or
// interaction machinery.

import { memo, useId, useMemo } from 'react';
import { Bot } from 'lucide-react';
import { useIsDark } from '~/hooks/useIsDark';
import { OpenAI } from '@lobehub/icons';
import { SerializedIcon } from '~/components/shared/SerializedIcon';
import type { SerializedIconEntry } from '~/components/shared/SerializedNodeIconStack';
import { IMG_META } from '~/components/workflow/nodes/base/AgentModelIcon';
import { resolveAgentModelKind, type AgentModelKind } from '~/lib/harnessBrand';
import { monochromeIconClassFromHtml } from '~/lib/monochromeIcons';
import { stickyScheme } from '~/lib/stickyColors';
import {
    DEFAULT_EDGE_STYLE,
    DEFAULT_NODE_WIDTH,
    DEFAULT_NODE_HEIGHT,
    NODE_WIDTH_MAP,
    NODE_HEIGHT_MAP,
} from '~/utils/workflowLayout';
import {
    getBackwardEdgePath,
    BACKWARD_EDGE_X_THRESHOLD,
} from '~/utils/edgePaths';
import {
    CANVAS_GRID_CSS_BG,
    CANVAS_GRID_CSS_BG_LIGHT,
} from '~/components/workflow/canvasBackground';
import { cn } from '~/lib/utils';
import type {
    GraphPreview,
    GraphPreviewNode,
} from '~/lib/workflowBrowserStore';

// The preview is a faithful zoom-out of the live canvas, so it must theme with
// it: a light mini-canvas in light mode (matching the now-light editor) and the
// original dark one in dark. SVG presentation attributes don't resolve CSS
// var(), so we resolve concrete per-theme colors and re-render on toggle.
interface GraphPalette {
    isDark: boolean;
    surface: string;
    tileSurface: string;
    gridBg: string;
    tileFrom: string;
    tileTo: string;
    tileStroke: string;
    edge: string;
    mockText: string;
    panelFill: string;
    panelStroke: string;
    codexClass: string;
}
const DARK_PALETTE: GraphPalette = {
    isDark: true,
    surface: '#09090b',
    tileSurface: '#09090b',
    gridBg: CANVAS_GRID_CSS_BG,
    tileFrom: 'rgba(63, 63, 70, 0.4)',
    tileTo: 'rgba(9, 9, 11, 0.95)',
    tileStroke: '#3f3f46',
    edge: '#fafafa',
    mockText: '#f4f4f5',
    panelFill: 'rgba(255, 255, 255, 0.08)',
    panelStroke: 'rgba(255, 255, 255, 0.14)',
    codexClass: 'text-white',
};
const LIGHT_PALETTE: GraphPalette = {
    isDark: false,
    surface: '#f1f1f4', // ≈ --canvas-bg light, so white tiles read as raised
    tileSurface: '#ffffff',
    gridBg: CANVAS_GRID_CSS_BG_LIGHT,
    tileFrom: 'rgba(255, 255, 255, 0.96)',
    tileTo: 'rgba(244, 244, 245, 0.98)',
    tileStroke: '#d4d4d8',
    edge: '#9a9aa5', // ≈ --canvas-edge in light (soft zinc gray)
    mockText: '#18181b',
    panelFill: 'rgba(0, 0, 0, 0.05)',
    panelStroke: 'rgba(0, 0, 0, 0.1)',
    codexClass: 'text-zinc-900',
};

// Keyed to the RENDERED `dark` class (not the stored preference — forced-dark
// routes render dark with a light preference stored). Re-renders on toggle.
function useGraphPalette(): GraphPalette {
    return useIsDark() ? DARK_PALETTE : LIGHT_PALETTE;
}

// Nominal drawing space; preserveAspectRatio="xMidYMid meet" keeps the scale uniform
// at any card width (the container's grid background fills any letterboxing).
const W = 320;
const H = 180;
// Asymmetric padding clears the card's overlay pill rows (logos/actions top,
// metadata bottom) so tiles never hide behind them.
const PAD_X = 22;
const PAD_TOP = 44;
const PAD_BOTTOM = 40;
const FULL_FRAME_PAD_TOP = 12;
const FULL_FRAME_PAD_BOTTOM = 12;

export type GraphPreviewFit = 'overlay-safe' | 'full-frame';

// Node footprints come from workflowLayout's shared maps; interface/sticky
// fallbacks (resizable nodes persist width/height, so these rarely apply) match
// ForkCanvas's interface default and StickyNoteNode's creation DIMENSIONS.
const FOOTPRINTS: Record<string, { w: number; h: number }> = {
    agent: { w: NODE_WIDTH_MAP['agent'], h: NODE_HEIGHT_MAP['agent'] },
    interface: { w: 320, h: 240 },
    sticky: { w: 200, h: 200 },
    tile: { w: DEFAULT_NODE_WIDTH, h: DEFAULT_NODE_HEIGHT },
};
// Tile visuals mirrored from AutomationNode (rounded-2xl, 48px icon).
const TILE_RADIUS = 16;
const ICON_SIZE = 48;

// Cap the zoom so small flows read as a zoomed-out canvas rather than blown-up tiles.
const MAX_SCALE = 0.4;

// DOM budget per card; beyond this a thumbnail is unreadable anyway. The card's
// node-count pill still shows the true total.
const MAX_TILES = 80;

// A projection node with its footprint resolved and everything scaled into the
// nominal drawing space (x/y/w/h in viewBox units; other fields pass through).
type PlacedNode = GraphPreviewNode & { w: number; h: number };

function nodeFootprint(
    type: string,
    width?: number,
    height?: number
): { w: number; h: number } {
    const fallback =
        type === 'agent'
            ? FOOTPRINTS.agent
            : type.startsWith('interface-')
              ? FOOTPRINTS.interface
              : type === 'stickyNote'
                ? FOOTPRINTS.sticky
                : FOOTPRINTS.tile;
    // `|| fallback` (not ??): a malformed persisted dimension of 0 or negative
    // would otherwise produce invisible tiles and a degenerate bounding box.
    return {
        w: (width && width > 0 && width) || fallback.w,
        h: (height && height > 0 && height) || fallback.h,
    };
}

function layoutGraph(
    graph: GraphPreview,
    fit: GraphPreviewFit
): {
    placed: PlacedNode[];
    paths: string[];
    scale: number;
    offsetX: number;
    offsetY: number;
} {
    const flowNodes = graph.nodes.slice(0, MAX_TILES);
    if (flowNodes.length === 0)
        return { placed: [], paths: [], scale: 1, offsetX: 0, offsetY: 0 };

    const rects = flowNodes.map((n) => {
        const { w, h } = nodeFootprint(n.type, n.width, n.height);
        return { ...n, w, h };
    });

    let minX = Infinity;
    let maxX = -Infinity;
    let minY = Infinity;
    let maxY = -Infinity;
    for (const r of rects) {
        if (r.x < minX) minX = r.x;
        if (r.x + r.w > maxX) maxX = r.x + r.w;
        if (r.y < minY) minY = r.y;
        if (r.y + r.h > maxY) maxY = r.y + r.h;
    }
    const bw = maxX - minX;
    const bh = maxY - minY;

    // Browser cards reserve the top/bottom bands for overlay metadata. The
    // editorial cover has no overlays in the graph frame, so it can reclaim
    // that vertical space. Keeping PAD_X unchanged is important: wide, shallow
    // flows are already width-bound and must not be cropped just to look larger.
    const padTop = fit === 'full-frame' ? FULL_FRAME_PAD_TOP : PAD_TOP;
    const padBottom = fit === 'full-frame' ? FULL_FRAME_PAD_BOTTOM : PAD_BOTTOM;
    const scale = Math.min(
        (W - 2 * PAD_X) / bw,
        (H - padTop - padBottom) / bh,
        MAX_SCALE
    );

    // Center the scaled graph inside the padded region.
    const offsetX = PAD_X + (W - 2 * PAD_X - bw * scale) / 2 - minX * scale;
    const offsetY =
        padTop + (H - padTop - padBottom - bh * scale) / 2 - minY * scale;

    const placed: PlacedNode[] = rects.map((r) => ({
        ...r,
        x: r.x * scale + offsetX,
        y: r.y * scale + offsetY,
        w: r.w * scale,
        h: r.h * scale,
    }));

    // Edge paths are built in RAW canvas coordinates and rendered inside a
    // translate+scale <g>: the shared getBackwardEdgePath's rounded-loop
    // constants are canvas pixels, so reusing it verbatim (identical loop shape
    // to the live canvas) requires canvas-space geometry.
    const rawById = new Map(rects.map((r) => [r.id, r]));
    const paths: string[] = [];
    for (const e of graph.edges) {
        const s = rawById.get(e.source);
        const t = rawById.get(e.target);
        if (!s || !t) continue;
        if (e.targetHandle === 'bottom') {
            // Tools-provider wiring: provider's top handle up into the agent's
            // underside. Vertical edges always bezier, like the canvas.
            const sx = s.x + s.w / 2;
            const sy = s.y;
            const tx = t.x + t.w / 2;
            const ty = t.y + t.h;
            const v = Math.max(controlOffset(sy - ty), 10);
            paths.push(
                `M ${sx} ${sy} C ${sx} ${sy - v}, ${tx} ${ty + v}, ${tx} ${ty}`
            );
        } else {
            // Dataflow: source right handle → target left handle.
            const sx = s.x + s.w;
            const sy = s.y + s.h / 2;
            const tx = t.x;
            const ty = t.y + t.h / 2;
            if (tx < sx - BACKWARD_EDGE_X_THRESHOLD) {
                // Loop-back to an earlier node (e.g. an iteration cycle): the
                // canvas routes these under the nodes, not as a bezier.
                paths.push(getBackwardEdgePath(sx, sy, tx, ty));
            } else {
                const c = Math.max(controlOffset(tx - sx), 16);
                paths.push(
                    `M ${sx} ${sy} C ${sx + c} ${sy}, ${tx - c} ${ty}, ${tx} ${ty}`
                );
            }
        }
    }

    return { placed, paths, scale, offsetX, offsetY };
}

// ReactFlow's getBezierPath control offset (default curvature 0.25) in canvas
// units: forward edges bow by half the distance; slightly-backward edges inside
// the loop-back threshold get the sqrt-scaled bulge.
function controlOffset(delta: number): number {
    if (delta >= 0) return delta * 0.5;
    return 6.25 * Math.sqrt(-delta);
}

// Pre-baked light-mode wordmark variants. Their colors are precomputed to match
// the tailwind.css recolor filters exactly (openclaw brightness(.65) saturate(1.4),
// opencode invert(1)), so in light mode the preview swaps the asset instead of
// applying a runtime CSS filter. A CSS filter on an <img>/<image> inside this
// viewBox-scaled <svg> mis-composites on iOS/WebKit and paints the mark OUTSIDE the
// tile (light-mode-only bug); a pre-baked asset has no filter surface at all.
const LIGHT_WORDMARK_SRC: Partial<Record<AgentModelKind, string>> = {
    openclaw: '/icons/openclaw-light.svg',
    opencode: '/icons/opencode-wordmark-light.svg',
};

// Agent tiles show the same logo assets as both live canvases (AgentModelIcon's
// IMG_META: full wordmarks, clawd mark for Claude Code; OpenAI/Bot glyphs), but
// oversized relative to the canvas so they stay legible at thumbnail zoom. Aspect
// ratio is preserved by constraining with max-width/max-height and auto sizing.
function AgentTileLogo({ n, pal }: { n: PlacedNode; pal: GraphPalette }) {
    // '' → 'bot', matching workflowIconTypes' fallback so pill and tile agree.
    const kind = resolveAgentModelKind(n.agentModel ?? '');
    // Mocked tiles show a MOCK label in the lower band, so shrink the logo and
    // lift it to make room — mirroring the non-agent TileContent path.
    const mockShrink = n.mocked ? 0.7 : 1;
    const cy = n.y + n.h * (n.mocked ? 0.4 : 0.5);

    if (kind === 'codex' || kind === 'bot') {
        const size = Math.min(n.h * 0.55, n.w * 0.5) * mockShrink;
        const Glyph = kind === 'codex' ? OpenAI : Bot;
        return (
            <foreignObject
                x={n.x + n.w / 2 - size / 2}
                y={cy - size / 2}
                width={size}
                height={size}
            >
                <div
                    style={{
                        width: size,
                        height: size,
                        display: 'flex',
                        lineHeight: 0,
                    }}
                >
                    <Glyph
                        className={
                            kind === 'codex'
                                ? pal.codexClass
                                : 'text-purple-400'
                        }
                        style={{ width: '100%', height: '100%' }}
                    />
                </div>
            </foreignObject>
        );
    }
    // Wordmark logos render as a NATIVE SVG <image> positioned in SVG user space,
    // NOT an <img> in a <foreignObject>. On iOS/WebKit, the light-mode recolor filter
    // on an <img> inside this viewBox-scaled foreignObject is promoted to a composited
    // layer whose offset is resolved in CSS coordinates — missing the SVG transform —
    // so the mark paints OUTSIDE the tile (the light-mode-only "wordmark escapes"
    // bug). <image> has no CSS box, so its geometry is immune. preserveAspectRatio
    // "meet" reproduces object-fit:contain + centering in SVG space. Light mode swaps
    // to a pre-baked recolored asset so there's no runtime filter at all. Mocked tiles
    // use a shorter band so the box centers higher, clearing the MOCK label below.
    const bandH = n.mocked ? n.h * 0.72 : n.h;
    const boxW = n.w * 0.78;
    const boxH = bandH * 0.52;
    const src = (!pal.isDark && LIGHT_WORDMARK_SRC[kind]) || IMG_META[kind].src;
    return (
        <image
            href={src}
            x={n.x + (n.w - boxW) / 2}
            y={n.y + (bandH - boxH) / 2}
            width={boxW}
            height={boxH}
            preserveAspectRatio="xMidYMid meet"
        />
    );
}

// Interface blocks read as an app-shell wireframe — sidebar, header bar, large main
// panel, two bottom panels — instead of pretending to render the real block.
// Proportional to the block's persisted size.
function InterfaceTileSkeleton({
    n,
    pal,
}: {
    n: PlacedNode;
    pal: GraphPalette;
}) {
    const pad = Math.min(n.w, n.h) * 0.07;
    const gap = Math.min(n.w, n.h) * 0.045;
    const x0 = n.x + pad;
    const y0 = n.y + pad;
    const innerW = n.w - pad * 2;
    const innerH = n.h - pad * 2;
    const sideW = innerW * 0.24;
    const rightX = x0 + sideW + gap;
    const rightW = innerW - sideW - gap;
    const headerH = innerH * 0.13;
    const bottomH = innerH * 0.18;
    const mainY = y0 + headerH + gap;
    const mainH = innerH - headerH - bottomH - gap * 2;
    const bottomY = y0 + innerH - bottomH;
    const halfW = (rightW - gap) / 2;
    const r = Math.min(n.w, n.h) * 0.035;
    const panel = {
        fill: pal.panelFill,
        stroke: pal.panelStroke,
        strokeWidth: 0.6,
    };
    return (
        <g>
            {/* sidebar */}
            <rect
                x={x0}
                y={y0}
                width={sideW}
                height={innerH}
                rx={r}
                {...panel}
            />
            {/* header bar, main panel, two bottom panels */}
            <rect
                x={rightX}
                y={y0}
                width={rightW}
                height={headerH}
                rx={r}
                {...panel}
            />
            <rect
                x={rightX}
                y={mainY}
                width={rightW}
                height={mainH}
                rx={r}
                {...panel}
            />
            <rect
                x={rightX}
                y={bottomY}
                width={halfW}
                height={bottomH}
                rx={r}
                {...panel}
            />
            <rect
                x={rightX + halfW + gap}
                y={bottomY}
                width={halfW}
                height={bottomH}
                rx={r}
                {...panel}
            />
        </g>
    );
}

// Sticky notes render behind everything at their real size, tinted with the same
// palette the canvas sticky uses (bg + muted border by config.color index). An
// opaque surface-colored underlay sits beneath the translucent tint so the grid
// doesn't bleed through (at thumbnail scale the 14px grid reads as noise inside
// nodes; the composite still matches the canvas look, whose surface is uniform).
function StickyRect({
    n,
    scale,
    pal,
}: {
    n: PlacedNode;
    scale: number;
    pal: GraphPalette;
}) {
    const scheme = stickyScheme(n.stickyColor, pal.isDark);
    const rx = Math.min(6 * scale, n.w / 4);
    return (
        <g>
            <rect
                x={n.x}
                y={n.y}
                width={n.w}
                height={n.h}
                rx={rx}
                fill={pal.tileSurface}
            />
            <rect
                x={n.x}
                y={n.y}
                width={n.w}
                height={n.h}
                rx={rx}
                fill={scheme.bg}
                stroke={scheme.border}
                strokeWidth={Math.max(2 * scale, 0.5)}
            />
        </g>
    );
}

function TileContent({
    n,
    scale,
    pal,
    invertFilterId,
    nodeIcons,
}: {
    n: PlacedNode;
    scale: number;
    pal: GraphPalette;
    invertFilterId: string;
    nodeIcons: Readonly<Record<string, SerializedIconEntry>>;
}) {
    if (n.type === 'agent') return <AgentTileLogo n={n} pal={pal} />;
    if (n.type.startsWith('interface-'))
        return <InterfaceTileSkeleton n={n} pal={pal} />;
    const meta = nodeIcons[n.type];
    if (!meta?.iconHtml) return null;
    // Mocked nodes mirror the canvas (AutomationNode scales the icon 0.7 and
    // shows the MOCK label): icon shrinks and shifts up to make room.
    const icon = Math.min(ICON_SIZE * scale, n.h * 0.6) * (n.mocked ? 0.7 : 1);
    const cy = n.y + n.h * (n.mocked ? 0.4 : 0.5);
    const x = n.x + n.w / 2 - icon / 2;
    const y = cy - icon / 2;
    // Image-based brand marks render as a native SVG <image>: a <foreignObject> <img>
    // rasterizes at CSS resolution (blurry on iOS retina), and a monochrome mark's
    // light-mode invert filter on that <img> mis-composites and displaces the icon —
    // the same iOS bug as the wordmark. Monochrome marks (cal-com, notion, …) invert
    // in light via a color-only SVG filter on a wrapping <g> (an SVG filter is applied
    // in user space, so it doesn't displace and, being color-only, doesn't blur).
    // Inline-<svg> brand icons keep the foreignObject path — they're multicolor with
    // no filter, so they neither displace nor need recoloring.
    // meta.iconHtml is either an inline <svg>, or an <img> (sometimes preceded by a
    // <link rel="preload">), so match the <img src> ANYWHERE — the same way
    // monochromeIconClassFromHtml reads it — rather than assuming a leading <img>.
    const imgSrc = meta.iconHtml.match(/<img[^>]*\ssrc="([^"]+)"/)?.[1];
    if (imgSrc) {
        const invert =
            !pal.isDark &&
            monochromeIconClassFromHtml(meta.iconHtml) === 'brand-mono';
        const image = (
            <image
                href={imgSrc}
                x={x}
                y={y}
                width={icon}
                height={icon}
                preserveAspectRatio="xMidYMid meet"
            />
        );
        return invert ? (
            <g filter={`url(#${invertFilterId})`}>{image}</g>
        ) : (
            image
        );
    }
    return (
        <foreignObject x={x} y={y} width={icon} height={icon}>
            {/* Block-level flex wrapper with explicit px size: SerializedIcon's
                inline-flex span would otherwise sit on a text baseline and get
                pushed below the foreignObject's default-clipped viewport. */}
            <div
                style={{
                    width: icon,
                    height: icon,
                    display: 'flex',
                    lineHeight: 0,
                }}
            >
                <SerializedIcon
                    html={meta.iconHtml}
                    iconColor={meta.iconColor}
                    className="w-full h-full"
                />
            </div>
        </foreignObject>
    );
}

// Mirrors the canvas disabled treatment (grayscale + dimmed content).
const DISABLED_STYLE = { filter: 'grayscale(1)', opacity: 0.35 } as const;

// The canvas's disabled badge: a lucide Ban (circle + diagonal slash, zinc-500
// @50%, iconSize × 1.15) centered over the icon — drawn natively in SVG.
function DisabledBanOverlay({ n, scale }: { n: PlacedNode; scale: number }) {
    const r = (Math.min(ICON_SIZE * scale, n.h * 0.6) * 1.15) / 2;
    const cx = n.x + n.w / 2;
    const cy = n.y + n.h / 2;
    const o = r * Math.SQRT1_2; // 45° slash endpoints on the circle, like lucide's Ban
    return (
        <g
            stroke="#71717a"
            strokeOpacity={0.5}
            strokeWidth={Math.max(r * 0.2, 0.6)}
            strokeLinecap="round"
            fill="none"
        >
            <circle cx={cx} cy={cy} r={r} />
            <line x1={cx - o} y1={cy - o} x2={cx + o} y2={cy + o} />
        </g>
    );
}

interface WorkflowGraphPreviewProps {
    graph: GraphPreview;
    /** Serialized node icon metadata. Injected by the dashboard registry in the
     * app and by nodeCatalog.server on public marketing routes, keeping this SVG
     * renderer pure and registry-free. */
    nodeIcons: Readonly<Record<string, SerializedIconEntry>>;
    className?: string;
    /** Let a parent card's surface/gradient show through. The graph still
     * renders its faithful nodes and edges, but does not paint a mini-canvas
     * rectangle or a second grid behind them. */
    transparentCanvas?: boolean;
    /** Reclaim the overlay-safe top/bottom bands for large editorial frames.
     * Horizontal padding stays intact so wide workflows never clip. */
    fit?: GraphPreviewFit;
}

function WorkflowGraphPreviewComponent({
    graph,
    nodeIcons,
    className,
    transparentCanvas = false,
    fit = 'overlay-safe',
}: WorkflowGraphPreviewProps) {
    const uid = useId().replace(/[^a-zA-Z0-9]/g, '');
    const pal = useGraphPalette();
    const { placed, paths, scale, offsetX, offsetY } = useMemo(
        () => layoutGraph(graph, fit),
        [fit, graph]
    );

    // Canvas paint order: stickies are annotations behind everything, then edges,
    // then node tiles. Zero-node workflows naturally render as a blank canvas
    // (surface + grid, empty svg).
    const stickies = placed.filter((n) => n.type === 'stickyNote');
    const tiles = placed.filter((n) => n.type !== 'stickyNote');

    // Zoom-compensated edge stroke: scaling the canvas's 3px linearly reads
    // gossamer on heavily zoomed-out graphs, so width/dash follow a sub-linear
    // power of the zoom with floors. Values are view units; the edge layer
    // renders inside the scaled group, hence the /scale at the use site.
    const edgeWidthView = Math.max(
        DEFAULT_EDGE_STYLE.strokeWidth * Math.pow(scale, 0.8),
        1
    );
    const edgeDashView = Math.max(5 * Math.pow(scale, 0.8), 1.6);
    const tileGradientId = `wgp-tile-${uid}`;
    // Per-instance id — inline SVGs share a document; a bare "#invert" would collide
    // across the many preview cards on one page (the same reason tileGradientId is uid-scoped).
    const invertFilterId = `wgp-invert-${uid}`;

    return (
        <div
            className={cn('relative overflow-hidden', className)}
            data-graph-fit={fit}
            style={{
                backgroundColor: transparentCanvas
                    ? 'transparent'
                    : pal.surface,
                backgroundImage: transparentCanvas ? 'none' : pal.gridBg,
            }}
        >
            <svg
                className="absolute inset-0 w-full h-full"
                viewBox={`0 0 ${W} ${H}`}
                preserveAspectRatio="xMidYMid meet"
                aria-hidden="true"
            >
                <defs>
                    {/* AutomationNode's tile background: radial-gradient(circle at 30% 30%, …) */}
                    <radialGradient
                        id={tileGradientId}
                        cx="30%"
                        cy="30%"
                        r="90%"
                    >
                        <stop offset="0%" stopColor={pal.tileFrom} />
                        <stop offset="100%" stopColor={pal.tileTo} />
                    </radialGradient>
                    {/* Light-mode invert for monochrome brand marks (cal-com, notion,
                        …), replacing the CSS `filter: invert(1)` that would displace an
                        <img> in a foreignObject on iOS. A color-only SVG filter is
                        applied in user space (no displacement, no perceptible blur).
                        colorInterpolationFilters="sRGB" so it matches CSS invert()
                        (SVG filters default to linearRGB). */}
                    <filter
                        id={invertFilterId}
                        colorInterpolationFilters="sRGB"
                    >
                        <feComponentTransfer>
                            <feFuncR type="table" tableValues="1 0" />
                            <feFuncG type="table" tableValues="1 0" />
                            <feFuncB type="table" tableValues="1 0" />
                        </feComponentTransfer>
                    </filter>
                </defs>
                {stickies.map((n) => (
                    <StickyRect key={n.id} n={n} scale={scale} pal={pal} />
                ))}
                {/* Edge paths are canvas-space (see layoutGraph); this group maps
                    them into the view like the node scaling does. */}
                <g
                    transform={`translate(${offsetX} ${offsetY}) scale(${scale})`}
                >
                    {paths.map((d, i) => (
                        <path
                            key={i}
                            d={d}
                            fill="none"
                            stroke={pal.edge}
                            strokeWidth={edgeWidthView / scale}
                            strokeDasharray={`${edgeDashView / scale} ${edgeDashView / scale}`}
                            opacity={DEFAULT_EDGE_STYLE.opacity}
                        />
                    ))}
                </g>
                {tiles.map((n) => {
                    const rx = Math.min(TILE_RADIUS * scale, n.w / 4);
                    return (
                        <g key={n.id}>
                            {/* Opaque underlay: the tile gradient is translucent (mirrors
                                AutomationNode) and would otherwise show the grid through it. */}
                            <rect
                                x={n.x}
                                y={n.y}
                                width={n.w}
                                height={n.h}
                                rx={rx}
                                fill={pal.tileSurface}
                            />
                            <rect
                                x={n.x}
                                y={n.y}
                                width={n.w}
                                height={n.h}
                                rx={rx}
                                fill={`url(#${tileGradientId})`}
                                stroke={pal.tileStroke}
                                strokeOpacity={n.disabled ? 0.4 : 0.7}
                                strokeWidth={0.75}
                            />
                            <g style={n.disabled ? DISABLED_STYLE : undefined}>
                                <TileContent
                                    n={n}
                                    scale={scale}
                                    pal={pal}
                                    invertFilterId={invertFilterId}
                                    nodeIcons={nodeIcons}
                                />
                            </g>
                            {n.disabled && (
                                <DisabledBanOverlay n={n} scale={scale} />
                            )}
                            {/* MOCK label ratio mirrors AutomationNode: 18px on a 90px tile = 0.2 */}
                            {n.mocked && (
                                <text
                                    x={n.x + n.w / 2}
                                    y={n.y + n.h * 0.78}
                                    textAnchor="middle"
                                    // Height-proportional, but capped by width so
                                    // "MOCK" (~3.3em wide) never overflows narrow
                                    // tiles when the fit-scale is small. No floor —
                                    // a fixed minimum overflows once the tile
                                    // shrinks below it.
                                    fontSize={Math.min(n.h * 0.2, n.w * 0.26)}
                                    fontWeight={700}
                                    letterSpacing="0.08em"
                                    fill={pal.mockText}
                                    style={
                                        n.disabled ? DISABLED_STYLE : undefined
                                    }
                                >
                                    MOCK
                                </text>
                            )}
                        </g>
                    );
                })}
            </svg>
        </div>
    );
}

export const WorkflowGraphPreview = memo(WorkflowGraphPreviewComponent);
