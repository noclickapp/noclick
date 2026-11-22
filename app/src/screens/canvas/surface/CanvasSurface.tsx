// The canvas's React Flow: how it's navigated (a trackpad's scroll pans and its pinch zooms, a drag on the empty canvas
// selects, a middle drag or Cmd/Ctrl+drag pans: useCtrlPan.ts), how far it zooms, how near a handle a dragged connection
// snaps, the line drawn while one is dragged, and that a frozen canvas (a run's replay) is only looked at. Whoever draws
// it hands the graph, the node and edge types and what each change does (useSurfaceEditing.ts), and draws what goes
// inside it (the grid, other people's pointers) as its children.
import { ReactFlow, type ReactFlowProps, type Edge, type Node } from '@xyflow/react';
import '@xyflow/react/dist/style.css';
import { CustomConnectionLine } from '../edges/CustomConnectionLine';

// The dragged line in the drawn connections' own colour, soft gray in light and white in dark.
const CONNECTION_LINE_STYLE = { stroke: 'hsl(var(--canvas-edge))', strokeWidth: 3, opacity: 0.8, strokeDasharray: '5 5' };
const FIT_VIEW_OPTIONS = { padding: 0.2 };
const FILL = { width: '100%', height: '100%' };
const PRO_OPTIONS = { hideAttribution: true };
// Only the middle button drags the view; the left one selects.
const PAN_ON_DRAG = [1];

export type CanvasSurfaceProps = Pick<
    ReactFlowProps<Node, Edge>,
    | 'nodes'
    | 'edges'
    | 'nodeTypes'
    | 'edgeTypes'
    | 'onNodesChange'
    | 'onEdgesChange'
    | 'onConnect'
    | 'onConnectEnd'
    | 'isValidConnection'
    | 'onSelectionChange'
    | 'onNodeClick'
    | 'onNodeDoubleClick'
    | 'onInit'
    | 'onMoveStart'
    | 'onMoveEnd'
    | 'onMouseMove'
    | 'onMouseLeave'
    | 'onNodeDragStart'
    | 'onNodeDrag'
    | 'onNodeDragStop'
    | 'onPaneClick'
    | 'onPaneContextMenu'
    | 'onNodeContextMenu'
    | 'onSelectionContextMenu'
    | 'defaultViewport'
    | 'panActivationKeyCode'
    | 'children'
> & {
    /** Nothing moves, connects or is deleted: a run's replay, looked at only. */
    frozen?: boolean;
};

export function CanvasSurface({ frozen = false, ...props }: CanvasSurfaceProps) {
    return (
        <ReactFlow
            {...props}
            // A drop just outside a step still snaps to its nearest handle (React Flow's own reach is 20).
            connectionRadius={30}
            nodesDraggable={!frozen}
            nodesConnectable={!frozen}
            deleteKeyCode={frozen ? null : undefined}
            elevateNodesOnSelect={false}
            onlyRenderVisibleElements={false}
            connectionLineStyle={CONNECTION_LINE_STYLE}
            connectionLineComponent={CustomConnectionLine}
            proOptions={PRO_OPTIONS}
            minZoom={0.05}
            maxZoom={2.5}
            fitView={false}
            fitViewOptions={FIT_VIEW_OPTIONS}
            style={FILL}
            panOnDrag={PAN_ON_DRAG}
            panOnScroll
            panOnScrollSpeed={1}
            zoomOnScroll={false}
            selectionOnDrag
        />
    );
}
