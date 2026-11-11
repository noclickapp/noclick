import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from '~/components/workflow/nodes/types';

const RudderIcon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
    ({ className, style, ...props }, ref) => (
        <img ref={ref} src="/icons/rudder.svg" alt="" className={className} style={style} {...props} />
    ),
);
RudderIcon.displayName = 'RudderIcon';

export const RudderNode: NodeDefinition = {
    type: 'automation-rudder',
    label: 'Rudder',
    description: 'Manage infrastructure nodes, rules, directives, groups and parameters; watch inventory updates',
    category: 'developer-tools',
    keywords: ['Rudder API', 'configuration management', 'compliance', 'inventory', 'infrastructure'],
    Icon: RudderIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 64 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={RudderIcon} iconColor="" />),
};
