// An agent or workflow drawn at the thread's size. The engine draws it with the Automations page's SVG preview; a
// platform with a richer read-only canvas registers it (canvasRegistry; hosted: the real ReactFlow canvas).
import { WorkflowGraphPreview } from '~/components/workflow/WorkflowGraphPreview';
import { getNodeIconData } from '~/lib/nodeIconRegistry';
import { buildGraphPreview } from '~/lib/workflowBrowserStore';
import { cn } from '~/lib/utils';
import { OpenPill } from '~/components/shared/OpenPill';
import { registeredCoordinatorCanvas, type CanvasProps } from './canvasRegistry';

export { registerCoordinatorCanvas, type CanvasProps } from './canvasRegistry';

const FRAME = 'h-[232px] min-h-0 rounded-xl';

function GraphCanvas({ blob, className }: CanvasProps) {
    const graph = buildGraphPreview(blob);
    if (!graph) return null;
    return (
        <div className={cn(FRAME, 'overflow-hidden bg-foreground/[0.03]', className)}>
            <WorkflowGraphPreview graph={graph} nodeIcons={getNodeIconData()} fit="full-frame" className="h-full w-full" />
        </div>
    );
}

/** `onOpen`: the canvas opens its automation from an Open pill in its top-right corner. */
export function Canvas({ blob, className, onOpen }: CanvasProps & { onOpen?: () => void }) {
    const Drawn = registeredCoordinatorCanvas() ?? GraphCanvas;
    const drawn = <Drawn blob={blob} className={cn(FRAME, className)} />;
    if (!onOpen) return drawn;
    return (
        <div className="relative">
            {drawn}
            <OpenPill onClick={onOpen} className="right-3 top-3 h-8 px-3.5" />
        </div>
    );
}
