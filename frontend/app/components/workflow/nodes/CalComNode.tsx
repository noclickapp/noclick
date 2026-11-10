// Cal.com scheduling automation node definition.
// Provides workflow integration with the Cal.com v2 API (bookings, event types,
// availability, schedules) plus a webhook trigger for booking events.

import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from './base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from './types';
import { ThemedBrandImg } from '~/components/shared/ThemedBrandImg';

const DIMENSIONS = { width: 90, height: 90, iconSize: 48 };

const CalComIcon: SvgIconComponent = forwardRef<
    HTMLImageElement,
    React.ImgHTMLAttributes<HTMLImageElement>
>((props, ref) => (
    <ThemedBrandImg ref={ref} light="/icons/cal-com-light.svg" dark="/icons/cal-com.svg" {...props} />
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
