import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from '~/components/workflow/nodes/types';


const SmilyIcon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
    ({ className, style, ...props }, ref) => (
        <img ref={ref} src="/icons/smily.png" alt="" className={className} style={{ ...style, objectFit: 'contain' }} {...props} />
    ),
);
SmilyIcon.displayName = 'SmilyIcon';

// Exact publisher asset; provenance is recorded beside the SVG.
export const SmilyNode: NodeDefinition = {
    type: 'automation-smily',
    label: 'Smily',
    keywords: ['BookingSync', 'Channel API', 'OTA', 'vacation rentals', 'availability'],
    description: 'Channel accounts, rentals, quotes, bookings, payments and LOS price changes',
    category: 'bookings',
    Icon: SmilyIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 64 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={SmilyIcon} iconColor="" />),
};
