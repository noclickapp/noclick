import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from '~/components/workflow/nodes/types';

import { ThemedBrandImg } from '~/components/shared/ThemedBrandImg';
const BlackboardIcon: SvgIconComponent = forwardRef<HTMLImageElement, React.ImgHTMLAttributes<HTMLImageElement>>(
    ({ className, style, ...props }, ref) => (
        <ThemedBrandImg {...props} light="/icons/blackboard.svg" className={className} style={style} ref={ref} />
    ),
);
BlackboardIcon.displayName = 'BlackboardIcon';

export const BlackboardNode: NodeDefinition = {
    type: 'automation-blackboard',
    label: 'Blackboard',
    description: 'Start workflows from new users, enrollments, courses and announcements, and manage Blackboard Learn',
    category: 'courses',
    Icon: BlackboardIcon,
    iconColor: '',
    dimensions: { width: 90, height: 90, iconSize: 64 },
    component: memo((props: NodeProps) => <AutomationNode {...props} Icon={BlackboardIcon} iconColor="" />),
};
