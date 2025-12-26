/**
 * ReactFlow node component for rendering collaborator cursors.
 * By making cursors actual nodes, they automatically stay in sync with the
 * flow coordinate system and handle pan/zoom correctly.
 * These nodes are non-interactive and purely visual.
 *
 * Features:
 * - Inverse scaling: Cursor stays the same screen size regardless of zoom level
 * - High z-index: Always renders above workflow nodes
 */

import { memo } from 'react';
import { NodeProps, useViewport } from 'reactflow';

interface CollaboratorCursorData {
  name: string;
  color: string;
}

/** SVG cursor icon - classic pointer shape, sized larger for visibility */
const CursorIcon = ({ color }: { color: string }) => (
  <svg
    width="32"
    height="32"
    viewBox="0 0 24 24"
    fill="none"
    style={{ filter: 'drop-shadow(0 2px 3px rgba(0,0,0,0.5))' }}
  >
    <path
      d="M5.5 3.21V20.8c0 .45.54.67.85.35l4.86-4.86a.5.5 0 0 1 .35-.15h6.87c.48 0 .72-.58.38-.92L6.35 2.85a.5.5 0 0 0-.85.36Z"
      fill={color}
      stroke="#fff"
      strokeWidth="1.5"
      strokeLinecap="round"
      strokeLinejoin="round"
    />
  </svg>
);

function CollaboratorCursorNodeComponent({ data }: NodeProps<CollaboratorCursorData>) {
  const { zoom } = useViewport();

  // Inverse scale: when zoomed out (zoom < 1), make cursor bigger to stay visible
  // Clamp to reasonable bounds to prevent extreme scaling
  const inverseScale = Math.min(Math.max(1 / zoom, 1), 4);

  return (
    <div
      className="pointer-events-none"
      style={{
        // Apply inverse scale to maintain consistent screen size
        transform: `scale(${inverseScale})`,
        transformOrigin: 'top left',
        // Very high z-index to ensure cursor is always on top
        zIndex: 10000,
        position: 'relative',
      }}
    >
      {/* Cursor icon */}
      <CursorIcon color={data.color} />

      {/* Name label - positioned relative to the larger cursor */}
      <div
        className="absolute left-7 top-6 px-2 py-0.5 rounded text-xs font-medium whitespace-nowrap"
        style={{
          backgroundColor: data.color,
          color: '#000',
          boxShadow: '0 1px 3px rgba(0,0,0,0.3)',
        }}
      >
        {data.name}
      </div>
    </div>
  );
}

export const CollaboratorCursorNode = memo(CollaboratorCursorNodeComponent);

/** Prefix for cursor node IDs to identify them */
export const CURSOR_NODE_PREFIX = 'collab-cursor-';

/** Check if a node ID is a cursor node */
export function isCursorNode(nodeId: string): boolean {
  return nodeId.startsWith(CURSOR_NODE_PREFIX);
}
