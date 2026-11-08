import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from '~/components/workflow/nodes/types';


const HalopsaIcon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
    ({ className, style, ...props }, ref) => (
        <img ref={ref} src="/icons/halopsa.png" alt="" className={className} style={{ ...style, objectFit: 'contain' }} {...props} />
    ),
);
HalopsaIcon.displayName = 'HalopsaIcon';

// Exact publisher asset; provenance is recorded beside the SVG.
export const HalopsaNode: NodeDefinition = {
    type: 'automation-halopsa',
    label: 'HaloPSA',
    description: 'Automate HaloPSA tickets, clients, users, sites and actions',
    category: 'support',
    Icon: HalopsaIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 64 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={HalopsaIcon} iconColor="" />),
};
