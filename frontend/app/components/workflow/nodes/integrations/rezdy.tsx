import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import {
    NodeDefinition,
    SvgIconComponent,
} from '~/components/workflow/nodes/types';

const RezdyIcon: SvgIconComponent = forwardRef<
    HTMLImageElement,
    React.ImgHTMLAttributes<HTMLImageElement>
>(({ className, style, ...props }, ref) => (
    <img
        ref={ref}
        src="/icons/rezdy.svg"
        alt=""
        className={className}
        style={{ ...style, objectFit: 'contain' }}
        {...props}
    />
));
RezdyIcon.displayName = 'RezdyIcon';

// Exact publisher asset; provenance is recorded beside the SVG.
export const RezdyNode: NodeDefinition = {
    type: 'automation-rezdy',
    label: 'Rezdy',
    description: 'Bookings, customers, products and tour availability',
    category: 'bookings',
    Icon: RezdyIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 64 },
    component: memo((props: NodeProps) => (
        <AutomationNode {...props} Icon={RezdyIcon} iconColor="" />
    )),
};
