import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from '~/components/workflow/nodes/types';

import { ThemedBrandImg } from '~/components/shared/ThemedBrandImg';
const BlackboardIcon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
    ({ className, style, ...props }, ref) => (
        <ThemedBrandImg light="/icons/blackboard.svg" dark="/icons/blackboard-dark.svg" className={className} style={style} {...props} ref={ref} />
    ),
);
BlackboardIcon.displayName = 'BlackboardIcon';

export const BlackboardNode: NodeDefinition = {
    type: 'automation-blackboard',
    label: 'Blackboard',
    description: 'Read users and manage courses, memberships and announcements in Blackboard Learn',
    category: 'courses',
    Icon: BlackboardIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 64 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={BlackboardIcon} iconColor="" />),
};
