// Google Tasks automation node definition.
// Uses AutomationNode component with Google Tasks-specific configuration.
// Enables managing task lists and tasks via OAuth credentials.

import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from './base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from './types';

const DIMENSIONS = { width: 90, height: 90, iconSize: 46 };

// Create icon component from SVG file
const GoogleTasksIcon: SvgIconComponent = forwardRef<
    HTMLImageElement,
    React.ImgHTMLAttributes<HTMLImageElement>
>(({ className, style, ...props }, ref) => (
    <img
        ref={ref}
        src="/icons/google-tasks.svg"
        alt=""
        className={className}
        style={style}
        {...props}
    />
));
GoogleTasksIcon.displayName = 'GoogleTasksIcon';

const GoogleTasksNodeComponent = (props: NodeProps) => {
    return <AutomationNode {...props} Icon={GoogleTasksIcon} iconColor="" />;
};

export const GoogleTasksNode: NodeDefinition = {
    type: 'automation-google-tasks',
    label: 'Google Tasks',
    description: 'Task management',
    Icon: GoogleTasksIcon,
    iconColor: '',
    dimensions: DIMENSIONS,
    component: memo(GoogleTasksNodeComponent),
};
