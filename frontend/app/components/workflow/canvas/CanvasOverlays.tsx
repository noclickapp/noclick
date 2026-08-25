import { ExternalLink } from 'lucide-react';
import type { ActiveExecution } from '~/hooks/useWorkflowExecutionTracking';
import type { NodeDefinition } from '~/components/workflow/nodes/types';
import { BrandIcon } from '~/components/shared/BrandIcon';

// Dynamic highlight injected as a <style> tag: outlines the nodes belonging
// to the hovered execution in the stop-dropdown and dims all others.
export function HoverExecutionGlow({
    hoveredExecutionId,
    activeExecutions,
}: {
    hoveredExecutionId: string | null;
    activeExecutions: Map<string, ActiveExecution>;
}) {
    if (!hoveredExecutionId) return null;
    const exec = activeExecutions.get(hoveredExecutionId);
    const nodeIds = exec ? [...exec.nodeIds] : [];
    if (nodeIds.length === 0) return null;

    const selectors = nodeIds.map((id) => `.react-flow__node[data-id="${id}"]`).join(',\n');
    const dimSelector = `.react-flow__node:not([data-id="${nodeIds.join('"]):not([data-id="')}"])`;

    return (
        <style>{`.react-flow__node {
            border-radius: 18px;
            transition: box-shadow 0.15s ease, opacity 0.15s ease;
        }
        ${selectors} {
            box-shadow: 0 0 0 3px rgba(251, 146, 60, 0.7), 0 0 20px 6px rgba(251, 146, 60, 0.2) !important;
            z-index: 10 !important;
        }
        ${dimSelector} {
            opacity: 0.3;
        }`}</style>
    );
}

// Desktop-only external-link chip that sits above the FlowHelperView and
// links to the selected node's external resource (e.g. the Google Sheets
// URL derived from a Sheets node's spreadsheet_id).
export function CanvasExternalLinkPill({
    url,
    label,
    Icon,
    bgColor,
    flowHelperHeight,
    noAnimation,
}: {
    url: string;
    label: string;
    Icon?: NodeDefinition['Icon'];
    bgColor: string;
    flowHelperHeight: number;
    /** Skip the reposition transition (flow helper opened via a key). */
    noAnimation?: boolean;
}) {
    return (
        <a
            href={url}
            target="_blank"
            rel="noopener noreferrer"
            className="absolute z-15 flex items-center gap-2 pl-0.5 pr-3 py-0.5 rounded-full text-xs font-semibold backdrop-blur-sm hover:brightness-125 hover:scale-105 active:scale-95"
            style={{
                bottom: `${flowHelperHeight + 12}px`,
                // Clear of the Crisp chat bubble in the bottom-right corner
                right: '72px',
                backgroundColor: `${bgColor}50`,
                color: 'hsl(var(--foreground))',
                // Match FlowHelperView's height transition exactly so this pill
                // stays glued to the top of the panel as it grows/shrinks.
                transition: noAnimation ? 'none' : 'all 280ms cubic-bezier(0.22, 0.61, 0.36, 1)',
            }}
            title={label}
        >
            {/* Dark chip behind the icon creates figure-ground separation */}
            {Icon && (
                <span className="flex items-center justify-center w-8 h-8 rounded-full bg-background/40">
                    <BrandIcon Icon={Icon} className="h-5 w-5" />
                </span>
            )}
            <span>{label}</span>
            <ExternalLink className="h-3 w-3 opacity-70" />
        </a>
    );
}
