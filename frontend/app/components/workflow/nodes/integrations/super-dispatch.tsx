import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from '~/components/workflow/nodes/types';


const SuperDispatchIcon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
    ({ className, style, ...props }, ref) => (
        <img ref={ref} src="/icons/super-dispatch.svg" alt="" className={className} style={{ ...style, objectFit: 'contain' }} {...props} />
    ),
);
SuperDispatchIcon.displayName = 'SuperDispatchIcon';

// Official favicon, converted to PNG; provenance is recorded beside the icon.
export const SuperDispatchNode: NodeDefinition = {
    type: 'automation-super-dispatch',
    label: 'Super Dispatch',
    description: 'Carrier orders, drivers, vehicles and load offers',
    category: 'industry',
    Icon: SuperDispatchIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 64 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={SuperDispatchIcon} iconColor="" />),
};
