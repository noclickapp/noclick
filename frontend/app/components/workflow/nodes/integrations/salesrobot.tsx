import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from '~/components/workflow/nodes/types';

const SalesrobotIcon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
    ({ className, style, ...props }, ref) => (
        <img ref={ref} src="/icons/salesrobot.png" alt="" className={className} style={{ ...style, objectFit: 'contain' }} {...props} />
    ),
);
SalesrobotIcon.displayName = 'SalesrobotIcon';

export const SalesrobotNode: NodeDefinition = {
    type: 'automation-salesrobot',
    label: 'SalesRobot',
    description: 'Automate LinkedIn campaigns, prospects, messages and outreach settings',
    category: 'crm-sales',
    Icon: SalesrobotIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 64 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={SalesrobotIcon} iconColor="" />),
};
