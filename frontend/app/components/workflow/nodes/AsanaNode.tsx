// Asana project-management automation node definition.
// Provides workflow integration with the Asana REST API (projects, tasks,
// subtasks, comments, tags) plus a webhook trigger for resource changes.

import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from './base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from './types';

const DIMENSIONS = { width: 90, height: 90, iconSize: 48 };

const AsanaIcon: SvgIconComponent = forwardRef<
    HTMLImageElement,
    React.ImgHTMLAttributes<HTMLImageElement>
>(({ className, style, ...props }, ref) => (
    <img ref={ref} src="/icons/asana.svg" alt="" className={className} style={style} {...props} />
));
AsanaIcon.displayName = 'AsanaIcon';

const AsanaNodeComponent = (props: NodeProps) => {
    return <AutomationNode {...props} Icon={AsanaIcon} iconColor="" />;
};

export const AsanaNode: NodeDefinition = {
    type: 'automation-asana',
    label: 'Asana',
    description: 'Asana project-management automation',
    Icon: AsanaIcon,
    iconColor: '',
    dimensions: DIMENSIONS,
    component: memo(AsanaNodeComponent),
};
