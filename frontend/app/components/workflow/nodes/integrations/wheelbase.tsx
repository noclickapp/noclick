import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from '~/components/workflow/nodes/types';


const WheelbaseIcon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
    ({ className, style, ...props }, ref) => (
        <img ref={ref} src="/icons/wheelbase.png" alt="" className={className} style={{ ...style, objectFit: 'contain' }} {...props} />
    ),
);
WheelbaseIcon.displayName = 'WheelbaseIcon';

// Exact publisher asset; provenance is recorded beside the SVG.
export const WheelbaseNode: NodeDefinition = {
    type: 'automation-wheelbase',
    label: 'Wheelbase',
    description: 'Manage rental bookings, customers, listings and quotes',
    category: 'bookings',
    keywords: ['rental', 'fleet', 'vehicles', 'RV', 'reservations'],
    Icon: WheelbaseIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 64 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={WheelbaseIcon} iconColor="" />),
};
