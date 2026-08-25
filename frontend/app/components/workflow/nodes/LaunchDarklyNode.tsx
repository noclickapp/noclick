// LaunchDarkly feature management automation node definition.
// Provides workflow integration with the LaunchDarkly REST management API
// (feature flags, projects, environments, segments, webhooks, members) plus a
// webhook trigger for account activity events.

import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from './base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from './types';

const DIMENSIONS = { width: 90, height: 90, iconSize: 48 };

const LaunchDarklyIcon: SvgIconComponent = forwardRef<
    HTMLImageElement,
    React.ImgHTMLAttributes<HTMLImageElement>
>(({ className, style, ...props }, ref) => (
    <img
        ref={ref}
        src="/icons/launchdarkly.svg"
        alt=""
        className={`brand-mono ${className || ''}`}
        style={style}
        {...props}
    />
));
LaunchDarklyIcon.displayName = 'LaunchDarklyIcon';

const LaunchDarklyNodeComponent = (props: NodeProps) => {
    return <AutomationNode {...props} Icon={LaunchDarklyIcon} iconColor="" />;
};

export const LaunchDarklyNode: NodeDefinition = {
    type: 'automation-launchdarkly',
    label: 'LaunchDarkly',
    description: 'LaunchDarkly feature management automation',
    Icon: LaunchDarklyIcon,
    iconColor: '',
    dimensions: DIMENSIONS,
    component: memo(LaunchDarklyNodeComponent),
};
