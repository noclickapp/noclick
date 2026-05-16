// A NodeToolbar that renders a fixed-size accessory next to a workflow node and
// scales it to match the canvas zoom. Extracted so the node label and the
// "Used by interface" badge share one implementation of the toolbar scaffold.

import { ReactNode } from 'react';
import { NodeToolbar, Position, useViewport } from '@xyflow/react';

interface ScaledNodeToolbarProps {
  position: Position;
  /** Distance from the node edge, in unscaled px — multiplied by zoom here. */
  offset?: number;
  transformOrigin?: string;
  children: ReactNode;
}

export function ScaledNodeToolbar({
  position,
  offset = 8,
  transformOrigin = 'top center',
  children,
}: ScaledNodeToolbarProps) {
  const { zoom } = useViewport();

  return (
    <NodeToolbar
      isVisible={true}
      position={position}
      align="center"
      offset={offset * zoom}
      // pointer-events: none on the wrapper so the toolbar's full-size outer box
      // doesn't steal clicks from the node beneath it. At low zoom the node
      // renders tiny but this wrapper keeps its natural layout size, so without
      // this every click within the toolbar rect landed on the toolbar instead
      // of the node. The child re-enables pointer events for itself.
      className="!bg-transparent !border-0 !shadow-none !p-0 !pointer-events-none"
    >
      <div style={{ transform: `scale(${zoom})`, transformOrigin, pointerEvents: 'auto' }}>
        {children}
      </div>
    </NodeToolbar>
  );
}
