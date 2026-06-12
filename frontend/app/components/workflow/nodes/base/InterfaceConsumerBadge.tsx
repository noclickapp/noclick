// Badge shown in a node's bottom stack (rendered by NodeLabel, below the label +
// status chip) when the node is referenced by one or more interface-html-react
// nodes through the @noclick/sdk. SDK-based interfaces reference other nodes by
// bare ID inside their code rather than through canvas edges, so this dependency
// is otherwise invisible — true even for connected nodes, since an edge doesn't
// reveal that an interface drives or reads the node. Hovering shows the full
// interface name(s) as links; clicking the badge — or an individual link — pans
// the canvas to the interface(s). Self-hides (returns null) when there are no
// consumers. Has no toolbar/positioning of its own: NodeLabel owns the single
// Bottom NodeToolbar so label, chip, and this badge always flow vertically.

import { useState } from 'react';
import { useReactFlow } from '@xyflow/react';
import { Code2, ArrowUpRight } from 'lucide-react';
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '~/components/ui/tooltip';
import { useInterfaceConsumers } from '~/hooks/useInterfaceConsumers';

interface InterfaceConsumerBadgeProps {
  nodeId: string;
}

export function InterfaceConsumerBadge({ nodeId }: InterfaceConsumerBadgeProps) {
  const { fitView, getNode } = useReactFlow();
  const consumers = useInterfaceConsumers(nodeId);
  // Bumped on click to hard-remount the Tooltip. A plain close isn't enough:
  // Radix keeps the portaled content mounted until its exit animation ends, and
  // the fitView pan below re-renders this badge every frame, stranding the
  // content mid-unmount (data-state="closed" but still on screen). Remounting
  // tears the old portal down instantly.
  const [tooltipKey, setTooltipKey] = useState(0);

  if (consumers.length === 0) return null;

  const single = consumers.length === 1;
  const label = single ? `Used by "${consumers[0].label}"` : `Used by ${consumers.length} interfaces`;

  const reveal = (ids: string[], trigger: HTMLElement) => {
    // An interface may have been deleted between render and click; fitView on
    // an unknown/empty set would just pan to the origin, so drop missing ids.
    const live = ids.filter((id) => getNode(id));
    if (live.length > 0) {
      fitView({ nodes: live.map((id) => ({ id })), duration: 400, maxZoom: 1 });
    }
    setTooltipKey((k) => k + 1);
    trigger.blur();
  };

  return (
      <TooltipProvider delayDuration={150}>
        <Tooltip key={tooltipKey}>
          <TooltipTrigger asChild>
            <button
              type="button"
              data-testid="interface-consumer-badge"
              data-node-id={nodeId}
              onClick={(e) => {
                e.stopPropagation();
                reveal(consumers.map((c) => c.id), e.currentTarget);
              }}
              className="nodrag flex items-center gap-1 px-1.5 py-0.5 rounded-full bg-card border border-border text-muted-foreground text-[10px] font-medium whitespace-nowrap hover:text-foreground hover:border-muted-foreground/40 transition-colors"
            >
              <Code2 className="w-2.5 h-2.5 shrink-0" />
              <span className="max-w-[110px] truncate">{label}</span>
            </button>
          </TooltipTrigger>
          {/* Portaled to the document root, so the tooltip stays full-size and
              readable even when the badge itself is tiny at low zoom. */}
          <TooltipContent side="bottom" className="bg-card border-border text-foreground max-w-[260px] p-2.5">
            <div className="text-[11px] font-semibold text-foreground">
              {single ? 'Used by interface' : `Used by ${consumers.length} interfaces`}
            </div>
            <ul className="mt-1.5 flex flex-col gap-1">
              {consumers.map((c) => (
                <li key={c.id}>
                  <button
                    type="button"
                    onClick={(e) => {
                      e.stopPropagation();
                      reveal([c.id], e.currentTarget);
                    }}
                    className="inline-flex items-center gap-1 text-xs text-foreground/80 hover:text-foreground transition-colors"
                  >
                    <Code2 className="w-3 h-3 shrink-0 text-violet-600 dark:text-violet-400" />
                    <span className="truncate underline underline-offset-2">{c.label}</span>
                    <ArrowUpRight className="h-3 w-3 shrink-0" />
                  </button>
                </li>
              ))}
            </ul>
            <div className="mt-1.5 text-[10px] text-muted-foreground">
              {single ? 'Open the interface on the canvas' : 'Open an interface on the canvas'}
            </div>
          </TooltipContent>
        </Tooltip>
      </TooltipProvider>
  );
}
