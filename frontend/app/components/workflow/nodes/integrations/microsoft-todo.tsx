// Microsoft To Do automation node definition.
// Provides task and task list management via Microsoft Graph API.
// Supports creating, updating, listing, and deleting tasks and task lists.

import { memo, forwardRef, type ImgHTMLAttributes } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from '~/components/workflow/nodes/types';

const DIMENSIONS = { width: 90, height: 90, iconSize: 60 };

// Microsoft To Do's icon, from Microsoft's Office icon CDN.
const MicrosoftTodoIcon: SvgIconComponent = forwardRef<HTMLImageElement, ImgHTMLAttributes<HTMLImageElement>>(
    ({ className, style, ...props }, ref) => (
        <img {...props} ref={ref} src="/icons/microsoft-todo.svg" alt="" aria-hidden="true" className={className}
            style={{ ...style, objectFit: 'contain' }} />
    ),
);
MicrosoftTodoIcon.displayName = 'MicrosoftTodoIcon';

const MicrosoftTodoNodeComponent = (props: NodeProps) => {
    return (
        <AutomationNode
            {...props}
            Icon={MicrosoftTodoIcon}
            iconColor=""
            width={DIMENSIONS.width}
            height={DIMENSIONS.height}
            iconSize={DIMENSIONS.iconSize}
        />
    );
};

export const MicrosoftTodoNode: NodeDefinition = {
    type: 'automation-microsoft-todo',
    label: 'To Do',
    description: 'To Do automation',
    Icon: MicrosoftTodoIcon,
    iconColor: '',
    dimensions: DIMENSIONS,
    component: memo(MicrosoftTodoNodeComponent),
};
