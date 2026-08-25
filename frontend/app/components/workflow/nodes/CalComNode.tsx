// Cal.com scheduling automation node definition.
// Provides workflow integration with the Cal.com v2 API (bookings, event types,
// availability, schedules) plus a webhook trigger for booking events.

import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from './base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from './types';

const DIMENSIONS = { width: 90, height: 90, iconSize: 48 };

const CalComIcon: SvgIconComponent = forwardRef<
    HTMLImageElement,
    React.ImgHTMLAttributes<HTMLImageElement>
>(({ className, style, ...props }, ref) => (
    <img
        ref={ref}
        src="/icons/cal-com.svg"
        alt=""
        className={`brand-mono ${className || ''}`}
        style={style}
        {...props}
    />
));
CalComIcon.displayName = 'CalComIcon';

const CalComNodeComponent = (props: NodeProps) => {
    return <AutomationNode {...props} Icon={CalComIcon} iconColor="" />;
};

export const CalComNode: NodeDefinition = {
    type: 'automation-cal-com',
    label: 'Cal.com',
    description: 'Cal.com scheduling automation',
    Icon: CalComIcon,
    iconColor: '',
    dimensions: DIMENSIONS,
    component: memo(CalComNodeComponent),
};
