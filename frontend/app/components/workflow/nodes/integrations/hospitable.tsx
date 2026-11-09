import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from '~/components/workflow/nodes/types';

const HospitableIcon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
    ({ className, style, ...props }, ref) => (
        <img ref={ref} src="/icons/hospitable.png" alt="" className={className} style={{ ...style, objectFit: 'contain' }} {...props} />
    ),
);
HospitableIcon.displayName = 'HospitableIcon';

export const HospitableNode: NodeDefinition = {
    type: 'automation-hospitable',
    label: 'Hospitable',
    description: 'Manage vacation rental properties, reservations, guest messages and tasks',
    category: 'bookings',
    keywords: ['vacation rental', 'short term rental', 'property management', 'guest messaging'],
    Icon: HospitableIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 64 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={HospitableIcon} iconColor="" />),
};
