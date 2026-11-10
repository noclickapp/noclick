import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from '~/components/workflow/nodes/types';

const HostfullyIcon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
    ({ className, style, ...props }, ref) => (
        <img ref={ref} src="/icons/hostfully.svg" alt="" className={className} style={{ ...style, objectFit: 'contain' }} {...props} />
    ),
);
HostfullyIcon.displayName = 'HostfullyIcon';

export const HostfullyNode: NodeDefinition = {
    type: 'automation-hostfully',
    label: 'Hostfully',
    description: 'Manage vacation rental properties, bookings, guest messages and jobs',
    category: 'bookings',
    keywords: ['vacation rentals', 'property management', 'reservations', 'PMS'],
    Icon: HostfullyIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 64 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={HostfullyIcon} iconColor="" />),
};
