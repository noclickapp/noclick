// PostHog product-analytics automation node definition.
// Integrates PostHog's ingestion API (event capture / identify / flag eval) and
// the private REST API (HogQL query, feature flags, persons, cohorts, annotations,
// insights, dashboards, actions, surveys, session recordings, experiments,
// definitions) plus a generic REST passthrough and a Hog-Function webhook trigger.

import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from './base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from './types';

const DIMENSIONS = { width: 90, height: 90, iconSize: 48 };

const PostHogIcon: SvgIconComponent = forwardRef<
    HTMLImageElement,
    React.ImgHTMLAttributes<HTMLImageElement>
>(({ className, style, ...props }, ref) => (
    <img
        ref={ref}
        src="/icons/posthog.svg"
        alt=""
        className={className}
        style={style}
        {...props}
    />
));
PostHogIcon.displayName = 'PostHogIcon';

const PostHogNodeComponent = (props: NodeProps) => {
    return <AutomationNode {...props} Icon={PostHogIcon} iconColor="" />;
};

export const PostHogNode: NodeDefinition = {
    type: 'automation-posthog',
    label: 'PostHog',
    description: 'PostHog product analytics automation',
    Icon: PostHogIcon,
    iconColor: '',
    dimensions: DIMENSIONS,
    component: memo(PostHogNodeComponent),
};
