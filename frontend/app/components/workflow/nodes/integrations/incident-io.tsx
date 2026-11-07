// Incident.io incident management & on-call automation node definition.
// Provides workflow integration with the incident.io REST API (incidents,
// alerts, on-call schedules/escalations, catalog, status pages) plus a webhook
// trigger for incident/action/follow-up events.

import { memo, forwardRef } from 'react';
import { NodeProps } from '@xyflow/react';
import AutomationNode from '~/components/workflow/nodes/base/AutomationNode';
import { NodeDefinition, SvgIconComponent } from '~/components/workflow/nodes/types';

const DIMENSIONS = { width: 90, height: 90, iconSize: 48 };

const IncidentIoIcon: SvgIconComponent = forwardRef<
    HTMLImageElement,
    React.ImgHTMLAttributes<HTMLImageElement>
>(({ className, style, ...props }, ref) => (
    <img
        ref={ref}
        src="/icons/incident-io.svg"
        alt=""
        className={className}
        style={style}
        {...props}
    />
));
IncidentIoIcon.displayName = 'IncidentIoIcon';

const IncidentIoNodeComponent = (props: NodeProps) => {
    return <AutomationNode {...props} Icon={IncidentIoIcon} iconColor="" />;
};

export const IncidentIoNode: NodeDefinition = {
    type: 'automation-incident-io',
    label: 'Incident.io',
    description: 'Incident.io incident management & on-call automation',
    Icon: IncidentIoIcon,
    iconColor: '',
    dimensions: DIMENSIONS,
    component: memo(IncidentIoNodeComponent),
};
