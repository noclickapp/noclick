// Calendly scheduling automation node definition.
// Provides workflow integration with the Calendly REST API v2 (event types,
// scheduled events + invitees, availability, memberships, no-shows, scheduling
// links, routing forms, groups, activity log) plus native webhook triggers for
// invitee / no-show / routing-form / contact events.

import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from './base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from './types';

const DIMENSIONS = { width: 90, height: 90, iconSize: 48 };

const CalendlyIcon: SvgIconComponent = forwardRef<
    HTMLImageElement,
    React.ImgHTMLAttributes<HTMLImageElement>
>(({ className, style, ...props }, ref) => (
    <img
        ref={ref}
        src="/icons/calendly.svg"
        alt=""
        className={className}
        style={style}
        {...props}
    />
));
CalendlyIcon.displayName = 'CalendlyIcon';

const CalendlyNodeComponent = (props: NodeProps) => {
    return <AutomationNode {...props} Icon={CalendlyIcon} iconColor="" />;
};

export const CalendlyNode: NodeDefinition = {
    type: 'automation-calendly',
    label: 'Calendly',
    description: 'Calendly scheduling automation',
    Icon: CalendlyIcon,
    iconColor: '',
    dimensions: DIMENSIONS,
    component: memo(CalendlyNodeComponent),
};
