import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from '~/components/workflow/nodes/types';


const CventIcon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
    ({ className, style, ...props }, ref) => (
        <img ref={ref} src="/icons/cvent.png" alt="" className={className} style={{ ...style, objectFit: 'contain' }} {...props} />
    ),
);
CventIcon.displayName = 'CventIcon';

// Exact publisher asset; provenance is recorded beside the SVG.
export const CventNode: NodeDefinition = {
    type: 'automation-cvent',
    label: 'Cvent',
    description: 'Events, attendees, contacts and session registrations',
    category: 'meetings',
    Icon: CventIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 64 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={CventIcon} iconColor="" />),
};
