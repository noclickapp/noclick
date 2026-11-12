import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from '~/components/workflow/nodes/types';

const TOPdeskIcon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
    ({ className, style, ...props }, ref) => (
        <img ref={ref} src="/icons/topdesk.svg" alt="" className={className} style={{ ...style, objectFit: 'contain' }} {...props} />
    ),
);
TOPdeskIcon.displayName = 'TOPdeskIcon';

export const TOPdeskNode: NodeDefinition = {
    type: 'automation-topdesk',
    label: 'TOPdesk',
    description: 'Manage incidents, actions and time registrations; monitor new and updated incidents',
    category: 'support',
    Icon: TOPdeskIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 64 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={TOPdeskIcon} iconColor="" />),
};
