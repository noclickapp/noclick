// PagerDuty incident management automation node definition.
// Provides workflow integration with the PagerDuty REST API v2 (incidents,
// services, schedules, on-call, users) plus a webhook trigger for incident events.

import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from './base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from './types';

const DIMENSIONS = { width: 90, height: 90, iconSize: 48 };

const PagerDutyIcon: SvgIconComponent = forwardRef<
    HTMLImageElement,
    React.ImgHTMLAttributes<HTMLImageElement>
>(({ className, style, ...props }, ref) => (
    <img
        ref={ref}
        src="/icons/pagerduty.svg"
        alt=""
        className={className}
        style={style}
        {...props}
    />
));
PagerDutyIcon.displayName = 'PagerDutyIcon';

const PagerDutyNodeComponent = (props: NodeProps) => {
    return <AutomationNode {...props} Icon={PagerDutyIcon} iconColor="" />;
};

export const PagerDutyNode: NodeDefinition = {
    type: 'automation-pagerduty',
    label: 'PagerDuty',
    description: 'PagerDuty incident management automation',
    Icon: PagerDutyIcon,
    iconColor: '',
    dimensions: DIMENSIONS,
    component: memo(PagerDutyNodeComponent),
};
