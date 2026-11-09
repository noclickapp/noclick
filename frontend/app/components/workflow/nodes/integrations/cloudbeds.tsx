import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from '~/components/workflow/nodes/types';


const CloudbedsIcon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
    ({ className, style, ...props }, ref) => (
        <img ref={ref} src="/icons/cloudbeds.svg" alt="" className={className} style={{ ...style, objectFit: 'contain' }} {...props} />
    ),
);
CloudbedsIcon.displayName = 'CloudbedsIcon';

// Exact publisher asset; provenance is recorded beside the SVG.
export const CloudbedsNode: NodeDefinition = {
    type: 'automation-cloudbeds',
    label: 'Cloudbeds',
    description: 'Manage hotel reservations, guests, rooms and housekeeping',
    category: 'bookings',
    Icon: CloudbedsIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 64 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={CloudbedsIcon} iconColor="" />),
};
