// ClickUp project-management automation node definition.
// Provides workflow integration with the ClickUp v2 API (tasks, lists, folders,
// comments, custom fields, time tracking, goals) plus a webhook trigger for
// task events.

import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from './base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from './types';

const DIMENSIONS = { width: 90, height: 90, iconSize: 48 };

const ClickUpIcon: SvgIconComponent = forwardRef<
    HTMLImageElement,
    React.ImgHTMLAttributes<HTMLImageElement>
>(({ className, style, ...props }, ref) => (
    <img ref={ref} src="/icons/clickup.svg" alt="" className={className} style={style} {...props} />
));
ClickUpIcon.displayName = 'ClickUpIcon';

const ClickUpNodeComponent = (props: NodeProps) => {
    return <AutomationNode {...props} Icon={ClickUpIcon} iconColor="" />;
};

export const ClickUpNode: NodeDefinition = {
    type: 'automation-clickup',
    label: 'ClickUp',
    description: 'ClickUp project-management automation',
    Icon: ClickUpIcon,
    iconColor: '',
    dimensions: DIMENSIONS,
    component: memo(ClickUpNodeComponent),
};
