// Slack Web API automation node definition.
// Provides messaging, channels, users, reactions, pins, files, and search operations.

import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from './base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from './types';

const DIMENSIONS = { width: 90, height: 90, iconSize: 48 };

// Create icon component from SVG file in /public/icons/
const SlackIcon: SvgIconComponent = forwardRef<
    HTMLImageElement,
    React.ImgHTMLAttributes<HTMLImageElement>
>(({ className, style, ...props }, ref) => (
    <img
        ref={ref}
        src="/icons/slack.svg"
        alt=""
        className={className}
        style={style}
        {...props}
    />
));
SlackIcon.displayName = 'SlackIcon';

const SlackNodeComponent = (props: NodeProps) => {
    return <AutomationNode {...props} Icon={SlackIcon} iconColor="" />;
};

export const SlackNode: NodeDefinition = {
    type: 'automation-slack',
    label: 'Slack',
    description: 'Slack automation',
    Icon: SlackIcon,
    iconColor: '',
    dimensions: DIMENSIONS,
    component: memo(SlackNodeComponent),
};
