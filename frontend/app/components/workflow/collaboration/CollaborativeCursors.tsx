/**
 * Overlay component that renders collaborator cursors on the flow canvas.
 * Cursors are positioned using flow coordinates transformed to container-relative
 * coordinates via the viewport (zoom and pan). Each cursor shows the user's color and name.
 */

import { memo, useMemo } from 'react';
import { useViewport } from '@xyflow/react';
import type { Collaborator } from '~/lib/collaboration';

interface CollaborativeCursorsProps {
  collaborators: Collaborator[];
}

/** SVG cursor icon - classic pointer shape, sized larger for visibility */
const CursorIcon = ({ color }: { color: string }) => (
  <svg
    width="24"
    height="24"
    viewBox="0 0 24 24"
    fill="none"
    style={{ filter: 'drop-shadow(0 1px 2px rgba(0,0,0,0.5))' }}
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

function CollaborativeCursorsComponent({ collaborators }: CollaborativeCursorsProps) {
  // Get viewport transform (pan and zoom) to convert flow coords to container coords
  const { x: panX, y: panY, zoom } = useViewport();

  // Filter to only collaborators with active cursors
  const activeCursors = useMemo(
    () => collaborators.filter(c => c.cursor !== null && c.isActive),
    [collaborators]
  );

  if (activeCursors.length === 0) return null;

  return (
    <div className="absolute inset-0 pointer-events-none overflow-hidden z-50">
      {activeCursors.map(collaborator => {
        if (!collaborator.cursor) return null;

        // Convert flow coordinates to container-relative coordinates
        // Formula: containerPos = (flowPos * zoom) + pan
        // Offset by (-6, -3) to align the cursor tip (which is at ~5.5, 3 in the SVG)
        const containerX = (collaborator.cursor.x * zoom) + panX - 6;
        const containerY = (collaborator.cursor.y * zoom) + panY - 3;

        return (
          <div
            key={collaborator.id}
            className="absolute left-0 top-0"
            style={{
              // Use transform for hardware-accelerated positioning
              transform: `translate(${containerX}px, ${containerY}px)`,
            }}
          >
            {/* Cursor icon */}
            <CursorIcon color={collaborator.color} />

            {/* Name label */}
            <div
              className="absolute left-5 top-4 px-2 py-0.5 rounded text-xs font-medium whitespace-nowrap"
              style={{
                backgroundColor: collaborator.color,
                color: '#000',
                boxShadow: '0 1px 3px rgba(0,0,0,0.3)',
              }}
            >
              {collaborator.name}
            </div>
          </div>
        );
      })}
    </div>
  );
}

export const CollaborativeCursors = memo(CollaborativeCursorsComponent);
