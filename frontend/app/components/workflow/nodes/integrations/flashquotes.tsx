// Flashquotes uses its official publisher icon and the shared automation canvas.
// This definition adds its catalog entry under Bookings & Events.
import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from '~/components/workflow/nodes/types';


const FlashquotesIcon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
    ({ className, style, ...props }, ref) => (
        <img ref={ref} src="/icons/flashquotes.svg" alt="" className={className} style={{ ...style, objectFit: 'contain' }} {...props} />
    ),
);
FlashquotesIcon.displayName = 'FlashquotesIcon';

// Exact publisher asset; provenance is recorded beside the SVG.
export const FlashquotesNode: NodeDefinition = {
    type: 'automation-flashquotes',
    label: 'Flashquotes',
    description: 'Read quotes, events, resources, form responses, staff and invoices',
    category: 'bookings',
    Icon: FlashquotesIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 64 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={FlashquotesIcon} iconColor="" />),
};
