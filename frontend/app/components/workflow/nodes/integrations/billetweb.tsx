import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from '~/components/workflow/nodes/types';


const BilletwebIcon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
    ({ className, style, ...props }, ref) => (
        <img ref={ref} src="/icons/billetweb.svg" alt="" className={className} style={{ ...style, objectFit: 'contain' }} {...props} />
    ),
);
BilletwebIcon.displayName = 'BilletwebIcon';

// Official publisher artwork; provenance is recorded beside the SVG.
export const BilletwebNode: NodeDefinition = {
    type: 'automation-billetweb',
    label: 'Billetweb',
    description: 'Manage events, attendees, ticket types, sessions, offline orders and lists',
    category: 'bookings',
    Icon: BilletwebIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 64 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={BilletwebIcon} iconColor="" />),
};
