// Datadog observability automation node definition.
// Provides workflow integration with the Datadog REST API (monitors, events,
// metrics, logs, dashboards, incidents, downtimes).

import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from './base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from './types';

const DIMENSIONS = { width: 90, height: 90, iconSize: 48 };

const DatadogIcon: SvgIconComponent = forwardRef<
    HTMLImageElement,
    React.ImgHTMLAttributes<HTMLImageElement>
>(({ className, style, ...props }, ref) => (
    <img ref={ref} src="/icons/datadog.svg" alt="" className={className} style={style} {...props} />
));
DatadogIcon.displayName = 'DatadogIcon';

const DatadogNodeComponent = (props: NodeProps) => {
    return <AutomationNode {...props} Icon={DatadogIcon} iconColor="" />;
};

export const DatadogNode: NodeDefinition = {
    type: 'automation-datadog',
    label: 'Datadog',
    description: 'Datadog observability automation',
    Icon: DatadogIcon,
    iconColor: '',
    dimensions: DIMENSIONS,
    component: memo(DatadogNodeComponent),
};
