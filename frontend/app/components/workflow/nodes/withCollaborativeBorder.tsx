/**
 * Higher-Order Component that wraps any node with collaborative selection border support.
 *
 * - When another user has this node selected, it shows a colored glow/border in their color.
 * - Hovering the node shows a tooltip with all collaborators who have it selected.
 *
 * This HOC only handles collaborative features. For the full node wrapper with labels,
 * use withNodeWrapper which composes this with NodeLabel.
 */

import { ComponentType, ReactNode, useState } from 'react';
import { NodeProps, useStore } from '@xyflow/react';
import { useCollaborativeNodeSelection } from '../collaboration/CollaborativeContext';

export function withCollaborativeBorder<P extends NodeProps>(
  WrappedComponent: ComponentType<P>
): ComponentType<P & { extraContent?: ReactNode }> {
  const WithCollaborativeBorder = (props: P & { extraContent?: ReactNode }) => {
    const selectingCollaborators = useCollaborativeNodeSelection(props.id);
    const [isHovered, setIsHovered] = useState(false);

    // True when more than one node is selected — used to suppress the per-node
    // edit hint during a multi-node drag-select. Returns a boolean (capped at 2
    // via early-exit) so the subscription only re-renders on the 1↔many flip.
    const multipleSelected = useStore((s: { nodeLookup: Map<string, { selected?: boolean }> }) => {
      let count = 0;
      for (const n of s.nodeLookup.values()) {
        if (n.selected) { count++; if (count > 1) return true; }
      }
      return false;
    });

    // Show the "press Enter to edit" hint only for a lone, non-hovered,
    // non-sticky selection — hovering shows the node's own toolbar (would
    // overlap) and a multi-select has no single node to edit.
    const showEditHint = props.selected && props.type !== 'stickyNote' && !multipleSelected && !isHovered;

    const borderColor = selectingCollaborators.length > 0 ? selectingCollaborators[0].color : null;

    // Apply border style when another user has this node selected
    // Use 16px to match rounded-2xl on node containers
    const borderStyle = borderColor
      ? {
          boxShadow: `0 0 0 2px ${borderColor}, 0 0 16px ${borderColor}80`,
          borderRadius: '16px',
        }
      : undefined;

    const showTooltip = isHovered && selectingCollaborators.length > 0;

    return (
      <div
        style={borderStyle}
        onMouseEnter={() => setIsHovered(true)}
        onMouseLeave={() => setIsHovered(false)}
        className="relative group w-full h-full"
      >
        <WrappedComponent {...props} />
        {props.extraContent}

        {/* Selected-node hint: press Enter to open the flow helper and edit.
            Outer wrapper owns the -translate-x-1/2 centering; the animation lives
            on the inner element so its slide transform doesn't clobber the
            centering (which produced a sideways slide instead of vertical). */}
        {showEditHint && (
          <div className="absolute bottom-full left-1/2 -translate-x-1/2 mb-2 z-40 pointer-events-none">
            <div className="flex items-center gap-1.5 rounded-full border border-border/60 dark:border-zinc-700/60 bg-popover/95 px-2 py-1 shadow-xl dark:shadow-black/40 backdrop-blur-md whitespace-nowrap animate-in fade-in slide-in-from-bottom-1 duration-150">
              <kbd className="flex h-[15px] min-w-[15px] items-center justify-center rounded-[3px] bg-foreground/[0.08] px-1 text-[10px] font-medium text-foreground/80">↵</kbd>
              <span className="text-[10px] font-medium text-muted-foreground">to edit</span>
            </div>
          </div>
        )}

        {/* Collaborator selection tooltip - shows who has this node selected.
            Anchored to the LEFT of the node (vertically centered) so it never
            collides with the label + status chip below or the action pills /
            edit hint above. */}
        {showTooltip && (
          <div
            className="absolute right-full top-1/2 -translate-y-1/2 mr-3.5 z-50 pointer-events-none"
          >
            <div className="bg-card border border-border dark:border-zinc-700 rounded-lg px-3 py-2 shadow-xl min-w-[100px]">
              <p className="text-[10px] font-medium text-muted-foreground uppercase tracking-wider mb-1.5 whitespace-nowrap">
                Selected by
              </p>
              <div className="space-y-1">
                {selectingCollaborators.map(collaborator => (
                  <div key={collaborator.id} className="flex items-center gap-2">
                    <div
                      className="w-2 h-2 rounded-full shrink-0"
                      style={{ backgroundColor: collaborator.color }}
                    />
                    <span className="text-xs text-foreground whitespace-nowrap">
                      {collaborator.name}
                    </span>
                  </div>
                ))}
              </div>
            </div>
          </div>
        )}
      </div>
    );
  };

  WithCollaborativeBorder.displayName = `WithCollaborativeBorder(${
    WrappedComponent.displayName || WrappedComponent.name || 'Component'
  })`;

  return WithCollaborativeBorder;
}
