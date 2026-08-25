// Renders a dotted "what comes next" affordance to the right of every workflow node:
// a dashed line ending in a `+` button, one per source handle that has no outgoing edge.
// Clicking the button dispatches `noclick:open-flow-helper-from-node` so FlowCanvas can
// open the Flow Helper picker with this node remembered as the source for click-to-add.
// Extracted from withNodeWrapper to keep that file focused on HOC composition.

import { useEffect } from 'react';
import { Handle, Position, useNodeConnections, useStore, useUpdateNodeInternals } from '@xyflow/react';
import { Bot, Plus } from 'lucide-react';
import { DEFAULT_EDGE_STYLE } from '~/utils/workflowLayout';
import { isAgentToolProviderType, isTriggerSource } from '~/utils/nodeSchemas';
import { CanvasDropTarget } from '~/components/workflow/CanvasDropTarget';

// Always start the line a hair past the node edge to clear the handle dot.
const HINT_GAP = 6;
// Multi-handle nodes (conditional/switch/iteration) render small text labels next to
// each source handle (e.g. "true", "false", "loop", "output") at right: -38..-68.
// The labels' opaque bg masks the line beneath, so we just extend the line past them.
const HINT_LINE_SINGLE = 40;
const HINT_LINE_MULTI = 60;
// Vertical hit area around the dashed line so the user has a forgiving target to
// grab the stub and drag a real connection out of it.
const HINT_HANDLE_HEIGHT = 18;
// Picker button is `w-6` (24px) with a 4px gap from the dashed line.
const HINT_BUTTON_SIZE = 24;
const HINT_BUTTON_GAP = 4;
// Suffix appended to a handle id to identify its corresponding hint-handle. We need
// a unique id to avoid colliding with the node's real source handle in the
// handleBounds store; consumers re-map any sourceHandle ending in this suffix back
// to the original handle id when the connection lands.
const HINT_SUFFIX = '__hint';
// Sentinel used in the hint id when the underlying handle has no id (the node's
// only/default handle). Must round-trip through `toHintHandleId`/`fromHintHandleId`.
const DEFAULT_HANDLE_SENTINEL = 'default';

const toHintHandleId = (handleId: string | null) => `${handleId ?? DEFAULT_HANDLE_SENTINEL}${HINT_SUFFIX}`;

/**
 * If `handleId` is a hint-handle id, return the underlying real handle id (or
 * null when the underlying handle is the default un-named one). Returns
 * `undefined` when `handleId` is not a hint-handle id at all.
 */
export function fromHintHandleId(handleId: string | null | undefined): string | null | undefined {
  if (!handleId || !handleId.endsWith(HINT_SUFFIX)) return undefined;
  const base = handleId.slice(0, -HINT_SUFFIX.length);
  return base === DEFAULT_HANDLE_SENTINEL ? null : base;
}

const isHintHandleId = (handleId: string | null | undefined): boolean =>
  !!handleId && handleId.endsWith(HINT_SUFFIX);

export function NextStepHintGroup({ nodeId }: { nodeId: string }) {
  // Hide all hints while the user is dragging a real connection from any handle
  const isDraggingConnection = useStore((s) => s.connection.inProgress);
  // ReactFlow stores per-handle bounds (id, x, y, width, height) once the node mounts;
  // reading from here is the only way the wrapper can discover handles defined inside
  // the wrapped node component (Conditional/Switch/Iteration etc.). Filter out the
  // hint-handles we add ourselves below so we don't render a dashed stub for them.
  const sourceHandles = useStore((s) => {
    const handles = s.nodeLookup.get(nodeId)?.internals.handleBounds?.source;
    return handles?.filter((h) => !isHintHandleId(h.id));
  });
  const nodeType = useStore((s) => s.nodeLookup.get(nodeId)?.type);
  const nodeOperation = useStore(
    (s) => (s.nodeLookup.get(nodeId)?.data as { operation?: string } | undefined)?.operation,
  );
  // Outgoing + incoming connections — drive the provider/dataflow hint rules.
  const allSourceConnections = useNodeConnections({ id: nodeId, handleType: 'source' });
  const allTargetConnections = useNodeConnections({ id: nodeId, handleType: 'target' });

  if (isDraggingConnection || !sourceHandles || sourceHandles.length === 0) return null;

  // Agent-tool-provider nodes: a node participating in dataflow (any left
  // input or right output connection) shouldn't hint the top tools→agent
  // wiring — the two roles are mutually exclusive (isValidConnection blocks
  // dataflow output on provider-wired nodes), and an input edge into a
  // provider is dead weight. Inversely, once the provider edge exists, don't
  // hint a dataflow output the validator would reject.
  const isProviderType = isAgentToolProviderType(nodeType);
  const hasProviderOut =
    isProviderType && allSourceConnections.some((c) => c.sourceHandle === 'top');
  const hasDataflow =
    isProviderType &&
    (allSourceConnections.some((c) => c.sourceHandle !== 'top') ||
      allTargetConnections.length > 0);
  // Either-or: a node with a trigger operation selected can't be a provider
  // (workflow_ops.trigger_provider_conflict) — never hint the tools wiring.
  const isTriggerMode = isTriggerSource(nodeType, nodeOperation);
  const hintableHandles = sourceHandles.filter((h) => {
    if (!isProviderType) return true;
    return h.position === Position.Top ? !hasDataflow && !isTriggerMode : !hasProviderOut;
  });
  if (hintableHandles.length === 0) return null;

  // Only handles that share a side with a sibling need the longer line — that's
  // where ReactFlow nodes (Conditional, Iteration, Switch) render small text
  // labels next to each branch handle (right: -38..-68) and the line has to
  // extend past them. A node with handles on different sides (Tool: top+right)
  // doesn't have that collision, so each side gets the shorter single-handle
  // length.
  const handlesPerSide = sourceHandles.reduce<Record<string, number>>((acc, h) => {
    acc[h.position] = (acc[h.position] ?? 0) + 1;
    return acc;
  }, {});

  // Switch renders a text label beside every source handle — including the lone
  // "default" fallback when no cases are configured — so its line must clear the
  // label even with a single handle. Conditional/iteration always have ≥2 handles,
  // so the per-side count already triggers the longer line for them.
  const rendersHandleLabels = nodeType === 'switch';

  // For each handle, the "reference axis" we measure offsets along is perpendicular
  // to the direction the stub points. Right/Left handles → vertical axis (Y);
  // Top/Bottom handles → horizontal axis (X). offsetFromCenter is then the handle's
  // position along that axis minus the average, so click-to-add can place the new
  // node above/below (or left/right of) the source, matching which branch the user
  // picked on multi-handle nodes (conditional 30/70, iteration 27/63, switch 15..85).
  const handleAxisCenter = (h: { x: number; y: number; width: number; height: number; position: Position }) =>
    isVerticalPosition(h.position) ? h.x + h.width / 2 : h.y + h.height / 2;
  const refAxis = sourceHandles.reduce((sum, h) => sum + handleAxisCenter(h), 0) / sourceHandles.length;

  // On single-handle nodes, match any outgoing source edge — legacy edges may omit
  // sourceHandle even when the handle has an explicit id (e.g. agent nodes use id="right"
  // but older saved edges have no sourceHandle). Only multi-handle nodes need per-branch
  // filtering.
  const isMulti = sourceHandles.length > 1;

  return (
    <>
      {hintableHandles.map((h) => {
        const center = handleAxisCenter(h);
        const lineWidth = ((handlesPerSide[h.position] ?? 0) > 1 || rendersHandleLabels)
          ? HINT_LINE_MULTI
          : HINT_LINE_SINGLE;
        return (
          <NextStepHint
            key={h.id ?? '__default'}
            nodeId={nodeId}
            handleId={h.id ?? null}
            filterHandleId={isMulti ? (h.id ?? null) : undefined}
            handlePosition={h.position}
            centerAlong={center}
            offsetFromCenter={center - refAxis}
            lineWidth={lineWidth}
            // MCP nodes also wire top→agent-bottom (their bundle/external
            // tools), so their top hint adds an agent directly too.
            directAddAgent={(isProviderType || nodeType === 'mcp-server') && h.position === Position.Top}
          />
        );
      })}
    </>
  );
}

const isVerticalPosition = (p: Position) => p === Position.Top || p === Position.Bottom;

// Per-direction layout for the stub: where to anchor it on the node, which axis
// to lay out the line+button along, and how to draw the dashed line itself.
function getStubLayout(position: Position, lineWidth: number, centerAlong: number) {
  const lineThickness = DEFAULT_EDGE_STYLE.strokeWidth;
  const longSide = lineWidth + HINT_BUTTON_GAP + HINT_BUTTON_SIZE;

  // Anchor: position the stub flush against the appropriate node edge, with a
  // small gap to clear the real handle dot. We explicitly null out the
  // opposite-side CSS props (`top`/`bottom`/`left`/`right`) because the
  // `.react-flow__handle-{position}` CSS class sets them to `0`, which would
  // otherwise stretch the Handle's box to fill the entire node.
  const anchor: React.CSSProperties = (() => {
    switch (position) {
      case Position.Right:
        return { left: '100%', right: 'auto', top: centerAlong, bottom: 'auto', transform: 'translateY(-50%)', marginLeft: HINT_GAP };
      case Position.Left:
        return { right: '100%', left: 'auto', top: centerAlong, bottom: 'auto', transform: 'translateY(-50%)', marginRight: HINT_GAP };
      case Position.Top:
        return { bottom: '100%', top: 'auto', left: centerAlong, right: 'auto', transform: 'translateX(-50%)', marginBottom: HINT_GAP };
      case Position.Bottom:
        return { top: '100%', bottom: 'auto', left: centerAlong, right: 'auto', transform: 'translateX(-50%)', marginTop: HINT_GAP };
    }
  })();

  const isVertical = isVerticalPosition(position);
  // Reverse the flex direction for Left/Top so the button always lands at the
  // far end of the stub (away from the node).
  const flexDirection = (
    position === Position.Right ? 'row' :
    position === Position.Left ? 'row-reverse' :
    position === Position.Bottom ? 'column' :
    'column-reverse'
  ) as React.CSSProperties['flexDirection'];

  const containerSize = isVertical
    ? { width: HINT_HANDLE_HEIGHT, height: longSide }
    : { width: longSide, height: HINT_HANDLE_HEIGHT };
  const lineSize = isVertical
    ? { width: lineThickness, height: lineWidth }
    : { width: lineWidth, height: lineThickness };
  // Draw the dashed line along the long axis of its SVG box.
  const linePath = isVertical
    ? { x1: lineThickness / 2, y1: 0, x2: lineThickness / 2, y2: lineWidth }
    : { x1: 0, y1: lineThickness / 2, x2: lineWidth, y2: lineThickness / 2 };

  return { anchor, flexDirection, containerSize, lineSize, linePath };
}

function NextStepHint({ nodeId, handleId, filterHandleId, handlePosition, centerAlong, offsetFromCenter, lineWidth, directAddAgent = false }: {
  nodeId: string;
  handleId: string | null;
  filterHandleId: string | null | undefined;
  handlePosition: Position;
  centerAlong: number;
  offsetFromCenter: number;
  lineWidth: number;
  /** Provider top hint: one-click adds an AI agent above and wires it,
   *  instead of opening the node picker. */
  directAddAgent?: boolean;
}) {
  const connections = useNodeConnections({
    id: nodeId,
    handleType: 'source',
    handleId: filterHandleId ?? undefined,
  });

  // ReactFlow only recomputes handleBounds when a node's dimensions change. The
  // hint Handle below is added to the DOM after the node mounts, so we have to
  // poke ReactFlow explicitly — otherwise nodes that don't already trigger a
  // re-measure (e.g. IterationNode, ConditionalNode, SwitchNode) end up with the
  // hint Handle in the DOM but missing from handleBounds, and connection drag
  // from it never starts. Mount/unmount-only is enough; we don't want this to
  // re-fire on every render.
  const updateNodeInternals = useUpdateNodeInternals();
  const hasHint = connections.length === 0;
  useEffect(() => {
    if (hasHint) updateNodeInternals(nodeId);
  }, [hasHint, nodeId, updateNodeInternals]);

  if (connections.length > 0) return null;

  const layout = getStubLayout(handlePosition, lineWidth, centerAlong);

  // The Handle wraps the dashed line + button so pointerdown anywhere inside
  // (including the button) bubbles up and starts a connection drag. A non-drag
  // click on the button still opens the picker — it stops propagation only on
  // click, not pointerdown, so ReactFlow's drag-threshold cancellation lets the
  // click through to fire normally.
  return (
    <Handle
      type="source"
      position={handlePosition}
      id={toHintHandleId(handleId)}
      className="nodrag"
      style={{
        position: 'absolute',
        background: 'transparent',
        border: 'none',
        borderRadius: 0,
        minWidth: 0,
        minHeight: 0,
        ...layout.containerSize,
        ...layout.anchor,
        pointerEvents: 'all',
        cursor: 'crosshair',
        display: 'flex',
        flexDirection: layout.flexDirection,
        alignItems: 'center',
        justifyContent: 'flex-start',
        gap: HINT_BUTTON_GAP,
        padding: 0,
        zIndex: 1,
      }}
    >
      <svg
        {...layout.lineSize}
        overflow="visible"
        // pointer-events: none so the parent Handle gets the events instead of the path
        style={{ pointerEvents: 'none', flex: '0 0 auto' }}
      >
        <line
          {...layout.linePath}
          stroke={DEFAULT_EDGE_STYLE.stroke}
          strokeWidth={DEFAULT_EDGE_STYLE.strokeWidth}
          strokeDasharray={DEFAULT_EDGE_STYLE.strokeDasharray}
          opacity={DEFAULT_EDGE_STYLE.opacity}
        />
      </svg>
      {/* Dropping a palette node on the "+" chains it off this handle — same
          wiring the click flow produces, minus the picker. A provider's top hint
          only ever means "add an agent above", so it accepts just the types that
          can receive a tools edge on their bottom. */}
      <CanvasDropTarget
        id={`node-tail-drop-${nodeId}-${handleId ?? 'default'}`}
        kind="node-tail-drop"
        payload={{ nodeId, handleId, handlePosition, offsetFromCenter, directAddAgent }}
        accepts={(t) =>
          directAddAgent ? t === 'agent' || t === 'mcp-server' : t !== 'stickyNote'
        }
        style={{ flex: '0 0 auto', position: 'relative', lineHeight: 0 }}
      >
        {({ isOver }) => (
          <>
            {isOver && (
              <span className="absolute -inset-1 rounded-lg border-2 border-dashed border-primary dark:border-foreground bg-primary/15 dark:bg-foreground/15 pointer-events-none" />
            )}
      <button
        type="button"
        onClick={(e) => {
          e.stopPropagation();
          if (directAddAgent) {
            // Provider top hint: skip the picker entirely — add an AI agent
            // directly above and wire provider.top → agent.bottom. The
            // explicit source/targetHandle make the add deterministic even
            // when no agent exists on canvas yet (pickTargetHandle can only
            // learn handle layouts from live instances).
            document.dispatchEvent(new CustomEvent('noclick:add-connected-node', {
              detail: {
                nodeType: 'agent',
                targetHandle: 'bottom',
                source: { nodeId, handleId, handlePosition, handleOffsetFromCenter: offsetFromCenter },
              },
            }));
            return;
          }
          // handleId targets the specific branch on multi-handle nodes (true/false
          // on conditional, output/loop on iteration); handlePosition tells the
          // click-to-add pipeline which side the source is on so the new node lands
          // in the right direction and (for top handles on tool/mcp/etc.) wires to
          // the agent's bottom handle instead of its default left input.
          // offsetFromCenter places the new node visually above/below (or beside)
          // the source for the picked branch.
          document.dispatchEvent(new CustomEvent('noclick:open-flow-helper-from-node', { detail: { nodeId, handleId, handlePosition, offsetFromCenter } }));
        }}
        className="flex items-center justify-center w-6 h-6 rounded-md bg-card border border-border dark:border-zinc-700/70 text-foreground/80 opacity-70 hover:opacity-100 hover:bg-accent hover:border-muted-foreground/40 dark:hover:border-zinc-500 hover:text-foreground hover:scale-110 transition-all duration-150"
        style={{ flex: '0 0 auto', cursor: 'pointer' }}
        title={directAddAgent ? 'Add an AI agent that can use this node\'s actions' : 'Add next node'}
      >
        {directAddAgent
          ? <Bot className="w-3.5 h-3.5" strokeWidth={2.25} />
          : <Plus className="w-3.5 h-3.5" strokeWidth={2.5} />}
      </button>
          </>
        )}
      </CanvasDropTarget>
    </Handle>
  );
}
